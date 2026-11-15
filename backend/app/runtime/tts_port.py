"""兼容层：t8 之前运行时使用的 TtsPort 名称。

Provider 类型已迁移到 ``app.models.tts.base``；本模块只做别名，保留旧的导入路径，
不再包含任何硬编码的参考音频 / prompt 路径（legacy 参数在
``backend/config/voices.json`` 的 ``gpt_sovits`` 段）。
"""

from app.models.tts.base import (
    SynthesisRequest as TtsSynthesisRequest,
)
from app.models.tts.base import (
    TtsProvider as TtsPort,
)
from app.models.tts.base import (
    TtsUnavailable,
)

__all__ = ["TtsPort", "TtsSynthesisRequest", "TtsUnavailable"]
