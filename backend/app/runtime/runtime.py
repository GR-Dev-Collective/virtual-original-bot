"""CharacterRuntime：进程级会话运行时。

- 管理 SessionStore、每个会话的 ReplyPipeline 与事件订阅者；
- ``publish`` 先写账本再扇出，保证重放与实时通知同形；
- ``hydrate`` 返回权威快照；
- ``select_voice`` 校验音色注册表后更新会话并广播 ``voice.selected``。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from pydantic import BaseModel

from app.models.tts.audio_store import AudioStore
from app.models.tts.base import TtsProvider
from app.runtime.pipeline import ReplyAgent, ReplyPipeline
from app.session.models import EventRecord, EventType, SessionMeta
from app.session.store import SessionStore
from app.transport.messages import SessionStatePayload, VoiceSelectedPayload
from app.voices.models import VoiceProfile
from app.voices.registry import VoiceRegistry


class CharacterRuntime:
    def __init__(
        self,
        *,
        store: SessionStore,
        agent: ReplyAgent,
        tts: TtsProvider,
        audio_store: AudioStore,
        voices: VoiceRegistry,
        history_max_messages: int = 12,
        history_max_chars: int = 4000,
    ) -> None:
        self._store = store
        self._agent = agent
        self._tts = tts
        self._audio_store = audio_store
        self._voices = voices
        self._history_max_messages = history_max_messages
        self._history_max_chars = history_max_chars

        self._pipelines: dict[str, ReplyPipeline] = {}
        self._subscribers: dict[str, set[asyncio.Queue[EventRecord]]] = {}

    @property
    def store(self) -> SessionStore:
        return self._store

    @property
    def voices(self) -> VoiceRegistry:
        return self._voices

    # ------------------------------------------------------------------ 会话

    def create_session(self) -> SessionMeta:
        return self._store.create_session(voice_id=self._voices.default_voice_id)

    def require_session(self, session_id: str) -> SessionMeta:
        return self._store.require_session(session_id)

    def cursor(self, session_id: str) -> int:
        return self._store.cursor(session_id)

    def replay(self, session_id: str, *, after: int = 0, limit: int = 10_000) -> list[EventRecord]:
        return self._store.replay(session_id, after=after, limit=limit)

    def hydrate(self, session_id: str) -> SessionStatePayload:
        return SessionStatePayload.model_validate(self._store.hydrate(session_id))

    # -------------------------------------------------------------- 订阅/扇出

    def subscribe(self, session_id: str) -> asyncio.Queue[EventRecord]:
        queue: asyncio.Queue[EventRecord] = asyncio.Queue()
        self._subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[EventRecord]) -> None:
        queues = self._subscribers.get(session_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._subscribers.pop(session_id, None)

    def publish(
        self,
        session_id: str,
        event_type: EventType,
        payload: BaseModel | Mapping[str, object],
        reply_to: str | None = None,
    ) -> EventRecord:
        event = self._store.append_event(
            session_id,
            event_type,
            payload,
            reply_to=reply_to,
        )
        for queue in tuple(self._subscribers.get(session_id, ())):
            queue.put_nowait(event)
        return event

    # ------------------------------------------------------------------ 音色

    def select_voice(self, session_id: str, voice_id: str) -> VoiceProfile:
        """校验并切换会话音色；未知音色抛 ``VoiceNotFound``。"""

        profile = self._voices.get(voice_id)
        self._store.set_voice_id(session_id, profile.id)
        self.publish(
            session_id,
            EventType.VOICE_SELECTED,
            VoiceSelectedPayload(voice_id=profile.id, display_name=profile.display_name),
        )
        return profile

    # ------------------------------------------------------------------ 回合

    def _pipeline(self, session_id: str) -> ReplyPipeline:
        pipeline = self._pipelines.get(session_id)
        if pipeline is None:
            pipeline = ReplyPipeline(
                session_id=session_id,
                store=self._store,
                agent=self._agent,
                tts=self._tts,
                audio_store=self._audio_store,
                voices=self._voices,
                publish=self.publish,
                history_max_messages=self._history_max_messages,
                history_max_chars=self._history_max_chars,
            )
            self._pipelines[session_id] = pipeline
        return pipeline

    async def start_turn(self, session_id: str, text: str, reply_to: str) -> str:
        return await self._pipeline(session_id).start_turn(text, reply_to)

    async def cancel_tts(self, session_id: str, tts_id: str, reason: str = "cancelled") -> bool:
        return await self._pipeline(session_id).cancel_tts(tts_id, reason=reason)

    async def finish_tts(self, session_id: str, tts_id: str) -> bool:
        return await self._pipeline(session_id).finish_tts(tts_id)

    async def shutdown(self) -> None:
        for pipeline in list(self._pipelines.values()):
            await pipeline.close("shutdown")
        self._pipelines.clear()
        self._subscribers.clear()


__all__ = ["CharacterRuntime"]
