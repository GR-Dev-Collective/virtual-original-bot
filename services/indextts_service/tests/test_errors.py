"""错误映射：503 / 400 / 500 与 Retry-After。"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from services.indextts_service.app import create_app
from services.indextts_service.engine import EngineStatus, MockEngine
from services.indextts_service.errors import (
    EMOTION_UNAVAILABLE,
    MODEL_LOADING,
    SYNTHESIS_FAILED,
    ServiceError,
)


class FakeEngine:
    def __init__(self, loaded: bool = True, error: Exception | None = None):
        self._loaded = loaded
        self._error = error

    def load(self) -> None:
        self._loaded = True

    def status(self) -> EngineStatus:
        return EngineStatus(
            engine="fake",
            loaded=self._loaded,
            device="cpu",
            model_dir="fake",
            sample_rate=22050,
        )

    def synthesize(self, request):
        if self._error is not None:
            raise self._error
        return b"RIFFfake"


class SlowEngine(FakeEngine):
    def synthesize(self, request):
        time.sleep(0.3)
        return b"RIFFfake"


def _post(payload, engine, settings):
    app = create_app(engine=engine, settings=settings)
    with TestClient(app) as client:
        return client.post("/synthesize", json=payload)


def test_not_loaded_returns_503(payload, mock_settings):
    response = _post(payload, MockEngine(), mock_settings)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    body = response.json()
    assert body["detail"]["code"] == MODEL_LOADING
    assert body["detail"]["message"]


def test_emotion_unavailable_returns_400(payload, mock_settings):
    error = ServiceError(
        400, EMOTION_UNAVAILABLE, "缺少 QwenEmotion 资源"
    )
    response = _post(payload, FakeEngine(error=error), mock_settings)
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == EMOTION_UNAVAILABLE
    assert "Retry-After" not in response.headers


def test_synthesis_failed_returns_500(payload, mock_settings):
    error = ServiceError(500, SYNTHESIS_FAILED, "推理失败")
    response = _post(payload, FakeEngine(error=error), mock_settings)
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == SYNTHESIS_FAILED


def test_unexpected_exception_returns_500(payload, mock_settings):
    response = _post(
        payload, FakeEngine(error=RuntimeError("boom")), mock_settings
    )
    assert response.status_code == 500
    body = response.json()
    assert body["detail"]["code"] == SYNTHESIS_FAILED
    assert "boom" in body["detail"]["message"]


def test_model_loading_error_keeps_retry_after(payload, mock_settings):
    error = ServiceError(503, MODEL_LOADING, "正在加载", retry_after=5)
    response = _post(payload, FakeEngine(error=error), mock_settings)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["detail"]["code"] == MODEL_LOADING


def test_timeout_returns_500(payload, mock_settings):
    settings = replace(mock_settings, request_timeout_seconds=0.05)
    response = _post(payload, SlowEngine(), settings)
    assert response.status_code == 500
    body = response.json()
    assert body["detail"]["code"] == SYNTHESIS_FAILED
    assert "超时" in body["detail"]["message"]


@pytest.mark.parametrize("code", [EMOTION_UNAVAILABLE, SYNTHESIS_FAILED])
def test_error_response_shape(code, payload, mock_settings):
    error = ServiceError(400, code, "消息")
    response = _post(payload, FakeEngine(error=error), mock_settings)
    assert set(response.json()["detail"]) == {"code", "message"}
