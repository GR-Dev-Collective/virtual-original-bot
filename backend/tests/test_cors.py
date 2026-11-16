"""CORS：Electron（file:// → Origin: null）与 Vite dev（127.0.0.1:5173）能访问后端。"""

from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_local_renderer_origins() -> None:
    with TestClient(app) as client:
        dev = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
        assert dev.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

        electron = client.get("/health", headers={"Origin": "null"})
        assert electron.headers["access-control-allow-origin"] == "null"


def test_cors_does_not_allow_remote_origin() -> None:
    with TestClient(app) as client:
        remote = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in remote.headers


def test_cors_allows_media_fetch_from_renderer() -> None:
    with TestClient(app) as client:
        sample = client.get("/voices/murasame/sample", headers={"Origin": "null"})
        assert sample.status_code == 200
        assert sample.headers["access-control-allow-origin"] == "null"
