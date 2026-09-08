"""
GPU avatar worker entry point.

CRITICAL: This file must NOT import anything that touches CUDA.
The parent process (PID 1) must not allocate a CUDA context.
All CUDA-touching code runs in the child subprocess.
"""
import os
import sys
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run_worker():
    """Run in a child subprocess — gets its own CUDA context, no deadlock."""
    import asyncio
    sys.path.insert(0, "/proto_gen")
    sys.path.insert(0, "/ditto")
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

    # Import server HERE (not in parent) — cv2, grpc, avatar_pb2_grpc all load here
    import server
    sdk = server._load_ditto()
    asyncio.run(server.serve(preloaded_sdk=sdk))


if __name__ == "__main__":
    log.info("Launcher: spawning worker child (CUDA-free parent)...")

    # Use subprocess.Popen — does NOT run Python imports in parent
    # The child gets its own CUDA context without conflict from parent
    env = os.environ.copy()
    env["_RUN_WORKER"] = "1"
    # Clear LD_PRELOAD so NVIDIA container toolkit preload doesn't
    # re-initialize CUDA in the child (conflicts with parent's CUDA state)
    env.pop("LD_PRELOAD", None)

    # Write a minimal worker script that the child executes.
    # CRITICAL import order: Ditto loads BEFORE cv2/grpc to avoid CUDA context conflict.
    child_script = os.path.join(os.path.dirname(__file__), "_worker_child.py")
    with open(child_script, "w") as f:
        f.write("""
import sys, os, asyncio, logging
sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Step 1: Load Ditto BEFORE importing cv2/grpc (cv2 allocates CUDA context that conflicts with TRT)
log.info("Step 1: Loading Ditto...")
from stream_pipeline_online import StreamSDK
from server import (RealtimeStreamSDK, _load_ditto, CFG_PKL, CHECKPOINTS,
                    SOURCE_IMAGE, SAMPLE_RATE, CHUNK_SAMPLES,
                    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET,
                    WIDTH, HEIGHT, LiveKitRoomPublisher, serve,
                    AvatarRendererServicer)
sdk = _load_ditto()
log.info("Step 2: Ditto loaded. Now importing cv2/grpc...")

# Step 2: Import cv2 and grpc AFTER Ditto is fully loaded
import cv2  # noqa: triggers CUDA init — must happen AFTER TRT engines load
import grpc
import avatar_pb2_grpc

log.info("Step 3: Starting gRPC server...")
asyncio.run(serve(preloaded_sdk=sdk))
""")

    proc = subprocess.Popen(
        [sys.executable, child_script],
        env=env,
    )
    log.info("Worker child started (PID %d). Waiting...", proc.pid)
    ret = proc.wait()
    log.info("Worker exited with code %d", ret)
    sys.exit(ret)
