#!/usr/bin/env bash
# Start local dev stack with auto-detected host IP for LiveKit.
set -e

cd "$(dirname "$0")/.."

# Detect LAN IP (works on macOS and Linux)
HOST_IP=$(ipconfig getifaddr en0 2>/dev/null || \
          ipconfig getifaddr en1 2>/dev/null || \
          hostname -I 2>/dev/null | awk '{print $1}')

if [ -z "$HOST_IP" ]; then
  echo "ERROR: Could not detect host IP. Set HOST_IP manually and re-run."
  exit 1
fi

echo "==> Detected host IP: $HOST_IP"

# Free any stale processes holding our ports
for PORT in 50051 8000; do
  PID=$(lsof -ti :$PORT 2>/dev/null || true)
  if [ -n "$PID" ]; then
    echo "==> Freeing port $PORT (pid $PID)"
    kill -9 $PID 2>/dev/null || true
  fi
done

# Write LiveKit config with current IP
cat > infra/livekit-dev.yaml <<EOF
port: 7880
rtc:
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: false
  node_ip: ${HOST_IP}
redis:
  address: redis:6379
keys:
  devkey: devsecret
log_level: info
EOF

# Patch LIVEKIT_PUBLIC_URL in .env
if grep -q "LIVEKIT_PUBLIC_URL" .env; then
  sed -i '' "s|LIVEKIT_PUBLIC_URL=.*|LIVEKIT_PUBLIC_URL=ws://${HOST_IP}:7880|" .env
else
  echo "LIVEKIT_PUBLIC_URL=ws://${HOST_IP}:7880" >> .env
fi

echo "==> LiveKit configured for ws://${HOST_IP}:7880"

# Start all services
docker compose up redis -d
docker compose up livekit avatar-worker gateway web -d

echo ""
echo "==> Stack running:"
echo "    Web app:  http://localhost:3000"
echo "    Gateway:  http://localhost:8000"
echo "    LiveKit:  ws://${HOST_IP}:7880"
echo ""
echo "To tail logs: docker compose logs -f gateway"
