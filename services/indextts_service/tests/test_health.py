"""GET /health 与预加载行为。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from services.indextts_service.app import create_app
from services.indextts_service.engine import MockEngine
from services.indextts_service.settings import Settings


def test_health_when_loaded(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "engine": "mock",
        "loaded": True,
        "device": "cpu",
        "model_dir": "mock",
    }


def test_health_when_not_loaded(mock_settings: Settings):
    app = create_app(engine=MockEngine(), settings=mock_settings)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["loaded"] is False


def test_preload_loads_engine_in_background(tmp_path):
    settings = Settings.from_env(
        {
            "INDEXTTS_ENGINE": "mock",
            "INDEXTTS_PRELOAD": "true",
            "INDEXTTS_HOME": str(tmp_path),
            "INDEXTTS_WORK_DIR": str(tmp_path / "work"),
        }
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        deadline = time.monotonic() + 5.0
        body = {}
        while time.monotonic() < deadline:
            body = client.get("/health").json()
            if body.get("loaded"):
                break
            time.sleep(0.05)
    assert body["loaded"] is True
