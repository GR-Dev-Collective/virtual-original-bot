"""VoiceRegistry：内置/用户档案加载、路径解析、注册与删除。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import REPO_ROOT
from app.voices.models import (
    BuiltinVoiceProtected,
    VoiceNotFound,
    VoiceProfile,
)
from app.voices.registry import VoiceRegistry


@pytest.fixture
def registry(tmp_path) -> VoiceRegistry:
    return VoiceRegistry("config/voices.json", tmp_path / "voices")


def test_loads_builtin_murasame_profile(registry: VoiceRegistry) -> None:
    assert registry.default_voice_id == "murasame"
    profile = registry.get("murasame")

    assert profile.id == "murasame"
    assert profile.display_name == "丛雨"
    assert profile.language == "ZH"
    assert profile.builtin is True
    assert "零样本" in profile.description
    assert profile.reference_audio == "assets/voices/murasame/murasame_ref.wav"
    assert profile.reference_audio_path == (
        REPO_ROOT / "assets" / "voices" / "murasame" / "murasame_ref.wav"
    )
    assert profile.reference_audio_path.is_file()
    assert profile.gpt_sovits == {
        "refer_wav_path": "/workspace/data/references/murasame_ref.ogg",
        "prompt_text": "はっはっはっは",
        "prompt_language": "ja",
    }


def test_profiles_list_keeps_builtin_flag(registry: VoiceRegistry) -> None:
    profiles = registry.list()
    assert [profile.id for profile in profiles] == ["murasame"]
    assert profiles[0].builtin is True


def test_user_profile_overrides_builtin(tmp_path) -> None:
    user_dir = tmp_path / "voices"
    user_dir.mkdir()
    (user_dir / "profiles.json").write_text(
        json.dumps(
            {
                "voices": [
                    {
                        "id": "murasame",
                        "display_name": "用户丛雨",
                        "language": "JA",
                        "reference_audio": "runtime/voices/murasame/reference.wav",
                        "description": "用户覆盖",
                        "builtin": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = VoiceRegistry("config/voices.json", user_dir)

    profile = registry.get("murasame")
    assert profile.display_name == "用户丛雨"
    assert profile.language == "JA"
    assert profile.builtin is False
    assert len(registry.list()) == 1


def test_register_persists_user_profile(registry: VoiceRegistry, tmp_path) -> None:
    reference = tmp_path / "ref.wav"
    reference.write_bytes(b"RIFF")

    profile = registry.register(
        display_name="Test Voice",
        reference_audio=reference,
        language="ja",
        emotion={"mode": "text", "text": "平静", "alpha": 0.6},
        duration_factor=0.9,
    )

    assert profile.id == "test-voice"
    assert profile.language == "JA"
    assert profile.builtin is False
    assert profile.duration_factor == 0.9
    assert profile.emotion is not None and profile.emotion.mode == "text"
    assert registry.get(profile.id) is not None

    data = json.loads(registry.profiles_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in data["voices"]] == ["test-voice"]
    assert data["voices"][0]["reference_audio"] == str(reference.resolve())


def test_allocate_id_avoids_collisions(registry: VoiceRegistry) -> None:
    assert registry.allocate_id("Test") == "test"
    assert registry.allocate_id("测试音色").startswith("voice-")


def test_register_same_name_gets_suffix(registry: VoiceRegistry, tmp_path) -> None:
    reference = tmp_path / "ref.wav"
    reference.write_bytes(b"RIFF")

    first = registry.register(display_name="Clone", reference_audio=reference)
    second = registry.register(display_name="Clone", reference_audio=reference)

    assert first.id == "clone"
    assert second.id == "clone-2"
    assert {profile.id for profile in registry.list()} == {"murasame", "clone", "clone-2"}


def test_delete_removes_user_profile_and_directory(registry: VoiceRegistry, tmp_path) -> None:
    reference = registry.reference_path("tmp-voice")
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"RIFF")
    profile = registry.register(
        display_name="Tmp Voice",
        reference_audio=reference,
        voice_id="tmp-voice",
    )

    registry.delete(profile.id)

    assert reference.parent.exists() is False
    with pytest.raises(VoiceNotFound):
        registry.get(profile.id)
    assert json.loads(registry.profiles_path.read_text(encoding="utf-8"))["voices"] == []


def test_delete_builtin_is_refused(registry: VoiceRegistry) -> None:
    with pytest.raises(BuiltinVoiceProtected):
        registry.delete("murasame")


def test_delete_unknown_is_not_found(registry: VoiceRegistry) -> None:
    with pytest.raises(VoiceNotFound):
        registry.delete("missing")


def test_get_unknown_is_not_found(registry: VoiceRegistry) -> None:
    with pytest.raises(VoiceNotFound):
        registry.get("missing")


def test_profile_id_must_be_path_safe() -> None:
    with pytest.raises(ValidationError):
        VoiceProfile(
            id="../evil",
            display_name="evil",
            reference_audio="assets/voices/murasame/murasame_ref.wav",
        )
    with pytest.raises(ValidationError):
        VoiceProfile(
            id="UPPER",
            display_name="evil",
            reference_audio="assets/voices/murasame/murasame_ref.wav",
        )


def test_reference_audio_relative_to_repo_root() -> None:
    profile = VoiceProfile(
        id="example",
        display_name="Example",
        reference_audio="assets/voices/murasame/murasame_ref.wav",
    )
    assert profile.reference_audio_path == Path(
        REPO_ROOT / "assets" / "voices" / "murasame" / "murasame_ref.wav"
    )
