"""状态投影：turn 与 character 状态完全由事件账本推导。

投影不持久化自己的状态，``hydrate`` 与实时广播都调用同一组函数，保证
「重放得到的 == 当时发出的」。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.session.models import EventRecord, EventType

TURN_TERMINAL_EVENTS = frozenset(
    {
        EventType.TURN_COMPLETED.value,
        EventType.TURN_CANCELLED.value,
        EventType.TURN_ERROR.value,
    }
)


def derive_turns(events: Sequence[EventRecord]) -> list[dict[str, Any]]:
    """按事件顺序推导回合列表；同一 turn_id 只保留一条最新状态。"""

    turns: dict[str, dict[str, Any]] = {}
    current_turn_id: str | None = None

    for event in events:
        payload = event.payload

        if event.type == EventType.TURN_STARTED:
            turn_id = str(payload.get("turn_id", ""))
            if not turn_id:
                continue
            turns[turn_id] = {
                "turn_id": turn_id,
                "reply_to": str(payload.get("reply_to", "")),
                "status": "active",
                "started_seq": event.seq,
                "ended_seq": None,
                "tts_id": None,
                "audio_url": None,
            }
            current_turn_id = turn_id
            continue

        if event.type in (EventType.TTS_STARTED, EventType.TTS_READY, EventType.TTS_FAILED):
            turn = turns.get(current_turn_id) if current_turn_id else None
            if turn is None:
                continue
            turn["tts_id"] = payload.get("tts_id", turn["tts_id"])
            if event.type == EventType.TTS_READY:
                turn["audio_url"] = payload.get("audio_url", turn["audio_url"])
            elif event.type == EventType.TTS_FAILED:
                turn["audio_url"] = None
            continue

        if event.type in TURN_TERMINAL_EVENTS:
            turn_id = str(payload.get("turn_id") or current_turn_id or "")
            turn = turns.get(turn_id)
            if turn is None:
                continue
            turn["status"] = {
                EventType.TURN_COMPLETED.value: "completed",
                EventType.TURN_CANCELLED.value: "cancelled",
                EventType.TURN_ERROR.value: "error",
            }[event.type]
            turn["ended_seq"] = event.seq
            if event.type == EventType.TURN_ERROR:
                turn["audio_url"] = None
            if current_turn_id == turn_id:
                current_turn_id = None

    return list(turns.values())


def derive_active_turn_id(turns: Sequence[dict[str, Any]]) -> str | None:
    for turn in reversed(turns):
        if turn.get("status") == "active":
            return str(turn["turn_id"])
    return None


def derive_character(events: Sequence[EventRecord]) -> dict[str, Any]:
    """推导角色状态。

    character.state 本身也会写进账本（便于重放时观察相位变化），但推导时忽略它，
    避免自引用。
    """

    state: dict[str, Any] = {
        "phase": "idle",
        "emotion": None,
        "tts_id": None,
        "audio_url": None,
    }

    for event in events:
        event_type = event.type
        payload = event.payload

        if event_type == EventType.TURN_STARTED:
            state["phase"] = "thinking"
            state["tts_id"] = None
            state["audio_url"] = None
        elif event_type == EventType.TTS_STARTED:
            state["phase"] = "thinking"
            state["tts_id"] = payload.get("tts_id")
            state["audio_url"] = None
        elif event_type == EventType.TTS_READY:
            state["phase"] = "speaking"
            state["tts_id"] = payload.get("tts_id")
            state["audio_url"] = payload.get("audio_url")
        elif event_type == EventType.TTS_FAILED:
            state["phase"] = "error"
            state["tts_id"] = payload.get("tts_id")
            state["audio_url"] = None
        elif event_type == EventType.TTS_CANCELLED:
            state["phase"] = "idle"
            state["tts_id"] = payload.get("tts_id")
            state["audio_url"] = None
        elif event_type == EventType.TTS_FINISHED:
            state["phase"] = "idle"
            state["tts_id"] = None
            state["audio_url"] = None
        elif event_type == EventType.TURN_COMPLETED:
            if state["phase"] == "thinking":
                state["phase"] = "idle"
        elif event_type == EventType.TURN_CANCELLED:
            state["phase"] = "idle"
            state["tts_id"] = None
            state["audio_url"] = None
        elif event_type == EventType.TURN_ERROR:
            state["phase"] = "error"
            state["tts_id"] = None
            state["audio_url"] = None

    return state
