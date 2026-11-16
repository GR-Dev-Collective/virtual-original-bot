"""音色档案领域模型。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import REPO_ROOT
from app.models.tts.base import VALID_LANGUAGES, EmotionSpec

VOICE_ID_PATTERN = re.compile(r"\A[a-z0-9_-]{1,64}\Z")


class VoiceNotFound(LookupError):
    """音色 id 未注册。"""

    def __init__(self, voice_id: str) -> None:
        super().__init__(voice_id)
        self.voice_id = voice_id

    def __str__(self) -> str:
        return f"音色不存在：{self.voice_id}"


class BuiltinVoiceProtected(ValueError):
    """内置音色不允许删除。"""

    def __init__(self, voice_id: str) -> None:
        super().__init__(voice_id)
        self.voice_id = voice_id

    def __str__(self) -> str:
        return f"内置音色不可删除：{self.voice_id}"


class VoiceProfile(BaseModel):
    """一个音色档案。

    ``reference_audio`` 保存档案里的原始路径：内置档案相对仓库根，用户档案优先
    存相对仓库根的路径（仓库外路径则保留绝对路径）。Provider 只接受
    ``reference_audio_path`` 解析后的绝对路径。
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str = Field(min_length=1)
    language: str = "ZH"
    reference_audio: str = Field(min_length=1)
    description: str = ""
    emotion: EmotionSpec | None = None
    duration_factor: float = Field(default=1.0, gt=0.0)
    builtin: bool = False
    gpt_sovits: dict[str, Any] | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not VOICE_ID_PATTERN.fullmatch(value):
            raise ValueError("音色 id 只能包含小写字母、数字、下划线和连字符（1-64 位）")
        return value

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("音色名称不能为空")
        return stripped

    @field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, value: object) -> str:
        if isinstance(value, str):
            value = value.strip().upper()
        if value not in VALID_LANGUAGES:
            raise ValueError(f"不支持的语言：{value!r}（可选 {'/'.join(VALID_LANGUAGES)}）")
        return str(value)

    @property
    def reference_audio_path(self) -> Path:
        path = Path(self.reference_audio)
        if path.is_absolute():
            return path
        return (REPO_ROOT / path).resolve()

    def to_public_dict(self) -> dict[str, Any]:
        """``/voices`` 返回给客户端的形状。"""

        return {
            "id": self.id,
            "display_name": self.display_name,
            "language": self.language,
            "description": self.description,
            "is_builtin": self.builtin,
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "language": self.language,
            "reference_audio": self.reference_audio,
            "description": self.description,
            "emotion": self.emotion.to_payload() if self.emotion is not None else None,
            "duration_factor": self.duration_factor,
            "builtin": self.builtin,
            "gpt_sovits": self.gpt_sovits,
        }


__all__ = [
    "BuiltinVoiceProtected",
    "VOICE_ID_PATTERN",
    "VoiceNotFound",
    "VoiceProfile",
]
