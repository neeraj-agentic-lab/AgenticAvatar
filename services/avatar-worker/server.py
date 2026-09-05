import asyncio
import os
import time
import grpc
import numpy as np

# Generated from avatar.proto — run scripts/gen-proto.sh to regenerate
import avatar_pb2
import avatar_pb2_grpc

MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"
FRAME_WIDTH = 512
FRAME_HEIGHT = 512
FPS = 25


def _make_idle_frame(ts_ms: int) -> bytes:
    """Generate a solid-colour placeholder frame (green = idle)."""
    frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    frame[:] = (0, 180, 0)
    return frame.tobytes()


def _make_speaking_frame(ts_ms: int) -> bytes:
    """Generate a solid-colour placeholder frame (blue = speaking)."""
    frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    frame[:] = (0, 0, 200)
    return frame.tobytes()


class AvatarRendererServicer(avatar_pb2_grpc.AvatarRendererServicer):
    async def OpenSession(self, request, context):
        print(f"[avatar-worker] OpenSession: {request.session_id}")
        return avatar_pb2.OpenSessionResponse(
            session_id=request.session_id,
            ready=True,
        )

    async def Stream(self, request_iterator, context):
        speaking = False
        generation = 0
        frame_interval = 1.0 / FPS

        async def frame_generator():
            nonlocal speaking
            while True:
                ts_ms = int(time.time() * 1000)
                frame = _make_speaking_frame(ts_ms) if speaking else _make_idle_frame(ts_ms)
                yield avatar_pb2.RenderOutput(
                    session_id="",
                    turn_id="",
                    generation=generation,
                    presentation_timestamp_ms=ts_ms,
                    encoded_frame=frame,
                    keyframe=False,
                )
                await asyncio.sleep(frame_interval)

        frame_task = asyncio.create_task(self._emit_frames(context, frame_generator()))

        async for msg in request_iterator:
            if msg.HasField("pcm_s16le"):
                speaking = len(msg.pcm_s16le) > 0
            elif msg.HasField("control"):
                if msg.control.type == avatar_pb2.ControlEvent.INTERRUPT:
                    speaking = False

        frame_task.cancel()

    async def _emit_frames(self, context, generator):
        async for frame in generator:
            await context.write(frame)

    async def CloseSession(self, request, context):
        print(f"[avatar-worker] CloseSession: {request.session_id}")
        return avatar_pb2.CloseSessionResponse(ok=True)


async def serve():
    server = grpc.aio.server()
    avatar_pb2_grpc.add_AvatarRendererServicer_to_server(
        AvatarRendererServicer(), server
    )
    server.add_insecure_port("[::]:50051")
    print("[avatar-worker] Mock avatar worker listening on :50051")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
