"""
GPU avatar worker — wraps Ditto talkinghead inference in the gRPC streaming interface.

Receives PCM audio chunks, accumulates them, runs Ditto inference,
and streams back encoded video frames.
"""

import asyncio
import io
import logging
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

import cv2
import grpc
import numpy as np

sys.path.insert(0, "/ditto")
sys.path.insert(0, "/proto_gen")

import avatar_pb2
import avatar_pb2_grpc

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

CHECKPOINTS = os.getenv("DITTO_CHECKPOINTS", "/models/ditto/checkpoints")
CFG_PKL = os.getenv("DITTO_CFG", "/models/ditto/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl")
SOURCE_IMAGE = os.getenv("AVATAR_SOURCE_IMAGE", "/models/ditto/portrait.png")
SAMPLE_RATE = 16000


def _load_ditto():
    """Load Ditto inference engine once at startup."""
    from inference import DittoInference
    log.info("Loading Ditto inference engine from %s ...", CHECKPOINTS)
    engine = DittoInference(
        data_root=CHECKPOINTS,
        cfg_pkl=CFG_PKL,
    )
    log.info("Ditto loaded.")
    return engine


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """Write raw PCM s16le bytes to a temporary WAV file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return tmp.name


def _frames_from_video(video_path: str):
    """Yield JPEG-encoded frames from an MP4 output."""
    cap = cv2.VideoCapture(video_path)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        yield buf.tobytes()
    cap.release()


class AvatarRendererServicer(avatar_pb2_grpc.AvatarRendererServicer):
    def __init__(self):
        self._engine = _load_ditto()
        self._source_image = SOURCE_IMAGE
        log.info("Avatar worker ready. Source image: %s", self._source_image)

    async def OpenSession(self, request, context):
        log.info("OpenSession: %s", request.session_id)
        return avatar_pb2.OpenSessionResponse(
            session_id=request.session_id,
            ready=True,
        )

    async def Stream(self, request_iterator, context):
        pcm_buffer = bytearray()
        current_generation = 0
        session_id = ""
        turn_id = ""

        async for msg in request_iterator:
            session_id = msg.session_id
            turn_id = msg.turn_id

            if msg.generation < current_generation:
                # Stale generation — discard
                continue

            if msg.generation > current_generation:
                # New generation — flush old buffer
                current_generation = msg.generation
                pcm_buffer.clear()

            if msg.HasField("control"):
                if msg.control.type == avatar_pb2.ControlEvent.INTERRUPT:
                    pcm_buffer.clear()
                    continue
                elif msg.control.type == avatar_pb2.ControlEvent.IDLE:
                    # End of speaking — run inference on accumulated audio
                    if len(pcm_buffer) > 0:
                        async for frame in self._synthesize(
                            bytes(pcm_buffer), session_id, turn_id, current_generation
                        ):
                            yield frame
                    pcm_buffer.clear()

            elif msg.HasField("pcm_s16le"):
                pcm_buffer.extend(msg.pcm_s16le)

    async def _synthesize(self, pcm: bytes, session_id: str, turn_id: str, generation: int):
        """Run Ditto inference on accumulated PCM, yield encoded frames."""
        wav_path = _pcm_to_wav(pcm)
        out_dir = tempfile.mkdtemp()
        out_video = os.path.join(out_dir, "output.mp4")

        try:
            log.info("Running Ditto inference: %d bytes PCM → %s", len(pcm), out_video)
            start = time.time()

            # Run in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._engine.inference(
                    audio_path=wav_path,
                    source_path=self._source_image,
                    output_path=out_video,
                ),
            )

            elapsed = time.time() - start
            log.info("Inference done in %.2fs", elapsed)

            ts_ms = int(time.time() * 1000)
            for i, frame_bytes in enumerate(_frames_from_video(out_video)):
                yield avatar_pb2.RenderOutput(
                    session_id=session_id,
                    turn_id=turn_id,
                    generation=generation,
                    presentation_timestamp_ms=ts_ms + i * 40,  # ~25fps
                    encoded_frame=frame_bytes,
                    keyframe=(i == 0),
                )

        except Exception as e:
            log.error("Inference error: %s", e)
        finally:
            Path(wav_path).unlink(missing_ok=True)
            import shutil
            shutil.rmtree(out_dir, ignore_errors=True)

    async def CloseSession(self, request, context):
        log.info("CloseSession: %s", request.session_id)
        return avatar_pb2.CloseSessionResponse(ok=True)


async def serve():
    server = grpc.aio.server()
    avatar_pb2_grpc.add_AvatarRendererServicer_to_server(AvatarRendererServicer(), server)
    server.add_insecure_port("[::]:50051")
    log.info("GPU avatar worker listening on :50051")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
