import asyncio
from typing import AsyncGenerator

from .base import ConversationAdapter, ConversationEvent, ConversationEventType

MOCK_RESPONSES = [
    "Hello! I'm your AI assistant. How can I help you today?",
    "That's a great question. Let me think about that for a moment.",
    "I understand what you're saying. Here's what I can tell you about that topic.",
    "Sure, I'd be happy to help you with that request.",
    "Thanks for sharing that. Is there anything else you'd like to know?",
]

_response_index = 0


class MockConversationAdapter(ConversationAdapter):
    """
    Returns canned responses without any external API calls.
    Used for local testing before Salesforce credentials are configured.
    """

    async def start_session(self, session_id: str) -> None:
        pass

    async def stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: str,
        turn_id: str,
        generation: int,
    ) -> AsyncGenerator[ConversationEvent, None]:
        # Don't drain audio — mock doesn't use STT.
        # Just simulate a brief thinking delay then respond.
        await asyncio.sleep(0.6)
        async for event in self._mock_response(turn_id):
            yield event

    async def send_text(
        self,
        text: str,
        session_id: str,
        turn_id: str,
    ) -> AsyncGenerator[ConversationEvent, None]:
        async for event in self._mock_response(turn_id):
            yield event

    async def cancel(self, session_id: str, generation: int) -> None:
        pass

    async def end_session(self, session_id: str) -> None:
        pass

    async def _mock_response(self, turn_id: str) -> AsyncGenerator[ConversationEvent, None]:
        global _response_index

        yield ConversationEvent(
            type=ConversationEventType.TRANSCRIPT_FINAL,
            text="(mock transcript)",
            is_final=True,
            turn_id=turn_id,
        )

        await asyncio.sleep(0.3)

        yield ConversationEvent(
            type=ConversationEventType.AGENT_THINKING,
            turn_id=turn_id,
        )

        await asyncio.sleep(0.3)

        # Stream response word by word to test phrase chunker
        response = MOCK_RESPONSES[_response_index % len(MOCK_RESPONSES)]
        _response_index += 1

        words = response.split()
        for i, word in enumerate(words):
            yield ConversationEvent(
                type=ConversationEventType.AGENT_TEXT_DELTA,
                text=word + (" " if i < len(words) - 1 else ""),
                is_final=(i == len(words) - 1),
                turn_id=turn_id,
            )
            await asyncio.sleep(0.05)

        yield ConversationEvent(
            type=ConversationEventType.AGENT_TURN_COMPLETE,
            turn_id=turn_id,
        )
