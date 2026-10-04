"""Agent 决策与流程编排。

当前只把用户文本交给 LLM 并返回回复文本。Memory、Action、情绪状态、
TTS 和打断属于后续阶段，都从这里接出去。
"""

import unicodedata

from app.models.llm import ChatModel

SYSTEM_PROMPT = """你是《千恋万花》中的丛雨，自称「吾辈」，语气古风、自信又带点傲娇。
你正在和主人对话。只用简体中文回应，简短自然，不要长篇大论，不要使用颜文字或表情符号。"""

REWRITE_SYSTEM_PROMPT = f"""{SYSTEM_PROMPT}
请把收到的回复草稿改写成简体中文，保留原意和丛雨的语气，并使用「吾辈」自称。
只输出改写后的回复正文，不要解释。"""

JAPANESE_KANA_NAME_PREFIXES = (
    "SQUARE HIRAGANA ",
    "HIRAGANA LETTER ",
    "HIRAGANA DIGRAPH ",
    "HIRAGANA ITERATION MARK",
    "HIRAGANA VOICED ITERATION MARK",
    "VERTICAL KANA ",
    "CIRCLED KATAKANA ",
    "KATAKANA LETTER ",
    "KATAKANA DIGRAPH ",
    "KATAKANA ITERATION MARK",
    "KATAKANA VOICED ITERATION MARK",
    "SQUARED KATAKANA ",
    "HALFWIDTH KATAKANA LETTER ",
    "HALFWIDTH KATAKANA VOICED SOUND MARK",
    "HALFWIDTH KATAKANA SEMI-VOICED SOUND MARK",
    "HALFWIDTH KATAKANA-HIRAGANA PROLONGED SOUND MARK",
    "KATAKANA-HIRAGANA PROLONGED SOUND MARK",
    "KATAKANA-HIRAGANA VOICED SOUND MARK",
    "KATAKANA-HIRAGANA SEMI-VOICED SOUND MARK",
    "COMBINING KATAKANA-HIRAGANA ",
)


class AgentLanguageUnresolved(Exception):
    """Agent 回复经一次改写后仍包含日文假名。"""


def _contains_japanese_kana(text: str) -> bool:
    return any(
        unicodedata.name(character, "").startswith(JAPANESE_KANA_NAME_PREFIXES)
        for character in text
    )


class AgentCore:
    def __init__(self, chat: ChatModel) -> None:
        self._chat = chat

    async def handle_user_text(self, text: str) -> str:
        reply = await self._chat.reply(text, system=SYSTEM_PROMPT)
        if not _contains_japanese_kana(reply):
            return reply

        rewritten = await self._chat.reply(reply, system=REWRITE_SYSTEM_PROMPT)
        if _contains_japanese_kana(rewritten):
            raise AgentLanguageUnresolved("回复经改写后仍包含日文假名")
        return rewritten
