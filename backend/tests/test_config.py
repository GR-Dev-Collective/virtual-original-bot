import pytest

from app.config import Settings
from app.models.tts.factory import build_tts_provider
from app.models.tts.gpt_sovits import GptSovitsProvider
from app.models.tts.index_tts import IndexTtsProvider


def test_asr_defaults_run_without_host_cuda_libraries() -> None:
    settings = Settings(_env_file=None)

    assert settings.asr_device == "cpu"
    assert settings.asr_compute_type == "int8"


def test_tts_and_voice_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.tts_provider == "index_tts"
    assert settings.index_tts_base_url == "http://127.0.0.1:9882"
    assert settings.index_tts_timeout_seconds == 180.0
    assert settings.voice_profiles_path == "config/voices.json"
    assert settings.user_voice_directory == "runtime/voices"
    assert settings.default_voice_id == "murasame"
    # legacy 配置保留
    assert settings.gpt_sovits_base_url == "http://127.0.0.1:9880/"


def test_unknown_tts_provider_fails_loudly() -> None:
    settings = Settings(_env_file=None)
    settings.tts_provider = "bogus"

    with pytest.raises(ValueError, match="未知的 TTS provider"):
        build_tts_provider(settings, None)  # type: ignore[arg-type]


def test_factory_builds_default_and_legacy_providers() -> None:
    settings = Settings(_env_file=None)
    assert isinstance(build_tts_provider(settings, None), IndexTtsProvider)  # type: ignore[arg-type]

    settings.tts_provider = "gpt_sovits"
    provider = build_tts_provider(settings, None)  # type: ignore[arg-type]
    assert isinstance(provider, GptSovitsProvider)
