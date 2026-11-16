"""引擎层测试：不依赖 GPU / torch。"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.indextts_service.engine import (
    IndexTts2Engine,
    MockEngine,
    build_engine,
)
from services.indextts_service.errors import (
    EMOTION_UNAVAILABLE,
    INVALID_REQUEST,
    MODEL_LOADING,
    SYNTHESIS_FAILED,
    ServiceError,
)
from services.indextts_service.settings import Settings


@pytest.fixture
def real_settings(tmp_path: Path) -> Settings:
    model_dir = tmp_path / "checkpoints"
    model_dir.mkdir()
    (model_dir / "config.yaml").write_text("version: 2.5\n", encoding="utf-8")
    return Settings.from_env(
        {
            "INDEXTTS_ENGINE": "indextts2",
            "INDEXTTS_PRELOAD": "false",
            "INDEXTTS_HOME": str(tmp_path),
            "INDEXTTS_MODEL_DIR": str(model_dir),
            "INDEXTTS_WORK_DIR": str(tmp_path / "work"),
        }
    )


@pytest.fixture
def ref_audio(tmp_path: Path) -> Path:
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


def _request(ref_audio: Path, **overrides) -> dict[str, object]:
    body: dict[str, object] = {
        "text": "こんにちは",
        "reference_audio": str(ref_audio),
    }
    body.update(overrides)
    return body


class RecordingModel:
    def __init__(self, payload: bytes = b"RIFFfake", error=None):
        self.payload = payload
        self.error = error
        self.kwargs: dict[str, object] | None = None

    def infer(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        Path(str(kwargs["output_path"])).write_bytes(self.payload)


def _ready_engine(settings, model, qwen_emo: bool = True) -> IndexTts2Engine:
    engine = IndexTts2Engine(settings)
    engine._model = model
    engine._loaded = True
    engine._has_qwen_emo = qwen_emo
    return engine


def _parse(request_body):
    from services.indextts_service.schemas import SynthesisRequest

    return SynthesisRequest.model_validate(request_body)


def test_build_engine_selects_implementation(real_settings):
    mock_settings = Settings.from_env(
        {
            "INDEXTTS_ENGINE": "mock",
            "INDEXTTS_HOME": str(real_settings.home),
        }
    )
    assert isinstance(build_engine(mock_settings), MockEngine)
    assert isinstance(build_engine(real_settings), IndexTts2Engine)


def test_status_not_loaded(real_settings):
    status = IndexTts2Engine(real_settings).status()
    assert status.engine == "index_tts_2"
    assert status.loaded is False
    assert status.device == "cuda:0"
    assert status.model_dir == str(real_settings.model_dir)
    assert status.sample_rate == 22050


def test_load_rejects_missing_model_dir(real_settings, tmp_path):
    engine = IndexTts2Engine(real_settings)
    engine._settings = Settings.from_env(
        {
            "INDEXTTS_ENGINE": "indextts2",
            "INDEXTTS_HOME": str(tmp_path),
            "INDEXTTS_MODEL_DIR": str(tmp_path / "nope"),
        }
    )
    with pytest.raises(FileNotFoundError):
        engine.load()


def test_load_rejects_missing_config(real_settings, tmp_path):
    model_dir = tmp_path / "empty-checkpoints"
    model_dir.mkdir()
    settings = Settings.from_env(
        {
            "INDEXTTS_ENGINE": "indextts2",
            "INDEXTTS_HOME": str(tmp_path),
            "INDEXTTS_MODEL_DIR": str(model_dir),
        }
    )
    with pytest.raises(FileNotFoundError):
        IndexTts2Engine(settings).load()


def test_find_qwen_emo_dir(tmp_path):
    model_dir = tmp_path / "checkpoints"
    model_dir.mkdir()
    assert IndexTts2Engine._find_qwen_emo_dir(model_dir) is None
    qwen = model_dir / "qwen0.6bemo4-merge"
    qwen.mkdir()
    assert IndexTts2Engine._find_qwen_emo_dir(model_dir) == qwen


def test_infer_kwargs_without_emotion(real_settings, ref_audio):
    engine = IndexTts2Engine(real_settings)
    kwargs = engine._build_infer_kwargs(
        _parse(_request(ref_audio)), "out.wav"
    )
    assert kwargs == {
        "spk_audio_prompt": str(ref_audio),
        "text": "こんにちは",
        "lang": "ZH",
        "output_path": "out.wav",
        "duration_factor": 1.0,
        "text_normalization": True,
        "max_text_tokens_per_segment": 120,
        "verbose": False,
    }


def test_infer_kwargs_with_vector_emotion(real_settings, ref_audio):
    engine = IndexTts2Engine(real_settings)
    request = _parse(
        _request(
            ref_audio,
            emotion={
                "mode": "vector",
                "vector": [0.0, 0.1, 0.2, 0.0, 0.0, 0.0, 0.0, 0.1],
                "alpha": 0.5,
            },
        )
    )
    kwargs = engine._build_infer_kwargs(request, "out.wav")
    assert kwargs["emo_vector"] == [0.0, 0.1, 0.2, 0.0, 0.0, 0.0, 0.0, 0.1]
    assert kwargs["emo_alpha"] == 0.5


def test_infer_kwargs_with_audio_emotion(real_settings, ref_audio):
    engine = IndexTts2Engine(real_settings)
    request = _parse(
        _request(
            ref_audio,
            emotion={"mode": "audio", "audio": str(ref_audio), "alpha": 0.8},
        )
    )
    kwargs = engine._build_infer_kwargs(request, "out.wav")
    assert kwargs["emo_audio_prompt"] == str(ref_audio)
    assert kwargs["emo_alpha"] == 0.8


def test_infer_kwargs_with_text_emotion(real_settings, ref_audio):
    engine = IndexTts2Engine(real_settings)
    request = _parse(
        _request(
            ref_audio,
            emotion={"mode": "text", "text": "开心", "alpha": 0.9},
        )
    )
    kwargs = engine._build_infer_kwargs(request, "out.wav")
    assert kwargs["use_emo_text"] is True
    assert kwargs["emo_text"] == "开心"
    assert kwargs["emo_alpha"] == 0.9


def test_synthesize_reads_and_removes_temp_file(real_settings, ref_audio):
    model = RecordingModel()
    engine = _ready_engine(real_settings, model)
    audio = engine.synthesize(_parse(_request(ref_audio)))
    assert audio == b"RIFFfake"
    assert model.kwargs is not None
    assert not list(
        Path(real_settings.work_dir).glob("indextts_*.wav")
    )


def test_synthesize_text_emotion_without_qwen(real_settings, ref_audio):
    engine = _ready_engine(real_settings, RecordingModel(), qwen_emo=False)
    request = _parse(
        _request(
            ref_audio, emotion={"mode": "text", "text": "开心", "alpha": 0.5}
        )
    )
    with pytest.raises(ServiceError) as exc_info:
        engine.synthesize(request)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == EMOTION_UNAVAILABLE


def test_synthesize_runtime_qwen_error_maps_to_400(real_settings, ref_audio):
    model = RecordingModel(
        error=RuntimeError("use_emo_text=True requires QwenEmotion")
    )
    engine = _ready_engine(real_settings, model)
    request = _parse(
        _request(
            ref_audio, emotion={"mode": "text", "text": "开心", "alpha": 0.5}
        )
    )
    with pytest.raises(ServiceError) as exc_info:
        engine.synthesize(request)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == EMOTION_UNAVAILABLE


def test_synthesize_value_error_maps_to_400(real_settings, ref_audio):
    engine = _ready_engine(
        real_settings, RecordingModel(error=ValueError("bad audio"))
    )
    with pytest.raises(ServiceError) as exc_info:
        engine.synthesize(_parse(_request(ref_audio)))
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == INVALID_REQUEST


def test_synthesize_generic_error_maps_to_500(real_settings, ref_audio):
    engine = _ready_engine(
        real_settings, RecordingModel(error=RuntimeError("boom"))
    )
    with pytest.raises(ServiceError) as exc_info:
        engine.synthesize(_parse(_request(ref_audio)))
    assert exc_info.value.status_code == 500
    assert exc_info.value.code == SYNTHESIS_FAILED


def test_synthesize_rejects_empty_output(real_settings, ref_audio):
    engine = _ready_engine(real_settings, RecordingModel(payload=b""))
    with pytest.raises(ServiceError) as exc_info:
        engine.synthesize(_parse(_request(ref_audio)))
    assert exc_info.value.status_code == 500
    assert exc_info.value.code == SYNTHESIS_FAILED


def test_synthesize_not_loaded(real_settings, ref_audio):
    engine = IndexTts2Engine(real_settings)
    with pytest.raises(ServiceError) as exc_info:
        engine.synthesize(_parse(_request(ref_audio)))
    assert exc_info.value.status_code == 503
    assert exc_info.value.code == MODEL_LOADING


def test_mock_engine_requires_load(ref_audio):
    engine = MockEngine()
    with pytest.raises(ServiceError) as exc_info:
        engine.synthesize(_parse(_request(ref_audio)))
    assert exc_info.value.status_code == 503
