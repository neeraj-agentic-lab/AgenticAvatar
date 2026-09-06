import asyncio
import json
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from dependencies import get_conversation_adapter, get_tts_adapter, get_avatar_client
from adapters.tts.base import TTSOptions
from config import settings
from conversation_loop import TurnContext, run_turn
from livekit_publisher import LiveKitPublisher

router = APIRouter()


@router.websocket("/sessions/{session_id}/events")
async def session_events(websocket: WebSocket, session_id: str):
    await websocket.accept()

    conversation = get_conversation_adapter()
    tts = get_tts_adapter()
    avatar = get_avatar_client()

    tts_options = TTSOptions(
        voice_id=settings.cartesia_voice_id,
        model_id=settings.cartesia_model_id,
        sample_rate=16000,
    )

    generation = 0
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    # Separate queue feeding PCM into the avatar worker stream
    avatar_audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    active_turn: asyncio.Task | None = None
    avatar_stream_task: asyncio.Task | None = None

    # Send ready immediately — Agentforce session created lazily on first turn
    agent_session_started = False

    import logging as _logging
    _log = _logging.getLogger(__name__)

    # LiveKit publisher — disabled until session is stable
    # TODO: re-enable once gateway session stays alive reliably
    publisher = None
    publisher_ready = False

    async def ensure_agent_session():
        nonlocal agent_session_started
        if not agent_session_started:
            agent_session_started = True
            await conversation.start_session(session_id)
            try:
                await avatar.connect()
                await avatar.open_session(session_id)
                import logging
                logging.getLogger(__name__).info("Avatar worker connected for session %s", session_id)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Avatar worker connection failed: %s", e)

    async def send_event(payload: dict) -> None:
        try:
            await websocket.send_json(payload)
        except Exception:
            pass

    total_pcm_bytes = 0

    async def send_audio(pcm: bytes, timestamp_ms: int) -> None:
        """Route PCM to avatar worker and also stream directly to browser."""
        nonlocal total_pcm_bytes
        total_pcm_bytes += len(pcm)
        await avatar_audio_queue.put(pcm)
        try:
            await websocket.send_bytes(pcm)
        except Exception:
            pass

    def current_generation() -> int:
        return generation

    async def run_avatar_stream(turn_id: str, gen: int) -> None:
        """Forward PCM to avatar worker, push returned frames to LiveKit."""
        _log.info("Avatar stream started turn=%s gen=%d", turn_id, gen)

        async def pcm_source():
            total = 0
            while True:
                chunk = await avatar_audio_queue.get()
                if chunk is None:
                    _log.info("PCM stream ended — sent %d bytes to worker", total)
                    return
                total += len(chunk)
                yield chunk

        frame_count = 0
        async for frame in avatar.stream(
            session_id=session_id,
            turn_id=turn_id,
            generation=gen,
            audio_chunks=pcm_source(),
            current_generation=current_generation,
        ):
            frame_count += 1
            if frame_count == 1:
                _log.info("First frame received from worker turn=%s", turn_id)
            if publisher_ready and publisher:
                await publisher.push_frame(frame.encoded_frame, frame.presentation_timestamp_ms)
        _log.info("Avatar stream done — %d frames turn=%s", frame_count, turn_id)

    def cancel_active_turn() -> None:
        nonlocal active_turn, avatar_stream_task
        if active_turn and not active_turn.done():
            active_turn.cancel()
        if avatar_stream_task and not avatar_stream_task.done():
            avatar_stream_task.cancel()

    def drain_queues() -> None:
        while not audio_queue.empty():
            audio_queue.get_nowait()
        while not avatar_audio_queue.empty():
            avatar_audio_queue.get_nowait()

    await send_event({"type": "session.ready", "session_id": session_id, "generation": generation})

    try:
        while True:
            data = await websocket.receive()

            # Binary frame = raw PCM from browser AudioWorklet
            if "bytes" in data and data["bytes"]:
                await audio_queue.put(data["bytes"])
                continue

            if "text" not in data:
                continue

            msg = json.loads(data["text"])
            event_type = msg.get("type")

            if event_type == "speech.started":
                await ensure_agent_session()
                generation += 1
                cancel_active_turn()
                await asyncio.gather(
                    active_turn or asyncio.sleep(0),
                    avatar_stream_task or asyncio.sleep(0),
                    return_exceptions=True,
                )
                drain_queues()

                turn_id = f"turn_{uuid.uuid4().hex[:8]}"
                ctx = TurnContext(
                    session_id=session_id,
                    turn_id=turn_id,
                    generation=generation,
                )

                async def audio_chunks():
                    while True:
                        chunk = await audio_queue.get()
                        if chunk is None:
                            return
                        yield chunk

                avatar_stream_task = asyncio.create_task(
                    run_avatar_stream(turn_id, generation)
                )

                async def _on_turn_complete():
                    # Signal end-of-audio to avatar worker so it runs inference
                    await avatar_audio_queue.put(None)

                active_turn = asyncio.create_task(
                    run_turn(
                        ctx=ctx,
                        audio_chunks=audio_chunks(),
                        conversation=conversation,
                        tts=tts,
                        tts_options=tts_options,
                        send_event=send_event,
                        send_audio=send_audio,
                        current_generation=current_generation,
                        on_turn_complete=_on_turn_complete,
                    )
                )

            elif event_type == "speech.ended":
                await audio_queue.put(None)

            elif event_type == "turn.interrupt":
                generation += 1
                cancel_active_turn()
                await asyncio.gather(
                    active_turn or asyncio.sleep(0),
                    avatar_stream_task or asyncio.sleep(0),
                    return_exceptions=True,
                )
                drain_queues()
                await avatar_audio_queue.put(None)
                await avatar.interrupt(session_id, "", generation)
                await send_event({
                    "type": "turn.cancelled",
                    "session_id": session_id,
                    "generation": generation,
                })

            elif event_type == "text.send":
                await ensure_agent_session()
                generation += 1
                cancel_active_turn()
                await asyncio.gather(
                    active_turn or asyncio.sleep(0),
                    avatar_stream_task or asyncio.sleep(0),
                    return_exceptions=True,
                )
                drain_queues()

                turn_id = f"turn_{uuid.uuid4().hex[:8]}"
                ctx = TurnContext(
                    session_id=session_id,
                    turn_id=turn_id,
                    generation=generation,
                )

                async def empty_audio():
                    return
                    yield

                avatar_stream_task = asyncio.create_task(
                    run_avatar_stream(turn_id, generation)
                )

                async def _on_text_turn_complete():
                    await avatar_audio_queue.put(None)

                active_turn = asyncio.create_task(
                    run_turn(
                        ctx=ctx,
                        audio_chunks=empty_audio(),
                        conversation=conversation,
                        tts=tts,
                        tts_options=tts_options,
                        send_event=send_event,
                        send_audio=send_audio,
                        current_generation=current_generation,
                        on_turn_complete=_on_text_turn_complete,
                    )
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await send_event({"type": "session.error", "message": str(e)})
    finally:
        cancel_active_turn()
        await avatar_audio_queue.put(None)
        if agent_session_started:
            await conversation.end_session(session_id)
            await avatar.close_session(session_id)
        await tts.close()
        if publisher:
            try:
                await publisher.disconnect()
            except Exception:
                pass
