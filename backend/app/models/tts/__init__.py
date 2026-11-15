"""TTS 适配器：IndexTTS-2.5 sidecar（默认）与 GPT-SoVITS legacy。

外部接口见 ``app.models.tts.base``；供应商选择见 ``app.models.tts.factory``。
"""

from app.models.tts.base import (
    VALID_LANGUAGES,
    EmotionSpec,
    SynthesisRequest,
    TtsProvider,
    TtsUnavailable,
)

__all__ = [
    "EmotionSpec",
    "SynthesisRequest",
    "TtsProvider",
    "TtsUnavailable",
    "VALID_LANGUAGES",
]
