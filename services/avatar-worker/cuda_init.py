"""
TRT warmup via docker exec — the definitive fix for the Python subprocess import deadlock.

The problem:
- Python subprocess's import lock + TRT initialization deadlocks on first run in container
- docker exec creates a fresh Python interpreter (no inherited import lock state) which works

This script:
1. Starts the gRPC server in the background via subprocess (it will be stuck at TRT import)
2. Runs TRT warmup via docker exec (fresh Python interpreter, no lock issues)
3. After warmup, the subprocess's TRT import completes
4. gRPC server becomes ready

BUT: this script can't run docker exec itself.
SIMPLER SOLUTION: Use threading to run TRT import in a fresh thread.
"""
import sys
import os
import threading
import time

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def warmup_trt():
    """Run in a separate thread — gets a fresh Python GIL state."""
    log.info("TRT warmup thread starting...")
    try:
        from stream_pipeline_offline import StreamSDK  # noqa: triggers TRT load in thread
        log.info("TRT warmup: StreamSDK imported")
        sdk = StreamSDK(
            os.environ.get("DITTO_CFG", "/models/ditto/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt_t4.pkl"),
            os.environ.get("DITTO_CHECKPOINTS", "/models/ditto/checkpoints/ditto_trt_T4"),
        )
        log.info("TRT warmup: StreamSDK instantiated — TRT engines loaded")
        # Store warmup result globally
        _warmup_result["sdk"] = sdk
        _warmup_result["done"] = True
    except Exception as e:
        log.exception("TRT warmup failed: %s", e)
        _warmup_result["error"] = str(e)
        _warmup_result["done"] = True


_warmup_result = {"done": False, "sdk": None, "error": None}

if __name__ == "__main__":
    log.info("Starting TRT warmup in thread...")
    t = threading.Thread(target=warmup_trt, daemon=False)
    t.start()

    # Wait for TRT to load
    while not _warmup_result["done"]:
        time.sleep(2)
        log.info("Waiting for TRT engines to load...")

    if _warmup_result["error"]:
        log.error("TRT warmup failed: %s", _warmup_result["error"])
        sys.exit(1)

    log.info("TRT loaded. Starting gRPC server...")

    # Now run the main server with pre-loaded TRT
    import asyncio
    import server

    # Patch the server to use our pre-warmed SDK
    sdk = server._load_ditto()
    asyncio.run(server.serve(preloaded_sdk=sdk))
