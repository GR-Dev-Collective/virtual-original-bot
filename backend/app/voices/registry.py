"""音色档案注册表。

- 内置档案：``backend/config/voices.json``（随仓库发布，不可删除）。
- 用户档案：``backend/runtime/voices/profiles.json``（克隆产生的档案，用户优先）。
- 参考音频路径相对仓库根解析；用户档案优先存相对仓库根路径，仓库外路径存绝对路径。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import BACKEND_ROOT
from app.voices.models import (
    VOICE_ID_PATTERN,
    BuiltinVoiceProtected,
    VoiceNotFound,
    VoiceProfile,
)

logger = logging.getLogger(__name__)

DEFAULT_VOICE_ID = "murasame"
BUILTIN_PROFILES_PATH = "config/voices.json"
USER_VOICE_DIRECTORY = "runtime/voices"
PROFILES_FILENAME = "profiles.json"
REFERENCE_AUDIO_FILENAME = "reference.wav"

_SLUG_SEPARATOR = re.compile(r"[^a-z0-9_-]+")


class VoiceRegistry:
    def __init__(
        self,
        builtin_path: str | Path = BUILTIN_PROFILES_PATH,
        user_directory: str | Path = USER_VOICE_DIRECTORY,
        *,
        default_voice_id: str | None = None,
        root: Path = BACKEND_ROOT,
    ) -> None:
        self._builtin_path = _resolve(root, builtin_path)
        self._user_directory = _resolve(root, user_directory)
        self._profiles_path = self._user_directory / PROFILES_FILENAME
        self._default_override = default_voice_id
        self._default_voice_id = default_voice_id or DEFAULT_VOICE_ID
        self._builtin: dict[str, VoiceProfile] = {}
        self._user: dict[str, VoiceProfile] = {}
        self.reload()

    # ------------------------------------------------------------------ 属性

    @property
    def builtin_path(self) -> Path:
        return self._builtin_path

    @property
    def user_directory(self) -> Path:
        return self._user_directory

    @property
    def profiles_path(self) -> Path:
        return self._profiles_path

    @property
    def default_voice_id(self) -> str:
        return self._default_voice_id

    @property
    def default_profile(self) -> VoiceProfile:
        return self.get(self._default_voice_id)

    # ------------------------------------------------------------------ 读取

    def reload(self) -> None:
        builtin_data = _read_json(self._builtin_path)
        builtin_voices = _extract_voices(builtin_data)
        self._builtin = {}
        for raw in builtin_voices:
            try:
                profile = VoiceProfile.model_validate({**raw, "builtin": True})
            except Exception as exc:  # noqa: BLE001 - 内置档案损坏必须启动即失败
                raise ValueError(f"内置音色档案无效（{self._builtin_path}）：{exc}") from exc
            self._builtin[profile.id] = profile

        configured_default = builtin_data.get("default_voice_id") if builtin_data else None
        self._default_voice_id = (
            self._default_override or str(configured_default or "") or DEFAULT_VOICE_ID
        )

        user_data = _read_json(self._profiles_path)
        self._user = {}
        for raw in _extract_voices(user_data):
            try:
                profile = VoiceProfile.model_validate({**raw, "builtin": False})
            except Exception as exc:  # noqa: BLE001 - 单个坏档案不阻塞启动
                logger.warning("忽略无效的用户音色档案（%s）：%s", self._profiles_path, exc)
                continue
            self._user[profile.id] = profile

    def list(self) -> list[VoiceProfile]:
        merged: dict[str, VoiceProfile] = dict(self._builtin)
        merged.update(self._user)
        return list(merged.values())

    def get(self, voice_id: str) -> VoiceProfile:
        profile = self._user.get(voice_id) or self._builtin.get(voice_id)
        if profile is None:
            raise VoiceNotFound(voice_id)
        return profile

    def default_profile_or_none(self) -> VoiceProfile | None:
        try:
            return self.default_profile
        except VoiceNotFound:
            return None

    def reference_path(self, voice_id: str) -> Path:
        """用户克隆档案的规范化参考音频落盘位置。"""

        if not VOICE_ID_PATTERN.fullmatch(voice_id):
            raise ValueError("无效的音色 id")
        return self._user_directory / voice_id / REFERENCE_AUDIO_FILENAME

    def allocate_id(self, display_name: str) -> str:
        base = _slugify(display_name)
        candidate = base
        index = 2
        taken = set(self._builtin) | set(self._user)
        while candidate in taken:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    # ------------------------------------------------------------------ 写入

    def register(
        self,
        *,
        display_name: str,
        reference_audio: str | Path,
        language: str = "ZH",
        voice_id: str | None = None,
        description: str = "",
        emotion: Any = None,
        duration_factor: float = 1.0,
        gpt_sovits: dict[str, Any] | None = None,
    ) -> VoiceProfile:
        profile_id = voice_id or self.allocate_id(display_name)
        if profile_id in self._builtin:
            raise BuiltinVoiceProtected(profile_id)
        profile = VoiceProfile(
            id=profile_id,
            display_name=display_name,
            language=language,
            reference_audio=_store_reference_path(Path(reference_audio)),
            description=description,
            emotion=emotion,
            duration_factor=duration_factor,
            builtin=False,
            gpt_sovits=gpt_sovits,
        )
        self._user[profile.id] = profile
        self._persist()
        return profile

    def delete(self, voice_id: str) -> None:
        profile = self._user.pop(voice_id, None)
        if profile is None:
            if voice_id in self._builtin:
                raise BuiltinVoiceProtected(voice_id)
            raise VoiceNotFound(voice_id)
        self._persist()
        self._remove_directory(profile.id)

    def _persist(self) -> None:
        self._user_directory.mkdir(parents=True, exist_ok=True)
        data = {"voices": [profile.to_json() for profile in self._user.values()]}
        _write_json_atomic(self._profiles_path, data)

    def _remove_directory(self, voice_id: str) -> None:
        directory = (self._user_directory / voice_id).resolve()
        root = self._user_directory.resolve()
        if directory == root or not directory.is_relative_to(root):
            logger.warning("拒绝删除音色目录之外的路径：%s", directory)
            return
        shutil.rmtree(directory, ignore_errors=True)


# --------------------------------------------------------------------- 工具


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取音色档案：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"音色档案必须是 JSON 对象：{path}")
    return data


def _extract_voices(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_voices = data.get("voices")
    if raw_voices is None:
        return []
    if not isinstance(raw_voices, list):
        raise ValueError("voices 必须是数组")
    return [item for item in raw_voices if isinstance(item, dict)]


def _slugify(value: str) -> str:
    slug = _SLUG_SEPARATOR.sub("-", value.strip().lower()).strip("-_")
    if not slug:
        return f"voice-{uuid4().hex[:8]}"
    return slug


def _store_reference_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(BACKEND_ROOT.parent).as_posix()
    except ValueError:
        return str(resolved)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


__all__ = [
    "BUILTIN_PROFILES_PATH",
    "DEFAULT_VOICE_ID",
    "PROFILES_FILENAME",
    "REFERENCE_AUDIO_FILENAME",
    "USER_VOICE_DIRECTORY",
    "VoiceRegistry",
]
