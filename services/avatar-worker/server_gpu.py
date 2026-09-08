"""
GPU avatar worker — Ditto online pipeline + direct LiveKit publishing.

Architecture:
  Gateway sends PCM chunks via gRPC → worker runs Ditto → worker publishes
  frames directly to LiveKit room → browser receives via WebRTC.

The LiveKit publisher runs in the same process as Ditto but on its own
thread, completely isolated from the gateway's WebSocket handler.
"""

import asyncio
import logging
import os
import queue
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
# cv2 and grpc imported AFTER Ditto loads (see start_gpu_worker.py _worker_child.py)
# cv2 with CUDA support allocates a CUDA context that conflicts with TRT engine loading

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")

try:
    import grpc
    import avatar_pb2
    import avatar_pb2_grpc
except ImportError:
    grpc = None
    avatar_pb2 = None
    avatar_pb2_grpc = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHECKPOINTS   = os.getenv("DITTO_CHECKPOINTS", "/models/ditto/checkpoints/ditto_trt_T4")
CFG_PKL       = os.getenv("DITTO_CFG", "/models/ditto/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt_t4_online.pkl")
SOURCE_IMAGE  = os.getenv("AVATAR_SOURCE_IMAGE", "/models/ditto/portrait.jpg")
SAMPLE_RATE   = 16000
CHUNK_SAMPLES = 6480  # int(sum((3,5,2)) * 0.04 * 16000) + 80

LIVEKIT_URL    = os.getenv("LIVEKIT_URL", "ws://livekit:7880")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "devsecret")

WIDTH, HEIGHT = 512, 512


# ── LiveKit publisher ─────────────────────────────────────────────────────────

def _make_room_token(room_name: str) -> str:
    from livekit.api import AccessToken, VideoGrants
    token = AccessToken(api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
    token.with_identity(f"avatar-worker-{room_name[:8]}")
    token.with_name("Avatar")
    token.with_grants(VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=False,
    ))
    token.with_ttl(timedelta(hours=4))
    return token.to_jwt()


class LiveKitRoomPublisher:
    """
    Publishes JPEG frames to a LiveKit room.
    Runs its own asyncio event loop in a background thread — completely
    isolated from the gRPC server's event loop.
    """

    def __init__(self, room_name: str):
        self._room_name  = room_name
        self._loop       = asyncio.new_event_loop()
        self._thread     = threading.Thread(target=self._run_loop, daemon=True)
        self._room       = None
        self._source     = None
        self._ready      = threading.Event()
        self._frame_q: queue.Queue = queue.Queue(maxsize=200)
        self._stopped    = False

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._publisher_main())

    async def _publisher_main(self):
        from livekit import rtc

        try:
            token = _make_room_token(self._room_name)
            self._room   = rtc.Room()
            self._source = rtc.VideoSource(width=WIDTH, height=HEIGHT)
            track = rtc.LocalVideoTrack.create_video_track("avatar", self._source)

            await self._room.connect(LIVEKIT_URL, token)
            await self._room.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(
                    source=rtc.TrackSource.SOURCE_CAMERA,
                    video_codec=rtc.VideoCodec.H264,
                    video_encoding=rtc.VideoEncoding(
                        max_framerate=25,
                        max_bitrate=1_500_000,
                    ),
                ),
            )
            log.info("LiveKit publisher connected — room=%s", self._room_name)
            self._ready.set()

            # Drain frame queue and push to LiveKit
            while not self._stopped:
                try:
                    item = self._frame_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break
                jpeg_bytes, ts_ms = item
                try:
                    rgba = await asyncio.get_event_loop().run_in_executor(
                        None, _jpeg_to_rgba, jpeg_bytes
                    )
                    frame = rtc.VideoFrame(
                        data=bytearray(rgba),
                        width=WIDTH,
                        height=HEIGHT,
                        type=rtc.VideoBufferType.RGBA,
                    )
                    self._source.capture_frame(frame, timestamp_us=ts_ms * 1000)
                except Exception as e:
                    log.warning("Frame push error: %s", e)

        except Exception:
            log.exception("LiveKit publisher failed for room=%s", self._room_name)
            self._ready.set()  # unblock waiters even on failure
        finally:
            if self._room:
                try:
                    await self._room.disconnect()
                except Exception:
                    pass

    def start(self):
        self._thread.start()

    def wait_ready(self, timeout=10.0) -> bool:
        return self._ready.wait(timeout=timeout)

    def push_frame(self, jpeg_bytes: bytes, ts_ms: int):
        if not self._frame_q.full():
            self._frame_q.put_nowait((jpeg_bytes, ts_ms))

    def stop(self):
        self._stopped = True
        self._frame_q.put(None)


