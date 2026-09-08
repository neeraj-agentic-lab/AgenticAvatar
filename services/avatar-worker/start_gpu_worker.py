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

    # Write a minimal worker script that the child executes
    child_script = os.path.join(os.path.dirname(__file__), "_worker_child.py")
    if not os.path.exists(child_script):
        with open(child_script, "w") as f:
            f.write("""
import sys, os
sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
import asyncio
import server
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
sdk = server._load_ditto()
asyncio.run(server.serve(preloaded_sdk=sdk))
""")

    proc = subprocess.Popen(
        [sys.executable, child_script],
        env=env,
    )
    log.info("Worker child started (PID %d). Waiting...", proc.pid)
    ret = proc.wait()
    log.info("Worker exited with code %d", ret)
    sys.exit(ret)
