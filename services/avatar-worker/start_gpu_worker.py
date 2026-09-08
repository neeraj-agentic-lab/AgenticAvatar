"""
GPU avatar worker entry point.

Critical import order to avoid Python import lock + CUDA init deadlock:
1. Pre-import stream_pipeline_online BEFORE importing server.py
   (server.py imports grpc which starts background threads that hold import lock)
2. Load Ditto after all module imports are done
3. Start gRPC server last
"""
import sys
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")

# Step 1: Pre-import Ditto modules BEFORE grpc background threads start
# This ensures Python's import lock is not held when grpc initializes
log.info("Pre-importing Ditto modules...")
from stream_pipeline_online import StreamSDK as _StreamSDK
log.info("Ditto modules imported OK")

# Step 2: Now import server (which imports grpc, cv2 etc.)
import server

if __name__ == "__main__":
    log.info("Loading Ditto (streaming SDK)...")
    sdk = server._load_ditto()
    log.info("Ditto ready. Starting gRPC server...")
    asyncio.run(server.serve(preloaded_sdk=sdk))
