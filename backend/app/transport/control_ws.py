"""控制通道 /ws/control。

连接建立后先发 session.ready，随后逐条处理入站消息。入站消息非法时不关闭连接，
而是回一条 error，让前端能继续使用。
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.models.llm import ChatModel, LlmUnavailable
from app.state.session import SessionState
from app.transport.messages import (
    AgentTextPayload,
    ControlMessage,
    ErrorPayload,
    MessageType,
    SessionReadyPayload,
    UserTextPayload,
    build,
)

router = APIRouter()


@router.websocket("/ws/control")
async def control_channel(websocket: WebSocket) -> None:
    await websocket.accept()

    session = SessionState.new()
    await websocket.send_json(
        build(MessageType.SESSION_READY, SessionReadyPayload(session_id=session.id))
    )

    agent: ChatModel = websocket.app.state.agent

    try:
        while True:
            raw = await websocket.receive_text()
            await _dispatch(websocket, agent, raw)
    except WebSocketDisconnect:
        return


async def _dispatch(websocket: WebSocket, agent: ChatModel, raw: str) -> None:
    try:
        message = ControlMessage.model_validate_json(raw)
    except ValidationError as exc:
        await _send_error(websocket, "invalid_message", _describe(exc), None)
        return

    if message.type is not MessageType.USER_TEXT:
        await _send_error(
            websocket,
            "unsupported_type",
            f"当前只接受 user.text，收到 {message.type}",
            message.id,
        )
        return

    try:
        payload = UserTextPayload.model_validate(message.payload)
    except ValidationError as exc:
        await _send_error(websocket, "invalid_message", _describe(exc), message.id)
        return

    try:
        reply = await agent.handle_user_text(payload.text)
    except LlmUnavailable as exc:
        await _send_error(websocket, "llm_unavailable", str(exc), message.id)
        return

    await websocket.send_json(
        build(MessageType.AGENT_TEXT, AgentTextPayload(text=reply, reply_to=message.id))
    )


async def _send_error(
    websocket: WebSocket, code: str, message: str, reply_to: str | None
) -> None:
    await websocket.send_json(
        build(MessageType.ERROR, ErrorPayload(code=code, message=message, reply_to=reply_to))
    )


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
