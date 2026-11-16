"""测试公共夹具。

用 ``backend\\.venv\\Scripts\\python.exe -m pytest`` 从仓库根目录运行；
本文件确保仓库根目录在 ``sys.path`` 中。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from services.indextts_service.app import create_app
from services.indextts_service.engine import EngineStatus, MockEngine
from services.indextts_service.settings import Settings


@pytest.fixture
def ref_audio(tmp_path: Path) -> Path:
    path = tmp_path / "murasame_ref.wav"
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


@pytest.fixture
def mock_settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {
            "INDEXTTS_ENGINE": "mock",
            "INDEXTTS_PRELOAD": "false",
            "INDEXTTS_HOME": str(tmp_path),
            "INDEXTTS_WORK_DIR": str(tmp_path / "work"),
        }
    )


@pytest.fixture
def loaded_engine() -> MockEngine:
    engine = MockEngine()
    engine.load()
    return engine


@pytest.fixture
def app(loaded_engine: MockEngine, mock_settings: Settings):
    return create_app(engine=loaded_engine, settings=mock_settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def payload(ref_audio: Path) -> dict[str, object]:
    return {"text": "你好，丛雨。", "reference_audio": str(ref_audio)}


class StaticStatusEngine:
    """注入固定状态/异常的最小引擎，用于错误映射测试。"""

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
