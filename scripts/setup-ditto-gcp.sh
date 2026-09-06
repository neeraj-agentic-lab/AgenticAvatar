#!/usr/bin/env bash
# Set up Ditto on GCP T4 VM.
# Run this ONCE inside the VM: bash scripts/setup-ditto-gcp.sh
set -e

MODELS_DIR="/models/ditto"
sudo mkdir -p "$MODELS_DIR"
sudo chown -R $USER:$USER "$MODELS_DIR"

echo "==> Step 1: Download Ditto weights from HuggingFace..."
if [ ! -d "$MODELS_DIR/checkpoints" ]; then
    git lfs install
    git clone https://huggingface.co/digital-avatar/ditto-talkinghead "$MODELS_DIR/checkpoints"
    echo "    Weights downloaded."
else
    echo "    Weights already exist, skipping."
fi

echo ""
echo "==> Step 2: Compile TensorRT engines for T4 (Turing arch)..."
echo "    This takes ~20-40 minutes. Do not interrupt."

sudo docker run --rm --gpus all \
    -v "$MODELS_DIR:/models/ditto" \
    pytorch/pytorch:2.1.0-cuda12.1-cudnn8-devel \
    bash -c "
        pip install -q tensorrt==8.6.1 colored tqdm cython && \
        git clone https://github.com/antgroup/ditto-talkinghead.git /ditto && \
        cd /ditto && \
        python cvt_onnx_to_trt.py \
            --onnx_dir /models/ditto/checkpoints/ditto_onnx \
            --trt_dir /models/ditto/checkpoints/ditto_trt_T4 \
            --fp16 && \
        echo 'TensorRT engines compiled for T4.'
    "

echo ""
echo "==> Step 3: Update config to use T4 engines..."
# Use T4-compiled engines instead of Ampere pre-built ones
CFG_SRC="$MODELS_DIR/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt.pkl"
CFG_T4="$MODELS_DIR/checkpoints/ditto_cfg/v0.4_hubert_cfg_trt_t4.pkl"

sudo docker run --rm --gpus all \
    -v "$MODELS_DIR:/models/ditto" \
    pytorch/pytorch:2.1.0-cuda12.1-cudnn8-devel \
    bash -c "
        git clone https://github.com/antgroup/ditto-talkinghead.git /ditto && \
        cd /ditto && python3 -c \"
import pickle, sys
with open('$CFG_SRC', 'rb') as f:
    cfg = pickle.load(f)
# Point data_root to T4-compiled engines
cfg.data_root = '/models/ditto/checkpoints/ditto_trt_T4'
with open('$CFG_T4', 'wb') as f:
    pickle.dump(cfg, f)
print('T4 config written to $CFG_T4')
\"
    "

echo ""
echo "==> Ditto setup complete."
echo "    Weights: $MODELS_DIR/checkpoints"
echo "    T4 engines: $MODELS_DIR/checkpoints/ditto_trt_T4"
echo "    T4 config: $CFG_T4"
echo ""
echo "Next: place your portrait image at $MODELS_DIR/portrait.png"
echo "Then: docker compose up avatar-worker-gpu -d"
