from dataclasses import dataclass

import httpx


class TtsUnavailable(RuntimeError):
    pass


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
