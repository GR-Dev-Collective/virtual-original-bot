"""HTTP 请求/响应模型与参数校验。

校验失败统一由 app 层转换为 422 + ``invalid_request``。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VALID_LANGUAGES = ("ZH", "EN", "JA", "ES", "AR")
EMOTION_VECTOR_SIZE = 8
EMOTION_VECTOR_MAX_SUM = 0.8


def _validate_audio_file(value: str) -> str:
    """路径必须是绝对路径、存在、是文件且可读。"""
    if not value or not value.strip():
        msg = "音频路径不能为空"
        raise ValueError(msg)
    path = Path(value)
    if not path.is_absolute():
        msg = f"音频路径必须是绝对路径: {value}"
        raise ValueError(msg)
    if not path.is_file():
        msg = f"音频文件不存在或不是普通文件: {value}"
        raise ValueError(msg)
    if not os.access(path, os.R_OK):
        msg = f"音频文件不可读: {value}"
        raise ValueError(msg)
    return str(path)


Alpha = Annotated[float, Field(ge=0.0, le=1.0)]
EmotionValue = Annotated[float, Field(ge=0.0, le=1.0)]


class EmotionVector(BaseModel):
    """8 维情感向量，各维 0..1 且总和不超过 0.8。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["vector"]
    vector: list[EmotionValue] = Field(
        min_length=EMOTION_VECTOR_SIZE,
        max_length=EMOTION_VECTOR_SIZE,
    )
    alpha: Alpha = 1.0

    @model_validator(mode="after")
    def _validate_sum(self) -> EmotionVector:
        total = sum(self.vector)
        if total > EMOTION_VECTOR_MAX_SUM:
            msg = (
                "emotion.vector 各维总和必须 ≤ "
                f"{EMOTION_VECTOR_MAX_SUM}，当前为 {total:.3f}"
            )
            raise ValueError(msg)
        return self


class EmotionText(BaseModel):
    """文本情感描述，由 QwenEmotion 转成向量。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["text"]
    text: str
    alpha: Alpha = 1.0

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if not value.strip():
            msg = "emotion.text 不能为空"
            raise ValueError(msg)
        return value


class EmotionAudio(BaseModel):
    """参考情感音频路径。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["audio"]
    audio: str
    alpha: Alpha = 1.0

    @field_validator("audio")
    @classmethod
    def _validate_audio(cls, value: str) -> str:
        return _validate_audio_file(value)


Emotion = Annotated[
    EmotionVector | EmotionText | EmotionAudio,
    Field(discriminator="mode"),
]


class SynthesisRequest(BaseModel):
    """``POST /synthesize`` 请求体。"""

    text: str = Field(min_length=1, max_length=2000)
    reference_audio: str
    language: Literal["ZH", "EN", "JA", "ES", "AR"] = "ZH"
    emotion: Emotion | None = None
    duration_factor: float = Field(default=1.0, ge=0.5, le=2.0)
    text_normalization: bool = True
    max_text_tokens_per_segment: int = Field(default=120, ge=1)
    request_id: str | None = None

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if not value.strip():
            msg = "text 不能为空"
            raise ValueError(msg)
        return value

    @field_validator("reference_audio")
    @classmethod
    def _validate_reference_audio(cls, value: str) -> str:
        return _validate_audio_file(value)

    @field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value
