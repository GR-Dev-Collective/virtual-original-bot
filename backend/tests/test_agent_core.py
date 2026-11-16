"""AgentCore：结构化回复、情绪与长度控制。"""

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


def test_structured_reply_parses_text_and_emotion() -> None:
    raw = '```json\n{"text": "哼，知道了。", "emotion": "angry"}\n```'

    reply = asyncio.run(AgentCore(_Chat(raw)).handle_turn("你好"))

    assert reply.text == "哼，知道了。"
    assert reply.emotion == "angry"


def test_unknown_emotion_is_dropped() -> None:
    raw = '{"text": "嗯。", "emotion": "excited"}'

    reply = asyncio.run(AgentCore(_Chat(raw)).handle_turn("你好"))

    assert reply.text == "嗯。"
    assert reply.emotion is None


def test_plain_text_falls_back_without_emotion() -> None:
    reply = asyncio.run(AgentCore(_Chat("哼，知道了。")).handle_turn("你好"))

    assert reply.text == "哼，知道了。"
    assert reply.emotion is None
