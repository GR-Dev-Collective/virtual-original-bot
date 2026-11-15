"""vob/1 控制协议：握手、能力协商、会话恢复、turn 生命周期与错误码。"""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.helpers import (
    FAKE_AUDIO,
    FakeTts,
    build_runtime,
    connect,
    expect_next,
    handshake,
    receive,
    receive_until,
    send,
    send_user_text,
)

ASSISTANT_TEXT = "我が輩 已收到。"


def complete_turn(ws, text: str = "你好", message_id: str = "m1") -> dict:
    """跑完一个 turn 并让播放结束，返回关键通知。"""

    send_user_text(ws, text, message_id=message_id)
    started = expect_next(ws, "turn.started")
    thinking = expect_next(ws, "character.state")
    agent_text = expect_next(ws, "agent.text")
    tts_started = expect_next(ws, "tts.started")
    tts_ready = expect_next(ws, "tts.ready")
    speaking = expect_next(ws, "character.state")
    completed = expect_next(ws, "turn.completed")

    send(ws, "tts.finished", {"tts_id": tts_ready["payload"]["tts_id"]}, message_id="finish-1")
    finished = expect_next(ws, "tts.finished")
    idle = expect_next(ws, "character.state")

    return {
        "started": started,
        "thinking": thinking,
        "agent_text": agent_text,
        "tts_started": tts_started,
        "tts_ready": tts_ready,
        "speaking": speaking,
        "completed": completed,
        "finished": finished,
        "idle": idle,
    }


def test_handshake_announces_protocol_and_capabilities(harness) -> None:
    with connect(harness.client) as ws:
        ready, opened = handshake(ws)

    assert ready["protocol"] == "vob/1"
    assert ready["payload"]["protocol_version"] == "vob/1"
    capabilities = ready["payload"]["capabilities"]
    assert set(capabilities["methods"]) >= {
        "session.open",
        "session.hydrate",
        "user.text",
        "tts.cancel",
        "tts.finished",
    }
    assert {"server.ready", "session.opened", "agent.text", "turn.completed"} <= set(
        capabilities["notifications"]
    )
    assert "replay" in capabilities["features"]
    assert "seq" not in ready or ready["seq"] is None

    payload = opened["payload"]
    assert payload["session_id"]
    assert payload["cursor"] == 0
    assert payload["replayed"] == 0
    assert payload["voice_id"] == "murasame"


def test_turn_lifecycle_and_audio_url(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)
        events = complete_turn(ws)

    started = events["started"]["payload"]
    assert started["reply_to"] == "m1"
    assert events["thinking"]["payload"]["phase"] == "thinking"
    assert events["agent_text"]["payload"]["text"] == ASSISTANT_TEXT
    assert events["agent_text"]["payload"]["reply_to"] == "m1"
    assert events["agent_text"]["payload"]["message_id"]
    assert events["tts_started"]["payload"]["voice_id"] == "murasame"

    audio_url = events["tts_ready"]["payload"]["audio_url"]
    assert audio_url == f"/tts/{audio_url.rsplit('/', 1)[-1]}"
    assert events["speaking"]["payload"] == {
        "phase": "speaking",
        "emotion": None,
        "tts_id": events["tts_ready"]["payload"]["tts_id"],
        "audio_url": audio_url,
    }
    assert events["completed"]["payload"]["turn_id"] == started["turn_id"]
    assert events["finished"]["payload"]["tts_id"] == events["tts_ready"]["payload"]["tts_id"]
    assert events["idle"]["payload"]["phase"] == "idle"

    seqs = [
        events[name]["seq"]
        for name in (
            "started",
            "thinking",
            "agent_text",
            "tts_started",
            "tts_ready",
            "speaking",
            "completed",
            "finished",
            "idle",
        )
    ]
    assert seqs == list(range(1, 10))

    audio = harness.client.get(audio_url)
    assert audio.status_code == 200
    assert audio.content == FAKE_AUDIO


def test_hydrate_returns_authoritative_snapshot(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)
        events = complete_turn(ws)
        send(ws, "session.hydrate", {}, message_id="hydrate-1")
        state = expect_next(ws, "session.state")

    payload = state["payload"]
    assert state.get("seq") is None
    assert payload["cursor"] == events["idle"]["seq"]
    assert payload["active_turn_id"] is None
    assert payload["voice"] == {"voice_id": "murasame", "display_name": None}
    assert payload["character"] == {
        "phase": "idle",
        "emotion": None,
        "tts_id": None,
        "audio_url": None,
    }

    assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
    user_message, assistant_message = payload["messages"]
    assert user_message["id"] == "m1"
    assert user_message["text"] == "你好"
    assert assistant_message["text"] == ASSISTANT_TEXT
    assert assistant_message["audio_url"] == events["tts_ready"]["payload"]["audio_url"]

    assert payload["turns"] == [
        {
            "turn_id": events["started"]["payload"]["turn_id"],
            "reply_to": "m1",
            "status": "completed",
            "started_seq": events["started"]["seq"],
            "ended_seq": events["completed"]["seq"],
            "tts_id": events["tts_ready"]["payload"]["tts_id"],
            "audio_url": events["tts_ready"]["payload"]["audio_url"],
        }
    ]


