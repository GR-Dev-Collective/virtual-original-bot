"""控制通道的端到端测试：握手、回复、非法消息，以及 LLM 不可用时的报错。

测试用假 ChatModel 替换真实 Ollama，不产生任何外部请求。
"""

from collections.abc import Iterator
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agent.agent_core import AgentCore
from app.main import app
from app.models.llm import LlmUnavailable
from app.models.tts.audio_store import AudioStore
from app.models.tts.gpt_sovits import TtsRequest, TtsUnavailable

USER_TEXT = {"type": "user.text", "id": "m1", "ts": 1, "payload": {"text": "你好"}}


class FakeChat:
    def __init__(
        self,
        reply_text: str = "吾辈 已收到。",
        failure: str | None = None,
        replies: list[str] | None = None,
    ) -> None:
        self._reply_text = reply_text
        self._replies = list(replies or [])
        self._failure = failure
        self.calls: list[tuple[str, str | None]] = []

    async def reply(self, text: str, system: str | None = None) -> str:
        self.calls.append((text, system))
        if self._failure is not None:
            raise LlmUnavailable(self._failure)
        if self._replies:
            return self._replies.pop(0)
        return self._reply_text


class FakeTts:
    def __init__(self, failure: str | None = None, block: bool = False) -> None:
        self.failure = failure
        self.block = block
        self.requests: list[TtsRequest] = []

    async def synthesize(self, request: TtsRequest) -> bytes:
        self.requests.append(request)
        if self.block:
            await asyncio.sleep(60)
        if self.failure is not None:
            raise TtsUnavailable(self.failure)
        return b"RIFF test audio"


@pytest.fixture
def chat() -> FakeChat:
    return FakeChat()


@pytest.fixture
def client(chat: FakeChat, tmp_path) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        app.state.agent = AgentCore(chat)
        app.state.tts = FakeTts()
        app.state.audio_store = AudioStore(str(tmp_path))
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_session_ready_is_sent_on_connect(client: TestClient) -> None:
    with client.websocket_connect("/ws/control") as ws:
        message = ws.receive_json()

    assert message["type"] == "session.ready"
    assert message["payload"]["session_id"]


def test_user_text_is_answered_by_the_agent(client: TestClient, chat: FakeChat) -> None:
    with client.websocket_connect("/ws/control") as ws:
        ws.receive_json()
        ws.send_json(USER_TEXT)
        reply = ws.receive_json()

    assert reply["type"] == "agent.text"
    assert reply["payload"]["reply_to"] == "m1"
    assert reply["payload"]["text"] == "吾辈 已收到。"
    assert chat.calls[0][0] == "你好"
    assert chat.calls[0][1] is not None  # 系统提示确实传下去了


def test_chinese_reply_is_not_rewritten(tmp_path) -> None:
    chat = FakeChat(reply_text="吾辈，主人好。")
    with TestClient(app) as test_client:
        app.state.agent = AgentCore(chat)
        app.state.tts = FakeTts()
        app.state.audio_store = AudioStore(str(tmp_path))

        with test_client.websocket_connect("/ws/control") as ws:
            ws.receive_json()
            ws.send_json(USER_TEXT)
            reply = ws.receive_json()
            assert reply["type"] == "agent.text"
            assert reply["payload"]["text"] == "吾辈，主人好。"
            assert ws.receive_json()["type"] == "tts.started"
            assert ws.receive_json()["type"] == "tts.ready"

    assert len(chat.calls) == 1
    assert app.state.tts.requests[0].text == "吾辈，主人好。"
    assert app.state.tts.requests[0].text_language == "zh"
    assert app.state.tts.requests[0].refer_wav_path == "/workspace/data/references/murasame_ref.ogg"
    assert app.state.tts.requests[0].prompt_text == "はっはっはっは"
    assert app.state.tts.requests[0].prompt_language == "ja"


def test_japanese_kana_reply_is_rewritten_before_agent_text_and_tts(tmp_path) -> None:
    chat = FakeChat(replies=["ご主人、元気？", "吾辈很好，主人呢？"])
    with TestClient(app) as test_client:
        app.state.agent = AgentCore(chat)
        app.state.tts = FakeTts()
        app.state.audio_store = AudioStore(str(tmp_path))

        with test_client.websocket_connect("/ws/control") as ws:
            ws.receive_json()
            ws.send_json(USER_TEXT)
            reply = ws.receive_json()
            assert reply["type"] == "agent.text"
            assert reply["payload"]["text"] == "吾辈很好，主人呢？"
            assert ws.receive_json()["type"] == "tts.started"
            assert ws.receive_json()["type"] == "tts.ready"

    assert len(chat.calls) == 2
    assert app.state.tts.requests[0].text == "吾辈很好，主人呢？"
    assert app.state.tts.requests[0].text_language == "zh"


