"""控制通道消息模型。

这是 shared/contracts/control-message.schema.json 的后端镜像，改动需与
shared/contracts/protocol.md 和前端 transport/protocol.ts 同步。
"""

import time
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    SESSION_READY = "session.ready"
    USER_TEXT = "user.text"
    AGENT_TEXT = "agent.text"
    TTS_STARTED = "tts.started"
    TTS_READY = "tts.ready"
    TTS_CANCEL = "tts.cancel"
    TTS_CANCELLED = "tts.cancelled"
    ERROR = "error"


class ControlMessage(BaseModel):
    type: MessageType
    id: str = Field(min_length=1)
    ts: int = Field(ge=0)
    payload: dict[str, Any]


class SessionReadyPayload(BaseModel):
    session_id: str = Field(min_length=1)


class UserTextPayload(BaseModel):
    text: str = Field(min_length=1)


class AgentTextPayload(BaseModel):
    text: str
    reply_to: str = Field(min_length=1)


class TtsStartedPayload(BaseModel):
    tts_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)


class TtsReadyPayload(BaseModel):
    tts_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    audio_url: str = Field(min_length=1)


class TtsCancelPayload(BaseModel):
    tts_id: str = Field(min_length=1)


class TtsCancelledPayload(BaseModel):
    tts_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ErrorPayload(BaseModel):
    code: str = Field(min_length=1)
    message: str
    reply_to: str | None = None


def new_id() -> str:
    return uuid4().hex


def now_ms() -> int:
    return int(time.time() * 1000)


def build(type_: MessageType, payload: BaseModel) -> dict[str, Any]:
    """组装一条待发送的控制消息。"""
    return ControlMessage(
        type=type_,
        id=new_id(),
        ts=now_ms(),
        payload=payload.model_dump(),
    ).model_dump(mode="json")
