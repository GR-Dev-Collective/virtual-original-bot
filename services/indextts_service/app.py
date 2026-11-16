"""FastAPI 应用装配。

启动方式：在仓库根目录执行 ``python -m services.indextts_service``。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .engine import Engine, build_engine
from .errors import (
    INVALID_REQUEST,
    MODEL_LOADING,
    SYNTHESIS_FAILED,
    ServiceError,
)
from .schemas import SynthesisRequest
from .settings import Settings

logger = logging.getLogger("indextts_service")

PRELOAD_EXIT_CODE = 1


def _validation_message(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(
            str(item) for item in error.get("loc", ()) if item != "body"
        )
        message = str(error.get("msg", "参数无效"))
        parts.append(f"{location}: {message}" if location else message)
    detail = "; ".join(parts) if parts else "请求参数无效"
    return f"请求参数无效: {detail}"


def create_app(
    engine: Engine | None = None, settings: Settings | None = None
) -> FastAPI:
    """创建 FastAPI 应用；``engine``/``settings`` 可注入以便测试。"""
    resolved_settings = settings if settings is not None else Settings.from_env()
    resolved_engine = engine if engine is not None else build_engine(
        resolved_settings
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        load_task: asyncio.Task[None] | None = None
        if resolved_settings.preload:
            load_task = asyncio.create_task(_preload())
        try:
            yield
        finally:
            if load_task is not None and not load_task.done():
                load_task.cancel()
                with suppress(asyncio.CancelledError):
                    await load_task

    app = FastAPI(
        title="IndexTTS-2.5 voice cloning sidecar",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.engine = resolved_engine
    # 推理与加载共用一把锁，保证单卡串行执行。
    app.state.engine_lock = asyncio.Lock()

    async def _load_engine() -> None:
        async with app.state.engine_lock:
            await asyncio.to_thread(resolved_engine.load)

    async def _preload() -> None:
        try:
            await _load_engine()
        except Exception:
            logger.exception("IndexTTS 模型加载失败，进程将以非零码退出")
            traceback.print_exc()
            sys.stderr.flush()
            sys.stdout.flush()
            os._exit(PRELOAD_EXIT_CODE)

    async def _release_after(
        future: asyncio.Future[bytes], lock: asyncio.Lock
    ) -> None:
        try:
            await future
        except Exception:
            logger.exception("超时后的后台推理失败")
        finally:
            lock.release()

    @app.exception_handler(ServiceError)
    async def _handle_service_error(
        _: Request, exc: ServiceError
    ) -> JSONResponse:
        headers: dict[str, str] = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"code": exc.code, "message": exc.message}},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": INVALID_REQUEST,
                    "message": _validation_message(exc),
                }
            },
        )

    @app.get("/health")
    async def health() -> dict[str, object]:
        status = resolved_engine.status()
        return {
            "status": "ok",
            "engine": status.engine,
            "loaded": status.loaded,
            "device": status.device,
            "model_dir": status.model_dir,
        }

    @app.post("/synthesize")
    async def synthesize(payload: SynthesisRequest) -> Response:
        status = resolved_engine.status()
        if not status.loaded:
            raise ServiceError(503, MODEL_LOADING, "模型尚未加载完成", 5)

        timeout = resolved_settings.request_timeout_seconds
        lock = app.state.engine_lock
        await lock.acquire()
        future = asyncio.ensure_future(
            asyncio.to_thread(resolved_engine.synthesize, payload)
        )
        try:
            audio = await asyncio.wait_for(
                asyncio.shield(future), timeout=timeout
            )
        except TimeoutError as exc:
            # wait_for 只取消等待协程，线程里的推理无法中止：把锁交给后台
            # 任务，等它真正结束后再释放，避免超时后出现两个推理同时抢 GPU。
            asyncio.create_task(_release_after(future, lock))
            raise ServiceError(
                500,
                SYNTHESIS_FAILED,
                f"语音合成超时（>{timeout:g} 秒，当前推理仍在后台完成）",
            ) from exc
        except ServiceError:
            future.cancel()
            lock.release()
            raise
        except Exception as exc:
            future.cancel()
            lock.release()
            logger.exception("语音合成出现未处理异常")
            raise ServiceError(
                500, SYNTHESIS_FAILED, f"语音合成失败: {exc}"
            ) from exc
        else:
            lock.release()

        return Response(
            content=audio,
            media_type="audio/wav",
            headers={"X-Sample-Rate": str(status.sample_rate)},
        )

    return app


app = create_app()