def test_replay_after_cursor(harness) -> None:
    with connect(harness.client) as ws:
        _, opened = handshake(ws)
        session_id = opened["payload"]["session_id"]
        events = complete_turn(ws)
        cursor = events["idle"]["seq"]

    with connect(harness.client, session_id=session_id, after="0") as ws:
        expect_next(ws, "server.ready")
        replayed_messages = receive_until(ws, "session.opened")
        replayed, opened_again = replayed_messages[:-1], replayed_messages[-1]

    assert opened_again["payload"]["session_id"] == session_id
    assert opened_again["payload"]["cursor"] == cursor
    assert opened_again["payload"]["replayed"] == cursor
    assert [message["seq"] for message in replayed] == list(range(1, cursor + 1))
    assert replayed[0]["type"] == "turn.started"
    assert replayed[-1]["type"] == "character.state"
    assert all(message["protocol"] == "vob/1" for message in replayed)

    with connect(harness.client, session_id=session_id, after=str(cursor)) as ws:
        expect_next(ws, "server.ready")
        opened_at_cursor = expect_next(ws, "session.opened")

    assert opened_at_cursor["payload"]["replayed"] == 0
    assert opened_at_cursor["payload"]["cursor"] == cursor


def test_session_open_switches_and_reports_unknown(harness) -> None:
    with connect(harness.client) as ws:
        _, opened = handshake(ws)
        first_session = opened["payload"]["session_id"]
        complete_turn(ws)

    with connect(harness.client) as ws:
        _, second_opened = handshake(ws)
        assert second_opened["payload"]["session_id"] != first_session

        send(
            ws,
            "session.open",
            {"session_id": first_session, "after": 0},
            message_id="open-1",
        )
        messages = receive_until(ws, "session.opened")
        replayed, opened_again = messages[:-1], messages[-1]
        assert opened_again["payload"]["session_id"] == first_session
        assert opened_again["payload"]["replayed"] == len(replayed)
        assert len(replayed) > 0

        send(ws, "session.hydrate", {}, message_id="hydrate-2")
        state = expect_next(ws, "session.state")
        assert state["payload"]["session_id"] == first_session
        assert len(state["payload"]["messages"]) == 2

        send(ws, "session.open", {"session_id": "does-not-exist"}, message_id="open-2")
        error = expect_next(ws, "error")
        assert error["payload"]["code"] == "session_not_found"
        assert error["payload"]["reply_to"] == "open-2"


def test_tts_cancel_during_synthesis_keeps_turn(harness_factory) -> None:
    tts = FakeTts(block_first=True)
    harness = harness_factory(tts=tts)

    with connect(harness.client) as ws:
        handshake(ws)
        send_user_text(ws)
        started = expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "agent.text")
        tts_started = expect_next(ws, "tts.started")

        send(
            ws,
            "tts.cancel",
            {"tts_id": tts_started["payload"]["tts_id"]},
            message_id="cancel-1",
        )
        cancelled = expect_next(ws, "tts.cancelled")
        idle = expect_next(ws, "character.state")
        completed = expect_next(ws, "turn.completed")

    assert cancelled["payload"]["reason"] == "cancelled"
    assert cancelled["payload"]["tts_id"] == tts_started["payload"]["tts_id"]
    assert idle["payload"]["phase"] == "idle"
    assert completed["payload"]["turn_id"] == started["payload"]["turn_id"]
    assert tts.cancelled_count == 1


def test_tts_cancel_after_ready_returns_to_idle(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)
        send_user_text(ws)
        expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "agent.text")
        expect_next(ws, "tts.started")
        ready = expect_next(ws, "tts.ready")
        expect_next(ws, "character.state")
        expect_next(ws, "turn.completed")

        send(
            ws,
            "tts.cancel",
            {"tts_id": ready["payload"]["tts_id"]},
            message_id="cancel-2",
        )
        cancelled = expect_next(ws, "tts.cancelled")
        idle = expect_next(ws, "character.state")

    assert cancelled["payload"]["reason"] == "cancelled"
    assert idle["payload"]["phase"] == "idle"


