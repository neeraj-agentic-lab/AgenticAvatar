"""
GPU avatar worker launcher.

Uses multiprocessing.spawn to start server.py in a child process.
This avoids the NVIDIA container runtime CUDA lock deadlock:
- Parent process: NVIDIA runtime holds CUDA context lock
- Child (spawned): clean CUDA context, TRT engines load in ~8s
"""
import multiprocessing as mp
import sys
import os

def run_server():
    """Entry point for the spawned child process."""
    # Fresh Python interpreter — no NVIDIA runtime lock inherited
    sys.path.insert(0, "/proto_gen")
    sys.path.insert(0, "/ditto")
    os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "false")

    # Import and run server.py's main logic
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("worker")

    log.info("Child process started (clean CUDA context)")
    log.info("Loading Ditto online pipeline...")

    import server
    sdk = server._load_ditto()

    log.info("Ditto ready. Starting gRPC server...")
    asyncio.run(server.serve(preloaded_sdk=sdk))


if __name__ == "__main__":
    # Must use spawn — fork inherits the CUDA lock from the NVIDIA runtime
    mp.set_start_method("spawn")
    p = mp.Process(target=run_server, daemon=False)
    p.start()
    p.join()
