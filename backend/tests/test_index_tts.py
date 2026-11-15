"""IndexTtsProvider：请求形状与错误映射（httpx.MockTransport，无真实 sidecar）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from app.models.tts.base import EmotionSpec, SynthesisRequest, TtsUnavailable
from app.models.tts.index_tts import IndexTtsProvider


async def call_provider(
    handler: Callable[[httpx.Request], httpx.Response],
    request: SynthesisRequest,
) -> bytes:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        provider = IndexTtsProvider("http://index.test/", client, timeout=12.5)
        return await provider.synthesize(request)


def test_posts_full_payload_and_returns_audio() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.read())
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFFaudio")

    emotion = EmotionSpec(mode="vector", vector=[0.1, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], alpha=0.5)
    request = SynthesisRequest(
        text="你好",
        reference_audio="/abs/ref.wav",
        language="ZH",
        emotion=emotion,
        duration_factor=1.2,
        provider_options={"unused": True},
    )

    audio = asyncio.run(call_provider(handler, request))

    assert audio == b"RIFFaudio"
    assert captured["url"] == "http://index.test/synthesize"
    assert captured["json"] == {
        "text": "你好",
        "reference_audio": "/abs/ref.wav",
        "language": "ZH",
        "emotion": {
            "mode": "vector",
            "vector": [0.1, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "alpha": 0.5,
        },
        "duration_factor": 1.2,
    }
    # provider_options 属于 Port 内部约定，不发给 sidecar。
    assert "provider_options" not in captured["json"]


def test_omits_empty_fields_and_normalizes_language() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFF")

    request = SynthesisRequest(text="hello", language="ja")

    assert asyncio.run(call_provider(handler, request)) == b"RIFF"
    assert captured == {"text": "hello", "language": "JA", "duration_factor": 1.0}


def test_text_emotion_is_forwarded() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFF")

    request = SynthesisRequest(
        text="hello",
        reference_audio="/abs/ref.wav",
        emotion=EmotionSpec(mode="text", text="开心", alpha=0.7),
    )
    asyncio.run(call_provider(handler, request))

    assert captured["emotion"] == {"mode": "text", "text": "开心", "alpha": 0.7}


def test_rejects_non_audio_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"detail": "bad"})

    with pytest.raises(TtsUnavailable, match="无效音频"):
        asyncio.run(call_provider(handler, SynthesisRequest(text="hello")))


def test_rejects_empty_audio_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"")

    with pytest.raises(TtsUnavailable, match="无效音频"):
        asyncio.run(call_provider(handler, SynthesisRequest(text="hello")))


def test_http_error_includes_sidecar_detail() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"detail": {"code": "model_loading", "message": "模型尚未加载完成"}},
        )

    with pytest.raises(TtsUnavailable, match="model_loading"):
        asyncio.run(call_provider(handler, SynthesisRequest(text="hello")))


def test_transport_error_becomes_tts_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(TtsUnavailable, match="请求失败"):
        asyncio.run(call_provider(handler, SynthesisRequest(text="hello")))
