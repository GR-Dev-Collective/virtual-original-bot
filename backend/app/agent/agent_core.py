"""Agent 决策与流程编排。

当前只把用户文本交给 LLM 并返回回复文本。Memory、Action、情绪状态、
TTS 和打断属于后续阶段，都从这里接出去。
"""

from app.models.llm import ChatModel

SYSTEM_PROMPT = """你是《千恋万花》中的丛雨（ムラサメ），自称「我が輩」，语气古风、自信又带点傲娇。
你正在和主人对话。用中文回应，简短自然，不要长篇大论，不要使用颜文字或表情符号。"""


class AgentCore:
    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def handle_user_text(self, text: str) -> str:
        return await self._chat.reply(text, system=SYSTEM_PROMPT)
