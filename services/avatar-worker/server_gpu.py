"""
GPU avatar worker — real-time streaming using Ditto's online pipeline.

Flow:
  1. OpenSession → sdk.setup(portrait) — precompute identity features once
  2. Stream RPC: each pcm_s16le chunk → sdk.run_chunk() → yield frames immediately
  3. IDLE control → signal pipeline end → yield remaining frames
"""

import asyncio
import logging
import os
import queue
import sys
import threading
import time
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
CFG_PKL      = os.getenv("DITTO_CFG", "/models/ditto/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt_t4_online.pkl")
SOURCE_IMAGE = os.getenv("AVATAR_SOURCE_IMAGE", "/models/ditto/portrait.jpg")
SAMPLE_RATE  = 16000
# Ditto online pipeline requires exactly this chunk size:
# int(sum(chunksize) * 0.04 * 16000) + 80 where chunksize=(3,5,2) → 6480 samples
CHUNK_SAMPLES = 6480


class RealtimeStreamSDK:
    """Wraps Ditto online StreamSDK, yielding frames from writer_queue in real-time."""

    def __init__(self, cfg_pkl: str, data_root: str):
        from stream_pipeline_online import StreamSDK
        self._sdk = StreamSDK(cfg_pkl, data_root)
        self._frame_queue: queue.Queue = queue.Queue(maxsize=500)
        self._setup_done = False

    def setup(self, source_path: str, output_path: str):
        self._sdk.setup(source_path, output_path)
        # Replace writer worker with frame interceptor
        self._sdk._writer_worker = self._intercepting_writer_worker
        self._setup_done = True
        log.info("Portrait features precomputed: %s", source_path)

    def _intercepting_writer_worker(self):
        sdk = self._sdk
        while not sdk.stop_event.is_set():
            try:
                item = sdk.writer_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                self._frame_queue.put(None)
                break
            self._frame_queue.put(item)  # RGB ndarray
            sdk.writer_pbar.update()

    def run_chunk(self, audio_np: np.ndarray):
        if not self._setup_done:
            raise RuntimeError("Call setup() before run_chunk()")
        self._sdk.run_chunk(audio_np)

    def signal_end(self):
        try:
            self._sdk.audio2motion_queue.put(None)
        except Exception:
            pass

    def close(self):
        try:
            self._sdk.close()
        except Exception:
            pass
        # Drain queue
        while True:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

    @property
    def frame_queue(self) -> queue.Queue:
        return self._frame_queue


def _load_ditto():
    log.info("Loading Ditto (online mode) from %s ...", CHECKPOINTS)
    sdk = RealtimeStreamSDK(CFG_PKL, CHECKPOINTS)
    log.info("Ditto loaded.")
    return sdk


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

        if self._sdk is None:
            log.error("Ditto not loaded")
            return avatar_pb2.OpenSessionResponse(session_id=request.session_id, ready=False)

        # Precompute portrait identity features now — not at inference time
        out_dir   = f"/tmp/ditto_out_{request.session_id}"
        os.makedirs(out_dir, exist_ok=True)
        out_video = os.path.join(out_dir, "output.mp4")

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: self._sdk.setup(SOURCE_IMAGE, out_video))
            log.info("OpenSession %s — portrait ready", request.session_id)
        except Exception:
            log.exception("Portrait setup failed")
            return avatar_pb2.OpenSessionResponse(session_id=request.session_id, ready=False)

        return avatar_pb2.OpenSessionResponse(session_id=request.session_id, ready=True)

    async def Stream(self, request_iterator, context):
        if self._sdk is None:
            return

        generation   = 0
        session_id   = ""
        turn_id      = ""
        pcm_leftover = np.array([], dtype=np.float32)  # partial chunk buffer
        frame_count  = 0
        ts_ms        = int(time.time() * 1000)
        loop         = asyncio.get_event_loop()

        async for msg in request_iterator:
            session_id = msg.session_id
            turn_id    = msg.turn_id

            if msg.generation < generation:
                continue
            if msg.generation > generation:
                generation   = msg.generation
                pcm_leftover = np.array([], dtype=np.float32)

            if msg.HasField("control"):
                if msg.control.type == avatar_pb2.ControlEvent.INTERRUPT:
                    pcm_leftover = np.array([], dtype=np.float32)
                    self._sdk.signal_end()

                elif msg.control.type == avatar_pb2.ControlEvent.IDLE:
                    # Signal end of audio — flush remaining frames
                    self._sdk.signal_end()
                    # Drain remaining frames
                    async for frame in self._drain_frames(session_id, turn_id, generation, ts_ms, frame_count, loop):
                        frame_count += 1
                        yield frame
                    log.info("Turn done: %d frames total", frame_count)
                    frame_count = 0
                    ts_ms = int(time.time() * 1000)

            elif msg.HasField("pcm_s16le"):
                audio_f32 = np.frombuffer(msg.pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
                combined  = np.concatenate([pcm_leftover, audio_f32])

                # Process all complete 6480-sample chunks immediately
                i = 0
                while i + CHUNK_SAMPLES <= len(combined):
                    chunk = combined[i:i + CHUNK_SAMPLES]
                    try:
                        await loop.run_in_executor(None, self._sdk.run_chunk, chunk)
                    except Exception as e:
                        log.warning("run_chunk error: %s", e)
                    i += CHUNK_SAMPLES

                    # Immediately yield any frames that came out
                    while not self._sdk.frame_queue.empty():
                        frame_rgb = self._sdk.frame_queue.get_nowait()
                        if frame_rgb is not None:
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

                pcm_leftover = combined[i:]

    async def _drain_frames(self, session_id, turn_id, generation, ts_ms, frame_offset, loop):
        """Drain remaining frames after IDLE with timeout."""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                frame_rgb = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: self._sdk.frame_queue.get(timeout=0.5)),
                    timeout=1.0,
                )
            except (asyncio.TimeoutError, queue.Empty):
                break
            if frame_rgb is None:
                break
            jpeg = await loop.run_in_executor(None, _rgb_to_jpeg, frame_rgb)
            frame_offset += 1
            yield avatar_pb2.RenderOutput(
                session_id=session_id,
                turn_id=turn_id,
                generation=generation,
                presentation_timestamp_ms=ts_ms + frame_offset * 40,
                encoded_frame=jpeg,
                keyframe=False,
            )

    async def CloseSession(self, request, context):
        log.info("CloseSession %s", request.session_id)
        try:
            self._sdk.close()
        except Exception:
            pass
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
