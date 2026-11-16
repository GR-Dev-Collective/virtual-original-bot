"""``/voices``：音色档案列表、参考音频克隆与删除。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.models.tts.base import VALID_LANGUAGES
from app.voices.audio import InvalidReferenceAudio, normalize_reference_audio
from app.voices.models import BuiltinVoiceProtected, VoiceNotFound, VoiceProfile
from app.voices.registry import VoiceRegistry

router = APIRouter(prefix="/voices", tags=["voices"])


class VoiceView(BaseModel):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    language: str = Field(min_length=1)
    description: str
    is_builtin: bool


class VoiceListResponse(BaseModel):
    default_voice_id: str = Field(min_length=1)
    voices: list[VoiceView]


@router.get("", response_model=VoiceListResponse)
async def list_voices(request: Request) -> VoiceListResponse:
    registry = _registry(request)
    return VoiceListResponse(
        default_voice_id=registry.default_voice_id,
        voices=[_view(profile) for profile in registry.list()],
    )


@router.post("", response_model=VoiceView, status_code=201)
async def create_voice(
    request: Request,
    name: Annotated[str, Form()],
    audio: Annotated[UploadFile, File()],
    language: Annotated[str, Form()] = "ZH",
) -> VoiceView:
    display_name = name.strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="音色名称不能为空")

    normalized_language = language.strip().upper()
    if normalized_language not in VALID_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的语种：{language}（可选 {'/'.join(VALID_LANGUAGES)}）",
        )

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="参考音频为空")

    registry = _registry(request)
    voice_id = registry.allocate_id(display_name)
    destination = registry.reference_path(voice_id)
    try:
        duration = normalize_reference_audio(data, destination)
    except InvalidReferenceAudio as exc:
        _cleanup(destination)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        profile = registry.register(
            display_name=display_name,
            reference_audio=destination,
            language=normalized_language,
            voice_id=voice_id,
            description=f"用户克隆音色（参考音频 {duration:.2f} 秒）",
        )
    except ValueError as exc:
        _cleanup(destination)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _view(profile)


@router.get("/{voice_id}/sample")
async def voice_sample(voice_id: str, request: Request) -> FileResponse:
    """试听参考音频；只返回注册表里已知档案的文件。"""

    registry = _registry(request)
    try:
        profile = registry.get(voice_id)
    except VoiceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = profile.reference_audio_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="参考音频不存在")
    return FileResponse(path, media_type="audio/wav")


@router.delete("/{voice_id}", status_code=204)
async def delete_voice(voice_id: str, request: Request) -> Response:
    registry = _registry(request)
    try:
        registry.delete(voice_id)
    except BuiltinVoiceProtected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except VoiceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


def _registry(request: Request) -> VoiceRegistry:
    return request.app.state.voices


def _view(profile: VoiceProfile) -> VoiceView:
    return VoiceView.model_validate(profile.to_public_dict())


def _cleanup(destination: Path) -> None:
    """删除失败克隆留下的目录（只针对 runtime/voices/<id>）。"""

    shutil.rmtree(destination.parent, ignore_errors=True)


__all__ = ["VoiceListResponse", "VoiceView", "create_voice", "delete_voice", "router"]
