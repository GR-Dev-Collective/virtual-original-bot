"""请求参数校验分支：全部应返回 422 + invalid_request。"""

from __future__ import annotations

from pathlib import Path

import pytest


def _assert_invalid(response) -> None:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"]["code"] == "invalid_request"
    message = body["detail"]["message"]
    assert isinstance(message, str)
    assert message.strip()


def test_unknown_emotion_mode(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "video", "vector": [0.1] * 8}
    _assert_invalid(client.post("/synthesize", json=body))


def test_missing_text(client, payload):
    body = dict(payload)
    body.pop("text")
    _assert_invalid(client.post("/synthesize", json=body))


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_invalid_text(client, payload, text):
    body = dict(payload)
    body["text"] = text
    _assert_invalid(client.post("/synthesize", json=body))


def test_relative_reference_audio(client, payload):
    body = dict(payload)
    body["reference_audio"] = "murasame_ref.wav"
    _assert_invalid(client.post("/synthesize", json=body))


def test_missing_reference_audio(client, payload, ref_audio: Path):
    body = dict(payload)
    body["reference_audio"] = str(ref_audio.parent / "missing.wav")
    _assert_invalid(client.post("/synthesize", json=body))


def test_reference_audio_directory(client, payload, ref_audio: Path):
    body = dict(payload)
    body["reference_audio"] = str(ref_audio.parent)
    _assert_invalid(client.post("/synthesize", json=body))


def test_invalid_language(client, payload):
    body = dict(payload)
    body["language"] = "FR"
    _assert_invalid(client.post("/synthesize", json=body))


@pytest.mark.parametrize("duration_factor", [0.4, 2.1])
def test_invalid_duration_factor(client, payload, duration_factor):
    body = dict(payload)
    body["duration_factor"] = duration_factor
    _assert_invalid(client.post("/synthesize", json=body))


def test_invalid_max_text_tokens(client, payload):
    body = dict(payload)
    body["max_text_tokens_per_segment"] = 0
    _assert_invalid(client.post("/synthesize", json=body))


def test_vector_must_have_eight_values(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "vector", "vector": [0.1] * 7}
    _assert_invalid(client.post("/synthesize", json=body))


def test_vector_value_out_of_range(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "vector", "vector": [0.0] * 7 + [1.1]}
    _assert_invalid(client.post("/synthesize", json=body))


def test_vector_sum_above_limit(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "vector", "vector": [0.2] * 8}
    _assert_invalid(client.post("/synthesize", json=body))


def test_vector_alpha_out_of_range(client, payload):
    body = dict(payload)
    body["emotion"] = {
        "mode": "vector",
        "vector": [0.1] * 8,
        "alpha": 1.5,
    }
    _assert_invalid(client.post("/synthesize", json=body))


def test_vector_missing_vector(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "vector"}
    _assert_invalid(client.post("/synthesize", json=body))


@pytest.mark.parametrize("text", ["", "   "])
def test_text_emotion_empty(client, payload, text):
    body = dict(payload)
    body["emotion"] = {"mode": "text", "text": text}
    _assert_invalid(client.post("/synthesize", json=body))


def test_text_emotion_missing_text(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "text"}
    _assert_invalid(client.post("/synthesize", json=body))


def test_audio_emotion_missing_file(client, payload, ref_audio: Path):
    body = dict(payload)
    body["emotion"] = {
        "mode": "audio",
        "audio": str(ref_audio.parent / "missing.wav"),
    }
    _assert_invalid(client.post("/synthesize", json=body))


def test_audio_emotion_relative_path(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "audio", "audio": "ref.wav"}
    _assert_invalid(client.post("/synthesize", json=body))


def test_audio_emotion_missing_audio(client, payload):
    body = dict(payload)
    body["emotion"] = {"mode": "audio"}
    _assert_invalid(client.post("/synthesize", json=body))


def test_emotion_modes_are_exclusive(client, payload):
    body = dict(payload)
    body["emotion"] = {
        "mode": "vector",
        "vector": [0.1] * 8,
        "text": "开心",
    }
    _assert_invalid(client.post("/synthesize", json=body))
