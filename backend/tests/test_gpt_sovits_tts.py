import asyncio

import httpx
import pytest

from app.models.tts.gpt_sovits import GptSovitsTts, TtsRequest, TtsUnavailable


def test_synthesizes_audio() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://tts.test")
        assert request.read() == b'{"text":"hello","text_language":"ja"}'
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFFaudio")

    async def run() -> bytes:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            tts = GptSovitsTts("http://tts.test/", client)
            return await tts.synthesize(TtsRequest(text="hello", text_language="ja"))

    assert asyncio.run(run()) == b"RIFFaudio"


def test_rejects_non_audio_response() -> None:
    async def run() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"error": "bad"}))
        async with httpx.AsyncClient(transport=transport) as client:
            tts = GptSovitsTts("http://tts.test/", client)
            with pytest.raises(TtsUnavailable, match="无效音频"):
                await tts.synthesize(TtsRequest(text="hello"))

    asyncio.run(run())
