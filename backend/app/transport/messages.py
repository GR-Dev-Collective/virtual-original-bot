"""控制通道 v2（``vob/1``）消息模型。

这是 ``shared/contracts/control-message.schema.json`` 的后端镜像：信封字段、
type 枚举与每个 payload 的 required/字段名必须与 schema 一致，
``tests/test_contract_consistency.py`` 会强制校验。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROTOCOL_VERSION = "vob/1"


class MessageType(StrEnum):
    # 服务端通知
    SERVER_READY = "server.ready"
    SESSION_OPENED = "session.opened"
    SESSION_STATE = "session.state"
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
    ERROR = "error"

    # 客户端命令
    SESSION_OPEN = "session.open"
    SESSION_HYDRATE = "session.hydrate"
    USER_TEXT = "user.text"
    VOICE_SELECT = "voice.select"
    TTS_CANCEL = "tts.cancel"


# tts.finished 同时是命令与通知，按命令一侧分发。
COMMAND_TYPES = frozenset(
    {
        MessageType.SESSION_OPEN,
        MessageType.SESSION_HYDRATE,
        MessageType.USER_TEXT,
        MessageType.VOICE_SELECT,
        MessageType.TTS_CANCEL,
        MessageType.TTS_FINISHED,
    }
)

NOTIFICATION_TYPES = frozenset(
    {
        MessageType.SERVER_READY,
        MessageType.SESSION_OPENED,
        MessageType.SESSION_STATE,
        MessageType.TURN_STARTED,
        MessageType.AGENT_TEXT,
        MessageType.TTS_STARTED,
        MessageType.TTS_READY,
        MessageType.TTS_FAILED,
        MessageType.TTS_CANCELLED,
        MessageType.TTS_FINISHED,
        MessageType.VOICE_SELECTED,
        MessageType.CHARACTER_STATE,
        MessageType.TURN_COMPLETED,
        MessageType.TURN_CANCELLED,
        MessageType.TURN_ERROR,
        MessageType.ERROR,
    }
)


class Payload(BaseModel):
    """payload 基类：schema 中所有 payload 都是 ``additionalProperties: false``。"""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- 信封与能力


class ControlMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal["vob/1"]
    id: str = Field(min_length=1)
    ts: int = Field(ge=0)
    type: MessageType
    reply_to: str | None = None
    seq: int | None = Field(default=None, ge=1)
    payload: dict[str, Any]


class Capabilities(Payload):
    methods: list[str]
    notifications: list[str]
    features: list[str]


class ServerReadyPayload(Payload):
    protocol_version: str = Field(min_length=1)
    capabilities: Capabilities


class SessionOpenedPayload(Payload):
    session_id: str = Field(min_length=1)
    cursor: int = Field(ge=0)
    replayed: int = Field(ge=0)
    voice_id: str = Field(min_length=1)


# ---------------------------------------------------------------- 快照模型


class MessageView(Payload):
    id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    role: Literal["user", "assistant"]
    text: str
    ts: int = Field(ge=0)
    audio_url: str | None = None
    turn_id: str | None = None
    reply_to: str | None = None


class TurnView(Payload):
    turn_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    status: Literal["active", "completed", "cancelled", "error"]
    started_seq: int | None = Field(default=None, ge=1)
    ended_seq: int | None = Field(default=None, ge=1)
    tts_id: str | None = None
    audio_url: str | None = None


class VoiceState(Payload):
    voice_id: str = Field(min_length=1)
    display_name: str | None = None


class CharacterStateView(Payload):
    phase: Literal["idle", "thinking", "speaking", "error"]
    emotion: str | None = None
    tts_id: str | None = None
    audio_url: str | None = None


class SessionStatePayload(Payload):
    session_id: str = Field(min_length=1)
    cursor: int = Field(ge=0)
    messages: list[MessageView]
    turns: list[TurnView]
    voice: VoiceState
    character: CharacterStateView
    active_turn_id: str | None = None


# ---------------------------------------------------------------- turn 通知


class TurnStartedPayload(Payload):
    turn_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)


class AgentTextPayload(Payload):
    text: str
    reply_to: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    audio_url: str | None = None


class TtsStartedPayload(Payload):
    tts_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)


class TtsReadyPayload(Payload):
    tts_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    audio_url: str = Field(min_length=1)


class TtsFailedPayload(Payload):
    tts_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str


class TtsCancelledPayload(Payload):
    tts_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class TtsFinishedPayload(Payload):
    """tts.finished 的 payload；命令只带 tts_id，通知额外带 reply_to。"""

    tts_id: str = Field(min_length=1)
    reply_to: str | None = None


class VoiceSelectedPayload(Payload):
    voice_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class TurnCompletedPayload(Payload):
    turn_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)


class TurnCancelledPayload(Payload):
    turn_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class TurnErrorPayload(Payload):
    turn_id: str = Field(min_length=1)
    reply_to: str = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str


class ErrorPayload(Payload):
    code: str = Field(min_length=1)
    message: str
    reply_to: str | None = None


# ---------------------------------------------------------------- 命令 payload


class SessionOpenPayload(Payload):
    session_id: str | None = Field(default=None, min_length=1)
    after: int | None = Field(default=None, ge=0)


class SessionHydratePayload(Payload):
    sections: list[str] | None = None
    after: int | None = Field(default=None, ge=0)


class UserTextPayload(Payload):
    text: str = Field(min_length=1)


class VoiceSelectPayload(Payload):
    voice_id: str = Field(min_length=1)


class TtsCancelPayload(Payload):
    tts_id: str = Field(min_length=1)


# ---------------------------------------------------------------- 类型注册表


PAYLOAD_MODELS: dict[MessageType, type[Payload]] = {
    MessageType.SERVER_READY: ServerReadyPayload,
    MessageType.SESSION_OPENED: SessionOpenedPayload,
    MessageType.SESSION_STATE: SessionStatePayload,
    MessageType.TURN_STARTED: TurnStartedPayload,
    MessageType.AGENT_TEXT: AgentTextPayload,
    MessageType.TTS_STARTED: TtsStartedPayload,
    MessageType.TTS_READY: TtsReadyPayload,
    MessageType.TTS_FAILED: TtsFailedPayload,
    MessageType.TTS_CANCELLED: TtsCancelledPayload,
    MessageType.TTS_FINISHED: TtsFinishedPayload,
    MessageType.VOICE_SELECTED: VoiceSelectedPayload,
    MessageType.CHARACTER_STATE: CharacterStateView,
    MessageType.TURN_COMPLETED: TurnCompletedPayload,
    MessageType.TURN_CANCELLED: TurnCancelledPayload,
    MessageType.TURN_ERROR: TurnErrorPayload,
    MessageType.ERROR: ErrorPayload,
    MessageType.SESSION_OPEN: SessionOpenPayload,
    MessageType.SESSION_HYDRATE: SessionHydratePayload,
    MessageType.USER_TEXT: UserTextPayload,
    MessageType.VOICE_SELECT: VoiceSelectPayload,
    MessageType.TTS_CANCEL: TtsCancelPayload,
}

COMMAND_PAYLOADS: dict[MessageType, type[Payload]] = {
    message_type: PAYLOAD_MODELS[message_type] for message_type in COMMAND_TYPES
}


# ------------------------------------------------------------------- 构建工具


def new_id() -> str:
    return uuid4().hex


def now_ms() -> int:
    return int(time.time() * 1000)


def build(
    type_: MessageType,
    payload: BaseModel | Mapping[str, Any],
    *,
    seq: int | None = None,
    reply_to: str | None = None,
    message_id: str | None = None,
    ts: int | None = None,
) -> dict[str, Any]:
    """组装一条待发送的控制消息。"""

    payload_data = (
        payload.model_dump(mode="json") if isinstance(payload, BaseModel) else dict(payload)
    )
    message = ControlMessage(
        protocol=PROTOCOL_VERSION,
        id=message_id or new_id(),
        ts=ts if ts is not None else now_ms(),
        type=type_,
        reply_to=reply_to,
        seq=seq,
        payload=payload_data,
    )
    return message.model_dump(mode="json")


def describe_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
