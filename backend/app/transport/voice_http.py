from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/asr")


class AsrResponse(BaseModel):
    text: str


@router.post("", response_model=AsrResponse)
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
) -> AsrResponse:
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="录音为空")

    with NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        temp.write(data)
        path = temp.name
    try:
        text = await request.app.state.asr.transcribe(path)
        return AsrResponse(text=text)
    finally:
        Path(path).unlink(missing_ok=True)
