"""GPT-SoVITS legacy 适配器。

保留原有的 ``GptSovitsTts``（直接接受 ``TtsRequest``，供既有脚本/测试使用），
并新增实现 ``TtsProvider`` 的 ``GptSovitsProvider``。容器内的参考音频路径、
prompt 文本等 legacy 参数只来自音色档案的 ``gpt_sovits`` 段（见
``backend/config/voices.json``），代码里不再硬编码 ``/workspace`` 路径。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.models.tts.base import SynthesisRequest, TtsUnavailable

# IndexTTS 使用大写语种代码，legacy GPT-SoVITS 用小写。
LEGACY_LANGUAGES = {
    "ZH": "zh",
    "EN": "en",
    "JA": "ja",
    "ES": "es",
    "AR": "ar",
}


@dataclass(frozen=True)
class TtsRequest:
    text: str
    text_language: str = "zh"
    refer_wav_path: str | None = None
    prompt_text: str | None = None
    prompt_language: str | None = None


class GptSovitsTts:
    def __init__(self, base_url: str, client: httpx.AsyncClient, timeout: float = 180.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    async def synthesize(self, request: TtsRequest) -> bytes:
        payload = {
            "text": request.text,
            "text_language": request.text_language,
        }
        for key in ("refer_wav_path", "prompt_text", "prompt_language"):
            value = getattr(request, key)
            if value is not None:
                payload[key] = value

        try:
            response = await self._client.post(
                self._base_url,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TtsUnavailable(f"GPT-SoVITS 请求失败: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("audio/") or not response.content:
            raise TtsUnavailable("GPT-SoVITS 返回了无效音频")
        return response.content


class GptSovitsProvider:
    """把通用 ``SynthesisRequest`` 映射到 legacy GPT-SoVITS payload。

    ``provider_options`` 里的 ``refer_wav_path`` / ``prompt_text`` /
    ``prompt_language`` 优先（容器内路径），缺省时退回请求里的参考音频。
    """

    def __init__(self, base_url: str, client: httpx.AsyncClient, timeout: float = 180.0) -> None:
        self._tts = GptSovitsTts(base_url, client, timeout=timeout)

    async def synthesize(self, request: SynthesisRequest) -> bytes:
        options = request.provider_options or {}
        refer_wav_path = _text_option(options.get("refer_wav_path")) or request.reference_audio
        prompt_text = _text_option(options.get("prompt_text"))
        prompt_language = _text_option(options.get("prompt_language"))
        text_language = (
            _text_option(options.get("text_language"))
            or LEGACY_LANGUAGES.get(request.language)
            or request.language.lower()
        )

        return await self._tts.synthesize(
            TtsRequest(
                text=request.text,
                text_language=text_language,
                refer_wav_path=refer_wav_path,
                prompt_text=prompt_text,
                prompt_language=prompt_language,
            )
        )


def _text_option(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


__all__ = [
    "GptSovitsProvider",
    "GptSovitsTts",
    "LEGACY_LANGUAGES",
    "TtsRequest",
    "TtsUnavailable",
]
