"""
GPU avatar worker — real-time streaming using Ditto's online pipeline.

Flow per turn:
  1. sdk.setup(portrait, output_path)  — precompute identity features
  2. For each ~640ms audio chunk: sdk.run_chunk(audio_np)
  3. Frames arrive in real-time via the writer_queue — we intercept them
  4. Each frame is JPEG-encoded and yielded as a gRPC RenderOutput
"""

import asyncio
import logging
import os
import queue
import sys
import threading
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
CHUNK_SAMPLES = SAMPLE_RATE * 2   # ~2 seconds of audio per chunk (Ditto needs ~1-2s)


class RealtimeStreamSDK:
    """
    Wraps Ditto's online StreamSDK to intercept frames in real-time
    instead of writing them to a file.
    """

    def __init__(self, cfg_pkl: str, data_root: str):
        from stream_pipeline_online import StreamSDK
        self._sdk = StreamSDK(cfg_pkl, data_root)
        self._frame_queue: queue.Queue = queue.Queue(maxsize=200)

    def setup(self, source_path: str, output_path: str):
        """Initialize identity features and start background workers."""
        self._sdk.setup(source_path, output_path)
        # Replace the writer worker with one that enqueues frames
        self._sdk._writer_worker = self._intercepting_writer_worker
        log.info("RealtimeStreamSDK ready, portrait=%s", source_path)

    def _intercepting_writer_worker(self):
        """Replaces Ditto's file writer — puts RGB frames into our queue instead."""
        sdk = self._sdk
        while not sdk.stop_event.is_set():
            try:
                item = sdk.writer_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                self._frame_queue.put(None)  # signal end of stream
                break
            self._frame_queue.put(item)  # item is RGB ndarray
            sdk.writer_pbar.update()

    def run_chunk(self, audio_np: np.ndarray):
        """Feed one audio chunk; frames appear asynchronously in frame_queue."""
        self._sdk.run_chunk(audio_np)

    def close(self):
        self._sdk.close()

    @property
    def frame_queue(self) -> queue.Queue:
        return self._frame_queue


def _load_ditto():
    log.info("Loading Ditto (online mode) from %s ...", CHECKPOINTS)
    sdk = RealtimeStreamSDK(CFG_PKL, CHECKPOINTS)
    log.info("Ditto ready.")
    return sdk


def _pcm_s16le_to_float32(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Convert raw PCM s16le bytes to float32 numpy array at sample_rate."""
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return arr


def _rgb_to_jpeg(rgb: np.ndarray) -> bytes:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


class AvatarRendererServicer(avatar_pb2_grpc.AvatarRendererServicer):
    def __init__(self):
        self._sdk: RealtimeStreamSDK | None = None
        self._loading = True
        self._lock = threading.Lock()

        def _load():
            try:
                self._sdk = _load_ditto()
            except Exception:
                log.exception("Failed to load Ditto")
            finally:
                self._loading = False

        threading.Thread(target=_load, daemon=True).start()

    async def OpenSession(self, request, context):
        for _ in range(300):
            if not self._loading:
                break
            await asyncio.sleep(1)
        ready = self._sdk is not None
        log.info("OpenSession %s (ready=%s)", request.session_id, ready)
        return avatar_pb2.OpenSessionResponse(session_id=request.session_id, ready=ready)

    async def Stream(self, request_iterator, context):
        pcm_buf     = bytearray()
        generation  = 0
        session_id  = ""
        turn_id     = ""

        async for msg in request_iterator:
            session_id = msg.session_id
            turn_id    = msg.turn_id

            if msg.generation < generation:
                continue
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
        if self._sdk is None:
            log.warning("Ditto not ready, skipping")
            return

        duration_s = len(pcm) / (SAMPLE_RATE * 2)
        log.info("Inference start: %.2fs audio, session=%s", duration_s, session_id)

        if duration_s < 0.3:
            log.warning("Audio too short (%.2fs), skipping", duration_s)
            return

        out_dir = f"/tmp/ditto_out_{session_id}"
        os.makedirs(out_dir, exist_ok=True)
        out_video = os.path.join(out_dir, "output.mp4")

        audio_f32 = _pcm_s16le_to_float32(pcm)
        t0 = time.time()
        frame_count = 0

        try:
            with self._lock:
                # Setup identity features for this portrait
                self._sdk.setup(SOURCE_IMAGE, out_video)

                # Feed audio in chunks
                loop = asyncio.get_event_loop()
                for start in range(0, len(audio_f32), CHUNK_SAMPLES):
                    chunk = audio_f32[start:start + CHUNK_SAMPLES]
                    if len(chunk) < 160:
                        break
                    await loop.run_in_executor(None, self._sdk.run_chunk, chunk)

                # Signal end of audio
                self._sdk._sdk.audio2motion_queue.put(None)

                # Drain frames as they arrive
                ts_ms = int(time.time() * 1000)
                while True:
                    try:
                        frame_rgb = await loop.run_in_executor(
                            None,
                            lambda: self._sdk.frame_queue.get(timeout=5.0)
                        )
                    except queue.Empty:
                        break

                    if frame_rgb is None:
                        break

                    jpeg = await loop.run_in_executor(None, _rgb_to_jpeg, frame_rgb)
                    frame_count += 1
                    yield avatar_pb2.RenderOutput(
                        session_id=session_id,
                        turn_id=turn_id,
                        generation=generation,
                        presentation_timestamp_ms=ts_ms + frame_count * 40,
                        encoded_frame=jpeg,
                        keyframe=(frame_count == 1),
                    )

        except Exception:
            log.exception("Inference failed")
        finally:
            try:
                self._sdk.close()
            except Exception:
                pass
            log.info("Inference done: %d frames in %.2fs", frame_count, time.time() - t0)


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
