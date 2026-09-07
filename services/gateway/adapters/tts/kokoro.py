import asyncio
import queue
import threading
import time
from typing import AsyncGenerator

import numpy as np

from .base import TTSAdapter, TTSOptions, AudioChunk

_kokoro_instance = None
_kokoro_lock = threading.Lock()


def _get_kokoro(model_path: str, voices_path: str):
    global _kokoro_instance
    if _kokoro_instance is None:
        with _kokoro_lock:
            if _kokoro_instance is None:
                from kokoro_onnx import Kokoro
                _kokoro_instance = Kokoro(model_path, voices_path)
    return _kokoro_instance


def _float32_to_pcm_s16le(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    int_samples = (clipped * 32767).astype(np.int16)
    return int_samples.tobytes()


def _synthesize_sync(kokoro, text: str, voice: str, speed: float) -> list:
    """Run Kokoro synthesis synchronously, return list of (samples, sample_rate)."""
    import asyncio
    loop = asyncio.new_event_loop()
    chunks = []
    async def _collect():
        async for samples, sr in kokoro.create_stream(text=text, voice=voice, speed=speed, lang="en-us"):
            if samples is not None and len(samples) > 0:
                chunks.append((samples, sr))
    loop.run_until_complete(_collect())
    loop.close()
    return chunks


class KokoroTTSAdapter(TTSAdapter):
    """
    Local TTS using Kokoro ONNX. Runs synthesis in a thread pool to avoid
    blocking the asyncio event loop (first call takes ~5s to load ONNX model).
    """

    def __init__(self, model_path: str, voices_path: str, voice: str = "af_heart"):
        self._model_path = model_path
        self._voices_path = voices_path
        self._voice = voice
        # Pre-warm Kokoro model in background thread
        threading.Thread(target=_get_kokoro, args=(model_path, voices_path), daemon=True).start()

    async def synthesize(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        kokoro = _get_kokoro(self._model_path, self._voices_path)
        voice = options.voice_id or self._voice
        start_ms = int(time.time() * 1000)
        offset_ms = 0

        # Run synthesis in executor so it doesn't block the event loop
        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(
            None,
            _synthesize_sync,
            kokoro, text, voice, options.speed,
        )

        for samples, sample_rate in chunks:
            pcm = _float32_to_pcm_s16le(samples)
            duration_ms = int(len(samples) * 1000 / sample_rate)
            yield AudioChunk(
                pcm=pcm,
                timestamp_ms=start_ms + offset_ms,
            )
            offset_ms += duration_ms

        yield AudioChunk(pcm=b"", timestamp_ms=start_ms + offset_ms, is_final=True)

    async def close(self) -> None:
        pass
