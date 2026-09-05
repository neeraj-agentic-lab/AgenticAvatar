from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator


@dataclass
class TranscriptEvent:
    text: str
    is_final: bool
    confidence: float = 0.0
    duration_ms: int = 0


class STTAdapter(ABC):
    """Stream PCM audio in, get transcript events out."""

    @abstractmethod
    async def stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> AsyncGenerator[TranscriptEvent, None]:
        """Yield TranscriptEvent for each partial and final transcript."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any open connections or resources."""
        ...