def test_new_user_text_cancels_active_turn(harness_factory) -> None:
    tts = FakeTts(block_first=True)
    harness = harness_factory(tts=tts)

    with connect(harness.client) as ws:
        handshake(ws)
        send_user_text(ws, "第一句", message_id="m1")
        first_started = expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "agent.text")
        expect_next(ws, "tts.started")

        send_user_text(ws, "第二句", message_id="m2")

        cancelled = expect_next(ws, "tts.cancelled")
        turn_cancelled = expect_next(ws, "turn.cancelled")
        expect_next(ws, "character.state")
        second_started = expect_next(ws, "turn.started")

        expect_next(ws, "character.state")
        second_agent_text = expect_next(ws, "agent.text")
        expect_next(ws, "tts.started")
        expect_next(ws, "tts.ready")
        expect_next(ws, "character.state")
        second_completed = expect_next(ws, "turn.completed")

    assert cancelled["payload"]["reason"] == "interrupted"
    assert turn_cancelled["payload"]["reason"] == "interrupted"
    assert turn_cancelled["payload"]["turn_id"] == first_started["payload"]["turn_id"]
    assert second_started["payload"]["turn_id"] != first_started["payload"]["turn_id"]
    assert second_completed["payload"]["turn_id"] == second_started["payload"]["turn_id"]
    assert second_agent_text["payload"]["reply_to"] == "m2"
    assert tts.cancelled_count == 1

    assert harness.chat.calls[1]["text"] == "第二句"
    assert harness.chat.calls[1]["history"] == [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": ASSISTANT_TEXT},
    ]


def test_agent_receives_recent_history(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)
        complete_turn(ws, "第一句", "m1")
        complete_turn(ws, "第二句", "m2")

    assert harness.chat.calls[0]["history"] == []
    assert harness.chat.calls[1]["history"] == [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": ASSISTANT_TEXT},
    ]


def test_invalid_and_unsupported_messages_do_not_close_connection(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)

        ws.send_text("这不是 JSON")
        assert expect_next(ws, "error")["payload"]["code"] == "invalid_message"

        send(ws, "ping", {})
        assert expect_next(ws, "error")["payload"]["code"] == "invalid_message"

        send(ws, "server.ready", {"protocol_version": "vob/1"})
        assert expect_next(ws, "error")["payload"]["code"] == "unsupported_type"

        send(ws, "agent.text", {})
        assert expect_next(ws, "error")["payload"]["code"] == "unsupported_type"

        send(ws, "user.text", {"text": ""})
        assert expect_next(ws, "error")["payload"]["code"] == "invalid_message"

        send(ws, "user.text", {"text": "你好", "extra": 1})
        assert expect_next(ws, "error")["payload"]["code"] == "invalid_message"

        send_user_text(ws, "恢复连接", message_id="m3")
        started = expect_next(ws, "turn.started")
        assert started["payload"]["reply_to"] == "m3"


def test_query_protocol_mismatch_closes_connection(harness) -> None:
    with connect(harness.client, protocol="vob/0") as ws:
        error = receive(ws)
        assert error["type"] == "error"
        assert error["payload"]["code"] == "protocol_mismatch"
        with pytest.raises(WebSocketDisconnect):
            receive(ws)


def test_message_protocol_mismatch_closes_connection(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)
        ws.send_json(
            {
                "protocol": "vob/0",
                "type": "user.text",
                "id": "x1",
                "ts": 1,
                "payload": {"text": "hi"},
            }
        )
        error = expect_next(ws, "error")
        assert error["payload"]["code"] == "protocol_mismatch"
        with pytest.raises(WebSocketDisconnect):
            receive(ws)


def test_unknown_or_unsafe_session_on_connect(harness) -> None:
    with connect(harness.client, session_id="missing") as ws:
        assert expect_next(ws, "server.ready")["type"] == "server.ready"
        error = expect_next(ws, "error")
        assert error["payload"]["code"] == "session_not_found"
        with pytest.raises(WebSocketDisconnect):
            receive(ws)

    with connect(harness.client, session_id="bad.id") as ws:
        expect_next(ws, "server.ready")
        error = expect_next(ws, "error")
        assert error["payload"]["code"] == "invalid_message"
        with pytest.raises(WebSocketDisconnect):
            receive(ws)

    with connect(harness.client, after="abc") as ws:
        expect_next(ws, "server.ready")
        error = expect_next(ws, "error")
        assert error["payload"]["code"] == "invalid_message"
        with pytest.raises(WebSocketDisconnect):
            receive(ws)


def test_hydrate_survives_runtime_restart(harness) -> None:
    with connect(harness.client) as ws:
        _, opened = handshake(ws)
        session_id = opened["payload"]["session_id"]
        events = complete_turn(ws)
        cursor = events["idle"]["seq"]

    # 模拟进程重启：新的 SessionStore 从同一目录恢复会话。
    build_runtime(
        sessions_dir=harness.sessions_dir,
        audio_dir=harness.audio_dir,
        chat=harness.chat,
        tts=harness.tts,
    )

    with connect(harness.client, session_id=session_id) as ws:
        expect_next(ws, "server.ready")
        reopened = expect_next(ws, "session.opened")
        assert reopened["payload"]["session_id"] == session_id
        assert reopened["payload"]["cursor"] == cursor
        assert reopened["payload"]["replayed"] == 0

        send(ws, "session.hydrate", {}, message_id="hydrate-3")
        state = expect_next(ws, "session.state")

    assert state["payload"]["cursor"] == cursor
    assert [message["role"] for message in state["payload"]["messages"]] == ["user", "assistant"]
    assert state["payload"]["turns"][0]["status"] == "completed"
    assert state["payload"]["character"]["phase"] == "idle"
