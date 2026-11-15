"""ReplyPipeline：单会话的回合编排。

一次 ``user.text``：

    turn.started → character.state(thinking) → 取历史 → AgentCore →
    agent.text → tts.started → tts.ready/tts.failed →
    character.state(speaking/error) → turn.completed

同一时刻只允许一个 active turn；新的 user.text 先取消旧 turn（含正在合成的 TTS），
``tts.cancel`` 只取消 TTS，回合本身继续以 turn.completed 收尾。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from app.models.llm import LlmUnavailable
from app.models.tts.audio_store import AudioStore
from app.models.tts.base import TtsProvider, TtsUnavailable
from app.session.models import (
    EventRecord,
    EventType,
    MessageRecord,
    new_id,
)
from app.session.store import SessionStore
from app.transport.messages import (
    AgentTextPayload,
    CharacterStateView,
    TtsCancelledPayload,
    TtsFailedPayload,
    TtsFinishedPayload,
    TtsReadyPayload,
    TtsStartedPayload,
    TurnCancelledPayload,
    TurnCompletedPayload,
    TurnErrorPayload,
    TurnStartedPayload,
)
from app.voices.models import VoiceNotFound, VoiceProfile
from app.voices.registry import VoiceRegistry
from app.voices.synthesis import build_synthesis_request

logger = logging.getLogger(__name__)

PublishFn = Callable[[str, EventType, BaseModel, str | None], EventRecord]


class ReplyAgent(Protocol):
    async def handle_user_text(
        self,
        text: str,
        history: Sequence[Mapping[str, str]] | None = None,
    ) -> str: ...


@dataclass(slots=True)
class _ActiveTurn:
    turn_id: str
    reply_to: str
    task: asyncio.Task[None]


@dataclass(slots=True)
class _ActiveTts:
    tts_id: str
    reply_to: str
    voice_id: str
    task: asyncio.Task[bytes] | None
    status: str = "synthesizing"
    audio_url: str | None = None


class ReplyPipeline:
    def __init__(
        self,
        *,
        session_id: str,
        store: SessionStore,
        agent: ReplyAgent,
        tts: TtsProvider,
        audio_store: AudioStore,
        voices: VoiceRegistry,
        publish: PublishFn,
        history_max_messages: int = 12,
        history_max_chars: int = 4000,
    ) -> None:
        self._session_id = session_id
        self._store = store
        self._agent = agent
        self._tts = tts
        self._audio_store = audio_store
        self._voices = voices
        self._publish = publish
        self._history_max_messages = history_max_messages
        self._history_max_chars = history_max_chars

        self._active_turn: _ActiveTurn | None = None
        self._active_tts: _ActiveTts | None = None
        self._tts_cancel_reason: str | None = None

    @property
    def active_turn_id(self) -> str | None:
        return self._active_turn.turn_id if self._active_turn else None

    @property
    def session_id(self) -> str:
        return self._session_id

    # --------------------------------------------------------------- commands

    async def start_turn(self, text: str, reply_to: str) -> str:
        await self._cancel_turn("interrupted")

        turn_id = new_id()
        user_message = self._store.append_message(
            self._session_id,
            role="user",
            text=text,
            message_id=reply_to,
            turn_id=turn_id,
        )
        task = asyncio.create_task(
            self._run_turn(
                turn_id=turn_id,
                text=text,
                reply_to=reply_to,
                user_seq=user_message.seq,
            ),
            name=f"turn-{turn_id}",
        )
        self._active_turn = _ActiveTurn(turn_id=turn_id, reply_to=reply_to, task=task)
        return turn_id

    async def cancel_tts(self, tts_id: str, reason: str = "cancelled") -> bool:
        tts = self._active_tts
        if tts is None or tts.tts_id != tts_id:
            return False
        if tts.status == "synthesizing":
            if tts.task is None or tts.task.done():
                return False
            self._tts_cancel_reason = reason
            tts.task.cancel(reason)
            return True

        self._active_tts = None
        self._emit(
            EventType.TTS_CANCELLED,
            TtsCancelledPayload(tts_id=tts.tts_id, reply_to=tts.reply_to, reason=reason),
            reply_to=tts.reply_to,
        )
        self._emit(
            EventType.CHARACTER_STATE,
            CharacterStateView(phase="idle"),
            reply_to=tts.reply_to,
        )
        return True

    async def finish_tts(self, tts_id: str) -> bool:
        tts = self._active_tts
        if tts is None or tts.tts_id != tts_id or tts.status != "ready":
            return False

        self._active_tts = None
        self._emit(
            EventType.TTS_FINISHED,
            TtsFinishedPayload(tts_id=tts.tts_id, reply_to=tts.reply_to),
            reply_to=tts.reply_to,
        )
        self._emit(
            EventType.CHARACTER_STATE,
            CharacterStateView(phase="idle"),
            reply_to=tts.reply_to,
        )
        return True

    async def close(self, reason: str = "shutdown") -> None:
        await self._cancel_turn(reason)

    # ---------------------------------------------------------------- 回合执行

    async def _run_turn(
        self,
        *,
        turn_id: str,
        text: str,
        reply_to: str,
        user_seq: int,
    ) -> None:
        try:
            self._emit(
                EventType.TURN_STARTED,
                TurnStartedPayload(turn_id=turn_id, reply_to=reply_to),
                reply_to=reply_to,
            )
            self._emit(
                EventType.CHARACTER_STATE,
                CharacterStateView(phase="thinking"),
                reply_to=reply_to,
            )

            history = [
                {"role": message.role, "content": message.text}
                for message in self._history(upto_seq=user_seq)
            ]
            reply = await self._agent.handle_user_text(text, history=history)

            message_id = new_id()
            self._store.append_message(
                self._session_id,
                role="assistant",
                text=reply,
                message_id=message_id,
                turn_id=turn_id,
                reply_to=reply_to,
            )
            self._emit(
                EventType.AGENT_TEXT,
                AgentTextPayload(text=reply, reply_to=reply_to, message_id=message_id),
                reply_to=reply_to,
            )

            requested_voice_id = self._current_voice_id()
            tts_id = new_id()
            try:
                profile = self._resolve_voice_profile(requested_voice_id)
            except TtsUnavailable as exc:
                # 音色档案不可用：没有可合成的请求，直接以 tts.failed 收敛。
                self._emit(
                    EventType.TTS_FAILED,
                    TtsFailedPayload(
                        tts_id=tts_id,
                        reply_to=reply_to,
                        voice_id=requested_voice_id,
                        code="tts_unavailable",
                        message=str(exc),
                    ),
                    reply_to=reply_to,
                )
                self._emit(
                    EventType.CHARACTER_STATE,
                    CharacterStateView(phase="error", tts_id=tts_id),
                    reply_to=reply_to,
                )
                self._emit(
                    EventType.TURN_COMPLETED,
                    TurnCompletedPayload(turn_id=turn_id, reply_to=reply_to),
                    reply_to=reply_to,
                )
                return

            voice_id = profile.id
            tts_task = asyncio.create_task(
                self._tts.synthesize(build_synthesis_request(reply, profile)),
                name=f"tts-{tts_id}",
            )
            self._active_tts = _ActiveTts(
                tts_id=tts_id,
                reply_to=reply_to,
                voice_id=voice_id,
                task=tts_task,
            )
            self._emit(
                EventType.TTS_STARTED,
                TtsStartedPayload(tts_id=tts_id, reply_to=reply_to, voice_id=voice_id),
                reply_to=reply_to,
            )

            try:
                audio = await tts_task
            except asyncio.CancelledError:
                reason = self._tts_cancel_reason
                if reason is None:
                    raise
                # tts.cancel：只结束 TTS，回合正常收尾。
                self._tts_cancel_reason = None
                self._active_tts = None
                self._emit(
                    EventType.TTS_CANCELLED,
                    TtsCancelledPayload(tts_id=tts_id, reply_to=reply_to, reason=reason),
                    reply_to=reply_to,
                )
                self._emit(
                    EventType.CHARACTER_STATE,
                    CharacterStateView(phase="idle"),
                    reply_to=reply_to,
                )
                self._emit(
                    EventType.TURN_COMPLETED,
                    TurnCompletedPayload(turn_id=turn_id, reply_to=reply_to),
                    reply_to=reply_to,
                )
                return

            audio_url = f"/tts/{self._audio_store.save(audio)}"
            # 消息以追加修订的方式补上 audio_url，hydrate 取同一 message_id 的最新记录。
            self._store.append_message(
                self._session_id,
                role="assistant",
                text=reply,
                message_id=message_id,
                turn_id=turn_id,
                reply_to=reply_to,
                audio_url=audio_url,
            )
            if self._active_tts is not None and self._active_tts.tts_id == tts_id:
                self._active_tts.status = "ready"
                self._active_tts.audio_url = audio_url
                self._active_tts.task = None

            self._emit(
                EventType.TTS_READY,
                TtsReadyPayload(
                    tts_id=tts_id,
                    reply_to=reply_to,
                    voice_id=voice_id,
                    audio_url=audio_url,
                ),
                reply_to=reply_to,
            )
            self._emit(
                EventType.CHARACTER_STATE,
                CharacterStateView(phase="speaking", tts_id=tts_id, audio_url=audio_url),
                reply_to=reply_to,
            )
            self._emit(
                EventType.TURN_COMPLETED,
                TurnCompletedPayload(turn_id=turn_id, reply_to=reply_to),
                reply_to=reply_to,
            )
        except asyncio.CancelledError as exc:
            reason = _cancelled_reason(exc)
            await self._abort_tts(reason)
            self._emit(
                EventType.TURN_CANCELLED,
                TurnCancelledPayload(turn_id=turn_id, reply_to=reply_to, reason=reason),
                reply_to=reply_to,
            )
            self._emit(
                EventType.CHARACTER_STATE,
                CharacterStateView(phase="idle"),
                reply_to=reply_to,
            )
        except LlmUnavailable as exc:
            self._emit(
                EventType.CHARACTER_STATE,
                CharacterStateView(phase="error"),
                reply_to=reply_to,
            )
            self._emit(
                EventType.TURN_ERROR,
                TurnErrorPayload(
                    turn_id=turn_id,
                    reply_to=reply_to,
                    code="llm_unavailable",
                    message=str(exc),
                ),
                reply_to=reply_to,
            )
        except TtsUnavailable as exc:
            tts = self._active_tts
            self._active_tts = None
            if tts is not None:
                self._emit(
                    EventType.TTS_FAILED,
                    TtsFailedPayload(
                        tts_id=tts.tts_id,
                        reply_to=reply_to,
                        voice_id=tts.voice_id,
                        code="tts_unavailable",
                        message=str(exc),
                    ),
                    reply_to=reply_to,
                )
                self._emit(
                    EventType.CHARACTER_STATE,
                    CharacterStateView(phase="error", tts_id=tts.tts_id),
                    reply_to=reply_to,
                )
            self._emit(
                EventType.TURN_COMPLETED,
                TurnCompletedPayload(turn_id=turn_id, reply_to=reply_to),
                reply_to=reply_to,
            )
        except Exception as exc:  # noqa: BLE001 - 回合必须收敛为 turn.error
            logger.exception("回合 %s 失败", turn_id)
            self._emit(
                EventType.CHARACTER_STATE,
                CharacterStateView(phase="error"),
                reply_to=reply_to,
            )
            self._emit(
                EventType.TURN_ERROR,
                TurnErrorPayload(
                    turn_id=turn_id,
                    reply_to=reply_to,
                    code="internal_error",
                    message=str(exc),
                ),
                reply_to=reply_to,
            )
        finally:
            current = asyncio.current_task()
            if self._active_turn is not None and self._active_turn.task is current:
                self._active_turn = None

    # ------------------------------------------------------------------ 内部

    def _history(self, *, upto_seq: int) -> list[MessageRecord]:
        return self._store.history(
            self._session_id,
            limit=self._history_max_messages,
            max_chars=self._history_max_chars,
            upto_seq=upto_seq,
        )

    def _current_voice_id(self) -> str:
        meta = self._store.get_session(self._session_id)
        return meta.voice_id if meta is not None else self._voices.default_voice_id

    def _resolve_voice_profile(self, voice_id: str) -> VoiceProfile:
        """取会话当前音色；档案被删除时退回默认音色。

        两边都不可用说明注册表为空/损坏，按 TTS 不可用处理。
        """

        try:
            return self._voices.get(voice_id)
        except VoiceNotFound:
            fallback = self._voices.default_profile_or_none()
            if fallback is None:
                raise TtsUnavailable(f"音色档案不可用：{voice_id}") from None
            logger.warning("音色 %s 不存在，回退到默认音色 %s", voice_id, fallback.id)
            return fallback

    async def _cancel_turn(self, reason: str) -> None:
        turn = self._active_turn
        if turn is not None and not turn.task.done():
            turn.task.cancel(reason)
            with suppress(asyncio.CancelledError):
                await turn.task
        self._active_turn = None
        await self._cancel_orphan_tts(reason)

    async def _cancel_orphan_tts(self, reason: str) -> None:
        tts = self._active_tts
        if tts is None or tts.status != "ready":
            return
        self._active_tts = None
        self._emit(
            EventType.TTS_CANCELLED,
            TtsCancelledPayload(tts_id=tts.tts_id, reply_to=tts.reply_to, reason=reason),
            reply_to=tts.reply_to,
        )
        self._emit(
            EventType.CHARACTER_STATE,
            CharacterStateView(phase="idle"),
            reply_to=tts.reply_to,
        )

    async def _abort_tts(self, reason: str) -> None:
        tts = self._active_tts
        if tts is None or tts.status != "synthesizing":
            return
        self._active_tts = None
        task = tts.task
        if task is not None and not task.done():
            task.cancel(reason)
        if task is not None:
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._emit(
            EventType.TTS_CANCELLED,
            TtsCancelledPayload(tts_id=tts.tts_id, reply_to=tts.reply_to, reason=reason),
            reply_to=tts.reply_to,
        )

    def _emit(
        self,
        event_type: EventType,
        payload: BaseModel,
        *,
        reply_to: str | None = None,
    ) -> EventRecord:
        return self._publish(self._session_id, event_type, payload, reply_to)


def _cancelled_reason(exc: asyncio.CancelledError) -> str:
    if exc.args and isinstance(exc.args[0], str):
        return exc.args[0]
    return "interrupted"


__all__ = ["PublishFn", "ReplyAgent", "ReplyPipeline"]
