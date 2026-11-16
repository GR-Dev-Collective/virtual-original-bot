"""TTS Provider 工厂：按配置选择 IndexTTS（默认）或 GPT-SoVITS legacy。"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.models.tts.base import TtsProvider
from app.models.tts.gpt_sovits import GptSovitsProvider
from app.models.tts.index_tts import IndexTtsProvider

SUPPORTED_PROVIDERS = ("index_tts", "gpt_sovits")
DEFAULT_PROVIDER = "index_tts"


def build_tts_provider(settings: Settings, client: httpx.AsyncClient) -> TtsProvider:
    """按 ``settings.tts_provider`` 构建 Provider。

    未知取值直接抛 ``ValueError``，让进程在启动时报出清晰错误，而不是静默降级。
    传入的 ``httpx.AsyncClient`` 必须由调用方以 ``trust_env=False`` 创建。
    """

    name = (settings.tts_provider or DEFAULT_PROVIDER).strip().lower()
    if name == "index_tts":
        return IndexTtsProvider(
            settings.index_tts_base_url,
            client,
            timeout=settings.index_tts_timeout_seconds,
        )
    if name == "gpt_sovits":
        return GptSovitsProvider(
            settings.gpt_sovits_base_url,
            client,
            timeout=settings.gpt_sovits_timeout_seconds,
        )
    raise ValueError(
        f"未知的 TTS provider：{settings.tts_provider!r}；可选值：{'、'.join(SUPPORTED_PROVIDERS)}"
    )


__all__ = ["DEFAULT_PROVIDER", "SUPPORTED_PROVIDERS", "build_tts_provider"]
