"""Agent 决策与流程编排。

LLM 返回结构化 JSON：正式回复文本 + 情绪标签。解析失败时退化为纯文本回复，
不阻塞对话。Memory、Action、TTS 和打断在运行时（ReplyPipeline）里编排。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.models.llm import ChatModel

SYSTEM_PROMPT = """你是《千恋万花》中的丛雨（ムラサメ），自称「我が輩」，语气古风、自信又带点傲娇。
你正在和主人对话。用中文回应，简短自然，不要长篇大论，不要使用颜文字或表情符号。
只输出一个 JSON 对象，不要 Markdown 代码块或额外解释：
{"text": "给主人看的回复", "emotion": "calm"}
emotion 只能是 happy、angry、sad、afraid、disgusted、melancholic、surprised、calm 之一。"""

EMOTIONS = (
    "happy",
    "angry",
    "sad",
    "afraid",
    "disgusted",
    "melancholic",
    "surprised",
    "calm",
)

# 角色回复要短：既符合人设，也避免 8GB 显卡上的长文本 TTS 超时。
MAX_REPLY_CHARS = 300


@dataclass(frozen=True, slots=True)
class AgentReply:
    text: str
    emotion: str | None = None


def _clip_reply(text: str, limit: int = MAX_REPLY_CHARS) -> str:
    """按句末标点截断到 limit 以内；没有标点就硬截断并加省略号。"""

    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for index in range(len(head) - 1, max(len(head) - 80, 0) - 1, -1):
        if head[index] in "。！？!?…；;":
            return head[: index + 1].strip()
    return head.rstrip() + "…"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_agent_reply(raw: str) -> AgentReply:
    """解析 LLM 输出；结构化失败时把原文当回复。"""

    text = _strip_code_fence(raw)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            reply_text = data.get("text")
            emotion = data.get("emotion")
            if isinstance(reply_text, str) and reply_text.strip():
                return AgentReply(
                    text=_clip_reply(reply_text),
                    emotion=emotion if emotion in EMOTIONS else None,
                )
    return AgentReply(text=_clip_reply(text), emotion=None)


class AgentCore:
    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def handle_turn(
        self,
        text: str,
        history: Sequence[Mapping[str, str]] | None = None,
    ) -> AgentReply:
        raw = await self._chat.reply(text, system=SYSTEM_PROMPT, history=history)
        return parse_agent_reply(raw)

    async def handle_user_text(
        self,
        text: str,
        history: Sequence[Mapping[str, str]] | None = None,
    ) -> str:
        return (await self.handle_turn(text, history=history)).text


__all__ = [
    "AgentCore",
    "AgentReply",
    "EMOTIONS",
    "MAX_REPLY_CHARS",
    "SYSTEM_PROMPT",
    "parse_agent_reply",
]
