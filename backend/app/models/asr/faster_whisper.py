import asyncio
from pathlib import Path


class AsrUnavailable(RuntimeError):
    pass


class FasterWhisperAsr:
    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> None:
        self._model_path = Path(model_path)
        self._device = device
        self._compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        if not self._model_path.exists():
            raise AsrUnavailable(f"ASR 模型不存在: {self._model_path}")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise AsrUnavailable("未安装 faster-whisper") from exc
        self._model = WhisperModel(
            str(self._model_path),
            device=self._device,
            compute_type=self._compute_type,
        )
        return self._model

    async def transcribe(self, audio_path: str, language: str | None = None) -> str:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language)

    def _transcribe_sync(self, audio_path: str, language: str | None) -> str:
        try:
            segments, _ = self._load().transcribe(audio_path, language=language, vad_filter=True)
            text = "".join(segment.text for segment in segments).strip()
        except AsrUnavailable:
            raise
        except Exception as exc:
            raise AsrUnavailable(f"ASR 转写失败: {exc}") from exc
        if not text:
            raise AsrUnavailable("ASR 未识别到语音")
        return text
