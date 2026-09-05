import uuid
from datetime import timedelta
from fastapi import APIRouter
from pydantic import BaseModel

from livekit.api import AccessToken, VideoGrants
from config import settings

router = APIRouter()


class CreateSessionRequest(BaseModel):
    avatar_id: str = "default"
    locale: str = "en-US"


class CreateSessionResponse(BaseModel):
    session_id: str
    websocket_url: str
    livekit_url: str
    livekit_token: str
    expires_at: str


def _make_livekit_token(session_id: str) -> str:
    token = AccessToken(
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    token.with_identity(f"user-{session_id}")
    token.with_name(f"User {session_id[:8]}")
    token.with_grants(VideoGrants(
        room_join=True,
        room=session_id,
        can_subscribe=True,
        can_publish=False,      # browser only receives avatar track
    ))
    token.with_ttl(timedelta(hours=2))
    return token.to_jwt()


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest):
    session_id = f"ses_{uuid.uuid4().hex[:12]}"

    livekit_token = _make_livekit_token(session_id)

    # TODO: store session in Redis
    # TODO: Agentforce session created lazily on first turn (see events.py)

    return CreateSessionResponse(
        session_id=session_id,
        websocket_url=f"ws://localhost:8000/v1/sessions/{session_id}/events",
        livekit_url=settings.livekit_public_url,
        livekit_token=livekit_token,
        expires_at="2099-01-01T00:00:00Z",
    )


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str):
    return {"status": "closed"}
