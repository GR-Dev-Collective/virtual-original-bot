"""连接级会话状态。"""

import asyncio
from dataclasses import dataclass
from uuid import uuid4


@dataclass
class SessionState:
    id: str
    active_task: asyncio.Task[None] | None = None
    active_tts_id: str | None = None
    active_reply_to: str | None = None

    @classmethod
    def new(cls) -> "SessionState":
        return cls(id=uuid4().hex)
