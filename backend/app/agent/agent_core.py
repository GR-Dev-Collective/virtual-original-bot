"""Agent 决策与流程编排。

当前只把用户文本 + 最近历史交给 LLM 并返回回复文本。Memory、Action、情绪状态、
TTS 和打断在运行时（ReplyPipeline）里编排，从这里接出去。
"""

from collections.abc import Mapping, Sequence

from app.models.llm import ChatModel

SYSTEM_PROMPT = """你是《千恋万花》中的丛雨（ムラサメ），自称「我が輩」，语气古风、自信又带点傲娇。
你正在和主人对话。用中文回应，简短自然，不要长篇大论，不要使用颜文字或表情符号。"""

# 角色回复要短：既符合人设，也避免 8GB 显卡上的长文本 TTS 超时。
MAX_REPLY_CHARS = 300


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


class AgentCore:
    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def handle_user_text(
        self,
        text: str,
        history: Sequence[Mapping[str, str]] | None = None,
    ) -> str:
        reply = await self._chat.reply(text, system=SYSTEM_PROMPT, history=history)
        return _clip_reply(reply)
