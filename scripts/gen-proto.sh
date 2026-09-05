#!/usr/bin/env bash
set -e

PROTO_SRC="packages/contracts/avatar.proto"
GATEWAY_OUT="services/gateway"
WORKER_OUT="services/avatar-worker"

python3 -m grpc_tools.protoc \
  -I packages/contracts \
  --python_out="$GATEWAY_OUT" \
  --grpc_python_out="$GATEWAY_OUT" \
  "$PROTO_SRC"

python3 -m grpc_tools.protoc \
  -I packages/contracts \
  --python_out="$WORKER_OUT" \
  --grpc_python_out="$WORKER_OUT" \
  "$PROTO_SRC"

echo "Proto files generated."
