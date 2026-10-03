from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


class FakeAsr:
    def __init__(self, result: str = "你好") -> None:
        self.result = result
        self.calls: list[bytes] = []

    async def transcribe(self, audio_path: str) -> str:
        self.calls.append(Path(audio_path).read_bytes())
        return self.result


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        app.state.asr = FakeAsr()
        yield test_client


def test_asr_accepts_recording_and_returns_transcription(client: TestClient) -> None:
    response = client.post(
        "/asr",
        files={"audio": ("recording.webm", b"recorded audio", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "你好"}
    assert app.state.asr.calls == [b"recorded audio"]


def test_asr_rejects_empty_recording(client: TestClient) -> None:
    response = client.post(
        "/asr",
        files={"audio": ("recording.webm", b"", "audio/webm")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "录音为空"}
    assert app.state.asr.calls == []
