"""参考音频规范化：PyAV 解码 → 16-bit 单声道 WAV。

规则（ARCHITECTURE_V2 §8）：

- WAV 源保留源采样率；非 WAV 统一 44.1kHz。
- 时长必须在 1–60 秒之间，否则拒绝（HTTP 400）。
- 先解码到内存并校验，再原子落盘，失败不会留下半个文件。
"""

from __future__ import annotations

import io
import os
import wave
from pathlib import Path

import av
from av.audio.resampler import AudioResampler

MIN_DURATION_SECONDS = 1.0
MAX_DURATION_SECONDS = 60.0
DEFAULT_SAMPLE_RATE = 44_100


class InvalidReferenceAudio(ValueError):
    """上传的参考音频无法解码 / 时长越界。"""


def normalize_reference_audio(data: bytes, destination: Path) -> float:
    """把任意容器音频规范化为 16-bit mono WAV，返回时长（秒）。"""

    if not data:
        raise InvalidReferenceAudio("参考音频为空")

    frames, sample_rate = _decode_mono_s16(data)
    duration = len(frames) / 2 / sample_rate
    if duration < MIN_DURATION_SECONDS or duration > MAX_DURATION_SECONDS:
        raise InvalidReferenceAudio(
            f"参考音频时长必须在 {MIN_DURATION_SECONDS:g}–{MAX_DURATION_SECONDS:g} 秒之间，"
            f"当前为 {duration:.2f} 秒"
        )

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with wave.open(str(temporary), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(frames)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return duration


def _decode_mono_s16(data: bytes) -> tuple[bytes, int]:
    try:
        container = av.open(io.BytesIO(data))
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise InvalidReferenceAudio(f"无法解码参考音频：{exc}") from exc

    with container:
        if not container.streams.audio:
            raise InvalidReferenceAudio("上传文件不包含音频轨道")
        stream = container.streams.audio[0]
        sample_rate = stream.rate or DEFAULT_SAMPLE_RATE
        # 只有 WAV 源保留采样率，其余统一 44.1kHz。
        target_rate = sample_rate if container.format.name == "wav" else DEFAULT_SAMPLE_RATE
        resampler = AudioResampler(format="s16", layout="mono", rate=target_rate)

        chunks: list[bytes] = []
        total_samples = 0
        try:
            for frame in container.decode(stream):
                for converted in resampler.resample(frame):
                    payload = _frame_bytes(converted)
                    chunks.append(payload)
                    total_samples += converted.samples
                    # 提前拦截明显超长的文件，避免全部解码进内存。
                    if total_samples / target_rate > MAX_DURATION_SECONDS + 1.0:
                        raise InvalidReferenceAudio(
                            f"参考音频超过 {MAX_DURATION_SECONDS:g} 秒上限"
                        )
            for converted in resampler.resample(None):
                chunks.append(_frame_bytes(converted))
                total_samples += converted.samples
        except InvalidReferenceAudio:
            raise
        except (av.error.FFmpegError, OSError, ValueError) as exc:
            raise InvalidReferenceAudio(f"无法解码参考音频：{exc}") from exc

    if total_samples <= 0:
        raise InvalidReferenceAudio("参考音频没有可用的音频采样")
    return b"".join(chunks), target_rate


def _frame_bytes(frame: av.AudioFrame) -> bytes:
    if frame.format.name != "s16" or not frame.format.is_packed:
        raise InvalidReferenceAudio(f"不支持的内部音频格式：{frame.format.name}")
    # 只取有效采样，忽略 FFmpeg 缓冲区尾部对齐字节。
    return bytes(frame.planes[0])[: frame.samples * 2]


__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "InvalidReferenceAudio",
    "MAX_DURATION_SECONDS",
    "MIN_DURATION_SECONDS",
    "normalize_reference_audio",
]