def test_unresolved_japanese_reply_sends_error_without_agent_text_or_tts(tmp_path) -> None:
    chat = FakeChat(replies=["こんにちは", "まだ日本語です"])
    with TestClient(app) as test_client:
        app.state.agent = AgentCore(chat)
        app.state.tts = FakeTts()
        app.state.audio_store = AudioStore(str(tmp_path))

        with test_client.websocket_connect("/ws/control") as ws:
            ws.receive_json()
            ws.send_json(USER_TEXT)
            error = ws.receive_json()

    assert error["type"] == "error"
    assert error["payload"]["code"] == "agent_language_unresolved"
    assert error["payload"]["reply_to"] == "m1"
    assert len(chat.calls) == 2
    assert app.state.tts.requests == []


def test_text_reply_is_synthesized_and_audio_can_be_fetched(client: TestClient) -> None:
    with client.websocket_connect("/ws/control") as ws:
        ws.receive_json()
        ws.send_json(USER_TEXT)
        assert ws.receive_json()["type"] == "agent.text"
        assert ws.receive_json()["type"] == "tts.started"
        ready = ws.receive_json()

    assert ready["type"] == "tts.ready"
    audio_response = client.get(ready["payload"]["audio_url"])
    assert audio_response.status_code == 200
    assert audio_response.content == b"RIFF test audio"
    tts = app.state.tts
    assert tts.requests[0].refer_wav_path == "/workspace/data/references/murasame_ref.ogg"
    assert tts.requests[0].prompt_text == "はっはっはっは"
    assert tts.requests[0].prompt_language == "ja"


def test_tts_cancel_reports_cancelled_reason(chat: FakeChat, tmp_path) -> None:
    with TestClient(app) as client:
        app.state.agent = AgentCore(chat)
        app.state.tts = FakeTts(block=True)
        app.state.audio_store = AudioStore(str(tmp_path))
        with client.websocket_connect("/ws/control") as ws:
            ws.receive_json()
            ws.send_json(USER_TEXT)
            ws.receive_json()
            started = ws.receive_json()
            ws.send_json(
                {
                    "type": "tts.cancel",
                    "id": "cancel-1",
                    "ts": 2,
                    "payload": {"tts_id": started["payload"]["tts_id"]},
                }
            )
            cancelled = ws.receive_json()

    assert cancelled["type"] == "tts.cancelled"
    assert cancelled["payload"]["reason"] == "cancelled"


def test_tts_failure_returns_tts_unavailable_error(chat: FakeChat, tmp_path) -> None:
    with TestClient(app) as client:
        app.state.agent = AgentCore(chat)
        app.state.tts = FakeTts(failure="服务不可用")
        app.state.audio_store = AudioStore(str(tmp_path))
        with client.websocket_connect("/ws/control") as ws:
            ws.receive_json()
            ws.send_json(USER_TEXT)
            assert ws.receive_json()["type"] == "agent.text"
            assert ws.receive_json()["type"] == "tts.started"
            error = ws.receive_json()

    assert error["type"] == "error"
    assert error["payload"]["code"] == "tts_unavailable"


def test_channel_survives_malformed_message(client: TestClient) -> None:
    with client.websocket_connect("/ws/control") as ws:
        ws.receive_json()

        ws.send_text("这不是 JSON")
        assert ws.receive_json()["payload"]["code"] == "invalid_message"

        ws.send_json({"type": "ping", "id": "m2", "ts": 1, "payload": {}})
        assert ws.receive_json()["payload"]["code"] == "invalid_message"

        # 信封合法但前端不该发这个类型，走 unsupported_type 分支
        ws.send_json({"type": "session.ready", "id": "m4", "ts": 1, "payload": {"session_id": "x"}})
        assert ws.receive_json()["payload"]["code"] == "unsupported_type"

        ws.send_json({"type": "user.text", "id": "m3", "ts": 1, "payload": {"text": ""}})
        assert ws.receive_json()["payload"]["code"] == "invalid_message"

        ws.send_json(USER_TEXT)
        assert ws.receive_json()["type"] == "agent.text"


def test_llm_failure_becomes_an_error_message() -> None:
    with TestClient(app) as test_client:
        app.state.agent = AgentCore(FakeChat(failure="连接被拒绝"))

        with test_client.websocket_connect("/ws/control") as ws:
            ws.receive_json()
            ws.send_json(USER_TEXT)
            error = ws.receive_json()

            assert error["type"] == "error"
            assert error["payload"]["code"] == "llm_unavailable"
            assert error["payload"]["reply_to"] == "m1"

            # 报错后连接仍可继续使用
            ws.send_json(USER_TEXT)
            assert ws.receive_json()["type"] == "error"
