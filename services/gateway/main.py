from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from dependencies import get_avatar_client
from routers import sessions, events


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to avatar worker on startup
    await get_avatar_client().connect()
    yield
    # Clean up on shutdown
    await get_avatar_client().aclose()


app = FastAPI(title="AgenticAvatar Gateway", version="0.1.0", lifespan=lifespan)

_CORS_ORIGINS = [
    "http://localhost:3000",
    f"http://{settings.public_host}:3000" if settings.public_host else None,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in _CORS_ORIGINS if o],
    allow_origin_regex=r"http://\d+\.\d+\.\d+\.\d+:3000",  # any IP:3000
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router, prefix="/v1")
app.include_router(events.router, prefix="/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
