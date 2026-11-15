"""FastAPI 应用装配。

启动：uvicorn app.main:app --port 8090
或：  python -m app.main（读取 backend/.env 中的 HOST / PORT）
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.agent.agent_core import AgentCore
from app.config import settings
from app.models.asr.faster_whisper import FasterWhisperAsr
from app.models.llm.ollama import OllamaChat
from app.models.tts.audio_store import AudioStore
from app.models.tts.factory import build_tts_provider
from app.runtime.runtime import CharacterRuntime
from app.session.store import SessionStore
from app.transport.control_ws import router as control_router
from app.transport.tts_http import router as tts_router
from app.transport.voice_http import router as voice_router
from app.transport.voices_http import router as voices_router
from app.voices.registry import VoiceRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # trust_env=False：本机代理环境变量会让 httpx 0.28 解析 NO_PROXY 时抛 InvalidURL。
    async with httpx.AsyncClient(
        timeout=settings.ollama_timeout_seconds,
        trust_env=False,
    ) as client:
        agent = AgentCore(
            OllamaChat(
                settings.ollama_base_url,
                settings.ollama_model,
                client,
                num_ctx=settings.ollama_num_ctx,
                num_gpu=settings.ollama_num_gpu,
            )
        )
        tts_provider = build_tts_provider(settings, client)
        voices = VoiceRegistry(
            settings.voice_profiles_path,
            settings.user_voice_directory,
            default_voice_id=settings.default_voice_id,
        )
        audio_store = AudioStore(settings.audio_directory)
        store = SessionStore(
            settings.session_directory,
            event_limit=settings.session_event_limit,
        )

        app.state.agent = agent
        app.state.tts = tts_provider
        app.state.tts_provider = tts_provider
        # 兼容既有脚本/测试里的旧属性名。
        app.state.tts_port = tts_provider
        app.state.voices = voices
        app.state.audio_store = audio_store
        app.state.runtime = CharacterRuntime(
            store=store,
            agent=agent,
            tts=tts_provider,
            audio_store=audio_store,
            voices=voices,
            history_max_messages=settings.history_max_messages,
            history_max_chars=settings.history_max_chars,
        )
        app.state.asr = FasterWhisperAsr(
            settings.asr_model_path,
            device=settings.asr_device,
            compute_type=settings.asr_compute_type,
        )
        try:
            yield
        finally:
            await app.state.runtime.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="virtual-original-bot backend", version="0.2.0", lifespan=lifespan)

    # Renderer 在 Electron（file:// → Origin: null）或 Vite dev（127.0.0.1:5173）
    # 下跨源访问 /voices、/asr、/tts；只放行本机来源，不开放任意远端。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null"],
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    app.include_router(voices_router)
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
