"""连接级会话状态。"""

from dataclasses import dataclass
from uuid import uuid4


@dataclass
class SessionState:
    id: str

    @classmethod
    def new(cls) -> "SessionState":
        return cls(id=uuid4().hex)
