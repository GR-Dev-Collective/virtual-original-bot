"""``POST /tts``：默认音色、显式音色与未知音色。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT, settings
from app.main import app
from app.models.tts.base import SynthesisRequest, TtsUnavailable
from app.voices.registry import VoiceRegistry


class FakeProvider:
    def __init__(self, *, failure: str | None = None) -> None:
        self.failure = failure
        self.requests: list[SynthesisRequest] = []

    async def synthesize(self, request: SynthesisRequest) -> bytes:
        self.requests.append(request)
        if self.failure is not None:
            raise TtsUnavailable(self.failure)
        return b"RIFFfake-audio"


@pytest.fixture
def env(tmp_path, monkeypatch) -> Iterator[tuple[TestClient, FakeProvider, VoiceRegistry]]:
    monkeypatch.setattr(settings, "user_voice_directory", str(tmp_path / "voices"))
    monkeypatch.setattr(settings, "session_directory", str(tmp_path / "sessions"))
    monkeypatch.setattr(settings, "audio_directory", str(tmp_path / "audio"))
    with TestClient(app) as client:
        provider = FakeProvider()
        app.state.tts_provider = provider
        app.state.tts = provider
        yield client, provider, app.state.voices


def test_default_voice_uses_murasame_profile(env) -> None:
    client, provider, registry = env

    response = client.post("/tts", json={"text": "你好"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == b"RIFFfake-audio"
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.text == "你好"
    assert request.language == "ZH"
    assert request.reference_audio == str(
        REPO_ROOT / "assets" / "voices" / "murasame" / "murasame_ref.wav"
    )
    assert request.provider_options["prompt_text"] == "はっはっはっは"
    assert registry.default_voice_id == "murasame"


def test_explicit_voice_uses_its_profile(env, tmp_path) -> None:
    client, provider, registry = env
    reference = tmp_path / "clone.wav"
    reference.write_bytes(b"RIFF")
    profile = registry.register(
        display_name="Clone",
        reference_audio=reference,
        language="JA",
        duration_factor=0.8,
    )

    response = client.post("/tts", json={"text": "こんにちは", "voice_id": profile.id})

    assert response.status_code == 200
    request = provider.requests[0]
    assert request.reference_audio == str(reference.resolve())
    assert request.language == "JA"
    assert request.duration_factor == 0.8
    assert request.provider_options == {}


def test_unknown_voice_is_404(env) -> None:
    client, provider, _ = env

    response = client.post("/tts", json={"text": "你好", "voice_id": "missing"})

    assert response.status_code == 404
    assert "音色不存在" in response.json()["detail"]
    assert provider.requests == []


def test_tts_unavailable_is_503(env) -> None:
    client, provider, _ = env
    provider.failure = "sidecar 未启动"

    response = client.post("/tts", json={"text": "你好"})

    assert response.status_code == 503
    assert "sidecar 未启动" in response.json()["detail"]


def test_empty_text_is_validation_error(env) -> None:
    client, _, _ = env

    response = client.post("/tts", json={"text": ""})

    assert response.status_code == 422


def test_unknown_voice_id_in_registry_is_isolated(env, tmp_path) -> None:
    """确认显式 id 不做路径拼接，注册表查不到即 404。"""

    client, _, _ = env
    response = client.post("/tts", json={"text": "hi", "voice_id": "../../etc/passwd"})

    assert response.status_code == 404
    assert Path(tmp_path).exists()