def _jpeg_to_rgba(jpeg_bytes: bytes) -> bytes:
    import cv2 as _cv2
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr = _cv2.imdecode(arr, _cv2.IMREAD_COLOR)
    if bgr is None:
        return bytes(WIDTH * HEIGHT * 4)
    bgr = _cv2.resize(bgr, (WIDTH, HEIGHT))
    rgba = _cv2.cvtColor(bgr, _cv2.COLOR_BGR2RGBA)
    return rgba.tobytes()


# ── Ditto streaming ───────────────────────────────────────────────────────────

class RealtimeStreamSDK:
    def __init__(self, cfg_pkl: str, data_root: str):
        from stream_pipeline_offline import StreamSDK
        self._sdk = StreamSDK(cfg_pkl, data_root)
        self._frame_queue: queue.Queue = queue.Queue(maxsize=500)
        self._setup_done = False

    def setup(self, source_path: str, output_path: str):
        log.info("RealtimeStreamSDK.setup() portrait=%s", source_path)
        # Replace writer BEFORE setup() starts background threads
        self._sdk._writer_worker = self._intercepting_writer_worker
        self._sdk.setup(source_path, output_path)
        self._setup_done = True
        log.info("RealtimeStreamSDK.setup() complete, threads started")

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
            self._frame_queue.put(item)
            sdk.writer_pbar.update()

    def run_chunk(self, audio_np: np.ndarray):
        log.debug("run_chunk: %d samples", len(audio_np))
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
        while True:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

    @property
    def frame_queue(self):
        return self._frame_queue


def _load_ditto():
    try:
        import time
        log.info("Step 1/3: Initializing StreamSDK (loading TRT engines)...")
        t0 = time.time()
        sdk = RealtimeStreamSDK(CFG_PKL, CHECKPOINTS)
        log.info("Step 2/3: StreamSDK ready in %.1fs. Precomputing portrait features...", time.time() - t0)
        os.makedirs("/tmp/ditto_warmup", exist_ok=True)
        t1 = time.time()
        sdk.setup(SOURCE_IMAGE, "/tmp/ditto_warmup/output.mp4")
        log.info("Step 3/3: Portrait precomputed in %.1fs. Ditto fully ready.", time.time() - t1)
        return sdk
    except Exception:
        log.exception("FATAL: Failed to load Ditto")
        raise


