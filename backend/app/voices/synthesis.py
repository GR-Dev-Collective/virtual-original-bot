"""音色档案 → TTS 合成请求。"""

from __future__ import annotations

from typing import Any

from app.models.tts.base import SynthesisRequest
from app.voices.models import VoiceProfile


def build_synthesis_request(text: str, profile: VoiceProfile) -> SynthesisRequest:
    """按档案组装 Provider 请求。

    - ``reference_audio`` 始终是绝对路径，IndexTTS sidecar 直接使用；
    - ``provider_options`` 透传 ``gpt_sovits`` 段（容器路径 / prompt），
      只对 legacy Provider 有意义，IndexTTS 会忽略。
    """

    options: dict[str, Any] = dict(profile.gpt_sovits or {})
    return SynthesisRequest(
        text=text,
        reference_audio=str(profile.reference_audio_path),
        language=profile.language,
        emotion=profile.emotion,
        duration_factor=profile.duration_factor,
        provider_options=options,
    )


__all__ = ["build_synthesis_request"]
