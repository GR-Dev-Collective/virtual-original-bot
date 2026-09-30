"""驱动 GPT-SoVITS v2 的丛雨重训流程。

为什么不用 Docker：推理服务用 Docker 是对的，但训练需要读写已有的预处理缓存
（4-cnhubert / 6-name2semantic）和预训练权重，而本机已有一套验证过的环境
（voice_clone_project/.gpt-sovits-venv，408 个包，Python 3.10.11，已产出过现有权重）。
用 Docker 重建同样的环境只会增加不确定性。

阶段：
    prepare    重算文本音素（文本变了），并复用音频侧的 hubert / semantic 缓存
    sovits     微调 SoVITS (s2)
    gpt        微调 GPT (s1)

用法：
    python scripts/train_murasame.py --stage prepare
    python scripts/train_murasame.py --stage sovits
    python scripts/train_murasame.py --stage gpt
"""

import argparse
import json
import os
import shutil
import subprocess

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROOT = os.path.join(
    os.path.expanduser("~"), "Desktop", "projects", "voice_cloning", "GPT-SoVITS旧目录_暂存"
)
DEFAULT_VENV = os.path.join(
    os.path.expanduser("~"),
    "Desktop",
    "projects",
    "voice_cloning",
    "voice_clone_project",
    ".gpt-sovits-venv",
    "Scripts",
    "python.exe",
)
DEFAULT_LIST = os.path.join(PROJECT, "docker", "gpt-sovits", "training", "murasame.list")
DEFAULT_WAVS = os.path.join(
    os.path.expanduser("~"),
    "Desktop",
    "projects",
    "voice_cloning",
    "GPT-SoVITS旧目录_暂存",
    "logs",
    "murasame_v2",
    "5-wav32k",
)

# 上一次实验的预处理产物：音频侧特征与文本无关，可以直接复用
PREVIOUS_EXP = "murasame_v2"

S2_CONFIG = {
    "train": {
        "log_interval": 100,
        "eval_interval": 500,
        "seed": 1234,
        "epochs": 8,
        "learning_rate": 0.0001,
        "betas": [0.8, 0.99],
        "eps": 1e-09,
        "batch_size": 4,
        "fp16_run": True,
        "lr_decay": 0.999875,
        "segment_size": 20480,
        "init_lr_ratio": 1,
        "warmup_epochs": 0,
        "c_mel": 45,
        "c_kl": 1.0,
        "text_low_lr_rate": 0.4,
        "grad_ckpt": False,
        "if_save_latest": 0,
        "if_save_every_weights": True,
        "save_every_epoch": 2,
        "gpu_numbers": "0",
    },
    "data": {
        "max_wav_value": 32768.0,
        "sampling_rate": 32000,
        "filter_length": 2048,
        "hop_length": 640,
        "win_length": 2048,
        "n_mel_channels": 128,
        "mel_fmin": 0.0,
        "mel_fmax": None,
        "add_blank": True,
        "n_speakers": 300,
        "cleaned_text": True,
    },
    "model": {
        "inter_channels": 192,
        "hidden_channels": 192,
        "filter_channels": 768,
        "n_heads": 2,
        "n_layers": 6,
        "kernel_size": 3,
        "p_dropout": 0.1,
        "resblock": "1",
        "resblock_kernel_sizes": [3, 7, 11],
        "resblock_dilation_sizes": [[1, 3, 5], [1, 3, 5], [1, 3, 5]],
        "upsample_rates": [10, 8, 2, 2, 2],
        "upsample_initial_channel": 512,
        "upsample_kernel_sizes": [16, 16, 8, 2, 2],
        "n_layers_q": 3,
        "use_spectral_norm": False,
        "gin_channels": 512,
        "semantic_frame_rate": "25hz",
        "freeze_quantizer": True,
        "version": "v2",
    },
    "content_module": "cnhubert",
    "version": "v2",
}

