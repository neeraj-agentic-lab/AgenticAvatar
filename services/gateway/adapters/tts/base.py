from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator


@dataclass
class TTSOptions:
    voice_id: str
    model_id: str = ""
    sample_rate: int = 16000
    language: str = "en"
    speed: float = 1.0


@dataclass
class AudioChunk:
    pcm: bytes
    timestamp_ms: int
    is_final: bool = False


class TTSAdapter(ABC):
    """Send text in, get PCM audio chunks out."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        options: TTSOptions,
    ) -> AsyncGenerator[AudioChunk, None]:
        """Yield AudioChunk as PCM becomes available, without waiting for full synthesis."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any open connections or resources."""
        ...
