"""控制通道端到端：握手、回复、失败路径与连接存活。"""

from __future__ import annotations

from app.config import REPO_ROOT
from tests.helpers import (
    FAKE_AUDIO,
    FakeChat,
    FakeTts,
    connect,
    expect_next,
    handshake,
    send,
    send_user_text,
)


def test_health(harness) -> None:
    response = harness.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_session_is_opened_on_connect(harness) -> None:
    with connect(harness.client) as ws:
        ready, opened = handshake(ws)

    assert ready["type"] == "server.ready"
    assert opened["payload"]["session_id"]
    assert opened["payload"]["voice_id"] == "murasame"


def test_user_text_is_answered_and_audio_can_be_fetched(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)
        send_user_text(ws)
        turn_started = expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        agent_text = expect_next(ws, "agent.text")
        tts_started = expect_next(ws, "tts.started")
        tts_ready = expect_next(ws, "tts.ready")

    assert turn_started["payload"]["reply_to"] == "m1"
    assert agent_text["payload"]["reply_to"] == "m1"
    assert agent_text["payload"]["text"] == "我が輩 已收到。"
    assert tts_started["payload"]["voice_id"] == "murasame"
    assert tts_ready["payload"]["audio_url"].startswith("/tts/")

    audio_response = harness.client.get(tts_ready["payload"]["audio_url"])
    assert audio_response.status_code == 200
    assert audio_response.content == FAKE_AUDIO
    assert harness.chat.calls[0]["system"] is not None


def test_llm_failure_becomes_turn_error_and_connection_survives(harness_factory) -> None:
    chat = FakeChat(failure="连接被拒绝")
    harness = harness_factory(chat=chat)

    with connect(harness.client) as ws:
        handshake(ws)

        send_user_text(ws)
        expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        error_state = expect_next(ws, "character.state")
        turn_error = expect_next(ws, "turn.error")

        assert error_state["payload"]["phase"] == "error"
        assert turn_error["payload"]["code"] == "llm_unavailable"
        assert turn_error["payload"]["reply_to"] == "m1"

        # 报错后连接仍可继续使用
        send_user_text(ws, "再来一次", message_id="m2")
        expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "character.state")
        assert expect_next(ws, "turn.error")["payload"]["reply_to"] == "m2"


def test_tts_failure_becomes_tts_failed(harness_factory) -> None:
    tts = FakeTts(failure="TTS 服务不可用")
    harness = harness_factory(tts=tts)

    with connect(harness.client) as ws:
        handshake(ws)
        send_user_text(ws)
        expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "agent.text")
        expect_next(ws, "tts.started")
        failed = expect_next(ws, "tts.failed")
        error_state = expect_next(ws, "character.state")
        completed = expect_next(ws, "turn.completed")

    assert failed["payload"]["code"] == "tts_unavailable"
    assert failed["payload"]["voice_id"] == "murasame"
    assert error_state["payload"]["phase"] == "error"
    assert completed["payload"]["reply_to"] == "m1"


def test_channel_survives_malformed_message(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)

        ws.send_text("这不是 JSON")
        assert expect_next(ws, "error")["payload"]["code"] == "invalid_message"

        send_user_text(ws, "仍然可用", message_id="m3")
        assert expect_next(ws, "turn.started")["payload"]["reply_to"] == "m3"


def test_tts_request_uses_default_voice_profile(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)
        send_user_text(ws)
        expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "agent.text")
        expect_next(ws, "tts.started")
        expect_next(ws, "tts.ready")

    request = harness.tts.requests[0]
    assert request.reference_audio == str(
        REPO_ROOT / "assets" / "voices" / "murasame" / "murasame_ref.wav"
    )
    assert request.language == "ZH"
    assert request.duration_factor == 1.0
    assert request.provider_options == {
        "refer_wav_path": "/workspace/data/references/murasame_ref.ogg",
        "prompt_text": "はっはっはっは",
        "prompt_language": "ja",
    }


def test_voice_select_broadcasts_and_tts_uses_selected_voice(harness, tmp_path) -> None:
    reference = tmp_path / "clone.wav"
    reference.write_bytes(b"RIFF")
    profile = harness.voices.register(
        display_name="测试音色",
        reference_audio=reference,
        language="JA",
    )

    with connect(harness.client) as ws:
        _, opened = handshake(ws)
        session_id = opened["payload"]["session_id"]

        send(ws, "voice.select", {"voice_id": profile.id}, message_id="vs-1")
        selected = expect_next(ws, "voice.selected")
        assert selected["payload"] == {
            "voice_id": profile.id,
            "display_name": "测试音色",
        }

        send_user_text(ws)
        expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "agent.text")
        tts_started = expect_next(ws, "tts.started")
        tts_ready = expect_next(ws, "tts.ready")

    assert tts_started["payload"]["voice_id"] == profile.id
    assert tts_ready["payload"]["voice_id"] == profile.id
    request = harness.tts.requests[0]
    assert request.reference_audio == str(profile.reference_audio_path)
    assert request.language == "JA"

    # 会话音色持久化：重连后 session.opened 仍是选中的音色。
    with connect(harness.client, session_id=session_id) as ws:
        _, reopened = handshake(ws)
    assert reopened["payload"]["voice_id"] == profile.id


def test_voice_select_unknown_reports_voice_not_found(harness) -> None:
    with connect(harness.client) as ws:
        handshake(ws)

        send(ws, "voice.select", {"voice_id": "missing"}, message_id="vs-2")
        error = expect_next(ws, "error")
        assert error["payload"]["code"] == "voice_not_found"
        assert error["payload"]["reply_to"] == "vs-2"

        # 失败不影响后续回合：仍用默认音色合成。
        send_user_text(ws)
        expect_next(ws, "turn.started")
        expect_next(ws, "character.state")
        expect_next(ws, "agent.text")
        assert expect_next(ws, "tts.started")["payload"]["voice_id"] == "murasame"
