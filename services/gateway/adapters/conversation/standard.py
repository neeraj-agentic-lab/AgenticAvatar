from typing import AsyncGenerator

from adapters.agentforce.client import AgentforceClient
from adapters.stt.base import STTAdapter
from .base import ConversationAdapter, ConversationEvent, ConversationEventType


class StandardConversationAdapter(ConversationAdapter):
    """
    Mode: STT_PROVIDER + Agentforce Agent API.
    STT streams partial/final transcripts; final transcript is sent to Agentforce.
    """

    def __init__(self, stt: STTAdapter, agentforce: AgentforceClient):
        self._stt = stt
        self._af = agentforce

    async def start_session(self, session_id: str) -> None:
        await self._af.start_session(session_id)

    async def stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: str,
        turn_id: str,
        generation: int,
    ) -> AsyncGenerator[ConversationEvent, None]:
        final_text = ""

        async for transcript in self._stt.stream(audio_chunks):
            event_type = (
                ConversationEventType.TRANSCRIPT_FINAL
                if transcript.is_final
                else ConversationEventType.TRANSCRIPT_PARTIAL
            )
            yield ConversationEvent(
                type=event_type,
                text=transcript.text,
                is_final=transcript.is_final,
                turn_id=turn_id,
            )
            if transcript.is_final:
                final_text = transcript.text

        if final_text:
            async for event in self.send_text(final_text, session_id, turn_id):
                yield event

    async def send_text(
        self,
        text: str,
        session_id: str,
        turn_id: str,
    ) -> AsyncGenerator[ConversationEvent, None]:
        yield ConversationEvent(
            type=ConversationEventType.AGENT_THINKING,
            turn_id=turn_id,
        )

        async for agent_event in self._af.send_message(session_id, text):
            yield ConversationEvent(
                type=ConversationEventType.AGENT_TEXT_DELTA,
                text=agent_event.text,
                is_final=agent_event.is_final,
                turn_id=turn_id,
            )

        yield ConversationEvent(
            type=ConversationEventType.AGENT_TURN_COMPLETE,
            turn_id=turn_id,
        )

    async def cancel(self, session_id: str, generation: int) -> None:
        # Cancellation is enforced by the caller dropping stale generations.
        # STT and Agentforce connections are closed via end_session or reconnect.
        pass

    async def end_session(self, session_id: str) -> None:
        await self._af.end_session(session_id)
        await self._stt.close()
