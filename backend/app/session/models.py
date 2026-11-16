"""会话域模型：会话元数据、消息记录与事件记录。

所有持久化结构都是 append-only 的 JSONL 行；这里只负责数据的形状与基础校验，
磁盘读写的容错在 ``app.session.store`` 中处理。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

# 首个内置音色档案；t8 接入 VoiceRegistry 后会从档案注册表解析。
DEFAULT_VOICE_ID = "murasame"

# 会话目录名同时用于文件路径，必须限制字符集，禁止路径穿越。
SESSION_ID_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")


class InvalidSessionId(ValueError):
    """会话 id 不满足安全字符集或长度限制。"""


class SessionNotFound(LookupError):
    """请求的会话在磁盘上不存在。"""


def new_id() -> str:
    return uuid4().hex


def now_ms() -> int:
    return int(time.time() * 1000)


def validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
        raise InvalidSessionId(session_id)
    return session_id


class EventType(StrEnum):
    """写入事件账本的事件类型（与协议通知同名）。"""

    TURN_STARTED = "turn.started"
    AGENT_TEXT = "agent.text"
    TTS_STARTED = "tts.started"
    TTS_READY = "tts.ready"
    TTS_FAILED = "tts.failed"
    TTS_CANCELLED = "tts.cancelled"
    TTS_FINISHED = "tts.finished"
    VOICE_SELECTED = "voice.selected"
    CHARACTER_STATE = "character.state"
    TURN_COMPLETED = "turn.completed"
    TURN_CANCELLED = "turn.cancelled"
    TURN_ERROR = "turn.error"


EVENT_TYPES = frozenset(item.value for item in EventType)


@dataclass(frozen=True, slots=True)
class SessionMeta:
    session_id: str
    created_at: int
    persona: str | None = None
    voice_id: str = DEFAULT_VOICE_ID

    def to_json(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "persona": self.persona,
            "voice_id": self.voice_id,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SessionMeta:
        return cls(
            session_id=validate_session_id(str(data["session_id"])),
            created_at=int(data.get("created_at", 0)),
            persona=data.get("persona"),
            voice_id=str(data.get("voice_id") or DEFAULT_VOICE_ID),
        )


@dataclass(frozen=True, slots=True)
class MessageRecord:
    seq: int
    id: str
    ts: int
    role: str
    text: str
    audio_url: str | None = None
    turn_id: str | None = None
    reply_to: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "id": self.id,
            "ts": self.ts,
            "role": self.role,
            "text": self.text,
            "audio_url": self.audio_url,
            "turn_id": self.turn_id,
            "reply_to": self.reply_to,
        }

    def to_view(self) -> dict[str, Any]:
        """hydrate/session.state 中的消息形状。"""

        return self.to_json()

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> MessageRecord:
        return cls(
            seq=int(data["seq"]),
            id=str(data["id"]),
            ts=int(data["ts"]),
            role=str(data["role"]),
            text=str(data["text"]),
            audio_url=data.get("audio_url"),
            turn_id=data.get("turn_id"),
            reply_to=data.get("reply_to"),
        )


@dataclass(frozen=True, slots=True)
class EventRecord:
    seq: int
    id: str
    ts: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    reply_to: str | None = None

    def to_json(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "seq": self.seq,
            "id": self.id,
            "ts": self.ts,
            "type": self.type,
            "payload": self.payload,
        }
        if self.reply_to is not None:
            record["reply_to"] = self.reply_to
        return record

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> EventRecord:
        payload = data.get("payload")
        return cls(
            seq=int(data["seq"]),
            id=str(data["id"]),
            ts=int(data["ts"]),
            type=str(data["type"]),
            payload=payload if isinstance(payload, dict) else {},
            reply_to=data.get("reply_to"),
        )
