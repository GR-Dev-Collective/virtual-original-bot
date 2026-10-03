import wave

import numpy as np
from faster_whisper.audio import decode_audio


def test_faster_whisper_decodes_audio_with_pyav_metadata_option(tmp_path) -> None:
    audio_path = tmp_path / "silence.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(np.zeros(16_000, dtype="<i2").tobytes())

    decoded = decode_audio(str(audio_path))

    assert decoded.shape == (16_000,)
