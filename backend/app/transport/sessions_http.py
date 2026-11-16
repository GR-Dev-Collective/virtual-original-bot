"""``/sessions``：已持久化会话列表。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionSummary(BaseModel):
    session_id: str = Field(min_length=1)
    title: str
    created_at: int = Field(ge=0)
    updated_at: int = Field(ge=0)
    message_count: int = Field(ge=0)
    voice_id: str = Field(min_length=1)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(request: Request) -> list[SessionSummary]:
    store = request.app.state.runtime.store
    return [SessionSummary(**item) for item in store.list_sessions()]


__all__ = ["SessionSummary", "list_sessions", "router"]
