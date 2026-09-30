"""重建丛雨训练集：丢弃无效切片 → 用 large-v3 重转写 → 规则修正。

背景与依据见 docs/murasame-dataset-audit.md。原标注由 Whisper small/tiny 生成，
存在大量幻觉、系统性错词，并且混入了无法作为训练目标的非语音片段。

阶段：
    drop        只做丢弃，产出保留清单与丢弃原因（很快，不需要 GPU）
    transcribe  对保留清单重转写，产出最终 .list（需要 GPU，耗时长，可中断续跑）

用法：
    python scripts/rebuild_murasame_dataset.py --stage drop
    python scripts/rebuild_murasame_dataset.py --stage transcribe
"""

import argparse
import json
import os
import re
import sys
import wave

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE = os.path.join(os.path.expanduser("~"), "Desktop", "projects", "voice_cloning")
STAGE_DIR = os.path.join(VOICE, "GPT-SoVITS旧目录_暂存")

DEFAULT_SRC_LIST = os.path.join(STAGE_DIR, "data", "murasame_training.list")
DEFAULT_WAV_DIR = os.path.join(STAGE_DIR, "logs", "murasame_v2", "5-wav32k")
DEFAULT_MODEL = os.path.join(
    PROJECT, "docker", "gpt-sovits", "models", "asr_models", "faster-whisper-large-v3"
)
DEFAULT_OUT_DIR = os.path.join(PROJECT, "docker", "gpt-sovits", "training")

MIN_DURATION = 1.0
MAX_DURATION = 20.0
MIN_TEXT_LENGTH = 3

HALLUCINATION = re.compile(r"ご視聴ありがとうございました|Thank you|Mr\.|www|チャンネル登録")
REPEATED_KANA = re.compile(r"([ぁ-んァ-ヶー])\1{3,}")
LATIN = re.compile(r"[A-Za-z]")

FIXES = [
    (re.compile(r"我が敗|我が範囲|我が拝|我が牌|わがはい|わが輩"), "我が輩"),
    (re.compile(r"ダンジュ(?!ン)"), "ダンジョン"),
    (re.compile(r"ムラサメモギ"), "ムラサメ丸"),
]

PROMPT = (
    "ムラサメの台詞。我が輩、お主、ご主人、ぬし、であるぞ、うむ、はっはっは、"
    "お館様、叢雨、ムラサメ。"
)

# 提示词泄漏检测：这些词单独出现都正常，但聚在一起说明模型照抄了提示词
PROMPT_TOKENS = ("うむ", "はっは", "お館様", "叢雨", "ムラサメ", "お主", "ぬし", "であるぞ")
LEAK_TOKEN_THRESHOLD = 3


