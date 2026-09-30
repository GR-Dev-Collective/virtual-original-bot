"""Agent 入口。"""


class AgentCore:
    async def handle_user_text(self, text: str) -> str:
        return f"收到：{text}"