def _rgb_to_jpeg(rgb: np.ndarray) -> bytes:
    import cv2 as _cv2
    bgr = _cv2.cvtColor(rgb, _cv2.COLOR_RGB2BGR)
    _, buf = _cv2.imencode(".jpg", bgr, [_cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


# ── gRPC server ───────────────────────────────────────────────────────────────

class AvatarRendererServicer(avatar_pb2_grpc.AvatarRendererServicer):
    def __init__(self, preloaded_sdk: "RealtimeStreamSDK | None" = None):
        # Accept a pre-loaded SDK (loaded before asyncio starts) to avoid CUDA deadlock
        self._sdk: RealtimeStreamSDK | None = preloaded_sdk
        self._loading = preloaded_sdk is None
        self._ditto_lock = threading.Lock()
        self._publishers: dict[str, LiveKitRoomPublisher] = {}

        if preloaded_sdk is not None:
            log.info("Using pre-loaded Ditto SDK")
            return

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

        if not self._sdk or not self._sdk._setup_done:
            return avatar_pb2.OpenSessionResponse(session_id=request.session_id, ready=False)

        # Start LiveKit publisher for this session in its own thread
        room_name = request.session_id
        if room_name not in self._publishers:
            pub = LiveKitRoomPublisher(room_name)
            pub.start()
            self._publishers[room_name] = pub
            # Wait up to 8s for publisher to connect (non-blocking for gRPC)
            loop = asyncio.get_event_loop()
            ready = await loop.run_in_executor(None, pub.wait_ready, 8.0)
            if ready:
                log.info("OpenSession %s — LiveKit publisher ready", request.session_id)
            else:
                log.warning("OpenSession %s — LiveKit publisher not ready (video may be delayed)", request.session_id)

        return avatar_pb2.OpenSessionResponse(session_id=request.session_id, ready=True)

    async def Stream(self, request_iterator, context):
        if self._sdk is None:
            return

        generation   = 0
        session_id   = ""
        turn_id      = ""
        pcm_leftover = np.array([], dtype=np.float32)
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
                    self._sdk.signal_end()
                    async for frame in self._drain_frames(session_id, turn_id, generation, ts_ms, frame_count, loop):
                        frame_count += 1
                        yield frame
                    log.info("Turn done: %d frames total session=%s", frame_count, session_id)
                    frame_count = 0
                    ts_ms = int(time.time() * 1000)

            elif msg.HasField("pcm_s16le"):
                audio_f32 = np.frombuffer(msg.pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
                combined  = np.concatenate([pcm_leftover, audio_f32])

                i = 0
                while i + CHUNK_SAMPLES <= len(combined):
                    chunk = combined[i:i + CHUNK_SAMPLES]
                    with self._ditto_lock:
                        try:
                            await loop.run_in_executor(None, self._sdk.run_chunk, chunk)
                        except Exception as e:
                            log.warning("run_chunk error: %s", e)
                    i += CHUNK_SAMPLES

                    # Yield frames immediately and push to LiveKit
                    while not self._sdk.frame_queue.empty():
                        frame_rgb = self._sdk.frame_queue.get_nowait()
                        if frame_rgb is not None:
                            jpeg = await loop.run_in_executor(None, _rgb_to_jpeg, frame_rgb)
                            frame_count += 1
                            pts = ts_ms + frame_count * 40

                            # Push to LiveKit in publisher thread
                            pub = self._publishers.get(session_id)
                            if pub:
                                pub.push_frame(jpeg, pts)

                            yield avatar_pb2.RenderOutput(
                                session_id=session_id,
                                turn_id=turn_id,
                                generation=generation,
                                presentation_timestamp_ms=pts,
                                encoded_frame=jpeg,
                                keyframe=(frame_count == 1),
                            )

                pcm_leftover = combined[i:]

    async def _drain_frames(self, session_id, turn_id, generation, ts_ms, frame_offset, loop):
        deadline = time.time() + 5.0
        pub = self._publishers.get(session_id)
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
            pts = ts_ms + frame_offset * 40
            if pub:
                pub.push_frame(jpeg, pts)
            yield avatar_pb2.RenderOutput(
                session_id=session_id,
                turn_id=turn_id,
                generation=generation,
                presentation_timestamp_ms=pts,
                encoded_frame=jpeg,
                keyframe=False,
            )

    async def CloseSession(self, request, context):
        log.info("CloseSession %s", request.session_id)
        pub = self._publishers.pop(request.session_id, None)
        if pub:
            pub.stop()
        return avatar_pb2.CloseSessionResponse(ok=True)


async def serve(preloaded_sdk=None):
    import grpc as _grpc
    server = _grpc.aio.server()
    avatar_pb2_grpc.add_AvatarRendererServicer_to_server(AvatarRendererServicer(preloaded_sdk), server)
    server.add_insecure_port("[::]:50051")
    log.info("GPU avatar worker listening on :50051")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    sdk = _load_ditto()
    asyncio.run(serve(preloaded_sdk=sdk))
