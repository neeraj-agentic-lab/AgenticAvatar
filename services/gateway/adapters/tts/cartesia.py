import time
from typing import AsyncGenerator

import httpx

from .base import TTSAdapter, TTSOptions, AudioChunk

CARTESIA_STREAM_URL = "https://api.cartesia.ai/tts/bytes"


class CartesiaTTSAdapter(TTSAdapter):
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=30)

    async def synthesize(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        headers = {
            "X-API-Key": self._api_key,
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }
        payload = {
            "model_id": options.model_id or "sonic-english",
            "transcript": text,
            "voice": {"mode": "id", "id": options.voice_id},
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": options.sample_rate,
            },
            "language": options.language,
        }

        start_ms = int(time.time() * 1000)
        byte_offset = 0

        async with self._client.stream("POST", CARTESIA_STREAM_URL, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if not chunk:
                    continue
                # Derive a rough presentation timestamp from byte position
                bytes_per_sample = 2  # s16le
                samples = byte_offset // bytes_per_sample
                ts_ms = start_ms + int(samples * 1000 / options.sample_rate)
                byte_offset += len(chunk)
                yield AudioChunk(pcm=chunk, timestamp_ms=ts_ms)

        yield AudioChunk(pcm=b"", timestamp_ms=int(time.time() * 1000), is_final=True)

    async def close(self) -> None:
        await self._client.aclose()
