import json
import uuid
from typing import AsyncGenerator

import httpx

from adapters.agentforce.auth import SalesforceAuth
from .base import ConversationAdapter, ConversationEvent, ConversationEventType


class AgentforceVoiceAdapter(ConversationAdapter):
    """
    Mode: Agentforce Voice API.
    Salesforce handles STT + agent routing in one streaming API.
    Replaces both the STT adapter and the Agentforce Agent API client.

    NOTE: Agentforce Voice API endpoints and payload shapes should be
    verified against the latest Salesforce documentation when integrating.
    """

    def __init__(self, auth: SalesforceAuth, instance_url: str, agent_id: str):
        self._auth = auth
        self._base = f"{instance_url.rstrip('/')}/einstein/ai-agent/v1"
        self._agent_id = agent_id
        self._http = httpx.AsyncClient(timeout=60)
        self._sessions: dict[str, str] = {}

    async def start_session(self, session_id: str) -> None:
        token = await self._auth.get_token()
        resp = await self._http.post(
            f"{self._base}/agents/{self._agent_id}/sessions",
            headers=self._headers(token),
            json={
                "externalSessionKey": session_id,
                "instanceConfig": {"endpoint": self._base},
                "capabilities": {"voice": True},
            },
        )
        resp.raise_for_status()
        self._sessions[session_id] = resp.json()["sessionId"]

    async def stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        session_id: str,
        turn_id: str,
        generation: int,
    ) -> AsyncGenerator[ConversationEvent, None]:
        af_session_id = self._sessions.get(session_id)
        if not af_session_id:
            raise RuntimeError(f"No Agentforce Voice session for {session_id}")

        token = await self._auth.get_token()

        async def audio_body():
            async for chunk in audio_chunks:
                yield chunk

        async with self._http.stream(
            "POST",
            f"{self._base}/sessions/{af_session_id}/voice/stream",
            headers={
                **self._headers(token),
                "Accept": "text/event-stream",
                "Content-Type": "audio/l16; rate=16000; channels=1",
                "X-Turn-Id": turn_id,
            },
            content=audio_body(),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                event = self._parse_sse_line(line, turn_id)
                if event:
                    yield event

    async def send_text(
        self,
        text: str,
        session_id: str,
        turn_id: str,
    ) -> AsyncGenerator[ConversationEvent, None]:
        af_session_id = self._sessions.get(session_id)
        if not af_session_id:
            raise RuntimeError(f"No Agentforce Voice session for {session_id}")

        token = await self._auth.get_token()

        async with self._http.stream(
            "POST",
            f"{self._base}/sessions/{af_session_id}/messages",
            headers={**self._headers(token), "Accept": "text/event-stream"},
            json={
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                "messageId": uuid.uuid4().hex,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                event = self._parse_sse_line(line, turn_id)
                if event:
                    yield event

    async def cancel(self, session_id: str, generation: int) -> None:
        pass

    async def end_session(self, session_id: str) -> None:
        af_session_id = self._sessions.pop(session_id, None)
        if not af_session_id:
            return
        token = await self._auth.get_token()
        await self._http.delete(
            f"{self._base}/sessions/{af_session_id}",
            headers=self._headers(token),
        )

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _parse_sse_line(self, line: str, turn_id: str) -> ConversationEvent | None:
        if not line.startswith("data:"):
            return None
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None

        event_type_str = payload.get("type", "")

        if event_type_str == "transcript.partial":
            return ConversationEvent(
                type=ConversationEventType.TRANSCRIPT_PARTIAL,
                text=payload.get("text", ""),
                turn_id=turn_id,
            )
        if event_type_str == "transcript.final":
            return ConversationEvent(
                type=ConversationEventType.TRANSCRIPT_FINAL,
                text=payload.get("text", ""),
                is_final=True,
                turn_id=turn_id,
            )
        if event_type_str == "agent.thinking":
            return ConversationEvent(
                type=ConversationEventType.AGENT_THINKING,
                turn_id=turn_id,
            )
        if event_type_str in ("agent.text.delta", "agent.message"):
            is_final = payload.get("isCompleted", False)
            event = ConversationEvent(
                type=ConversationEventType.AGENT_TEXT_DELTA,
                text=payload.get("text", ""),
                is_final=is_final,
                turn_id=turn_id,
            )
            return event

        return None

    async def aclose(self) -> None:
        await self._http.aclose()
