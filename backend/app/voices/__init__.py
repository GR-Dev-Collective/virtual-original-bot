"""音色档案领域：档案模型、注册表、参考音频规范化与合成请求组装。"""

from app.voices.audio import (
    DEFAULT_SAMPLE_RATE,
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    InvalidReferenceAudio,
    normalize_reference_audio,
)
from app.voices.models import (
    BuiltinVoiceProtected,
    VoiceNotFound,
    VoiceProfile,
)
from app.voices.registry import VoiceRegistry
from app.voices.synthesis import build_synthesis_request

__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "MAX_DURATION_SECONDS",
    "MIN_DURATION_SECONDS",
    "BuiltinVoiceProtected",
    "InvalidReferenceAudio",
    "VoiceNotFound",
    "VoiceProfile",
    "VoiceRegistry",
    "build_synthesis_request",
    "normalize_reference_audio",
]
