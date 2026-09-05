from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator


class ConversationEventType(str, Enum):
    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"
    AGENT_THINKING = "agent.thinking"
    AGENT_TEXT_DELTA = "agent.text.delta"
    AGENT_TURN_COMPLETE = "agent.turn.complete"
    ERROR = "error"


@dataclass
class ConversationEvent:
    type: ConversationEventType
    text: str = ""
    is_final: bool = False
    turn_id: str = ""
    error: str = ""


class ConversationAdapter(ABC):
    """
    Single interface for the full audio-in → agent-text-out pipeline.

    Implementations:
      - StandardConversationAdapter  : STT adapter + Agentforce Agent API
      - AgentforceVoiceAdapter       : Agentforce Voice API (handles both)
    """

    @abstractmethod
    async def start_session(self, session_id: str) -> None:
        """Create the underlying agent/voice session."""
        ...

    @abstractmethod
    async def stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: str,
        turn_id: str,
        generation: int,
    ) -> AsyncGenerator[ConversationEvent, None]:
        """
        Feed PCM audio, yield ConversationEvents.
        Must stop yielding when generation is superseded.
        """
        ...

    @abstractmethod
    async def send_text(
        self,
        text: str,
        session_id: str,
        turn_id: str,
    ) -> AsyncGenerator[ConversationEvent, None]:
        """Send a text turn directly (text-input fallback)."""
        ...

    @abstractmethod
    async def cancel(self, session_id: str, generation: int) -> None:
        """Cancel the current in-flight turn."""
        ...

    @abstractmethod
    async def end_session(self, session_id: str) -> None:
        """Close the underlying agent/voice session."""
        ...
