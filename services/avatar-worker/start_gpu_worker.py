"""
Single-process GPU avatar worker.
CRITICAL: cv2 must be imported AFTER Ditto loads (cv2 CUDA init conflicts with TRT).
Solution: server.py does NOT import cv2 at module level.
cv2 is imported lazily inside functions that need it.
"""
import sys
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, "/proto_gen")
sys.path.insert(0, "/ditto")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

if __name__ == "__main__":
    # Step 1: Load Ditto BEFORE anything that touches CUDA (cv2, torch, etc.)
    # server.py must NOT import cv2 at module level
    import server
    log.info("Loading Ditto (cv2 not yet imported)...")
    sdk = server._load_ditto()
    log.info("Ditto ready. Starting gRPC server...")
    asyncio.run(server.serve(preloaded_sdk=sdk))
