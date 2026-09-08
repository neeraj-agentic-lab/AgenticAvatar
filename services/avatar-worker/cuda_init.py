"""
Minimal CUDA context initializer.
Runs before the main worker to "unlock" the CUDA driver context.
Must complete and EXIT before Python worker starts.
"""
import ctypes
import sys

# Initialize CUDA via ctypes (minimal — just enough to unlock the driver)
libcuda = ctypes.CDLL("libcuda.so.1")
result = libcuda.cuInit(0)
if result != 0:
    print(f"cuInit failed with {result}", file=sys.stderr)
    sys.exit(1)

# Get device count to confirm CUDA is ready
count = ctypes.c_int(0)
libcuda.cuDeviceGetCount(ctypes.byref(count))
print(f"CUDA initialized: {count.value} device(s)", flush=True)
# Process exits here — CUDA driver is now in "ready" state for next process
