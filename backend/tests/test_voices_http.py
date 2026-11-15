"""``/voices`` HTTP：列表、克隆上传（PyAV 规范化）、删除与错误码。"""

from __future__ import annotations

import io
import json
import re
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def wav_bytes(seconds: float, *, sample_rate: int = 16_000, channels: int = 1) -> bytes:
    frames = int(sample_rate * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * frames * channels)
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "user_voice_directory", str(tmp_path / "voices"))
    monkeypatch.setattr(settings, "session_directory", str(tmp_path / "sessions"))
    monkeypatch.setattr(settings, "audio_directory", str(tmp_path / "audio"))
    with TestClient(app) as test_client:
        yield test_client


def upload_wav(client: TestClient, *, name: str, seconds: float, language: str = "ZH"):
    return client.post(
        "/voices",
        data={"name": name, "language": language},
        files={"audio": ("reference.wav", wav_bytes(seconds), "audio/wav")},
    )


def test_get_lists_builtin_default_voice(client: TestClient) -> None:
    response = client.get("/voices")

    assert response.status_code == 200
    body = response.json()
    assert body["default_voice_id"] == "murasame"
    assert body["voices"] == [
        {
            "id": "murasame",
            "display_name": "丛雨",
            "language": "ZH",
            "description": body["voices"][0]["description"],
            "is_builtin": True,
        }
    ]
    assert "零样本" in body["voices"][0]["description"]


def test_post_clones_voice_and_normalizes_wav(client: TestClient, tmp_path) -> None:
    response = upload_wav(client, name="测试音色", seconds=1.5, language="zh")

    assert response.status_code == 201, response.text
    profile = response.json()
    assert re.fullmatch(r"[a-z0-9_-]+", profile["id"])
    assert profile["display_name"] == "测试音色"
    assert profile["language"] == "ZH"
    assert profile["is_builtin"] is False

    reference = tmp_path / "voices" / profile["id"] / "reference.wav"
    assert reference.is_file()
    with wave.open(str(reference), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16_000  # WAV 源保留采样率
        assert audio.getnframes() == 24_000

    profiles = json.loads((tmp_path / "voices" / "profiles.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in profiles["voices"]] == [profile["id"]]
    stored = Path(profiles["voices"][0]["reference_audio"])
    assert stored.name == "reference.wav"
    assert stored.parent.name == profile["id"]

    listed = client.get("/voices").json()["voices"]
    assert {item["id"] for item in listed} == {"murasame", profile["id"]}


def test_post_rejects_too_short_audio(client: TestClient) -> None:
    response = upload_wav(client, name="太短", seconds=0.4)

    assert response.status_code == 400
    assert "时长" in response.json()["detail"]
    assert [item["id"] for item in client.get("/voices").json()["voices"]] == ["murasame"]


def test_post_rejects_empty_audio(client: TestClient) -> None:
    response = client.post(
        "/voices",
        data={"name": "空文件", "language": "ZH"},
        files={"audio": ("reference.wav", b"", "audio/wav")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "参考音频为空"


def test_post_rejects_unsupported_language(client: TestClient) -> None:
    response = upload_wav(client, name="坏语种", seconds=1.0, language="XX")

    assert response.status_code == 400
    assert "语种" in response.json()["detail"]


def test_post_rejects_undecodable_audio(client: TestClient) -> None:
    response = client.post(
        "/voices",
        data={"name": "坏音频", "language": "ZH"},
        files={"audio": ("reference.wav", b"not an audio file", "audio/wav")},
    )

    assert response.status_code == 400
    assert "解码" in response.json()["detail"]


def test_delete_builtin_voice_is_conflict(client: TestClient) -> None:
    response = client.delete("/voices/murasame")

    assert response.status_code == 409
    assert "内置" in response.json()["detail"]
    assert client.get("/voices").json()["voices"][0]["id"] == "murasame"


def test_delete_unknown_voice_is_not_found(client: TestClient) -> None:
    response = client.delete("/voices/does-not-exist")

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_delete_user_voice_removes_files(client: TestClient, tmp_path) -> None:
    profile = upload_wav(client, name="待删除", seconds=1.0).json()

    response = client.delete(f"/voices/{profile['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert not (tmp_path / "voices" / profile["id"]).exists()
    assert [item["id"] for item in client.get("/voices").json()["voices"]] == ["murasame"]
    assert client.delete(f"/voices/{profile['id']}").status_code == 404
