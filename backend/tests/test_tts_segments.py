"""TTS 文本切分：按句末标点、过长硬切、空文本兜底。"""

from app.runtime.pipeline import split_tts_segments


def test_splits_at_sentence_ends() -> None:
    assert split_tts_segments("第一句。第二句！第三句？") == [
        "第一句。",
        "第二句！",
        "第三句？",
    ]


def test_long_sentence_is_hard_cut() -> None:
    segments = split_tts_segments("啊" * 200, max_chars=80)

    assert len(segments) == 3
    assert [len(segment) for segment in segments] == [80, 80, 40]


def test_empty_text_has_fallback() -> None:
    assert split_tts_segments("   ") == ["……"]


def test_trailing_text_is_kept() -> None:
    assert split_tts_segments("第一句。没标点的尾巴") == ["第一句。", "没标点的尾巴"]
