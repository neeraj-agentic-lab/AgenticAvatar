"""
GPU avatar worker — wraps Ditto talkinghead in our gRPC streaming interface.
Receives PCM audio chunks, accumulates them, runs Ditto inference,
streams back encoded video frames.

Verified working with:
  pytorch/pytorch:2.3.0-cuda12.1-cudnn8-devel
  numpy>=2, tensorrt==8.6.1, cuda-python==12.1.0
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

import cv2
import grpc
import numpy as np

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")

import avatar_pb2
import avatar_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHECKPOINTS  = os.getenv("DITTO_CHECKPOINTS", "/models/ditto/checkpoints/ditto_trt_T4")
CFG_PKL      = os.getenv("DITTO_CFG",         "/models/ditto/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt_t4.pkl")
SOURCE_IMAGE = os.getenv("AVATAR_SOURCE_IMAGE", "/models/ditto/portrait.jpg")
SAMPLE_RATE  = 16000


def _load_ditto():
    log.info("Loading Ditto from %s ...", CHECKPOINTS)
    from stream_pipeline_offline import StreamSDK
    sdk = StreamSDK(CFG_PKL, CHECKPOINTS)
    log.info("Ditto ready.")
    return sdk


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return tmp.name


def _frames_from_video(video_path: str):
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
        self._sdk = _load_ditto()
        log.info("Portrait: %s", SOURCE_IMAGE)

    async def OpenSession(self, request, context):
        log.info("OpenSession %s", request.session_id)
        return avatar_pb2.OpenSessionResponse(session_id=request.session_id, ready=True)

    async def Stream(self, request_iterator, context):
        pcm_buf     = bytearray()
        generation  = 0
        session_id  = ""
        turn_id     = ""

        async for msg in request_iterator:
            session_id = msg.session_id
            turn_id    = msg.turn_id

            if msg.generation < generation:
                continue  # stale

            if msg.generation > generation:
                generation = msg.generation
                pcm_buf.clear()

            if msg.HasField("control"):
                if msg.control.type == avatar_pb2.ControlEvent.INTERRUPT:
                    pcm_buf.clear()
                elif msg.control.type == avatar_pb2.ControlEvent.IDLE:
                    if pcm_buf:
                        async for frame in self._run_inference(
                            bytes(pcm_buf), session_id, turn_id, generation
                        ):
                            yield frame
                        pcm_buf.clear()

            elif msg.HasField("pcm_s16le"):
                pcm_buf.extend(msg.pcm_s16le)

    async def _run_inference(self, pcm: bytes, session_id: str, turn_id: str, generation: int):
        wav_path = _pcm_to_wav(pcm)
        out_dir   = tempfile.mkdtemp()
        out_video = os.path.join(out_dir, "output.mp4")

        try:
            t0 = time.time()
            log.info("Inference start: %d bytes PCM", len(pcm))

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._sdk.inference(
                    audio_path=wav_path,
                    source_path=SOURCE_IMAGE,
                    output_path=out_video,
                ),
            )

            log.info("Inference done in %.2fs", time.time() - t0)

            ts_ms = int(time.time() * 1000)
            for i, frame_bytes in enumerate(_frames_from_video(out_video)):
                yield avatar_pb2.RenderOutput(
                    session_id=session_id,
                    turn_id=turn_id,
                    generation=generation,
                    presentation_timestamp_ms=ts_ms + i * 40,
                    encoded_frame=frame_bytes,
                    keyframe=(i == 0),
                )
        except Exception:
            log.exception("Inference failed")
        finally:
            Path(wav_path).unlink(missing_ok=True)
            shutil.rmtree(out_dir, ignore_errors=True)

    async def CloseSession(self, request, context):
        log.info("CloseSession %s", request.session_id)
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
