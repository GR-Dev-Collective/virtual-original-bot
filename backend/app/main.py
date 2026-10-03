"""FastAPI 应用装配。

启动：uvicorn app.main:app --port 8090
或：  python -m app.main（读取 backend/.env 中的 HOST / PORT）
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.agent.agent_core import AgentCore
from app.config import settings
from app.models.asr.faster_whisper import FasterWhisperAsr
from app.models.llm.ollama import OllamaChat
from app.models.tts.audio_store import AudioStore
from app.models.tts.gpt_sovits import GptSovitsTts
from app.transport.control_ws import router as control_router
from app.transport.tts_http import router as tts_router
from app.transport.voice_http import router as voice_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
        app.state.agent = AgentCore(
            OllamaChat(settings.ollama_base_url, settings.ollama_model, client)
        )
        app.state.tts = GptSovitsTts(
            settings.gpt_sovits_base_url,
            client,
            timeout=settings.gpt_sovits_timeout_seconds,
        )
        app.state.audio_store = AudioStore(settings.audio_directory)
        app.state.asr = FasterWhisperAsr(
            settings.asr_model_path,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
        )
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="virtual-original-bot backend", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/tts/{audio_id}")
    async def get_tts_audio(audio_id: str) -> FileResponse:
        path = app.state.audio_store.path(audio_id)
        if not path.is_file():
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="音频不存在")
        return FileResponse(path, media_type="audio/wav")

    app.include_router(control_router)
    app.include_router(tts_router)
    app.include_router(voice_router)
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
