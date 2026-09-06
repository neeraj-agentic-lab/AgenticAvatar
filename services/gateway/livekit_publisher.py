"""
Publishes avatar video frames to a LiveKit room as a video track.
Decodes JPEG frames to RGBA before pushing — LiveKit VideoSource requires raw pixels.
"""

import asyncio
import logging
from datetime import timedelta

import cv2
import numpy as np
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from config import settings

log = logging.getLogger(__name__)

WIDTH  = 512
HEIGHT = 512


def _make_publisher_token(room_name: str) -> str:
    token = AccessToken(
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    token.with_identity(f"avatar-{room_name}")
    token.with_name("Avatar")
    token.with_grants(VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=False,
    ))
    token.with_ttl(timedelta(hours=4))
    return token.to_jwt()


def _jpeg_to_rgba(jpeg_bytes: bytes) -> bytes:
    """Decode JPEG bytes → RGBA byte array (512×512×4)."""
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return bytes(WIDTH * HEIGHT * 4)
    bgr = cv2.resize(bgr, (WIDTH, HEIGHT))
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
    return rgba.tobytes()


class LiveKitPublisher:
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._room: rtc.Room | None = None
        self._video_source: rtc.VideoSource | None = None
        self._connected = False

    async def connect(self) -> None:
        # Create Room inside async context so its event loop matches ours
        self._room = rtc.Room()
        token = _make_publisher_token(self._session_id)

        await self._room.connect(settings.livekit_url, token)
        self._connected = True

        self._video_source = rtc.VideoSource(width=WIDTH, height=HEIGHT)
        track = rtc.LocalVideoTrack.create_video_track("avatar", self._video_source)
        options = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA,
            video_codec=rtc.VideoCodec.H264,
            video_encoding=rtc.VideoEncoding(
                max_framerate=25,
                max_bitrate=1_500_000,
            ),
        )
        await self._room.local_participant.publish_track(track, options)
        log.info("LiveKit publisher connected for session %s", self._session_id)

    async def push_frame(self, jpeg_bytes: bytes, timestamp_ms: int) -> None:
        if not self._video_source or not jpeg_bytes:
            return
        try:
            rgba = await asyncio.get_event_loop().run_in_executor(
                None, _jpeg_to_rgba, jpeg_bytes
            )
            frame = rtc.VideoFrame(
                data=bytearray(rgba),
                width=WIDTH,
                height=HEIGHT,
                type=rtc.VideoBufferType.RGBA,
            )
            self._video_source.capture_frame(frame, timestamp_us=timestamp_ms * 1000)
        except Exception as e:
            log.warning("Frame push error: %s", e)

    async def disconnect(self) -> None:
        if self._connected and self._room:
            await self._room.disconnect()
            self._connected = False
