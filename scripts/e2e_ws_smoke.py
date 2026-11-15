"""End-to-end smoke test for the vob/1 control channel.

Prerequisites:
  * backend running (default http://127.0.0.1:8090)
  * IndexTTS sidecar reachable (real or `scripts/start_indextts.ps1 -Mock`)
  * Ollama running with the configured model

Usage:
  backend\\.venv\\Scripts\\python.exe scripts\\e2e_ws_smoke.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
import websockets


def _message(type_: str, payload: dict, message_id: str | None = None) -> str:
    return json.dumps(
        {
            "protocol": "vob/1",
            "id": message_id or uuid4().hex,
            "ts": int(time.time() * 1000),
            "type": type_,
            "payload": payload,
        },
        ensure_ascii=False,
    )


async def _receive_until(ws, wanted: str, timeout: float) -> tuple[dict, list[dict]]:
    collected: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=max(deadline - time.monotonic(), 0.1))
        item = json.loads(raw)
        collected.append(item)
        if item["type"] == wanted:
            return item, collected
    raise TimeoutError(f"did not receive {wanted} within {timeout}s")


async def _run(args: argparse.Namespace) -> int:
    ws_url = args.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/control"
    timeout = args.timeout

    async with websockets.connect(ws_url, max_size=2**23) as ws:
        ready = json.loads(await ws.recv())
        opened = json.loads(await ws.recv())
        assert ready["type"] == "server.ready", ready
        assert opened["type"] == "session.opened", opened
        session_id = opened["payload"]["session_id"]
        print(f"opened session={session_id} cursor={opened['payload']['cursor']}")

        await ws.send(_message("user.text", {"text": args.text}))
        completed, events = await _receive_until(ws, "turn.completed", timeout)
        types = [event["type"] for event in events]
        print("events:", ", ".join(types))
        tts_ready = next((event for event in events if event["type"] == "tts.ready"), None)
        if tts_ready is None:
            failed = next((event for event in events if event["type"] == "tts.failed"), None)
            raise AssertionError(f"TTS did not become ready: {failed}")
        assert tts_ready["payload"]["voice_id"] == args.voice, tts_ready
        print(f"tts_id={tts_ready['payload']['tts_id']} audio_url={tts_ready['payload']['audio_url']}")

        audio_url = args.base_url.rstrip("/") + tts_ready["payload"]["audio_url"]
        with httpx.Client(trust_env=False, timeout=60) as client:
            audio = client.get(audio_url)
        assert audio.status_code == 200 and len(audio.content) > 1024, (
            audio.status_code,
            len(audio.content),
        )
        print(f"audio bytes={len(audio.content)}")

        await ws.send(_message("tts.finished", {"tts_id": tts_ready["payload"]["tts_id"]}))
        await _receive_until(ws, "character.state", timeout)

        await ws.send(_message("session.hydrate", {}))
        state, _ = await _receive_until(ws, "session.state", timeout)
        payload = state["payload"]
        assert payload["messages"], "hydrate returned no messages"
        assert payload["turns"], "hydrate returned no turns"
        print(f"hydrate messages={len(payload['messages'])} turns={len(payload['turns'])}")
        cursor = payload["cursor"]

    async with websockets.connect(
        f"{ws_url}?session_id={session_id}&after=0", max_size=2**23
    ) as ws:
        await ws.recv()  # server.ready
        opened, replay = await _receive_until(ws, "session.opened", timeout)
        replayed = replay[:-1]
        assert opened["payload"]["session_id"] == session_id, opened
        assert opened["payload"]["cursor"] == cursor, opened
        assert len(replayed) == cursor, (len(replayed), cursor)
        assert replayed[0]["type"] == "turn.started", replayed[0]
        print(f"replay events={len(replayed)} cursor={cursor}")

        await ws.send(_message("voice.select", {"voice_id": args.voice}))
        selected, _ = await _receive_until(ws, "voice.selected", timeout)
        print(f"voice.selected={selected['payload']['voice_id']}")

    print("E2E smoke OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--text", default="主人，今天也辛苦了。")
    parser.add_argument("--voice", default="murasame")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
