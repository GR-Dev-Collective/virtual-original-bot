"""控制通道 /ws/control。"""

import asyncio
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.models.llm import ChatModel, LlmUnavailable
from app.models.tts.gpt_sovits import TtsRequest, TtsUnavailable
from app.state.session import SessionState
from app.transport.messages import (
    AgentTextPayload,
    ControlMessage,
    ErrorPayload,
    MessageType,
    SessionReadyPayload,
    TtsCancelledPayload,
    TtsCancelPayload,
    TtsReadyPayload,
    TtsStartedPayload,
    UserTextPayload,
    build,
)

router = APIRouter()


@router.websocket("/ws/control")
async def control_channel(websocket: WebSocket) -> None:
    await websocket.accept()

    session = SessionState.new()
    send_lock = asyncio.Lock()
    await _send(
        websocket,
        send_lock,
        build(MessageType.SESSION_READY, SessionReadyPayload(session_id=session.id)),
    )

    agent: ChatModel = websocket.app.state.agent
    try:
        while True:
            raw = await websocket.receive_text()
            await _dispatch(websocket, send_lock, session, agent, raw)
    except WebSocketDisconnect:
        await _cancel_active(session, "disconnected")
    finally:
        await _cancel_active(session, "disconnected")


async def _dispatch(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session: SessionState,
    agent: ChatModel,
    raw: str,
) -> None:
    try:
        message = ControlMessage.model_validate_json(raw)
    except ValidationError as exc:
        await _send_error(websocket, send_lock, "invalid_message", _describe(exc), None)
        return

    if message.type is MessageType.USER_TEXT:
        try:
            payload = UserTextPayload.model_validate(message.payload)
        except ValidationError as exc:
            await _send_error(websocket, send_lock, "invalid_message", _describe(exc), message.id)
            return
        await _cancel_active(session, "interrupted")
        session.active_task = asyncio.create_task(
            _respond(websocket, send_lock, session, agent, message.id, payload)
        )
        return

    if message.type is MessageType.TTS_CANCEL:
        try:
            payload = TtsCancelPayload.model_validate(message.payload)
        except ValidationError as exc:
            await _send_error(websocket, send_lock, "invalid_message", _describe(exc), message.id)
            return
        if session.active_tts_id == payload.tts_id:
            await _cancel_active(session, "cancelled")
        return

    await _send_error(
        websocket,
        send_lock,
        "unsupported_type",
        f"当前只接受 user.text 或 tts.cancel，收到 {message.type}",
        message.id,
    )


async def _respond(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session: SessionState,
    agent: ChatModel,
    message_id: str,
    payload: UserTextPayload,
) -> None:
    try:
        reply = await agent.handle_user_text(payload.text)
        await _send(
            websocket,
            send_lock,
            build(MessageType.AGENT_TEXT, AgentTextPayload(text=reply, reply_to=message_id)),
        )

        tts_id = uuid4().hex
        session.active_tts_id = tts_id
        session.active_reply_to = message_id
        await _send(
            websocket,
            send_lock,
            build(MessageType.TTS_STARTED, TtsStartedPayload(tts_id=tts_id, reply_to=message_id)),
        )

        audio = await websocket.app.state.tts.synthesize(
            TtsRequest(
                text=reply,
                text_language="zh",
                refer_wav_path="/workspace/data/references/murasame_ref.ogg",
                prompt_text="はっはっはっは",
                prompt_language="ja",
            )
        )
        audio_id = websocket.app.state.audio_store.save(audio)
        await _send(
            websocket,
            send_lock,
            build(
                MessageType.TTS_READY,
                TtsReadyPayload(
                    tts_id=tts_id,
                    reply_to=message_id,
                    audio_url=f"/tts/{audio_id}",
                ),
            ),
        )
    except asyncio.CancelledError as exc:
        if session.active_tts_id:
            reason = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "interrupted"
            await _send_cancelled(websocket, send_lock, session, reason)
        raise
    except LlmUnavailable as exc:
        await _send_error(websocket, send_lock, "llm_unavailable", str(exc), message_id)
    except TtsUnavailable as exc:
        await _send_error(websocket, send_lock, "tts_unavailable", str(exc), message_id)
    finally:
        session.active_tts_id = None
        session.active_reply_to = None


async def _cancel_active(session: SessionState, reason: str) -> None:
    task = session.active_task
    if task is None or task.done():
        session.active_task = None
        return
    task.cancel(reason)
    try:
        await task
    except asyncio.CancelledError:
        pass
    session.active_task = None


async def _send_cancelled(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session: SessionState,
    reason: str,
) -> None:
    if session.active_tts_id and session.active_reply_to:
        await _send(
            websocket,
            send_lock,
            build(
                MessageType.TTS_CANCELLED,
                TtsCancelledPayload(
                    tts_id=session.active_tts_id,
                    reply_to=session.active_reply_to,
                    reason=reason,
                ),
            ),
        )


async def _send(websocket: WebSocket, lock: asyncio.Lock, message: dict) -> None:
    async with lock:
        await websocket.send_json(message)


async def _send_error(
    websocket: WebSocket,
    lock: asyncio.Lock,
    code: str,
    message: str,
    reply_to: str | None,
) -> None:
    await _send(
        websocket,
        lock,
        build(MessageType.ERROR, ErrorPayload(code=code, message=message, reply_to=reply_to)),
    )


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
