"""SessionStore：持久化、重放、投影、裁剪与容错。"""

from __future__ import annotations

import json

import pytest

from app.session.models import (
    DEFAULT_VOICE_ID,
    EventType,
    InvalidSessionId,
    SessionNotFound,
    validate_session_id,
)
from app.session.store import SessionStore


def _new_store(tmp_path, **kwargs) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path, **kwargs)
    return store, store.create_session().session_id


def test_append_events_returns_monotonic_seq_and_replays(tmp_path) -> None:
    store, session_id = _new_store(tmp_path)

    first = store.append_event(
        session_id,
        EventType.TURN_STARTED,
        {"turn_id": "t1", "reply_to": "m1"},
        reply_to="m1",
    )
    second = store.append_event(
        session_id,
        EventType.TURN_COMPLETED,
        {"turn_id": "t1", "reply_to": "m1"},
        reply_to="m1",
    )

    assert (first.seq, second.seq) == (1, 2)
    assert store.cursor(session_id) == 2
    assert [event.seq for event in store.replay(session_id, after=0)] == [1, 2]
    assert [event.seq for event in store.replay(session_id, after=1)] == [2]
    assert store.replay(session_id, after=2) == []
    assert first.reply_to == "m1"
    assert first.payload["turn_id"] == "t1"


@pytest.mark.parametrize(
    "bad_id",
    ["../escape", "a/b", "", "a" * 65, "会话", "a.b", "..", "a b", "a\\b"],
)
def test_session_ids_are_path_safe(tmp_path, bad_id) -> None:
    store = SessionStore(tmp_path)

    with pytest.raises(InvalidSessionId):
        store.create_session(bad_id)
    with pytest.raises(InvalidSessionId):
        store.get_session(bad_id)
    with pytest.raises(InvalidSessionId):
        store.append_event(bad_id, EventType.TURN_STARTED, {})


def test_unknown_session_raises(tmp_path) -> None:
    store = SessionStore(tmp_path)

    with pytest.raises(SessionNotFound):
        store.require_session("missing")
    with pytest.raises(SessionNotFound):
        store.append_message("missing", role="user", text="hi")


def test_explicit_session_id_is_restorable(tmp_path) -> None:
    store = SessionStore(tmp_path)
    meta = store.create_session("keep-me")

    restored = SessionStore(tmp_path).get_session("keep-me")

    assert restored is not None
    assert restored.session_id == "keep-me"
    assert restored.voice_id == DEFAULT_VOICE_ID
    assert meta.created_at > 0


def test_voice_id_update_persists(tmp_path) -> None:
    store = SessionStore(tmp_path)
    store.create_session("voice-session")

    store.set_voice_id("voice-session", "another")

    assert store.get_session("voice-session").voice_id == "another"


def test_message_revision_keeps_order_and_latest_audio_url(tmp_path) -> None:
    store, session_id = _new_store(tmp_path)

    store.append_message(session_id, role="user", text="你好", message_id="m1")
    store.append_message(
        session_id,
        role="assistant",
        text="我が輩 在此。",
        message_id="a1",
        turn_id="t1",
        reply_to="m1",
    )
    revised = store.append_message(
        session_id,
        role="assistant",
        text="我が輩 在此。",
        message_id="a1",
        turn_id="t1",
        reply_to="m1",
        audio_url="/tts/abc",
    )

    messages = store.messages(session_id)

    assert revised.seq == 3
    assert [message.id for message in messages] == ["m1", "a1"]
    assert messages[1].audio_url == "/tts/abc"
    assert store.history(session_id, limit=10, max_chars=1000) == messages


def test_history_honours_count_and_character_budget(tmp_path) -> None:
    store, session_id = _new_store(tmp_path)
    for index in range(5):
        store.append_message(
            session_id,
            role="user",
            text=f"消息-{index}-abcdefghij",
            message_id=f"m{index}",
        )

    by_count = store.history(session_id, limit=3, max_chars=1000)
    by_budget = store.history(session_id, limit=10, max_chars=20)

    assert [message.id for message in by_count] == ["m2", "m3", "m4"]
    assert [message.id for message in by_budget] == ["m4"]


