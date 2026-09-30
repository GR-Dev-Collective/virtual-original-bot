"""控制通道的端到端测试：握手、回声、以及非法消息的处理。"""

from fastapi.testclient import TestClient

from app.main import app

USER_TEXT = {"type": "user.text", "id": "m1", "ts": 1, "payload": {"text": "你好"}}


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_session_ready_is_sent_on_connect() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/control") as ws:
        message = ws.receive_json()

    assert message["type"] == "session.ready"
    assert message["payload"]["session_id"]


def test_user_text_gets_agent_reply() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/control") as ws:
        ws.receive_json()
        ws.send_json(USER_TEXT)
        reply = ws.receive_json()

    assert reply["type"] == "agent.text"
    assert reply["payload"]["reply_to"] == "m1"
    assert "你好" in reply["payload"]["text"]


def test_channel_survives_malformed_message() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/control") as ws:
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
