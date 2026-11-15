"""服务统一错误类型。

错误响应体固定为 ``{"detail": {"code": ..., "message": ...}}``，由 app 层
的异常处理器转换。
"""

from __future__ import annotations

INVALID_REQUEST = "invalid_request"
MODEL_LOADING = "model_loading"
SYNTHESIS_FAILED = "synthesis_failed"
EMOTION_UNAVAILABLE = "emotion_unavailable"

VALID_ERROR_CODES = (
    INVALID_REQUEST,
    MODEL_LOADING,
    SYNTHESIS_FAILED,
    EMOTION_UNAVAILABLE,
)


class ServiceError(Exception):
    """带 HTTP 状态码与错误码的业务异常。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retry_after: int | None = None,
    ) -> None:
        if code not in VALID_ERROR_CODES:
            msg = f"未知错误码: {code}"
            raise ValueError(msg)
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after

    def __repr__(self) -> str:
        return (
            f"ServiceError(status_code={self.status_code!r}, "
            f"code={self.code!r}, message={self.message!r})"
        )