def test_event_limit_trims_oldest_events(tmp_path) -> None:
    store, session_id = _new_store(tmp_path, event_limit=5)

    for index in range(8):
        store.append_event(session_id, EventType.TURN_STARTED, {"index": index})

    events = store.events(session_id)
    lines = (tmp_path / session_id / "events.jsonl").read_text(encoding="utf-8").splitlines()

    assert [event.seq for event in events] == [4, 5, 6, 7, 8]
    assert store.cursor(session_id) == 8
    assert [event.seq for event in store.replay(session_id, after=6)] == [7, 8]
    assert len(lines) == 5
    assert json.loads(lines[0])["seq"] == 4


def test_truncated_last_jsonl_line_is_dropped_and_logged(tmp_path, caplog) -> None:
    store, session_id = _new_store(tmp_path)
    store.append_event(session_id, EventType.TURN_STARTED, {"turn_id": "t1"})
    store.append_event(session_id, EventType.TURN_COMPLETED, {"turn_id": "t1"})

    path = tmp_path / session_id / "events.jsonl"
    path.write_bytes(path.read_bytes() + b'{"seq": 99, "id": "half')

    with caplog.at_level("WARNING"):
        events = store.events(session_id)

    assert [event.seq for event in events] == [1, 2]
    assert path.read_bytes().endswith(b"\n")
    assert "末尾不完整" in caplog.text

    # 截断后继续追加，seq 从最后一个有效事件继续。
    third = store.append_event(session_id, EventType.TURN_ERROR, {"turn_id": "t1"})
    assert third.seq == 3


def test_invalid_middle_jsonl_line_is_skipped(tmp_path, caplog) -> None:
    store, session_id = _new_store(tmp_path)
    store.append_event(session_id, EventType.TURN_STARTED, {"turn_id": "t1"})
    path = tmp_path / session_id / "events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{不是 JSON}\n")
    store.append_event(session_id, EventType.TURN_COMPLETED, {"turn_id": "t1"})

    with caplog.at_level("WARNING"):
        events = store.events(session_id)

    assert [event.seq for event in events] == [1, 2]
    assert "非法 JSONL 行" in caplog.text


def test_hydrate_derives_turns_and_character(tmp_path) -> None:
    store, session_id = _new_store(tmp_path)
    store.append_message(session_id, role="user", text="你好", message_id="m1")
    store.append_event(
        session_id,
        EventType.TURN_STARTED,
        {"turn_id": "t1", "reply_to": "m1"},
        reply_to="m1",
    )
    store.append_event(
        session_id,
        EventType.AGENT_TEXT,
        {"text": "我が輩 在此。", "reply_to": "m1", "message_id": "a1"},
        reply_to="m1",
    )
    store.append_event(
        session_id,
        EventType.TTS_STARTED,
        {"tts_id": "tts1", "reply_to": "m1", "voice_id": "murasame"},
        reply_to="m1",
    )
    store.append_event(
        session_id,
        EventType.TTS_READY,
        {"tts_id": "tts1", "reply_to": "m1", "voice_id": "murasame", "audio_url": "/tts/a"},
        reply_to="m1",
    )
    store.append_event(
        session_id,
        EventType.CHARACTER_STATE,
        {"phase": "speaking", "tts_id": "tts1", "audio_url": "/tts/a"},
        reply_to="m1",
    )
    store.append_event(
        session_id,
        EventType.TURN_COMPLETED,
        {"turn_id": "t1", "reply_to": "m1"},
        reply_to="m1",
    )

    snapshot = store.hydrate(session_id)

    assert snapshot["cursor"] == 6
    assert snapshot["voice"] == {"voice_id": DEFAULT_VOICE_ID, "display_name": None}
    assert snapshot["messages"][0]["id"] == "m1"
    assert snapshot["turns"] == [
        {
            "turn_id": "t1",
            "reply_to": "m1",
            "status": "completed",
            "started_seq": 1,
            "ended_seq": 6,
            "tts_id": "tts1",
            "audio_url": "/tts/a",
        }
    ]
    assert snapshot["character"] == {
        "phase": "speaking",
        "emotion": None,
        "tts_id": "tts1",
        "audio_url": "/tts/a",
    }
    assert snapshot["active_turn_id"] is None


def test_validate_session_id_accepts_safe_values() -> None:
    assert validate_session_id("abc_DEF-123") == "abc_DEF-123"
    assert validate_session_id("a" * 64) == "a" * 64
