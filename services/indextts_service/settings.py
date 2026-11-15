"""服务配置：全部来自环境变量，并提供适合本机环境的默认值。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INDEXTTS_HOME = Path(
    r"C:\Users\chen\Documents\deepseek-harness\default-workspace\index-tts"
)

VALID_ENGINES = ("indextts2", "mock")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_str(env: Mapping[str, str], name: str, default: str) -> str:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    msg = f"{name} 必须是布尔值（true/false），当前为 {raw!r}"
    raise ValueError(msg)


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        msg = f"{name} 必须是整数，当前为 {raw!r}"
        raise ValueError(msg) from exc


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        msg = f"{name} 必须是数字，当前为 {raw!r}"
        raise ValueError(msg) from exc


@dataclass(frozen=True)
class Settings:
    """运行期配置快照。"""

    engine: str
    home: Path
    model_dir: Path
    cfg_path: Path
    device: str
    use_bf16: bool
    host: str
    port: int
    preload: bool
    work_dir: Path
    request_timeout_seconds: float

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """从环境变量构建配置；``env`` 可注入用于测试。"""
        source: Mapping[str, str] = os.environ if env is None else env

        engine = _env_str(source, "INDEXTTS_ENGINE", "indextts2").lower()
        if engine not in VALID_ENGINES:
            msg = (
                "INDEXTTS_ENGINE 只能是 indextts2 或 mock，"
                f"当前为 {engine!r}"
            )
            raise ValueError(msg)

        home = Path(
            _env_str(source, "INDEXTTS_HOME", str(DEFAULT_INDEXTTS_HOME))
        ).expanduser()
        model_dir = Path(
            _env_str(source, "INDEXTTS_MODEL_DIR", str(home / "checkpoints"))
        ).expanduser()
        cfg_path = Path(
            _env_str(
                source, "INDEXTTS_CFG_PATH", str(model_dir / "config.yaml")
            )
        ).expanduser()
        work_dir = Path(
            _env_str(
                source,
                "INDEXTTS_WORK_DIR",
                str(home / ".runtime" / "indextts_service"),
            )
        ).expanduser()

        port = _env_int(source, "INDEXTTS_PORT", 9882)
        if not 1 <= port <= 65535:
            msg = f"INDEXTTS_PORT 必须在 1..65535 之间，当前为 {port}"
            raise ValueError(msg)

        timeout = _env_float(source, "INDEXTTS_REQUEST_TIMEOUT_SECONDS", 180.0)
        if timeout <= 0:
            msg = "INDEXTTS_REQUEST_TIMEOUT_SECONDS 必须大于 0"
            raise ValueError(msg)

        return cls(
            engine=engine,
            home=home,
            model_dir=model_dir,
            cfg_path=cfg_path,
            device=_env_str(source, "INDEXTTS_DEVICE", "cuda:0"),
            use_bf16=_env_bool(source, "INDEXTTS_USE_BF16", True),
            host=_env_str(source, "INDEXTTS_HOST", "127.0.0.1"),
            port=port,
            preload=_env_bool(source, "INDEXTTS_PRELOAD", True),
            work_dir=work_dir,
            request_timeout_seconds=timeout,
        )
