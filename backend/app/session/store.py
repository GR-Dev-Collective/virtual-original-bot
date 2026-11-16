"""持久会话存储。

布局（相对 ``session_directory``）::

    <session_id>/meta.json
    <session_id>/messages.jsonl
    <session_id>/events.jsonl

写入先落盘再返回记录，调用方负责随后广播；读取对末尾半行/非法行容错。
单会话事件数超过上限时从最旧裁剪（只影响 replay，hydrate 从 messages 重建）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.runtime.projection import derive_active_turn_id, derive_character, derive_turns
from app.session.models import (
    DEFAULT_VOICE_ID,
    EventRecord,
    EventType,
    InvalidSessionId,
    MessageRecord,
    SessionMeta,
    SessionNotFound,
    new_id,
    now_ms,
    validate_session_id,
)

logger = logging.getLogger(__name__)

DEFAULT_EVENT_LIMIT = 2000


class SessionStore:
    def __init__(self, root: str | Path, *, event_limit: int = DEFAULT_EVENT_LIMIT) -> None:
        if event_limit < 1:
            raise ValueError("event_limit 必须大于 0")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._event_limit = event_limit
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def event_limit(self) -> int:
        return self._event_limit

    # ------------------------------------------------------------------ meta

    def create_session(
        self,
        session_id: str | None = None,
        *,
        persona: str | None = None,
        voice_id: str = DEFAULT_VOICE_ID,
    ) -> SessionMeta:
        sid = validate_session_id(session_id) if session_id is not None else new_id()
        with self._lock:
            existing = self._read_meta(sid)
            if existing is not None:
                return existing
            directory = self._session_dir(sid)
            directory.mkdir(parents=True, exist_ok=True)
            meta = SessionMeta(
                session_id=sid,
                created_at=now_ms(),
                persona=persona,
                voice_id=voice_id,
            )
            _write_json_atomic(directory / "meta.json", meta.to_json())
            for name in ("messages.jsonl", "events.jsonl"):
                (directory / name).touch(exist_ok=True)
            return meta

    def get_session(self, session_id: str) -> SessionMeta | None:
        validate_session_id(session_id)
        with self._lock:
            return self._read_meta(session_id)

    def require_session(self, session_id: str) -> SessionMeta:
        meta = self.get_session(session_id)
        if meta is None:
            raise SessionNotFound(session_id)
        return meta

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出已持久化会话（按最近活动倒序），标题取首条用户消息。"""

        sessions: list[dict[str, Any]] = []
        with self._lock:
            for directory in self._root.iterdir():
                if not directory.is_dir():
                    continue
                session_id = directory.name
                try:
                    validate_session_id(session_id)
                except InvalidSessionId:
                    continue
                meta = self._read_meta(session_id)
                if meta is None:
                    continue
                messages = self._read_messages(directory)
                first_user = next(
                    (
                        message.text
                        for message in messages
                        if message.role == "user" and message.text.strip()
                    ),
                    "",
                )
                title = " ".join(first_user.split())[:24] or "新会话"
                updated_at = messages[-1].ts if messages else meta.created_at
                sessions.append(
                    {
                        "session_id": meta.session_id,
                        "title": title,
                        "created_at": meta.created_at,
                        "updated_at": updated_at,
                        "message_count": len(messages),
                        "voice_id": meta.voice_id,
                    }
                )
        sessions.sort(key=lambda item: item["updated_at"], reverse=True)
        return sessions

    def set_voice_id(self, session_id: str, voice_id: str) -> SessionMeta:
        """更新会话音色；t8 的音色选择会调用它。"""

        with self._lock:
            meta = self.require_session(session_id)
            updated = SessionMeta(
                session_id=meta.session_id,
                created_at=meta.created_at,
                persona=meta.persona,
                voice_id=voice_id,
            )
            _write_json_atomic(self._session_dir(session_id) / "meta.json", updated.to_json())
            return updated

    # -------------------------------------------------------------- messages

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        text: str,
        message_id: str | None = None,
        turn_id: str | None = None,
        reply_to: str | None = None,
        audio_url: str | None = None,
        ts: int | None = None,
    ) -> MessageRecord:
        directory = self._require_directory(session_id)
        with self._lock:
            messages = self._read_messages(directory)
            seq = max((message.seq for message in messages), default=0) + 1
            record = MessageRecord(
                seq=seq,
                id=message_id or new_id(),
                ts=ts if ts is not None else now_ms(),
                role=role,
                text=text,
                audio_url=audio_url,
                turn_id=turn_id,
                reply_to=reply_to,
            )
            _append_jsonl(directory / "messages.jsonl", record.to_json())
            return record

    def messages(self, session_id: str) -> list[MessageRecord]:
        """返回去重后的消息（同一 id 的修订记录取最新值）。"""

        directory = self._require_directory(session_id)
        with self._lock:
            return self._read_messages(directory)

    def history(
        self,
        session_id: str,
        *,
        limit: int,
        max_chars: int,
        upto_seq: int | None = None,
    ) -> list[MessageRecord]:
        """取最近历史（按时间正序返回）；条数与字符预算同时生效。"""

        if limit <= 0:
            return []
        candidates = self.messages(session_id)
        if upto_seq is not None:
            candidates = [message for message in candidates if message.seq < upto_seq]

        picked: list[MessageRecord] = []
        chars = 0
        for message in reversed(candidates):
            if len(picked) >= limit:
                break
            length = len(message.text)
            if picked and chars + length > max_chars:
                break
            picked.append(message)
            chars += length
        return list(reversed(picked))

    # ---------------------------------------------------------------- events

    def append_event(
        self,
        session_id: str,
        event_type: EventType | str,
        payload: BaseModel | Mapping[str, Any],
        *,
        message_id: str | None = None,
        reply_to: str | None = None,
        ts: int | None = None,
    ) -> EventRecord:
        directory = self._require_directory(session_id)
        type_value = event_type.value if isinstance(event_type, EventType) else str(event_type)
        if isinstance(payload, BaseModel):
            payload_data = payload.model_dump(mode="json")
        else:
            payload_data = dict(payload)

        with self._lock:
            events = self._read_events(directory)
            seq = (events[-1].seq if events else 0) + 1
            record = EventRecord(
                seq=seq,
                id=message_id or new_id(),
                ts=ts if ts is not None else now_ms(),
                type=type_value,
                payload=payload_data,
                reply_to=reply_to,
            )
            path = directory / "events.jsonl"
            keep_count = self._event_limit - 1
            if len(events) >= self._event_limit:
                kept = events[-keep_count:] if keep_count > 0 else []
                _rewrite_jsonl(path, [*kept, record])
            else:
                _append_jsonl(path, record.to_json())
            return record

    def events(self, session_id: str) -> list[EventRecord]:
        directory = self._require_directory(session_id)
        with self._lock:
            return self._read_events(directory)

    def replay(
        self,
        session_id: str,
        *,
        after: int = 0,
        limit: int = 200,
    ) -> list[EventRecord]:
        if limit <= 0:
            return []
        events = self.events(session_id)
        selected = [event for event in events if event.seq > after]
        return selected[:limit]

    def cursor(self, session_id: str) -> int:
        events = self.events(session_id)
        return events[-1].seq if events else 0

    # --------------------------------------------------------------- hydrate

    def hydrate(self, session_id: str) -> dict[str, Any]:
        meta = self.require_session(session_id)
        events = self.events(session_id)
        turns = derive_turns(events)
        messages = self.messages(session_id)
        return {
            "session_id": meta.session_id,
            "cursor": events[-1].seq if events else 0,
            "messages": [message.to_view() for message in messages],
            "turns": turns,
            "voice": {"voice_id": meta.voice_id, "display_name": None},
            "character": derive_character(events),
            "active_turn_id": derive_active_turn_id(turns),
        }

    # --------------------------------------------------------------- private

    def _session_dir(self, session_id: str) -> Path:
        return self._root / validate_session_id(session_id)

    def _require_directory(self, session_id: str) -> Path:
        directory = self._session_dir(session_id)
        if not (directory / "meta.json").is_file():
            raise SessionNotFound(session_id)
        return directory

    def _read_meta(self, session_id: str) -> SessionMeta | None:
        path = self._session_dir(session_id) / "meta.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SessionMeta.from_json(data)
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("忽略损坏的会话元数据：%s", path)
            return None

    def _read_messages(self, directory: Path) -> list[MessageRecord]:
        records: dict[str, MessageRecord] = {}
        for row in _read_jsonl(directory / "messages.jsonl"):
            try:
                record = MessageRecord.from_json(row)
            except (KeyError, TypeError, ValueError):
                logger.warning("忽略非法的消息记录：%s", row)
                continue
            # 同一 message_id 的修订记录覆盖旧值，但保留首次出现的位置。
            records[record.id] = record
        return list(records.values())

    def _read_events(self, directory: Path) -> list[EventRecord]:
        events: list[EventRecord] = []
        for row in _read_jsonl(directory / "events.jsonl"):
            try:
                events.append(EventRecord.from_json(row))
            except (KeyError, TypeError, ValueError):
                logger.warning("忽略非法的事件记录：%s", row)
        return events


