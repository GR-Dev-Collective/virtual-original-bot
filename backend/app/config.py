"""后端运行配置。

默认值可直接运行；需要覆盖时在 backend/ 下建 .env（见 .env.example）。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8090
    log_level: str = "info"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = 120.0

    gpt_sovits_base_url: str = "http://127.0.0.1:9880/"
    gpt_sovits_timeout_seconds: float = 180.0
    audio_directory: str = "runtime/audio"
    asr_model_path: str = "../docker/gpt-sovits/models/asr_models/faster-whisper-large-v3"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"


settings = Settings()
