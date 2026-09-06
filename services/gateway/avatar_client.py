"""
gRPC client for the GPU avatar worker.
One instance per gateway process — sessions are multiplexed over one channel.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncGenerator

import grpc

import avatar_pb2
import avatar_pb2_grpc


@dataclass
class AvatarFrame:
    session_id: str
    turn_id: str
    generation: int
    presentation_timestamp_ms: int
    encoded_frame: bytes
    keyframe: bool


class AvatarWorkerClient:
    def __init__(self, target: str):
        self._target = target
        self._channel: grpc.aio.Channel | None = None
        self._stub: avatar_pb2_grpc.AvatarRendererStub | None = None

    async def connect(self) -> None:
        # Force IPv4 — GCP internal DNS fails on AAAA (IPv6) queries
        options = [
            ("grpc.dns_min_time_between_resolutions_ms", 0),
            ("grpc.enable_http_proxy", 0),
        ]
        self._channel = grpc.aio.insecure_channel(
            self._target,
            options=options,
        )
        self._stub = avatar_pb2_grpc.AvatarRendererStub(self._channel)

    async def open_session(self, session_id: str, avatar_id: str = "default") -> None:
        assert self._stub, "Call connect() first"
        await self._stub.OpenSession(
            avatar_pb2.OpenSessionRequest(
                session_id=session_id,
                avatar_id=avatar_id,
            )
        )

    async def stream(
        self,
        session_id: str,
        turn_id: str,
        generation: int,
        audio_chunks: AsyncGenerator[bytes, None],
        current_generation,  # callable() -> int
    ) -> AsyncGenerator[AvatarFrame, None]:
        """
        Send PCM audio to the worker, yield back encoded video frames.
        Stops sending/receiving as soon as generation becomes stale.
        """
        assert self._stub, "Call connect() first"

        async def input_generator():
            async for pcm in audio_chunks:
                if current_generation() > generation:
                    break
                yield avatar_pb2.RenderInput(
                    session_id=session_id,
                    turn_id=turn_id,
                    generation=generation,
                    timestamp_ms=int(time.time() * 1000),
                    pcm_s16le=pcm,
                )
            # Signal end of speaking — switch worker back to idle
            yield avatar_pb2.RenderInput(
                session_id=session_id,
                turn_id=turn_id,
                generation=generation,
                timestamp_ms=int(time.time() * 1000),
                control=avatar_pb2.ControlEvent(
                    type=avatar_pb2.ControlEvent.IDLE
                ),
            )

        async for output in self._stub.Stream(input_generator()):
            if current_generation() > generation:
                break
            yield AvatarFrame(
                session_id=output.session_id,
                turn_id=output.turn_id,
                generation=output.generation,
                presentation_timestamp_ms=output.presentation_timestamp_ms,
                encoded_frame=output.encoded_frame,
                keyframe=output.keyframe,
            )

    async def interrupt(self, session_id: str, turn_id: str, generation: int) -> None:
        """Send an interrupt control event to flush worker buffers immediately."""
        assert self._stub, "Call connect() first"

        async def interrupt_input():
            yield avatar_pb2.RenderInput(
                session_id=session_id,
                turn_id=turn_id,
                generation=generation,
                timestamp_ms=int(time.time() * 1000),
                control=avatar_pb2.ControlEvent(
                    type=avatar_pb2.ControlEvent.INTERRUPT
                ),
            )

        async for _ in self._stub.Stream(interrupt_input()):
            break

    async def close_session(self, session_id: str) -> None:
        if not self._stub:
            return
        await self._stub.CloseSession(
            avatar_pb2.CloseSessionRequest(session_id=session_id)
        )

    async def aclose(self) -> None:
        if self._channel:
            await self._channel.close()
