"""IndexTTS-2.5 sidecar 适配器。

sidecar 契约（``services/indextts_service``）：

    POST {base_url}/synthesize
    {"text": ..., "reference_audio": "/abs/path.wav", "language": "ZH",
     "emotion": {"mode": "vector", "vector": [...], "alpha": 0.8},
     "duration_factor": 1.0}
    → 200 audio/wav

只发送非空字段；sidecar 校验失败（422）、模型未加载（503）等 HTTP 错误与
传输错误统一转成 ``TtsUnavailable``，由运行时映射为 tts.failed。
"""

from __future__ import annotations

import httpx

from app.models.tts.base import (
    SynthesisRequest,
    TtsUnavailable,
)


class IndexTtsProvider:
    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient,
        timeout: float = 180.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    async def synthesize(self, request: SynthesisRequest) -> bytes:
        payload = self._payload(request)
        try:
            response = await self._client.post(
                f"{self._base_url}/synthesize",
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TtsUnavailable(
                f"IndexTTS 返回 HTTP {exc.response.status_code}: {_detail(exc.response)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise TtsUnavailable(f"IndexTTS 请求失败: {exc}") from exc

        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("audio/") or not response.content:
            raise TtsUnavailable("IndexTTS 返回了无效音频")
        return response.content

    @staticmethod
    def _payload(request: SynthesisRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "text": request.text,
            "language": request.language,
            "duration_factor": request.duration_factor,
        }
        if request.reference_audio:
            payload["reference_audio"] = request.reference_audio
        if request.emotion is not None:
            payload["emotion"] = request.emotion.to_payload()
        return payload


def _detail(response: httpx.Response) -> str:
    """尽量把 sidecar 的可读错误带进 TtsUnavailable。"""

    try:
        data = response.json()
    except ValueError:
        return response.text[:200] or "无响应内容"
    if isinstance(data, dict):
        detail = data.get("detail", data)
        if isinstance(detail, dict):
            code = detail.get("code")
            message = detail.get("message")
            if message:
                return f"{code}: {message}" if code else str(message)
        if isinstance(detail, str):
            return detail
    return str(data)[:200]


__all__ = ["IndexTtsProvider"]
