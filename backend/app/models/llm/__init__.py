"""LLM 适配器。

ChatModel 是对外暴露的统一接口；接入别的模型时实现同一接口，
AgentCore 不需要知道具体是哪一个。
"""

from typing import Protocol


class LlmUnavailable(RuntimeError):
    """LLM 服务不可达、超时，或返回了无法解析的响应。"""


class ChatModel(Protocol):
    async def reply(self, text: str, system: str | None = None) -> str: ...
