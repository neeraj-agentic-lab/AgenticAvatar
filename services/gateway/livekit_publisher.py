"""
Publishes avatar video frames to a LiveKit room as a video track.

One LiveKitPublisher per session — connects as a server-side participant,
publishes JPEG frames received from the avatar worker gRPC stream.
"""

import asyncio
import logging
from typing import AsyncGenerator

from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from config import settings

log = logging.getLogger(__name__)


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
    from datetime import timedelta
    token.with_ttl(timedelta(hours=4))
    return token.to_jwt()


class LiveKitPublisher:
    """
    Joins a LiveKit room as a server-side participant and publishes
    a VideoSource that avatar JPEG frames are pushed into.
    """

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._room = rtc.Room()
        self._video_source: rtc.VideoSource | None = None
        self._video_track: rtc.LocalVideoTrack | None = None
        self._connected = False

    async def connect(self) -> None:
        token = _make_publisher_token(self._session_id)
        livekit_url = settings.livekit_url  # internal URL e.g. ws://livekit:7880

        await self._room.connect(livekit_url, token)
        self._connected = True

        # Create a video source and publish it
        self._video_source = rtc.VideoSource(width=512, height=512)
        self._video_track = rtc.LocalVideoTrack.create_video_track(
            "avatar", self._video_source
        )
        options = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA,
            video_codec=rtc.VideoCodec.H264,
            video_encoding=rtc.VideoEncoding(
                max_framerate=25,
                max_bitrate=1_500_000,
            ),
        )
        await self._room.local_participant.publish_track(self._video_track, options)
        log.info("LiveKit publisher connected for session %s", self._session_id)

    async def push_frame(self, jpeg_bytes: bytes, timestamp_ms: int) -> None:
        """Push one JPEG-encoded frame to the video source."""
        if not self._video_source:
            return
        try:
            frame = rtc.VideoFrame(
                data=jpeg_bytes,
                width=512,
                height=512,
                type=rtc.VideoBufferType.JPEG,
            )
            self._video_source.capture_frame(frame, timestamp_us=timestamp_ms * 1000)
        except Exception as e:
            log.warning("Frame push error: %s", e)

    async def disconnect(self) -> None:
        if self._connected:
            await self._room.disconnect()
            self._connected = False
            log.info("LiveKit publisher disconnected for session %s", self._session_id)
