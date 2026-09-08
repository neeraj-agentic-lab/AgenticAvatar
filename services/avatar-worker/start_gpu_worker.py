"""
GPU avatar worker entry point.
Uses Ditto's exact conda environment (PyTorch 2.5.1 + cuDNN 9.1 + TRT 8.6.1)
which is the tested, working combination. No initialization hacks needed.
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
