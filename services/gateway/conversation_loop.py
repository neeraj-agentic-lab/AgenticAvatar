"""
Drives one active conversation turn end-to-end:

  ConversationAdapter → phrase_chunker → TTS adapter → WebSocket + avatar worker

Each turn is identified by (session_id, turn_id, generation).
Any component that receives a stale generation must discard its output.
"""

import asyncio
import logging

log = logging.getLogger(__name__)
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator

from adapters.conversation.base import ConversationAdapter, ConversationEventType
from adapters.tts.base import TTSAdapter, TTSOptions
from phrase_chunker import chunk_text


@dataclass
class TurnContext:
    session_id: str
    turn_id: str = field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:8]}")
    generation: int = 0


async def run_turn(
    ctx: TurnContext,
    audio_chunks: AsyncGenerator[bytes, None],
    conversation: ConversationAdapter,
    tts: TTSAdapter,
    tts_options: TTSOptions,
    send_event,           # async callable(dict) — sends JSON to the WebSocket client
    send_audio,           # async callable(bytes, int) — sends PCM to avatar worker
    current_generation,   # callable() -> int — returns latest generation atomically
    on_turn_complete=None, # optional async callable() — called when all audio is sent
) -> None:
    """
    Run one full user turn:
    1. Stream audio through ConversationAdapter → transcript + agent text events.
    2. Pipe agent text deltas through phrase_chunker.
    3. For each phrase, stream TTS PCM to both the WebSocket (for audio track) and
       the avatar worker (for lip sync).
    4. Drop everything the moment current_generation() > ctx.generation.
    """

    def is_stale() -> bool:
        return current_generation() > ctx.generation

    # ── Phase 1: speech → transcript → agent text deltas ──────────────────────

    agent_delta_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def collect_conversation_events():
        try:
            async for event in conversation.stream(
                audio_chunks,
                ctx.session_id,
                ctx.turn_id,
                ctx.generation,
            ):
                if is_stale():
                    break

                if event.type == ConversationEventType.TRANSCRIPT_PARTIAL:
                    await send_event({
                        "type": "transcript.partial",
                        "text": event.text,
                        "turn_id": ctx.turn_id,
                        "generation": ctx.generation,
                    })

                elif event.type == ConversationEventType.TRANSCRIPT_FINAL:
                    await send_event({
                        "type": "transcript.final",
                        "text": event.text,
                        "turn_id": ctx.turn_id,
                        "generation": ctx.generation,
                    })

                elif event.type == ConversationEventType.AGENT_THINKING:
                    await send_event({
                        "type": "agent.thinking",
                        "turn_id": ctx.turn_id,
                        "generation": ctx.generation,
                    })

                elif event.type == ConversationEventType.AGENT_TEXT_DELTA:
                    await agent_delta_queue.put(event.text)

                elif event.type == ConversationEventType.AGENT_TURN_COMPLETE:
                    pass

        finally:
            await agent_delta_queue.put(None)  # signal end of stream

    # ── Phase 2: agent deltas → phrase chunker ────────────────────────────────

    async def delta_generator() -> AsyncGenerator[str, None]:
        while True:
            delta = await agent_delta_queue.get()
            if delta is None:
                return
            yield delta

    # ── Phase 3: phrases → TTS → audio ───────────────────────────────────────

    async def synthesize_phrases():
        async for phrase in chunk_text(delta_generator()):
            if is_stale():
                break

            await send_event({
                "type": "avatar.speaking",
                "text": phrase,
                "turn_id": ctx.turn_id,
                "generation": ctx.generation,
            })

            async for audio_chunk in tts.synthesize(phrase, tts_options):
                if is_stale():
                    break
                if audio_chunk.is_final:
                    continue
                await send_audio(audio_chunk.pcm, audio_chunk.timestamp_ms)

        if not is_stale():
            await send_event({
                "type": "avatar.turn.complete",
                "turn_id": ctx.turn_id,
                "generation": ctx.generation,
            })
            if on_turn_complete:
                await on_turn_complete()

    async def _safe_collect():
        try:
            await collect_conversation_events()
        except Exception as e:
            log.exception("Error in conversation adapter: %s", e)
            await agent_delta_queue.put(None)
            await send_event({"type": "session.error", "message": str(e)})

    async def _safe_synthesize():
        try:
            await synthesize_phrases()
        except Exception as e:
            log.exception("Error in TTS/synthesis: %s", e)
            await send_event({"type": "session.error", "message": str(e)})

    # Run both concurrently — conversation feeds the queue; TTS drains it
    await asyncio.gather(
        _safe_collect(),
        _safe_synthesize(),
    )
