"""``/sessions``：已持久化会话列表（标题、消息数、最近活动排序）。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "session_directory", str(tmp_path / "sessions"))
    monkeypatch.setattr(settings, "audio_directory", str(tmp_path / "audio"))
    monkeypatch.setattr(settings, "user_voice_directory", str(tmp_path / "voices"))
    with TestClient(app) as test_client:
        yield test_client


def test_lists_sessions_newest_first(client: TestClient) -> None:
    store = app.state.runtime.store
    first = store.create_session()
    store.append_message(first.session_id, role="user", text="第一句 你好", message_id="m1")
    store.append_message(first.session_id, role="assistant", text="你好。", message_id="a1")
    second = store.create_session()
    store.append_message(second.session_id, role="user", text="第二个会话", message_id="m2")

    response = client.get("/sessions")

    assert response.status_code == 200
    sessions = response.json()
    assert [item["session_id"] for item in sessions] == [second.session_id, first.session_id]
    assert sessions[0]["title"] == "第二个会话"
    assert sessions[1]["title"] == "第一句 你好"
    assert sessions[1]["message_count"] == 2
    assert sessions[1]["voice_id"] == "murasame"


def test_empty_sessions_returns_list(client: TestClient) -> None:
    response = client.get("/sessions")

    assert response.status_code == 200
    assert response.json() == []