# --------------------------------------------------------------------- JSONL


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL；末尾半行丢弃并截断，非法行记录日志后跳过。"""

    if not path.is_file():
        return []
    raw = path.read_bytes()
    if not raw:
        return []

    parts = raw.split(b"\n")
    non_empty = [index for index, part in enumerate(parts) if part.strip()]
    last_index = non_empty[-1] if non_empty else -1
    # 只有「没有换行收尾的最后一行」才视为进程崩溃留下的半行；带换行的
    # 非法行是完整写入的坏记录，跳过即可，不能把之后追加的数据一起截掉。
    ends_with_newline = raw.endswith(b"\n")

    rows: list[dict[str, Any]] = []
    offset = 0
    for index, part in enumerate(parts):
        start = offset
        offset += len(part) + 1
        if not part.strip():
            continue
        try:
            value = json.loads(part.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if index == last_index and not ends_with_newline:
                logger.warning("丢弃 %s 末尾不完整的 JSONL 行（offset=%s）", path, start)
                try:
                    path.write_bytes(raw[:start])
                except OSError:  # pragma: no cover - 磁盘异常时保持只读容错
                    logger.warning("截断损坏的 JSONL 失败：%s", path)
            else:
                logger.warning("跳过 %s 中的非法 JSONL 行（offset=%s）", path, start)
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            logger.warning("跳过 %s 中的非对象 JSONL 行（offset=%s）", path, start)
    return rows


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _rewrite_jsonl(path: Path, records: list[EventRecord]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_json(), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


__all__ = [
    "DEFAULT_EVENT_LIMIT",
    "EventRecord",
    "InvalidSessionId",
    "MessageRecord",
    "SessionMeta",
    "SessionNotFound",
    "SessionStore",
    "derive_active_turn_id",
    "derive_character",
    "derive_turns",
]
