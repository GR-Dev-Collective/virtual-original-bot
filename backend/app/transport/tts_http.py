"""``POST /tts``：调试/脚本用的单次合成接口（默认音色可省略 voice_id）。"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.models.tts.base import TtsUnavailable
from app.voices.models import VoiceNotFound
from app.voices.synthesis import build_synthesis_request

router = APIRouter(prefix="/tts")


class TtsPayload(BaseModel):
    text: str = Field(min_length=1)
    voice_id: str | None = None


@router.post("")
async def synthesize(payload: TtsPayload, request: Request) -> Response:
    registry = request.app.state.voices
    voice_id = payload.voice_id or registry.default_voice_id
    try:
        profile = registry.get(voice_id)
    except VoiceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    provider = getattr(request.app.state, "tts_provider", None) or request.app.state.tts
    try:
        audio = await provider.synthesize(build_synthesis_request(payload.text, profile))
    except TtsUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"TTS 不可用：{exc}") from exc
    return Response(content=audio, media_type="audio/wav")


__all__ = ["TtsPayload", "router", "synthesize"]
