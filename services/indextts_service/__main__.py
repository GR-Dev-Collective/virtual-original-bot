"""``python -m services.indextts_service`` 入口。"""

from __future__ import annotations

import sys

import uvicorn

from .settings import Settings


def main() -> int:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"[indextts_service] 配置错误: {exc}", file=sys.stderr)
        return 2

    print(
        "[indextts_service] engine="
        f"{settings.engine} model_dir={settings.model_dir} "
        f"device={settings.device} preload={settings.preload}",
        flush=True,
    )
    print(
        "[indextts_service] health check: "
        f"http://{settings.host}:{settings.port}/health",
        flush=True,
    )
    uvicorn.run(
        "services.indextts_service.app:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
