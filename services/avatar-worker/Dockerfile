FROM python:3.11-slim

RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/avatar-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Generate proto stubs into /proto_gen
COPY packages/contracts/avatar.proto /tmp/avatar.proto
RUN mkdir -p /proto_gen && python -m grpc_tools.protoc \
    -I /tmp \
    --python_out=/proto_gen \
    --grpc_python_out=/proto_gen \
    /tmp/avatar.proto

COPY services/avatar-worker/ .

ENV PYTHONPATH="/proto_gen:${PYTHONPATH}"

EXPOSE 50051
CMD ["python", "server.py"]
