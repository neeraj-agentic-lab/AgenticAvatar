#!/usr/bin/env bash
# Download Kokoro ONNX model files into models/kokoro/
set -e

DEST="$(dirname "$0")/../models/kokoro"
mkdir -p "$DEST"

echo "==> Downloading Kokoro v1.0 model files..."

if [ ! -f "$DEST/kokoro-v1_0.onnx" ]; then
  curl -L -o "$DEST/kokoro-v1_0.onnx" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1_0.onnx"
  echo "    kokoro-v1_0.onnx downloaded"
else
  echo "    kokoro-v1_0.onnx already exists, skipping"
fi

if [ ! -f "$DEST/voices-v1_0.bin" ]; then
  curl -L -o "$DEST/voices-v1_0.bin" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1_0.bin"
  echo "    voices-v1_0.bin downloaded"
else
  echo "    voices-v1_0.bin already exists, skipping"
fi

echo ""
echo "==> Kokoro model files ready at $DEST"
echo "    Available voices: af_heart, af_bella, af_nicole, am_adam, am_michael"
echo "    bf_emma, bf_isabella, bm_george, bm_lewis (British English)"
