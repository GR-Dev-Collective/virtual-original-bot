"""长期记忆与关系状态的本地 JSON 实现（MVP）。

不引入向量库：只保存用户称呼、备注/偏好、互动次数与关系阶段，并把整理后的
文本注入 system prompt。显式指令（“记住…”“叫我…”“我喜欢…”）会被识别成备注；
其余对话只累计关系值，不自动抽取自由文本，避免误记。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

MEMORY_FILENAME = "memory.json"
MAX_NOTES = 50
MAX_NOTE_CHARS = 200
MAX_NAME_CHARS = 32
AFFINITY_MAX = 100
STAGES = ((80, "信赖"), (50, "亲近"), (20, "熟悉"), (0, "初识"))

_NOTE_ID_PATTERN = re.compile(r"\A[a-f0-9]{8,32}\Z")
_REMEMBER = re.compile(r"^\s*(?:请)?记住[：:，,\s]+(.+?)\s*$")
_CALL_ME = re.compile(r"^\s*(?:以后)?(?:叫我|我叫)[：:，,\s]*(.+?)[。！!？?]*\s*$")
_PREFERENCE = re.compile(r"^\s*我(喜欢|讨厌|不喜欢)(.+?)\s*$")
_BIRTHDAY = re.compile(r"^\s*我的生日是[：:，,\s]*(.+?)[。！!？?]*\s*$")
_LIVE_IN = re.compile(r"^\s*我(?:住在|来自)[：:，,\s]*(.+?)[。！!？?]*\s*$")
_WORK_AT = re.compile(r"^\s*我在(.+?)(?:工作|上班)[。！!？?]*\s*$")

_STAGE_TONE = {
    "初识": "保持礼貌，留一点距离，不要过度亲昵。",
    "熟悉": "语气放松一些，可以偶尔主动关心。",
    "亲近": "可以自然地关心用户，使用更亲近的称呼。",
    "信赖": "像长期伙伴一样直接、放松，可以适度开玩笑。",
}


@dataclass(frozen=True, slots=True)
class MemoryNote:
    id: str
    text: str
    kind: str
    created_at: int

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> MemoryNote:
        return cls(
            id=str(data["id"]),
            text=str(data["text"]),
            kind=str(data.get("kind") or "note"),
            created_at=int(data.get("created_at", 0)),
        )


def _stage_for(affinity: int) -> str:
    for threshold, name in STAGES:
        if affinity >= threshold:
            return name
    return "初识"


def _now_ms() -> int:
    return int(time.time() * 1000)


class MemoryStore:
    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._path = self._directory / MEMORY_FILENAME
        self._lock = threading.RLock()
        self._state: dict[str, Any] | None = None

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------ 读写

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._ensure_loaded()
            affinity = int(state["relationship"]["affinity"])
            return {
                "user_name": state["user_name"],
                "notes": [note.to_json() for note in self._notes(state)],
                "relationship": {
                    "affinity": affinity,
                    "stage": _stage_for(affinity),
                    "interactions": int(state["relationship"]["interactions"]),
                    "updated_at": int(state["relationship"]["updated_at"]),
                },
            }

    def context_text(self) -> str:
        """生成注入 system prompt 的长期记忆段落；没有内容时返回空字符串。"""

        data = self.snapshot()
        lines: list[str] = []
        if data["user_name"]:
            lines.append(f"- 用户希望你称呼他/她：{data['user_name']}")
        relationship = data["relationship"]
        lines.append(
            f"- 关系：{relationship['stage']}（好感度 {relationship['affinity']}/{AFFINITY_MAX}，"
            f"共同对话 {relationship['interactions']} 次）"
        )
        tone = _STAGE_TONE.get(relationship["stage"])
        if tone:
            lines.append(f"- 当前相处方式：{tone}")
        notes = data["notes"]
        if notes:
            lines.append("- 你记得的事情：")
            for note in notes[-20:]:
                lines.append(f"  - {note['text']}")
        return "长期记忆（可能过时，以当前对话为准）：\n" + "\n".join(lines)

    # ------------------------------------------------------------------ 变更

    def add_note(self, text: str, *, kind: str = "note") -> MemoryNote:
        normalized = " ".join(text.split())
        if not normalized:
            raise ValueError("备注内容不能为空")
        if len(normalized) > MAX_NOTE_CHARS:
            normalized = normalized[:MAX_NOTE_CHARS]

        note = MemoryNote(
            id=uuid4().hex[:16],
            text=normalized,
            kind=kind,
            created_at=_now_ms(),
        )
        with self._lock:
            state = self._ensure_loaded()
            notes = self._notes(state)
            notes.append(note)
            if len(notes) > MAX_NOTES:
                del notes[: len(notes) - MAX_NOTES]
            state["notes"] = [item.to_json() for item in notes]
            self._save(state)
        return note

    def delete_note(self, note_id: str) -> bool:
        if not _NOTE_ID_PATTERN.fullmatch(note_id):
            return False
        with self._lock:
            state = self._ensure_loaded()
            notes = self._notes(state)
            kept = [note for note in notes if note.id != note_id]
            if len(kept) == len(notes):
                return False
            state["notes"] = [note.to_json() for note in kept]
            self._save(state)
            return True

    def set_user_name(self, name: str) -> str | None:
        normalized = " ".join(name.split())[:MAX_NAME_CHARS].strip()
        with self._lock:
            state = self._ensure_loaded()
            state["user_name"] = normalized or None
            self._save(state)
            return state["user_name"]

    def observe_user_text(self, text: str) -> None:
        """从显式指令里更新记忆；普通对话不自动抽取。"""

        remember = _REMEMBER.match(text)
        if remember:
            self.add_note(remember.group(1), kind="note")
            return

        call_me = _CALL_ME.match(text)
        if call_me:
            self.set_user_name(call_me.group(1))
            return

        preference = _PREFERENCE.match(text)
        if preference:
            self.add_note(f"{preference.group(1)}：{preference.group(2)}", kind="preference")
            return

        birthday = _BIRTHDAY.match(text)
        if birthday:
            self.add_note(f"生日：{birthday.group(1).strip()}", kind="profile")
            return

        live_in = _LIVE_IN.match(text)
        if live_in:
            self.add_note(f"居住/来自：{live_in.group(1).strip()}", kind="profile")
            return

        work_at = _WORK_AT.match(text)
        if work_at:
            self.add_note(f"工作：{work_at.group(1).strip()}", kind="profile")

    def record_turn(self) -> None:
        with self._lock:
            state = self._ensure_loaded()
            relationship = state["relationship"]
            relationship["affinity"] = min(AFFINITY_MAX, int(relationship["affinity"]) + 1)
            relationship["interactions"] = int(relationship["interactions"]) + 1
            relationship["updated_at"] = _now_ms()
            self._save(state)

    # ------------------------------------------------------------------ 内部

    def _ensure_loaded(self) -> dict[str, Any]:
        if self._state is None:
            self._state = self._read()
        return self._state

    def _read(self) -> dict[str, Any]:
        default = {
            "user_name": None,
            "notes": [],
            "relationship": {
                "affinity": 0,
                "interactions": 0,
                "updated_at": _now_ms(),
            },
        }
        if not self._path.is_file():
            return default
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("长期记忆读取失败，使用空记忆：%s", exc)
            return default
        if not isinstance(data, dict):
            return default
        return {
            "user_name": data.get("user_name") if isinstance(data.get("user_name"), str) else None,
            "notes": [item for item in data.get("notes", []) if isinstance(item, dict)],
            "relationship": {
                "affinity": min(AFFINITY_MAX, int(data.get("relationship", {}).get("affinity", 0))),
                "interactions": int(data.get("relationship", {}).get("interactions", 0)),
                "updated_at": int(data.get("relationship", {}).get("updated_at", _now_ms())),
            },
        }

    @staticmethod
    def _notes(state: dict[str, Any]) -> list[MemoryNote]:
        try:
            return [MemoryNote.from_json(item) for item in state["notes"]]
        except (KeyError, TypeError, ValueError):
            logger.warning("长期记忆里有无效备注，已忽略")
            state["notes"] = []
            return []

    def _save(self, state: dict[str, Any]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)


__all__ = ["AFFINITY_MAX", "MEMORY_FILENAME", "MemoryNote", "MemoryStore", "_stage_for"]
