FROM python:3.11-slim

WORKDIR /app

COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Generate proto stubs into /proto_gen (outside /app so source mount won't overwrite)
COPY packages/contracts/avatar.proto /tmp/avatar.proto
RUN mkdir -p /proto_gen && python -m grpc_tools.protoc \
    -I /tmp \
    --python_out=/proto_gen \
    --grpc_python_out=/proto_gen \
    /tmp/avatar.proto

COPY services/gateway/ .

# Add /proto_gen to Python path at runtime
ENV PYTHONPATH="/proto_gen:${PYTHONPATH}"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
