"""pytest 全局准备。

本机 HTTPS_PROXY/NO_PROXY 中的 ``[::1]`` 会让 httpx 0.28 在构造 Client 时抛
InvalidURL；TestClient 会读取这些环境变量建立代理 mount，因此测试进程内先清掉。
应用内的 AsyncClient 一律 ``trust_env=False``。
"""

import os
from collections.abc import Iterator

import pytest

for _proxy_name in (
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
):
    os.environ.pop(_proxy_name, None)

from app.config import settings  # noqa: E402
from app.voices.registry import VoiceRegistry  # noqa: E402
from tests.helpers import (  # noqa: E402
    FakeChat,
    FakeTts,
    Harness,
    build_runtime,
    make_client,
)


@pytest.fixture
def harness_factory(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    audio_dir = tmp_path / "audio"
    monkeypatch.setattr(settings, "session_directory", str(sessions_dir))
    monkeypatch.setattr(settings, "audio_directory", str(audio_dir))

    clients = []

    def factory(*, chat: FakeChat | None = None, tts: FakeTts | None = None) -> Harness:
        chat = chat if chat is not None else FakeChat()
        tts = tts if tts is not None else FakeTts()
        client = make_client()
        client.__enter__()
        clients.append(client)
        voices = VoiceRegistry(
            "config/voices.json",
            tmp_path / "voices",
            default_voice_id=settings.default_voice_id,
        )
        runtime = build_runtime(
            sessions_dir=sessions_dir,
            audio_dir=audio_dir,
            chat=chat,
            tts=tts,
            voices=voices,
        )
        return Harness(
            client=client,
            chat=chat,
            tts=tts,
            runtime=runtime,
            voices=voices,
            sessions_dir=sessions_dir,
            audio_dir=audio_dir,
        )

    yield factory

    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def harness(harness_factory) -> Iterator[Harness]:
    harness = harness_factory()
    yield harness
