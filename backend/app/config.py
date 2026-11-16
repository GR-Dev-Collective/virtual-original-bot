"""后端运行配置。

默认值可直接运行；需要覆盖时在 backend/ 下建 .env（见 .env.example）。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py → backend/ 与仓库根。
# 配置/运行目录相对 backend/ 解析，音色参考音频相对仓库根解析。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8090
    log_level: str = "info"

    # 控制协议与会话运行时
    protocol_version: str = "vob/1"
    session_directory: str = "runtime/sessions"
    history_max_messages: int = 12
    history_max_chars: int = 4000
    session_event_limit: int = 2000
    memory_directory: str = "runtime/memory"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = 300.0
    ollama_num_ctx: int = 4096
    # None = 交给 Ollama 自动分配；0 = 强制 CPU，避免和 IndexTTS 抢 8GB 显存。
    ollama_num_gpu: int | None = None

    # TTS：默认 IndexTTS-2.5 sidecar，GPT-SoVITS 保留为 legacy。
    tts_provider: str = "index_tts"
    index_tts_base_url: str = "http://127.0.0.1:9882"
    index_tts_timeout_seconds: float = 180.0
    gpt_sovits_base_url: str = "http://127.0.0.1:9880/"
    gpt_sovits_timeout_seconds: float = 180.0

    # 音色档案：内置档案 + 用户克隆档案（用户优先）。
    voice_profiles_path: str = "config/voices.json"
    user_voice_directory: str = "runtime/voices"
    default_voice_id: str = "murasame"

    audio_directory: str = "runtime/audio"
    asr_model_path: str = "../docker/gpt-sovits/models/asr_models/faster-whisper-large-v3"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"


settings = Settings()

__all__ = ["BACKEND_ROOT", "REPO_ROOT", "Settings", "settings"]
