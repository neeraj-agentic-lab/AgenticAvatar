"""
GPU avatar worker entry point.
Loads Ditto before gRPC to avoid CUDA context conflicts.
Uses grpcio 1.59.3 which doesn't register pthread_atfork handlers.
"""
import sys
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")

if __name__ == "__main__":
    import server
    log.info("Loading Ditto...")
    sdk = server._load_ditto()
    log.info("Ditto ready. Starting gRPC server...")
    asyncio.run(server.serve(preloaded_sdk=sdk))
