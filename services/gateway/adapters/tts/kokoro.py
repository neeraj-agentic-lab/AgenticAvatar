import struct
import time
from typing import AsyncGenerator

import numpy as np

from .base import TTSAdapter, TTSOptions, AudioChunk

_kokoro_instance = None


def _get_kokoro(model_path: str, voices_path: str):
    global _kokoro_instance
    if _kokoro_instance is None:
        from kokoro_onnx import Kokoro
        _kokoro_instance = Kokoro(model_path, voices_path)
    return _kokoro_instance


def _float32_to_pcm_s16le(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    int_samples = (clipped * 32767).astype(np.int16)
    return int_samples.tobytes()


class KokoroTTSAdapter(TTSAdapter):
    """
    Local TTS using Kokoro ONNX. Runs on CPU or Apple MPS.
    No API key needed. Apache 2.0 license.
    Model files downloaded separately — see scripts/download-kokoro.sh
    """

    def __init__(self, model_path: str, voices_path: str, voice: str = "af_heart"):
        self._model_path = model_path
        self._voices_path = voices_path
        self._voice = voice

    async def synthesize(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        kokoro = _get_kokoro(self._model_path, self._voices_path)
        voice = options.voice_id or self._voice
        start_ms = int(time.time() * 1000)
        offset_ms = 0

        async for samples, sample_rate in kokoro.create_stream(
            text=text,
            voice=voice,
            speed=options.speed,
            lang="en-us",
        ):
            if samples is None or len(samples) == 0:
                continue

            # Use Kokoro's native 24kHz — don't resample, tell caller the real rate
            actual_rate = sample_rate  # 24000

            pcm = _float32_to_pcm_s16le(samples)
            duration_ms = int(len(samples) * 1000 / actual_rate)

            yield AudioChunk(
                pcm=pcm,
                timestamp_ms=start_ms + offset_ms,
            )
            offset_ms += duration_ms

        yield AudioChunk(pcm=b"", timestamp_ms=start_ms + offset_ms, is_final=True)

    async def close(self) -> None:
        pass


def _resample(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate:
        return samples
    ratio = to_rate / from_rate
    new_length = int(len(samples) * ratio)
    indices = np.linspace(0, len(samples) - 1, new_length)
    return np.interp(indices, np.arange(len(samples)), samples).astype(np.float32)
