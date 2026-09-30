"""从 ModelScope 下载 ASR 模型。

本机访问 HuggingFace 会被 429 限流，hf-mirror.com 同样被跳转回 HF 后失败，
因此改用 ModelScope。默认取 faster-whisper large-v3 的 CTranslate2 版本。

用法：
    python scripts/fetch_asr_model.py
    python scripts/fetch_asr_model.py --repo Systran/faster-whisper-large-v3 --target <dir>
"""

import argparse
import json
import os
import urllib.parse
import urllib.request

DEFAULT_REPO = "Systran/faster-whisper-large-v3"
DEFAULT_TARGET = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docker",
    "gpt-sovits",
    "models",
    "asr_models",
    "faster-whisper-large-v3",
)

LIST_API = "https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision={rev}&Root="
RAW_API = "https://www.modelscope.cn/api/v1/models/{repo}/repo?Revision={rev}&FilePath={path}"

CHUNK = 1 << 20


def list_files(repo, revision):
    url = LIST_API.format(repo=repo, rev=revision)
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    files = payload.get("Data", {}).get("Files", [])
    return [f for f in files if f.get("Type") == "blob"]


def download(repo, revision, path, destination):
    if os.path.isfile(destination) and os.path.getsize(destination) > 0:
        print("skip  %s" % path, flush=True)
        return

    url = RAW_API.format(repo=repo, rev=revision, path=urllib.parse.quote(path))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    print("get   %s" % path, flush=True)

    with urllib.request.urlopen(url, timeout=120) as response, open(destination, "wb") as handle:
        total = 0
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            handle.write(chunk)
            total += len(chunk)
    print("done  %s  %.1f MB" % (path, total / 1048576), flush=True)


def main():
    parser = argparse.ArgumentParser(description="从 ModelScope 下载 ASR 模型")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--revision", default="master")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    args = parser.parse_args()

    files = list_files(args.repo, args.revision)
    if not files:
        raise SystemExit("模型仓库没有可下载的文件：%s" % args.repo)

    print("仓库 %s，共 %d 个文件 -> %s" % (args.repo, len(files), args.target), flush=True)
    for item in files:
        relative = item["Path"]
        download(
            args.repo,
            args.revision,
            relative,
            os.path.join(args.target, relative.replace("/", os.sep)),
        )
    print("全部完成", flush=True)


if __name__ == "__main__":
    main()
