"""
CUDA context initializer + worker launcher.
This process:
1. Initializes CUDA (creates primary context)
2. Launches the Python worker as a subprocess (inherits initialized CUDA)
3. Waits for the worker to complete
"""
import sys
import os
import subprocess
import ctypes
import time

# Step 1: Initialize CUDA runtime in THIS process
libcudart = ctypes.CDLL("libcudart.so")
ret = libcudart.cudaFree(0)
if ret != 0:
    print(f"cudaFree failed: {ret}", file=sys.stderr)
    sys.exit(1)

count = ctypes.c_int(0)
libcudart.cudaGetDeviceCount(ctypes.byref(count))
print(f"CUDA initialized in parent: {count.value} GPU(s)", flush=True)

# Step 2: Small delay to let CUDA fully settle
time.sleep(1)

# Step 3: Launch Python worker — inherits our initialized CUDA context
worker_env = os.environ.copy()
proc = subprocess.Popen(
    [sys.executable, "/app/start.py"],
    env=worker_env,
)

# Step 4: Keep this process alive (parent of worker) and wait
print(f"Worker launched (PID {proc.pid})", flush=True)
ret = proc.wait()
print(f"Worker exited: {ret}", flush=True)
sys.exit(ret)
