"""
CUDA + TRT context pre-warmer.
Must run and EXIT before the main Python worker starts.
Creates a TRT runtime context to fully initialize CUDA for subsequent processes.
"""
import sys

try:
    import tensorrt as trt
    import pycuda.driver as cuda
    import pycuda.autoinit  # noqa: initializes CUDA context

    # Create a TRT logger and runtime — this fully initializes TRT+CUDA
    logger = trt.Logger(trt.Logger.WARNING)
    runtime = trt.Runtime(logger)

    # Force CUDA context to be fully ready
    ctx = cuda.Device(0).make_context()
    ctx.pop()

    print("TRT+CUDA pre-warm complete", flush=True)
except Exception as e:
    # If pycuda not available, fall back to ctypes cuInit
    try:
        import ctypes
        libcuda = ctypes.CDLL("libcuda.so.1")
        libcuda.cuInit(0)
        # Also initialize the CUDA runtime
        libcudart = ctypes.CDLL("libcudart.so")
        libcudart.cudaFree(0)  # forces runtime context creation
        print("CUDA runtime pre-warm complete", flush=True)
    except Exception as e2:
        print(f"Pre-warm failed: {e}, {e2}", file=sys.stderr)
