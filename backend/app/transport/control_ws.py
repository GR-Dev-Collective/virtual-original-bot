"""控制通道 /ws/control：``vob/1`` 协议网关。

Gateway 只负责协议编解码、连接、重放与命令分发；回合编排在
``app.runtime.pipeline.ReplyPipeline``，会话事实在 ``SessionStore``。
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.runtime.runtime import CharacterRuntime
from app.session.models import (
    EventRecord,
    InvalidSessionId,
    SessionMeta,
    SessionNotFound,
    validate_session_id,
)
from app.transport.messages import (
    COMMAND_PAYLOADS,
    PROTOCOL_VERSION,
    Capabilities,
    ControlMessage,
    ErrorPayload,
    MessageType,
    ServerReadyPayload,
    SessionHydratePayload,
    SessionOpenedPayload,
    SessionOpenPayload,
    TtsCancelPayload,
    TtsFinishedPayload,
    UserTextPayload,
    VoiceSelectPayload,
    build,
    describe_validation_error,
)
from app.voices.models import VoiceNotFound

router = APIRouter()
logger = logging.getLogger(__name__)

_CLOSE_POLICY = 1008
_REPLAY_LIMIT = 10_000

_SUPPORTED_METHODS = (
    MessageType.SESSION_OPEN,
    MessageType.SESSION_HYDRATE,
    MessageType.USER_TEXT,
    MessageType.VOICE_SELECT,
    MessageType.TTS_CANCEL,
    MessageType.TTS_FINISHED,
)

_NOTIFICATION_ORDER = (
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
)

CAPABILITIES = Capabilities(
    methods=[item.value for item in _SUPPORTED_METHODS],
    notifications=[item.value for item in _NOTIFICATION_ORDER],
    features=["replay", "hydrate", "session-persistence", "history"],
)


@router.websocket("/ws/control")
async def control_channel(websocket: WebSocket) -> None:
    await websocket.accept()
    connection = _ControlConnection(websocket)
    try:
        await connection.run()
    finally:
        await connection.close()


class _ControlConnection:
    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._runtime: CharacterRuntime = websocket.app.state.runtime
        self._send_lock = asyncio.Lock()
        self._queue: asyncio.Queue[EventRecord] | None = None
        self._sender: asyncio.Task[None] | None = None
        self._session_id: str | None = None
        self._last_seq = 0
        self._closed = False

    # ------------------------------------------------------------- 生命周期

    async def run(self) -> None:
        if not await self._check_query_protocol():
            return
        await self._send(
            build(
                MessageType.SERVER_READY,
                ServerReadyPayload(
                    protocol_version=PROTOCOL_VERSION,
                    capabilities=CAPABILITIES,
                ),
            )
        )
        if not await self._open_initial():
            return

        self._sender = asyncio.create_task(self._send_loop(), name="control-sender")
        try:
            await self._receive_loop()
        except WebSocketDisconnect:
            logger.debug("控制通道断开：%s", self._session_id)
        finally:
            await self._stop_sender()

    async def close(self) -> None:
        self._closed = True
        await self._stop_sender()
        await self._unsubscribe()

    async def _check_query_protocol(self) -> bool:
        protocol = self._websocket.query_params.get("protocol")
        if protocol is not None and protocol != PROTOCOL_VERSION:
            await self._close_with_error(
                "protocol_mismatch",
                f"不支持的协议版本：{protocol}（服务端为 {PROTOCOL_VERSION}）",
            )
            return False
        return True

    async def _open_initial(self) -> bool:
        query = self._websocket.query_params
        session_param = query.get("session_id")
        after_raw = query.get("after")

        try:
            after = _parse_after(after_raw)
        except ValueError:
            await self._close_with_error("invalid_message", "after 必须是非负整数")
            return False

        if session_param is not None:
            try:
                validate_session_id(session_param)
            except InvalidSessionId:
                await self._close_with_error("invalid_message", "无效的 session_id")
                return False

        try:
            if session_param is None:
                meta = self._runtime.create_session()
                after = None
            else:
                meta = self._runtime.require_session(session_param)
        except SessionNotFound:
            await self._close_with_error(
                "session_not_found",
                f"会话不存在：{session_param}",
            )
            return False

        self._session_id = meta.session_id
        self._queue = self._runtime.subscribe(meta.session_id)
        await self._announce_session(meta, after)
        return True

    # --------------------------------------------------------------- 会话命令

    async def _announce_session(self, meta: SessionMeta, after: int | None) -> None:
        cursor = self._runtime.cursor(meta.session_id)
        replayed = 0
        if after is not None:
            for event in self._runtime.replay(meta.session_id, after=after, limit=_REPLAY_LIMIT):
                if event.seq > cursor:
                    break
                await self._send_event(event)
                replayed += 1
        self._last_seq = cursor
        await self._send(
            build(
                MessageType.SESSION_OPENED,
                SessionOpenedPayload(
                    session_id=meta.session_id,
                    cursor=cursor,
                    replayed=replayed,
                    voice_id=meta.voice_id,
                ),
            )
        )

    async def _switch_session(self, session_id: str) -> None:
        await self._stop_sender()
        old_id = self._session_id
        old_queue = self._queue
        if old_id is not None and old_queue is not None:
            self._runtime.unsubscribe(old_id, old_queue)
        self._session_id = session_id
        self._queue = self._runtime.subscribe(session_id)

    # ----------------------------------------------------------------- 收包

    async def _receive_loop(self) -> None:
        while True:
            raw = await self._websocket.receive_text()
            if not await self._handle_raw(raw):
                return

    async def _handle_raw(self, raw: str) -> bool:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._send_error("invalid_message", "消息不是合法的 JSON")
            return True
        if not isinstance(data, dict):
            await self._send_error("invalid_message", "消息必须是 JSON 对象")
            return True

        reply_hint = data.get("id") if isinstance(data.get("id"), str) else None
        protocol = data.get("protocol")
        if protocol is not None and protocol != PROTOCOL_VERSION:
            await self._close_with_error(
                "protocol_mismatch",
                f"不支持的协议版本：{protocol}（服务端为 {PROTOCOL_VERSION}）",
                reply_to=reply_hint,
            )
            return False

        try:
            message = ControlMessage.model_validate(data)
        except ValidationError as exc:
            await self._send_error(
                "invalid_message",
                describe_validation_error(exc),
                reply_to=reply_hint,
            )
            return True

        return await self._dispatch(message)

    async def _dispatch(self, message: ControlMessage) -> bool:
        payload_model = COMMAND_PAYLOADS.get(message.type)
        if payload_model is None:
            await self._send_error(
                "unsupported_type",
                f"服务端不接受类型 {message.type}",
                reply_to=message.id,
            )
            return True

        try:
            payload = payload_model.model_validate(message.payload)
        except ValidationError as exc:
            await self._send_error(
                "invalid_message",
                describe_validation_error(exc),
                reply_to=message.id,
            )
            return True

        if message.type is MessageType.SESSION_OPEN:
            return await self._session_open(message, payload)
        if message.type is MessageType.SESSION_HYDRATE:
            return await self._session_hydrate(payload)
        if message.type is MessageType.USER_TEXT:
            return await self._user_text(message, payload)
        if message.type is MessageType.VOICE_SELECT:
            return await self._voice_select(message, payload)
        if message.type is MessageType.TTS_CANCEL:
            return await self._tts_cancel(payload)
        if message.type is MessageType.TTS_FINISHED:
            return await self._tts_finished(payload)

        await self._send_error(
            "unsupported_type",
            f"服务端不接受类型：{message.type}",
            reply_to=message.id,
        )
        return True

    async def _session_open(self, message: ControlMessage, payload: BaseModel) -> bool:
        assert isinstance(payload, SessionOpenPayload)
        session_id = payload.session_id

        if session_id is None:
            await self._stop_sender()
            meta = self._runtime.require_session(_require(self._session_id))
            await self._announce_session(meta, payload.after)
            self._sender = asyncio.create_task(self._send_loop(), name="control-sender")
            return True

        try:
            meta = self._runtime.require_session(session_id)
        except InvalidSessionId:
            await self._send_error("invalid_message", "无效的 session_id", reply_to=message.id)
            return True
        except SessionNotFound:
            await self._send_error(
                "session_not_found",
                f"会话不存在：{session_id}",
                reply_to=message.id,
            )
            return True

        if session_id != self._session_id:
            await self._switch_session(session_id)
        else:
            await self._stop_sender()

        await self._announce_session(meta, payload.after)
        self._sender = asyncio.create_task(self._send_loop(), name="control-sender")
        return True

    async def _session_hydrate(self, payload: BaseModel) -> bool:
        assert isinstance(payload, SessionHydratePayload)
        del payload
        snapshot = self._runtime.hydrate(_require(self._session_id))
        await self._send(build(MessageType.SESSION_STATE, snapshot))
        return True

    async def _user_text(self, message: ControlMessage, payload: BaseModel) -> bool:
        assert isinstance(payload, UserTextPayload)
        await self._runtime.start_turn(
            _require(self._session_id),
            payload.text,
            message.id,
        )
        return True

    async def _tts_cancel(self, payload: BaseModel) -> bool:
        assert isinstance(payload, TtsCancelPayload)
        await self._runtime.cancel_tts(_require(self._session_id), payload.tts_id)
        return True

    async def _voice_select(self, message: ControlMessage, payload: BaseModel) -> bool:
        assert isinstance(payload, VoiceSelectPayload)
        try:
            self._runtime.select_voice(_require(self._session_id), payload.voice_id)
        except VoiceNotFound:
            await self._send_error(
                "voice_not_found",
                f"音色不存在：{payload.voice_id}",
                reply_to=message.id,
            )
        return True

    async def _tts_finished(self, payload: BaseModel) -> bool:
        assert isinstance(payload, TtsFinishedPayload)
        await self._runtime.finish_tts(_require(self._session_id), payload.tts_id)
        return True

    # ----------------------------------------------------------------- 发送

    async def _send_loop(self) -> None:
        while True:
            queue = self._queue
            if queue is None:
                return
            event = await queue.get()
            if event.seq <= self._last_seq:
                continue
            if queue is not self._queue:
                continue
            try:
                await self._send_event(event)
            except (WebSocketDisconnect, RuntimeError):
                return

    async def _send_event(self, event: EventRecord) -> None:
        try:
            message_type = MessageType(event.type)
        except ValueError:
            logger.warning("忽略未知事件类型：%s", event.type)
            return
        await self._send(
            build(
                message_type,
                event.payload,
                seq=event.seq,
                reply_to=event.reply_to,
                message_id=event.id,
                ts=event.ts,
            )
        )
        self._last_seq = max(self._last_seq, event.seq)

    async def _send(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            try:
                await self._websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                logger.debug("控制通道已关闭，丢弃消息 %s", message.get("type"))

    async def _send_error(self, code: str, message: str, reply_to: str | None = None) -> None:
        await self._send(
            build(
                MessageType.ERROR,
                ErrorPayload(code=code, message=message, reply_to=reply_to),
                reply_to=reply_to,
            )
        )

    async def _close_with_error(
        self,
        code: str,
        message: str,
        *,
        reply_to: str | None = None,
    ) -> None:
        await self._send_error(code, message, reply_to=reply_to)
        await self._safe_close()

    async def _safe_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(Exception):
            await self._websocket.close(code=_CLOSE_POLICY)

    async def _stop_sender(self) -> None:
        task = self._sender
        self._sender = None
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _unsubscribe(self) -> None:
        if self._session_id is not None and self._queue is not None:
            self._runtime.unsubscribe(self._session_id, self._queue)
        self._queue = None


def _parse_after(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    value = int(raw)
    if value < 0:
        raise ValueError(raw)
    return value


def _require(session_id: str | None) -> str:
    if session_id is None:
        raise RuntimeError("连接尚未绑定会话")
    return session_id


__all__ = ["CAPABILITIES", "control_channel", "router"]
