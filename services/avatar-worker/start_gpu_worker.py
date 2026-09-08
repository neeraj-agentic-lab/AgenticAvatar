"""
GPU avatar worker entry point.

Uses os.execv to replace itself with a fresh Python process for TRT loading.
The fresh process (re-exec'd) doesn't have the Python import lock state that
causes TRT to deadlock in subprocess/fork contexts.
"""
import sys
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Check if we've already re-exec'd
if os.environ.get("_AVATAR_WORKER_EXEC") != "1":
    # Re-exec ourselves as a fresh Python process
    # This avoids the Python import lock + TRT deadlock
    log.info("Re-execing for fresh Python interpreter...")
    env = os.environ.copy()
    env["_AVATAR_WORKER_EXEC"] = "1"
    os.execve(sys.executable, [sys.executable] + sys.argv, env)
    # Never reaches here

# We are now in the re-exec'd process
sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

if __name__ == "__main__":
    import server
    log.info("Loading Ditto...")
    sdk = server._load_ditto()
    log.info("Ditto ready. Starting gRPC server...")
    asyncio.run(server.serve(preloaded_sdk=sdk))
