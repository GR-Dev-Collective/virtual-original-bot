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


settings = Settings()
