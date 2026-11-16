"""``/memory`` HTTP：读取、新增/删除备注、修改称呼。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "memory_directory", str(tmp_path / "memory"))
    monkeypatch.setattr(settings, "session_directory", str(tmp_path / "sessions"))
    monkeypatch.setattr(settings, "audio_directory", str(tmp_path / "audio"))
    monkeypatch.setattr(settings, "user_voice_directory", str(tmp_path / "voices"))
    with TestClient(app) as test_client:
        yield test_client


def test_memory_roundtrip(client: TestClient) -> None:
    initial = client.get("/memory")
    assert initial.status_code == 200
    assert initial.json()["user_name"] is None
    assert initial.json()["notes"] == []

    created = client.post("/memory/notes", json={"text": "我喜欢红茶"})
    assert created.status_code == 201
    note_id = created.json()["id"]

    renamed = client.patch("/memory/user", json={"name": "主人"})
    assert renamed.status_code == 200
    assert renamed.json()["user_name"] == "主人"

    snapshot = client.get("/memory").json()
    assert snapshot["notes"][0]["text"] == "我喜欢红茶"
    assert snapshot["relationship"]["affinity"] == 0

    deleted = client.delete(f"/memory/notes/{note_id}")
    assert deleted.status_code == 204
    assert client.delete(f"/memory/notes/{note_id}").status_code == 404


def test_memory_rejects_empty_note(client: TestClient) -> None:
    response = client.post("/memory/notes", json={"text": "   "})

    assert response.status_code == 400
