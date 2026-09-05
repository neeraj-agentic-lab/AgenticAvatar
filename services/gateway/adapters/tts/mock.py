import asyncio
import math
import struct
import time
from typing import AsyncGenerator

from .base import TTSAdapter, TTSOptions, AudioChunk


def _sine_wave(frequency: float, duration_ms: int, sample_rate: int = 16000) -> bytes:
    """Generate a simple sine wave as PCM s16le — sounds like a tone, not speech."""
    num_samples = int(sample_rate * duration_ms / 1000)
    samples = []
    for i in range(num_samples):
        value = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(struct.pack("<h", value))
    return b"".join(samples)


class MockTTSAdapter(TTSAdapter):
    """
    Returns a short tone instead of real speech.
    Used for local testing without a TTS API key.
    """

    async def synthesize(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        # ~40ms per word at a rough speaking rate
        words = len(text.split())
        duration_ms = max(300, words * 40)

        chunk_ms = 80
        total_chunks = duration_ms // chunk_ms
        start_ms = int(time.time() * 1000)

        for i in range(total_chunks):
            pcm = _sine_wave(frequency=220.0, duration_ms=chunk_ms)
            await asyncio.sleep(chunk_ms / 1000)
            yield AudioChunk(
                pcm=pcm,
                timestamp_ms=start_ms + i * chunk_ms,
            )

        yield AudioChunk(pcm=b"", timestamp_ms=int(time.time() * 1000), is_final=True)

    async def close(self) -> None:
        pass
