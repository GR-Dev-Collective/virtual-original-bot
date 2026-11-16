"""``/memory``：长期记忆与关系状态。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryNoteView(BaseModel):
    id: str
    text: str
    kind: str
    created_at: int


class RelationshipView(BaseModel):
    affinity: int
    stage: str
    interactions: int
    updated_at: int


class MemoryView(BaseModel):
    user_name: str | None
    notes: list[MemoryNoteView]
    relationship: RelationshipView


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="note", max_length=16)


class UserNamePatch(BaseModel):
    name: str = Field(max_length=32)


@router.get("", response_model=MemoryView)
async def get_memory(request: Request) -> MemoryView:
    return MemoryView.model_validate(request.app.state.memory.snapshot())


@router.post("/notes", response_model=MemoryNoteView, status_code=201)
async def add_note(payload: NoteCreate, request: Request) -> MemoryNoteView:
    try:
        note = request.app.state.memory.add_note(payload.text, kind=payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MemoryNoteView.model_validate(note.to_json())


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: str, request: Request) -> Response:
    if not request.app.state.memory.delete_note(note_id):
        raise HTTPException(status_code=404, detail="备注不存在")
    return Response(status_code=204)


@router.patch("/user", response_model=MemoryView)
async def update_user_name(payload: UserNamePatch, request: Request) -> MemoryView:
    store = request.app.state.memory
    store.set_user_name(payload.name)
    return MemoryView.model_validate(store.snapshot())


__all__ = [
    "MemoryNoteView",
    "MemoryView",
    "NoteCreate",
    "RelationshipView",
    "UserNamePatch",
    "router",
]
