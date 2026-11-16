"""Ollama 适配器测试：请求形状、历史、响应解析与错误转换（全部走 MockTransport）。"""

import asyncio
import json
from collections.abc import Mapping, Sequence

import httpx
import pytest

from app.models.llm import LlmUnavailable
from app.models.llm.ollama import OllamaChat

SEEN: dict[str, object] = {}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN["url"] = str(request.url)
    SEEN["body"] = json.loads(request.content)
    message = {"role": "assistant", "content": " 我が輩 在此。 "}
    return httpx.Response(200, json={"message": message})


def _failing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="boom")


def _unreachable_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


async def _reply(
    handler,
    text: str = "你好",
    system: str | None = "系统提示",
    history: Sequence[Mapping[str, str]] | None = None,
) -> str:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    ) as client:
        chat = OllamaChat("http://127.0.0.1:11434/", "qwen3:8b", client)
        return await chat.reply(text, system=system, history=history)


def test_request_shape_and_content_trimming() -> None:
    SEEN.clear()
    result = asyncio.run(_reply(_handler))

    assert result == "我が輩 在此。"
    assert SEEN["url"] == "http://127.0.0.1:11434/api/chat"

    body = SEEN["body"]
    assert body["model"] == "qwen3:8b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"] == {"num_ctx": 4096}
    assert body["messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "你好"},
    ]


def test_system_prompt_is_optional() -> None:
    SEEN.clear()
    asyncio.run(_reply(_handler, system=None))

    assert SEEN["body"]["messages"] == [{"role": "user", "content": "你好"}]


def test_history_is_inserted_after_system_prompt() -> None:
    SEEN.clear()
    history = [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": "我が輩 已收到。"},
    ]
    asyncio.run(_reply(_handler, text="第三句", history=history))

    assert SEEN["body"]["messages"] == [
        {"role": "system", "content": "系统提示"},
        *history,
        {"role": "user", "content": "第三句"},
    ]


def test_http_error_becomes_llm_unavailable() -> None:
    with pytest.raises(LlmUnavailable):
        asyncio.run(_reply(_failing_handler))


def test_connection_error_becomes_llm_unavailable() -> None:
    with pytest.raises(LlmUnavailable):
        asyncio.run(_reply(_unreachable_handler))


def test_thinking_leak_is_stripped_from_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = "<think>内部推理</think>哼，辛苦？吾辈今日连云都数清了。"
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    result = asyncio.run(_reply(handler))

    assert result == "哼，辛苦？吾辈今日连云都数清了。"
    assert "内部推理" not in result
