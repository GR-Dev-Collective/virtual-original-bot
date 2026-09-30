from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.models.tts.gpt_sovits import TtsRequest

router = APIRouter(prefix="/tts")


class TtsPayload(BaseModel):
    text: str = Field(min_length=1)
    text_language: str = "zh"
    refer_wav_path: str | None = None
    prompt_text: str | None = None
    prompt_language: str | None = None


@router.post("")
async def synthesize(payload: TtsPayload, request: Request) -> Response:
    audio = await request.app.state.tts.synthesize(TtsRequest(**payload.model_dump()))
    return Response(content=audio, media_type="audio/wav")
