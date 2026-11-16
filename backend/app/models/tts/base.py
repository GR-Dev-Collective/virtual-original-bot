"""TTS Port 的公共类型。

运行时只依赖这里的 ``TtsProvider`` 协议；具体供应商（IndexTTS sidecar /
GPT-SoVITS legacy）在各自模块实现。参考音频路径一律由调用方解析为绝对路径，
Provider 不做仓库路径假设。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VALID_LANGUAGES = ("ZH", "EN", "JA", "ES", "AR")


class TtsUnavailable(RuntimeError):
    """TTS 供应商不可用（请求失败、返回非音频、超时等）。"""


class EmotionSpec(BaseModel):
    """IndexTTS 的情感控制参数。

    ``mode`` 决定使用哪个字段：``vector``（8 维向量）、``text``（文本描述）
    或 ``audio``（参考音频）。``alpha`` 是情感强度。
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["vector", "text", "audio"]
    vector: list[float] | None = None
    text: str | None = None
    audio: str | None = None
    alpha: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_value(self) -> EmotionSpec:
        if self.mode == "vector":
            if not self.vector:
                raise ValueError("emotion.mode=vector 时 vector 不能为空")
        elif self.mode == "text":
            if not self.text or not self.text.strip():
                raise ValueError("emotion.mode=text 时 text 不能为空")
        elif self.mode == "audio":
            if not self.audio or not self.audio.strip():
                raise ValueError("emotion.mode=audio 时 audio 不能为空")
        return self

    def to_payload(self) -> dict[str, Any]:
        """转成 sidecar 的 emotion 对象；只带当前 mode 对应的值。"""

        payload: dict[str, Any] = {"mode": self.mode, "alpha": self.alpha}
        if self.mode == "vector":
            payload["vector"] = list(self.vector or [])
        elif self.mode == "text":
            payload["text"] = self.text
        else:
            payload["audio"] = self.audio
        return payload


class SynthesisRequest(BaseModel):
    """一次合成请求（与协议/供应商解耦）。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    reference_audio: str | None = None
    language: str = "ZH"
    emotion: EmotionSpec | None = None
    duration_factor: float = Field(default=1.0, gt=0.0)
    provider_options: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, value: object) -> str:
        if isinstance(value, str):
            value = value.strip().upper()
        if value not in VALID_LANGUAGES:
            raise ValueError(f"不支持的语言：{value!r}（可选 {'/'.join(VALID_LANGUAGES)}）")
        return str(value)


@runtime_checkable
class TtsProvider(Protocol):
    async def synthesize(self, request: SynthesisRequest) -> bytes: ...


__all__ = [
    "EmotionSpec",
    "SynthesisRequest",
    "TtsProvider",
    "TtsUnavailable",
    "VALID_LANGUAGES",
]
