"""
Minimal GPU worker launcher.
Imports NOTHING that touches CUDA before spawning the child.
The child gets a completely clean CUDA context.
"""
import multiprocessing as mp
import sys
import os


def run_server():
    """Child process — completely clean, no inherited CUDA state."""
    sys.path.insert(0, "/proto_gen")
    sys.path.insert(0, "/ditto")
    os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "false")

    import logging
    import asyncio
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # All CUDA-touching imports happen here, in the child, with clean context
    import server
    sdk = server._load_ditto()
    asyncio.run(server.serve(preloaded_sdk=sdk))


if __name__ == "__main__":
    # spawn = fresh Python interpreter, no inherited file descriptors or CUDA handles
    mp.set_start_method("spawn")
    p = mp.Process(target=run_server, daemon=False)
    p.start()
    p.join()
