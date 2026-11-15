"""TTS 引擎实现：MockEngine（无 GPU）与 IndexTts2Engine（真实模型）。

本模块在导入时不会导入 torch 或 indextts；真实模型只在 ``load()`` 中延迟导入，
因此单元测试可以在没有 GPU / torch 的环境中运行。
"""

from __future__ import annotations

import io
import math
import os
import struct
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .schemas import SynthesisRequest
from .settings import Settings

MOCK_SAMPLE_RATE = 22050
MOCK_DURATION_SECONDS = 0.5
EMOTION_ERROR_MESSAGE = (
    "当前模型缺少 QwenEmotion 资源（qwen_emo_path），无法使用 emotion.mode=text；"
    "请改用 vector/audio 情感模式，或把 QwenEmotion 模型放入 checkpoints 目录。"
)
MODEL_LOADING_MESSAGE = "模型尚未加载完成，请稍后重试"


@dataclass(frozen=True)
class EngineStatus:
    engine: str
    loaded: bool
    device: str
    model_dir: str
    sample_rate: int


class Engine(Protocol):
    """引擎接口：加载、合成与状态查询。"""

    def load(self) -> None:
        """加载模型；失败时抛出真实异常。"""

    def synthesize(self, request: SynthesisRequest) -> bytes:
        """返回 WAV 字节；失败时抛出 ServiceError。"""

    def status(self) -> EngineStatus:
        """返回健康检查所需状态。"""


def _build_mock_wav() -> bytes:
    """生成 0.5 秒、22050Hz、16-bit 单声道正弦 WAV。"""
    frame_count = int(MOCK_SAMPLE_RATE * MOCK_DURATION_SECONDS)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(MOCK_SAMPLE_RATE)
        frames = bytearray()
        for index in range(frame_count):
            angle = 2.0 * math.pi * 440.0 * index / MOCK_SAMPLE_RATE
            frames.extend(struct.pack("<h", int(0.3 * 32767 * math.sin(angle))))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


class MockEngine:
    """纯标准库引擎，用于无 GPU 环境、启动脚本自检与测试。"""

    engine_name = "mock"
    sample_rate = MOCK_SAMPLE_RATE

    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return self._loaded

    def status(self) -> EngineStatus:
        return EngineStatus(
            engine=self.engine_name,
            loaded=self._loaded,
            device="cpu",
            model_dir="mock",
            sample_rate=self.sample_rate,
        )

    def synthesize(self, request: SynthesisRequest) -> bytes:
        if not self._loaded:
            from .errors import MODEL_LOADING, ServiceError

            raise ServiceError(503, MODEL_LOADING, MODEL_LOADING_MESSAGE, 5)
        return _build_mock_wav()


class IndexTts2Engine:
    """IndexTTS-2.5 真实推理引擎（延迟导入 torch / indextts）。"""

    engine_name = "index_tts_2"
    sample_rate = 22050

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: object | None = None
        self._loaded = False
        self._has_qwen_emo = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def status(self) -> EngineStatus:
        return EngineStatus(
            engine=self.engine_name,
            loaded=self._loaded,
            device=self._settings.device,
            model_dir=str(self._settings.model_dir),
            sample_rate=self.sample_rate,
        )

    def load(self) -> None:
        """加载 IndexTTS2 模型；异常原样抛出，由调用方记录/退出。"""
        if self._loaded:
            return

        model_dir = Path(self._settings.model_dir)
        cfg_path = Path(self._settings.cfg_path)
        if not model_dir.is_dir():
            msg = f"模型目录不存在: {model_dir}"
            raise FileNotFoundError(msg)
        if not cfg_path.is_file():
            msg = f"模型配置不存在: {cfg_path}"
            raise FileNotFoundError(msg)

        # 延迟导入，避免测试/无 GPU 环境导入 torch。
        from indextts.infer_v2_5 import IndexTTS2

        qwen_emo_dir = self._find_qwen_emo_dir(model_dir)
        self._model = IndexTTS2(
            cfg_path=str(cfg_path),
            model_dir=str(model_dir),
            use_bf16=self._settings.use_bf16,
            device=self._settings.device,
            use_qwen_emo=qwen_emo_dir is not None,
        )
        self._has_qwen_emo = qwen_emo_dir is not None
        self._loaded = True

    @staticmethod
    def _find_qwen_emo_dir(model_dir: Path) -> Path | None:
        """QwenEmotion 资源可选；缺失时文本情感模式返回 emotion_unavailable。"""
        candidates = [model_dir / "qwen0.6bemo4-merge"]
        candidates.extend(sorted(model_dir.glob("qwen*emo*")))
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    def _build_infer_kwargs(
        self, request: SynthesisRequest, output_path: str
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "spk_audio_prompt": request.reference_audio,
            "text": request.text,
            "lang": request.language,
            "output_path": output_path,
            "duration_factor": request.duration_factor,
            "text_normalization": request.text_normalization,
            "max_text_tokens_per_segment": request.max_text_tokens_per_segment,
            "verbose": False,
        }
        emotion = request.emotion
        if emotion is None:
            return kwargs
        if emotion.mode == "vector":
            kwargs["emo_vector"] = list(emotion.vector)
            kwargs["emo_alpha"] = emotion.alpha
        elif emotion.mode == "audio":
            kwargs["emo_audio_prompt"] = emotion.audio
            kwargs["emo_alpha"] = emotion.alpha
        else:
            kwargs["use_emo_text"] = True
            kwargs["emo_text"] = emotion.text
            kwargs["emo_alpha"] = emotion.alpha
        return kwargs

    def synthesize(self, request: SynthesisRequest) -> bytes:
        from .errors import (
            EMOTION_UNAVAILABLE,
            INVALID_REQUEST,
            MODEL_LOADING,
            SYNTHESIS_FAILED,
            ServiceError,
        )

        if not self._loaded or self._model is None:
            raise ServiceError(503, MODEL_LOADING, MODEL_LOADING_MESSAGE, 5)

        emotion = request.emotion
        if emotion is not None and emotion.mode == "text" and not self._has_qwen_emo:
            raise ServiceError(400, EMOTION_UNAVAILABLE, EMOTION_ERROR_MESSAGE)

        work_dir = Path(self._settings.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        file_descriptor, output_path = tempfile.mkstemp(
            prefix="indextts_", suffix=".wav", dir=work_dir
        )
        os.close(file_descriptor)
        try:
            kwargs = self._build_infer_kwargs(request, output_path)
            try:
                self._model.infer(**kwargs)  # type: ignore[attr-defined]
                audio = Path(output_path).read_bytes()
            except ServiceError:
                raise
            except RuntimeError as exc:
                text = str(exc)
                if "QwenEmotion" in text or "use_qwen_emo" in text:
                    raise ServiceError(
                        400, EMOTION_UNAVAILABLE, EMOTION_ERROR_MESSAGE
                    ) from exc
                raise ServiceError(
                    500, SYNTHESIS_FAILED, f"语音合成失败: {text}"
                ) from exc
            except ValueError as exc:
                raise ServiceError(
                    400, INVALID_REQUEST, f"合成参数无效: {exc}"
                ) from exc
            except Exception as exc:  # 统一映射为 500
                raise ServiceError(
                    500, SYNTHESIS_FAILED, f"语音合成失败: {exc}"
                ) from exc
            if not audio:
                raise ServiceError(500, SYNTHESIS_FAILED, "模型未生成音频数据")
            return audio
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass


def build_engine(settings: Settings) -> Engine:
    if settings.engine == "mock":
        return MockEngine()
    return IndexTts2Engine(settings)
