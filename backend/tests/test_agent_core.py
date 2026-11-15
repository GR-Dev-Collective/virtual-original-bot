"""AgentCore：回复长度控制。"""

import asyncio

from app.agent.agent_core import MAX_REPLY_CHARS, AgentCore


class _Chat:
    def __init__(self, text: str) -> None:
        self._text = text

    async def reply(self, text: str, system: str | None = None, history=None) -> str:
        return self._text


def test_short_reply_is_untouched() -> None:
    reply = asyncio.run(AgentCore(_Chat("哼，知道了。")).handle_user_text("你好"))

    assert reply == "哼，知道了。"


def test_long_reply_is_clipped_at_sentence_boundary() -> None:
    long_text = "第一句话。" * 100

    reply = asyncio.run(AgentCore(_Chat(long_text)).handle_user_text("你好"))

    assert len(reply) <= MAX_REPLY_CHARS + 1
    assert reply.endswith("。")
    assert "第一句话。" in reply


def test_long_reply_without_punctuation_gets_ellipsis() -> None:
    reply = asyncio.run(AgentCore(_Chat("啊" * 500)).handle_user_text("你好"))

    assert len(reply) <= MAX_REPLY_CHARS + 1
    assert reply.endswith("…")