S1_CONFIG = {
    "train": {
        "seed": 1234,
        # 上次只训到 4 轮就停了，这里补到 8 轮
        "epochs": 8,
        "batch_size": 8,
        "save_every_n_epoch": 1,
        "precision": "16-mixed",
        "gradient_clip": 1.0,
    },
    "optimizer": {
        "lr": 0.01,
        "lr_init": 1e-05,
        "lr_end": 0.0001,
        "warmup_steps": 2000,
        "decay_steps": 40000,
    },
    "data": {"max_eval_sample": 8, "max_sec": 54, "num_workers": 1, "pad_val": 1024},
    "model": {
        "vocab_size": 1025,
        "phoneme_vocab_size": 732,
        "embedding_dim": 512,
        "hidden_dim": 512,
        "head": 16,
        "linear_units": 2048,
        "n_layer": 24,
        "dropout": 0,
        "EOS": 1024,
        "random_bert": 0,
    },
    "inference": {"top_k": 15},
}


def run(command, cwd, env=None):
    print("\n>>> %s" % " ".join(str(c) for c in command), flush=True)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(command, cwd=cwd, env=merged)
    if result.returncode != 0:
        raise SystemExit("命令失败，退出码 %d" % result.returncode)


def write_config(path, payload):
    """写出配置。

    必须用 ASCII 转义（ensure_ascii=True）：GPT-SoVITS 的 utils.get_hparams 里是
    `open(config_path, "r")`，没有指定 encoding，会按系统默认编码（中文 Windows 上是
    GBK）读取。路径里含中文目录名时会被解码坏掉，表现为 os.path.exists 返回 False，
    而打印出来的路径看起来完全正常。转义后文件是纯 ASCII，任何编码读都还原正确。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)
    print("配置 -> %s" % path)


def stage_prepare(args):
    exp_dir = os.path.join(args.root, "logs", args.exp)
    gsv = os.path.join(args.root, "GPT_SoVITS")
    os.makedirs(exp_dir, exist_ok=True)
    py = [args.venv_python, "-u"]

    # 1) 文本音素：文本变了，必须重算
    # 脚本位于 prepare_datasets/ 下，Python 只会把该目录加进 sys.path，
    # 而它要 import 的 text 在 GPT_SoVITS 下、tools 在仓库根下，因此两者都要给。
    run(
        [*py, "prepare_datasets/1-get-text.py"],
        cwd=gsv,
        env={
            "inp_text": args.list,
            "inp_wav_dir": args.wavs,
            "exp_name": args.exp,
            "i_part": "0",
            "all_parts": "1",
            "opt_dir": exp_dir,
            "bert_pretrained_dir": os.path.join(
                gsv, "pretrained_models", "chinese-roberta-wwm-ext-large"
            ),
            "is_half": "True",
            "version": "v2",
        },
    )

    # 2) 音频侧缓存：与文本无关，从上次实验直接复用
    #    data_utils.TextAudioSpeakerLoader 会断言这三个路径都存在：
    #    2-name2text.txt（本次重算）、4-cnhubert、5-wav32k
    previous = os.path.join(args.root, "logs", PREVIOUS_EXP)
    for name in ("4-cnhubert", "5-wav32k", "6-name2semantic-0.tsv"):
        source = os.path.join(previous, name)
        target = os.path.join(exp_dir, name)
        if not os.path.exists(source):
            raise SystemExit("上次实验缺少 %s，需要完整跑一遍预处理" % source)
        if os.path.exists(target):
            print("已存在，跳过复用：%s" % name)
            continue
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        print("复用 %s -> %s" % (source, target))

    # 3) 1-get-text.py 只产出分片文件 2-name2text-{i}.txt，webui 里的合并步骤要自己补
    merge_phoneme_parts(exp_dir)
    # 4) 语义缓存来自旧实验，含已丢弃的切片，裁到与音素文件一致
    prune_semantic(exp_dir, os.path.join(exp_dir, "2-name2text.txt"))


def merge_phoneme_parts(exp_dir):
    merged = os.path.join(exp_dir, "2-name2text.txt")
    parts = sorted(
        name for name in os.listdir(exp_dir) if name.startswith("2-name2text-") and name.endswith(".txt")
    )
    if not parts:
        raise SystemExit("没有找到 2-name2text-{i}.txt 分片")

    with open(merged, "w", encoding="utf-8") as out:
        for name in parts:
            with open(os.path.join(exp_dir, name), encoding="utf-8") as handle:
                shutil.copyfileobj(handle, out)
    print("合并 %d 个分片 -> %s" % (len(parts), merged))


def prune_semantic(exp_dir, phoneme_path):
    semantic = os.path.join(exp_dir, "6-name2semantic-0.tsv")
    if not os.path.isfile(semantic):
        return

    with open(phoneme_path, encoding="utf-8") as handle:
        wanted = {line.split("\t")[0] for line in handle if line.strip()}

    with open(semantic, encoding="utf-8") as handle:
        rows = [line for line in handle if line.split("\t")[0] in wanted]

    with open(semantic, "w", encoding="utf-8") as handle:
        handle.writelines(rows)
    print("语义表裁剪到 %d 条（音素 %d 条）" % (len(rows), len(wanted)))


def stage_sovits(args):
    exp_dir = os.path.join(args.root, "logs", args.exp)
    pretrained = os.path.join(args.root, "GPT_SoVITS", "pretrained_models", "gsv-v2final-pretrained")
    py = [args.venv_python, "-u"]

    config = json.loads(json.dumps(S2_CONFIG))
    config["train"]["pretrained_s2G"] = os.path.join(pretrained, "s2G2333k.pth")
    config["train"]["pretrained_s2D"] = os.path.join(pretrained, "s2D2333k.pth")
    config["data"]["exp_dir"] = exp_dir
    config["s2_ckpt_dir"] = os.path.join(exp_dir, "logs_s2_v2")
    config["save_weight_dir"] = os.path.join(args.root, "SoVITS_weights_v2")
    config["name"] = args.exp

    config_path = os.path.join(args.out_dir, "s2_%s.json" % args.exp)
    write_config(config_path, config)

    run(
        [*py, "s2_train.py", "-c", config_path],
        cwd=os.path.join(args.root, "GPT_SoVITS"),
    )


def stage_gpt(args):
    exp_dir = os.path.join(args.root, "logs", args.exp)
    pretrained = os.path.join(
        args.root,
        "GPT_SoVITS",
        "pretrained_models",
        "gsv-v2final-pretrained",
        "s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    )
    py = [args.venv_python, "-u"]

    config = json.loads(json.dumps(S1_CONFIG))
    config["output_dir"] = os.path.join(exp_dir, "logs_s1_v2")
    config["train_semantic_path"] = os.path.join(exp_dir, "6-name2semantic-0.tsv")
    config["train_phoneme_path"] = os.path.join(exp_dir, "2-name2text.txt")
    config["data_root"] = args.wavs

    config_path = os.path.join(args.out_dir, "s1_%s.json" % args.exp)
    write_config(config_path, config)

    run(
        [*py, "s1_train.py", "-c", config_path, "-p", pretrained],
        cwd=os.path.join(args.root, "GPT_SoVITS"),
    )


def main():
    parser = argparse.ArgumentParser(description="丛雨 GPT-SoVITS 重训流程")
    parser.add_argument("--stage", choices=("prepare", "sovits", "gpt"), required=True)
    parser.add_argument("--exp", default="murasame_v3", help="实验名，不要覆盖已有的 murasame_v2")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="GPT-SoVITS 仓库根目录")
    parser.add_argument("--venv-python", default=DEFAULT_VENV, help="训练用解释器")
    parser.add_argument("--list", default=DEFAULT_LIST, help="训练清单")
    parser.add_argument("--wavs", default=DEFAULT_WAVS, help="切片目录")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(PROJECT, "docker", "gpt-sovits", "training", "generated"),
        help="生成的配置目录",
    )
    args = parser.parse_args()

    for label, path in (
        ("GPT-SoVITS 根目录", args.root),
        ("训练解释器", args.venv_python),
        ("训练清单", args.list),
        ("切片目录", args.wavs),
    ):
        if not os.path.exists(path):
            raise SystemExit("%s 不存在：%s" % (label, path))

    if args.exp == PREVIOUS_EXP:
        raise SystemExit("实验名不能是 %s，会覆盖已有权重" % PREVIOUS_EXP)

    # GPT-SoVITS 的脚本大量 `from tools...` / `from text...`，而这两个包分别位于
    # 仓库根和 GPT_SoVITS 下。显式设定，避免依赖调用方当前目录。
    gsv = os.path.join(args.root, "GPT_SoVITS")
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [p for p in (args.root, gsv, existing) if p]
    )

    {"prepare": stage_prepare, "sovits": stage_sovits, "gpt": stage_gpt}[args.stage](args)


if __name__ == "__main__":
    main()
