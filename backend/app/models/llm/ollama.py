"""Ollama 适配器。"""

import httpx

from app.models.llm import LlmUnavailable


class OllamaChat:
    """调用本地 Ollama 的 /api/chat。

    think=False 关闭 qwen3 一类模型的思考输出：思考内容走独立的 message.thinking
    字段，对交互式角色对话没有价值，却会把首字节时间拉长数倍。

    AsyncClient 由调用方持有并复用，不在这里每次请求新建。
    """

    def __init__(self, base_url: str, model: str, client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client

    async def reply(self, text: str, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": text})

        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                },
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise LlmUnavailable(f"调用 Ollama 失败：{exc}") from exc

        return str(content).strip()
