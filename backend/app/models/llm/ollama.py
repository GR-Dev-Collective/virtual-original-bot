"""Ollama 适配器。"""

from collections.abc import Mapping, Sequence

import httpx

from app.models.llm import LlmUnavailable


class OllamaChat:
    """调用本地 Ollama 的 /api/chat。

    think=False 关闭 qwen3 一类模型的思考输出：思考内容走独立的 message.thinking
    字段，对交互式角色对话没有价值，却会把首字节时间拉长数倍。

    AsyncClient 由调用方持有并复用，不在这里每次请求新建。
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        client: httpx.AsyncClient,
        *,
        num_ctx: int = 4096,
        num_gpu: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client
        self._num_ctx = num_ctx
        self._num_gpu = num_gpu

    async def reply(
        self,
        text: str,
        system: str | None = None,
        history: Sequence[Mapping[str, str]] | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for message in history or ():
            role = str(message.get("role", ""))
            content = str(message.get("content", ""))
            if role and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})

        try:
            options: dict[str, int] = {"num_ctx": self._num_ctx}
            if self._num_gpu is not None:
                # 与 IndexTTS 共用 8GB 显卡时可设 0，让 LLM 走 CPU，把显存留给 TTS。
                options["num_gpu"] = self._num_gpu
            response = await self._client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    # Ollama 默认上下文可能大到超出本机内存（qwen3 上见过 36GB
                    # KV 分配失败），显式给一个够用的窗口。
                    "options": options,
                },
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise LlmUnavailable(f"调用 Ollama 失败：{exc}") from exc

        text = _strip_thinking(str(content)).strip()
        if not text:
            raise LlmUnavailable("Ollama 返回了空回复")
        return text


def _strip_thinking(content: str) -> str:
    """去掉 qwen3 等模型即使 think=False 也可能混进 content 的思考块。

    只保留最后一个 ``<｜end▁of▁thinking｜>`` 之后的内容；同时清理起止标签。模型只输出
    思考而没有正式回复时，返回空字符串，由调用方报错。
    """

    for marker in ("<｜end▁of▁thinking｜>", "</think>"):
        index = content.rfind(marker)
        if index != -1:
            content = content[index + len(marker) :]
    return content.replace("<think>", "").replace("</think>", "").strip()
