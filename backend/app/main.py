"""FastAPI 应用装配。

启动：uvicorn app.main:app --port 8090
或：  python -m app.main（读取 backend/.env 中的 HOST / PORT）
"""

from fastapi import FastAPI

from app.config import settings
from app.transport.control_ws import router as control_router


def create_app() -> FastAPI:
    app = FastAPI(title="virtual-original-bot backend", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(control_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
