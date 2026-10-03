from pathlib import Path
from uuid import uuid4


class AudioStore:
    def __init__(self, directory: str) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def save(self, audio: bytes) -> str:
        audio_id = uuid4().hex
        (self._directory / f"{audio_id}.wav").write_bytes(audio)
        return audio_id

    def path(self, audio_id: str) -> Path:
        if not audio_id.isalnum():
            raise ValueError("无效音频 ID")
        return self._directory / f"{audio_id}.wav"