def load_source(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("|")
            if len(parts) == 4:
                rows.append(parts[0])
    return rows


def duration_of(path):
    try:
        with wave.open(path, "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except Exception:
        return 0.0


def drop_reasons(name, text, duration):
    reasons = []
    if duration <= 0:
        reasons.append("音频不可读")
    elif duration < MIN_DURATION:
        reasons.append("音频短于 %.1fs" % MIN_DURATION)
    elif duration > MAX_DURATION:
        reasons.append("音频长于 %.0fs" % MAX_DURATION)
    if not text.strip():
        reasons.append("空标注")
    elif len(text.strip()) < MIN_TEXT_LENGTH:
        reasons.append("标注少于 %d 字" % MIN_TEXT_LENGTH)
    if HALLUCINATION.search(text):
        reasons.append("Whisper 幻觉")
    if REPEATED_KANA.search(text):
        reasons.append("重复假名")
    if LATIN.search(text):
        reasons.append("含拉丁字母")
    return reasons


def stage_drop(args):
    names = load_source(args.src_list)
    kept, dropped = [], []

    for name in names:
        text = args.source_text[name]
        duration = duration_of(os.path.join(args.wav_dir, name))
        reasons = drop_reasons(name, text, duration)
        if reasons:
            dropped.append((name, text, duration, reasons))
        else:
            kept.append(name)

    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.kept_path, "w", encoding="utf-8") as handle:
        for name in kept:
            handle.write(name + "\n")
    with open(args.dropped_path, "w", encoding="utf-8") as handle:
        for name, text, duration, reasons in dropped:
            handle.write("%s | %.2fs | %s | %s\n" % (name, duration, "/".join(reasons), text))

    total_duration = sum(
        duration_of(os.path.join(args.wav_dir, n)) for n in kept
    )
    print("原始 %d 条" % len(names))
    print("丢弃 %d 条 (%.1f%%)" % (len(dropped), 100 * len(dropped) / max(1, len(names))))
    print("保留 %d 条，总时长 %.1f 分钟" % (len(kept), total_duration / 60))
    print("保留清单 -> %s" % args.kept_path)
    print("丢弃明细 -> %s" % args.dropped_path)


def stage_transcribe(args):
    from faster_whisper import WhisperModel

    with open(args.kept_path, encoding="utf-8") as handle:
        names = [line.strip() for line in handle if line.strip()]

    done = {}
    if os.path.isfile(args.progress_path):
        with open(args.progress_path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    done[row["name"]] = row["text"]
                except (ValueError, KeyError):
                    continue
        print("续跑：已完成 %d 条" % len(done))

    pending = [n for n in names if n not in done]
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

    with open(args.progress_path, "a", encoding="utf-8") as progress:
        for index, name in enumerate(pending, start=1):
            path = os.path.join(args.wav_dir, name)
            segments, _info = model.transcribe(
                path, language="ja", beam_size=5, initial_prompt=PROMPT
            )
            text = "".join(seg.text for seg in segments).strip()
            done[name] = text
            progress.write(json.dumps({"name": name, "text": text}, ensure_ascii=False) + "\n")
            progress.flush()
            if index % 100 == 0 or index == len(pending):
                print("进度 %d/%d" % (index, len(pending)), flush=True)

    write_final(args, names, done)


def write_final(args, names, texts):
    fix_counts = {pattern.pattern: 0 for pattern, _ in FIXES}
    dropped_late = []
    final = []

    for name in names:
        text = texts.get(name, "").strip()
        if not text:
            dropped_late.append((name, "重转写为空"))
            continue
        tokens = sum(1 for token in PROMPT_TOKENS if token in text)
        if tokens >= LEAK_TOKEN_THRESHOLD:
            dropped_late.append((name, "疑似提示词泄漏"))
            continue
        for pattern, replacement in FIXES:
            text, count = pattern.subn(replacement, text)
            fix_counts[pattern.pattern] += count
        if len(text) < MIN_TEXT_LENGTH:
            dropped_late.append((name, "重转写后标注过短"))
            continue
        final.append((name, text))

    with open(args.out_list, "w", encoding="utf-8") as handle:
        for name, text in final:
            handle.write("%s|%s|ja|%s\n" % (name, args.speaker, text))

    with open(args.late_dropped_path, "w", encoding="utf-8") as handle:
        for name, reason in dropped_late:
            handle.write("%s | %s\n" % (name, reason))

    print()
    print("规则修正命中：")
    for pattern, count in fix_counts.items():
        print("  %-40s %d" % (pattern, count))
    print("重转写后追加丢弃 %d 条 -> %s" % (len(dropped_late), args.late_dropped_path))
    print("最终 %d 条 -> %s" % (len(final), args.out_list))


def main():
    parser = argparse.ArgumentParser(description="重建丛雨训练集")
    parser.add_argument("--stage", choices=("drop", "transcribe"), required=True)
    parser.add_argument("--src-list", default=DEFAULT_SRC_LIST)
    parser.add_argument("--wav-dir", default=DEFAULT_WAV_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--speaker", default="murasame")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="float16")
    args = parser.parse_args()

    args.kept_path = os.path.join(args.out_dir, "kept.txt")
    args.dropped_path = os.path.join(args.out_dir, "dropped.txt")
    args.progress_path = os.path.join(args.out_dir, "progress.jsonl")
    args.out_list = os.path.join(args.out_dir, "murasame.list")
    args.late_dropped_path = os.path.join(args.out_dir, "dropped_after_transcribe.txt")

    if not os.path.isfile(args.src_list):
        raise SystemExit("找不到原始标注：%s" % args.src_list)
    if not os.path.isdir(args.wav_dir):
        raise SystemExit("找不到音频目录：%s" % args.wav_dir)

    args.source_text = {}
    with open(args.src_list, encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("|")
            if len(parts) == 4:
                args.source_text[parts[0]] = parts[3]

    os.makedirs(args.out_dir, exist_ok=True)
    if args.stage == "drop":
        stage_drop(args)
    else:
        if not os.path.isfile(args.kept_path):
            raise SystemExit("请先执行 --stage drop，缺少 %s" % args.kept_path)
        stage_transcribe(args)


if __name__ == "__main__":
    main()
