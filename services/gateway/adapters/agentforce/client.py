import json
import uuid
from dataclasses import dataclass
from typing import AsyncGenerator

import httpx

from .auth import SalesforceAuth


@dataclass
class AgentTextEvent:
    text: str
    is_final: bool = False


class AgentforceClient:
    """
    Thin async client for the Salesforce Agentforce Agent API.
    Handles session lifecycle and SSE streaming.
    """

    def __init__(self, auth: SalesforceAuth, instance_url: str, agent_id: str, api_version: str = "v1"):
        self._auth = auth
        self._base = f"{instance_url.rstrip('/')}/einstein/ai-agent/v1"
        self._agent_id = agent_id
        self._http = httpx.AsyncClient(timeout=60)
        # Maps app session_id → Agentforce session_id
        self._sessions: dict[str, str] = {}

    async def start_session(self, session_id: str) -> None:
        token = await self._auth.get_token()
        resp = await self._http.post(
            f"{self._base}/agents/{self._agent_id}/sessions",
            headers=self._headers(token),
            json={
                "externalSessionKey": session_id,
                "instanceConfig": {"endpoint": self._base},
            },
        )
        resp.raise_for_status()
        af_session_id = resp.json()["sessionId"]
        self._sessions[session_id] = af_session_id

    async def send_message(
        self,
        session_id: str,
        text: str,
    ) -> AsyncGenerator[AgentTextEvent, None]:
        af_session_id = self._sessions.get(session_id)
        if not af_session_id:
            raise RuntimeError(f"No Agentforce session for {session_id}")

        token = await self._auth.get_token()
        message_id = uuid.uuid4().hex

        async with self._http.stream(
            "POST",
            f"{self._base}/sessions/{af_session_id}/messages",
            headers={**self._headers(token), "Accept": "text/event-stream"},
            json={
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                "messageId": message_id,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                event = self._parse_sse_line(line)
                if event:
                    yield event

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

    def _parse_sse_line(self, line: str) -> AgentTextEvent | None:
        if not line.startswith("data:"):
            return None
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None

        # Extract user-facing text from Agentforce SSE envelope
        for msg in payload.get("messages", []):
            if msg.get("role") == "assistant":
                for part in msg.get("content", []):
                    if part.get("type") == "text":
                        return AgentTextEvent(
                            text=part["text"],
                            is_final=payload.get("isCompleted", False),
                        )
        return None

    async def aclose(self) -> None:
        await self._http.aclose()
