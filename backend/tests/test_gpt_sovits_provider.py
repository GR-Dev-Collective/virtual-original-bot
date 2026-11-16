"""GptSovitsProvider：legacy payload 映射（provider_options 来自音色档案）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from app.models.tts.base import SynthesisRequest, TtsUnavailable
from app.models.tts.gpt_sovits import GptSovitsProvider


async def call_provider(
    handler: Callable[[httpx.Request], httpx.Response],
    request: SynthesisRequest,
) -> bytes:
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        provider = GptSovitsProvider("http://tts.test/", client)
        return await provider.synthesize(request)


def test_maps_profile_options_to_legacy_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.read())
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFFaudio")

    request = SynthesisRequest(
        text="こんにちは",
        reference_audio="/repo/assets/voices/murasame/murasame_ref.wav",
        language="JA",
        provider_options={
            "refer_wav_path": "/workspace/data/references/murasame_ref.ogg",
            "prompt_text": "はっはっはっは",
            "prompt_language": "ja",
        },
    )

    assert asyncio.run(call_provider(handler, request)) == b"RIFFaudio"
    assert captured["url"] == "http://tts.test"
    assert captured["json"] == {
        "text": "こんにちは",
        "text_language": "ja",
        "refer_wav_path": "/workspace/data/references/murasame_ref.ogg",
        "prompt_text": "はっはっはっは",
        "prompt_language": "ja",
    }


def test_falls_back_to_request_reference_audio_and_language() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFF")

    request = SynthesisRequest(text="hello", reference_audio="/abs/ref.wav", language="zh")
    asyncio.run(call_provider(handler, request))

    assert captured == {
        "text": "hello",
        "text_language": "zh",
        "refer_wav_path": "/abs/ref.wav",
    }


def test_provider_options_text_language_overrides_mapping() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFF")

    request = SynthesisRequest(
        text="hello",
        language="ZH",
        provider_options={"text_language": "auto"},
    )
    asyncio.run(call_provider(handler, request))
    assert captured["text_language"] == "auto"


def test_provider_rejects_non_audio() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"detail": "bad"})

    with pytest.raises(TtsUnavailable, match="无效音频"):
        asyncio.run(call_provider(handler, SynthesisRequest(text="hello")))


def test_provider_maps_http_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(TtsUnavailable, match="请求失败"):
        asyncio.run(call_provider(handler, SynthesisRequest(text="hello")))
