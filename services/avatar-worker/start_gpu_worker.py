"""
GPU avatar worker entry point.

Uses os.execv to replace the PID 1 process with a new Python process
that doesn't inherit the NVIDIA runtime's primary CUDA context lock.
The new process (not PID 1) can initialize TRT engines without deadlock.
"""
import os
import sys

# If we're PID 1 and haven't re-exec'd yet, spawn a child and wait
if os.getpid() == 1 and os.environ.get("_WORKER_REEXEC") != "1":
    import subprocess
    env = os.environ.copy()
    env["_WORKER_REEXEC"] = "1"
    # Run as a non-PID-1 child process
    proc = subprocess.Popen(
        [sys.executable] + sys.argv,
        env=env,
    )
    sys.exit(proc.wait())

# We're now running as a non-PID-1 process
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")

os.environ["CUDA_VISIBLE_DEVICES"] = "0"

if __name__ == "__main__":
    import server
    log.info("Loading Ditto...")
    sdk = server._load_ditto()
    log.info("Ditto ready. Starting gRPC server...")
    asyncio.run(server.serve(preloaded_sdk=sdk))
