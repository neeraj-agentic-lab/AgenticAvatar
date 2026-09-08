"""
GPU avatar worker entry point.

Uses fork+exec to create a child process with a NEW PID for TRT loading.
TRT engine locks are tracked per-PID at the kernel level.
docker exec works because it uses a fresh PID — this replicates that.

CRITICAL: Must fork() BEFORE importing ANYTHING that touches Python's import
machinery, so the child doesn't inherit import locks.
"""
import sys
import os

# Fork IMMEDIATELY — before any Python imports that could hold import locks
# Child gets a new PID, which is what TRT needs
if os.environ.get("_AVATAR_WORKER_CHILD") != "1":
    pid = os.fork()
    if pid == 0:
        # Child process — new PID, fresh TRT context
        os.environ["_AVATAR_WORKER_CHILD"] = "1"
        # exec to get a completely clean Python state
        os.execve(sys.executable, [sys.executable] + sys.argv, os.environ)
    else:
        # Parent — wait for child
        _, status = os.waitpid(pid, 0)
        sys.exit(os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1)

# We are in the child process with a new PID
import asyncio
import logging

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
log.info("Worker child PID=%d — pre-importing torch to init CUDA before TRT...", os.getpid())

# Pre-import torch to complete PyTorch's CUDA initialization BEFORE TRT loads.
# tensorrt_utils.py imports torch, and PyTorch + TRT concurrent CUDA init deadlocks.
# Pre-importing torch here ensures CUDA is fully initialized before TRT needs it.
import torch
if torch.cuda.is_available():
    torch.cuda.init()
    log.info("PyTorch CUDA initialized: %s", torch.cuda.get_device_name(0))
else:
    log.warning("CUDA not available to PyTorch")

if __name__ == "__main__":
    import server
    log.info("Loading Ditto...")
    sdk = server._load_ditto()
    log.info("Ditto ready. Starting gRPC server...")
    asyncio.run(server.serve(preloaded_sdk=sdk))
