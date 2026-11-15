"""测试替身与 WebSocket 工具。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.agent.agent_core import AgentCore
from app.config import settings
from app.main import app
from app.models.llm import LlmUnavailable
from app.models.tts.audio_store import AudioStore
from app.models.tts.base import SynthesisRequest, TtsUnavailable
from app.runtime.runtime import CharacterRuntime
from app.session.store import SessionStore
from app.voices.registry import VoiceRegistry

PROTOCOL = "vob/1"
FAKE_AUDIO = b"RIFF test audio"


class FakeChat:
    def __init__(self, reply_text: str = "我が輩 已收到。", failure: str | None = None) -> None:
        self.reply_text = reply_text
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    async def reply(
        self,
        text: str,
        system: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls.append({"text": text, "system": system, "history": list(history or [])})
        if self.failure is not None:
            raise LlmUnavailable(self.failure)
        return self.reply_text


class FakeTts:
    def __init__(
        self,
        *,
        failure: str | None = None,
        block_first: bool = False,
        audio: bytes = FAKE_AUDIO,
    ) -> None:
        self.failure = failure
        self.block_first = block_first
        self.audio = audio
        self.requests: list[SynthesisRequest] = []
        self.cancelled_count = 0
        self._blocked_once = False

    async def synthesize(self, request: SynthesisRequest) -> bytes:
        self.requests.append(request)
        if self.failure is not None:
            raise TtsUnavailable(self.failure)
        if self.block_first and not self._blocked_once:
            self._blocked_once = True
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled_count += 1
                raise
        return self.audio


@dataclass
class Harness:
    client: TestClient
    chat: FakeChat
    tts: FakeTts
    runtime: CharacterRuntime
    voices: VoiceRegistry
    sessions_dir: Path
    audio_dir: Path


def build_runtime(
    *,
    sessions_dir: Path,
    audio_dir: Path,
    chat: FakeChat,
    tts: FakeTts,
    voices: VoiceRegistry | None = None,
) -> CharacterRuntime:
    if voices is None:
        voices = VoiceRegistry(
            "config/voices.json",
            sessions_dir.parent / "voices",
        )
    runtime = CharacterRuntime(
        store=SessionStore(sessions_dir, event_limit=settings.session_event_limit),
        agent=AgentCore(chat),
        tts=tts,
        audio_store=AudioStore(str(audio_dir)),
        voices=voices,
        history_max_messages=settings.history_max_messages,
        history_max_chars=settings.history_max_chars,
    )
    app.state.runtime = runtime
    app.state.tts_port = tts
    app.state.tts_provider = tts
    app.state.voices = voices
    return runtime


def make_client() -> TestClient:
    return TestClient(app)


def connect(client: TestClient, **params: str):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    url = "/ws/control" + (f"?{query}" if query else "")
    return client.websocket_connect(url)


def send(
    ws,
    type_: str,
    payload: dict[str, Any],
    *,
    message_id: str = "cmd-1",
    ts: int = 1,
    **extra: Any,
) -> None:
    message = {"protocol": PROTOCOL, "type": type_, "id": message_id, "ts": ts, "payload": payload}
    message.update(extra)
    ws.send_json(message)


def send_user_text(ws, text: str = "你好", *, message_id: str = "m1") -> None:
    send(ws, "user.text", {"text": text}, message_id=message_id)


def receive(ws) -> dict[str, Any]:
    return ws.receive_json()


def expect_next(ws, type_: str) -> dict[str, Any]:
    message = ws.receive_json()
    assert message["type"] == type_, message
    return message


def receive_until(ws, type_: str, *, limit: int = 80) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for _ in range(limit):
        message = ws.receive_json()
        collected.append(message)
        if message["type"] == type_:
            return collected
    raise AssertionError(f"未在 {limit} 条消息内收到 {type_}: {collected}")


def handshake(ws) -> tuple[dict[str, Any], dict[str, Any]]:
    ready = expect_next(ws, "server.ready")
    opened = expect_next(ws, "session.opened")
    return ready, opened
