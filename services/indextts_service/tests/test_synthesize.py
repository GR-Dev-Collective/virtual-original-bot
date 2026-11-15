"""POST /synthesize 的成功路径（MockEngine）。"""

from __future__ import annotations

import io
import wave

from services.indextts_service.engine import MOCK_SAMPLE_RATE


def test_mock_synthesize_returns_wav(client, payload):
    response = client.post("/synthesize", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["x-sample-rate"] == str(MOCK_SAMPLE_RATE)
    assert response.content[:4] == b"RIFF"
    assert response.content[8:12] == b"WAVE"

    with wave.open(io.BytesIO(response.content), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == MOCK_SAMPLE_RATE
        assert wav_file.getnframes() == int(MOCK_SAMPLE_RATE * 0.5)


def test_synthesize_accepts_optional_parameters(client, payload, ref_audio):
    body = dict(payload)
    body.update(
        {
            "language": "ja",
            "duration_factor": 1.25,
            "text_normalization": False,
            "max_text_tokens_per_segment": 80,
            "request_id": "req-123",
            "emotion": {
                "mode": "vector",
                "vector": [0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "alpha": 0.5,
            },
        }
    )
    response = client.post("/synthesize", json=body)
    assert response.status_code == 200
    assert response.content[:4] == b"RIFF"


def test_synthesize_accepts_audio_emotion(client, payload, ref_audio):
    body = dict(payload)
    body["emotion"] = {"mode": "audio", "audio": str(ref_audio), "alpha": 0.7}
    response = client.post("/synthesize", json=body)
    assert response.status_code == 200


def test_synthesize_accepts_text_emotion(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "text", "text": "开心地说话", "alpha": 0.6}
    response = client.post("/synthesize", json=body)
    assert response.status_code == 200
