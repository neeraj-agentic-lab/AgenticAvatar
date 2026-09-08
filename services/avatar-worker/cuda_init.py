"""
CUDA context keeper.
Stays alive as a background process holding an active CUDA context.
This allows the Python worker process to find an existing context
instead of trying to create the first one (which deadlocks on T4+TRT8.6.1).
"""
import sys
import time
import signal

def _handle_signal(signum, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

try:
    import ctypes
    libcudart = ctypes.CDLL("libcudart.so")
    # Initialize CUDA runtime and create primary context
    ret = libcudart.cudaFree(0)
    if ret != 0:
        print(f"cudaFree failed: {ret}", file=sys.stderr)
        sys.exit(1)

    # Get device count
    count = ctypes.c_int(0)
    libcudart.cudaGetDeviceCount(ctypes.byref(count))
    print(f"CUDA context keeper ready: {count.value} GPU(s)", flush=True)

    # Stay alive — keep the CUDA context active
    while True:
        time.sleep(10)
        # Periodically touch CUDA to keep context warm
        libcudart.cudaFree(0)

except Exception as e:
    print(f"cuda_init error: {e}", file=sys.stderr)
    sys.exit(1)
