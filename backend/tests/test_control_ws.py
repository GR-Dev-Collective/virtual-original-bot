"""控制通道的端到端测试：握手、回复、非法消息，以及 LLM 不可用时的报错。

测试用假 ChatModel 替换真实 Ollama，不产生任何外部请求。
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.agent.agent_core import AgentCore
from app.main import app
from app.models.llm import LlmUnavailable

USER_TEXT = {"type": "user.text", "id": "m1", "ts": 1, "payload": {"text": "你好"}}


class FakeChat:
    def __init__(self, reply_text: str = "我が輩 已收到。", failure: str | None = None) -> None:
        self._reply_text = reply_text
        self._failure = failure
        self.calls: list[tuple[str, str | None]] = []

    async def reply(self, text: str, system: str | None = None) -> str:
        self.calls.append((text, system))
        if self._failure is not None:
            raise LlmUnavailable(self._failure)
        return self._reply_text


@pytest.fixture
def chat() -> FakeChat:
    return FakeChat()


@pytest.fixture
def client(chat: FakeChat) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        app.state.agent = AgentCore(chat)
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
    assert reply["payload"]["text"] == "我が輩 已收到。"
    assert chat.calls[0][0] == "你好"
    assert chat.calls[0][1] is not None  # 系统提示确实传下去了


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
