"""长期记忆：显式指令识别、关系累计、持久化与删除。"""

from app.memory.store import MemoryStore


def test_observes_name_notes_and_preferences(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory")

    store.observe_user_text("叫我 主人")
    store.observe_user_text("记住 我喜欢红茶")
    store.observe_user_text("我讨厌吵闹")

    snapshot = store.snapshot()
    assert snapshot["user_name"] == "主人"
    assert [note["text"] for note in snapshot["notes"]] == [
        "我喜欢红茶",
        "讨厌：吵闹",
    ]
    assert [note["kind"] for note in snapshot["notes"]] == ["note", "preference"]
    context = store.context_text()
    assert "主人" in context
    assert "我喜欢红茶" in context
    assert "初识" in context


def test_relationship_accumulates_and_persists(tmp_path) -> None:
    directory = tmp_path / "memory"
    store = MemoryStore(directory)
    for _ in range(25):
        store.record_turn()

    snapshot = store.snapshot()
    assert snapshot["relationship"]["affinity"] == 25
    assert snapshot["relationship"]["interactions"] == 25
    assert snapshot["relationship"]["stage"] == "熟悉"

    reloaded = MemoryStore(directory)
    assert reloaded.snapshot()["relationship"]["affinity"] == 25


def test_notes_can_be_deleted(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory")
    note = store.add_note("测试备注")

    assert store.delete_note(note.id) is True
    assert store.delete_note(note.id) is False
    assert store.snapshot()["notes"] == []


def test_empty_note_is_rejected(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory")

    try:
        store.add_note("   ")
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:  # pragma: no cover - 断言失败路径
        raise AssertionError("应当拒绝空备注")
