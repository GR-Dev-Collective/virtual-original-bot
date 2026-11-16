"""音色档案 + 情绪 → TTS 合成请求。"""

from __future__ import annotations

from typing import Any

from app.models.tts.base import EmotionSpec, SynthesisRequest
from app.voices.models import VoiceProfile

# IndexTTS 情感向量顺序：高兴、愤怒、悲伤、害怕、厌恶、忧郁、惊讶、平静。
EMOTION_VECTORS: dict[str, list[float]] = {
    "happy": [0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "angry": [0.0, 0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "sad": [0.0, 0.0, 0.8, 0.0, 0.0, 0.0, 0.0, 0.0],
    "afraid": [0.0, 0.0, 0.0, 0.8, 0.0, 0.0, 0.0, 0.0],
    "disgusted": [0.0, 0.0, 0.0, 0.0, 0.8, 0.0, 0.0, 0.0],
    "melancholic": [0.0, 0.0, 0.0, 0.0, 0.0, 0.8, 0.0, 0.0],
    "surprised": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8, 0.0],
    "calm": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8],
}


def emotion_spec(emotion: str | None) -> EmotionSpec | None:
    """把 Agent 情绪标签转成 IndexTTS 8 维向量；未知标签返回 None。"""

    vector = EMOTION_VECTORS.get(emotion or "")
    if vector is None:
        return None
    return EmotionSpec(mode="vector", vector=list(vector), alpha=0.8)


def build_synthesis_request(
    text: str,
    profile: VoiceProfile,
    *,
    emotion: str | None = None,
) -> SynthesisRequest:
    """按档案与 Agent 情绪组装 Provider 请求。

    - 档案显式配置的 ``emotion`` 优先（固定人设情感）；
    - 否则用 Agent 标签生成向量；
    - ``provider_options`` 透传 ``gpt_sovits`` 段（容器路径 / prompt），
      只对 legacy Provider 有意义，IndexTTS 会忽略。
    """

    options: dict[str, Any] = dict(profile.gpt_sovits or {})
    resolved_emotion = profile.emotion or emotion_spec(emotion)
    return SynthesisRequest(
        text=text,
        reference_audio=str(profile.reference_audio_path),
        language=profile.language,
        emotion=resolved_emotion,
        duration_factor=profile.duration_factor,
        provider_options=options,
    )


__all__ = ["EMOTION_VECTORS", "build_synthesis_request", "emotion_spec"]
