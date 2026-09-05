import time
import httpx


class SalesforceAuth:
    """Fetches and caches Salesforce OAuth access tokens server-side."""

    def __init__(self, login_url: str, client_id: str, client_secret: str):
        self._login_url = login_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._expires_at: float = 0

    async def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        await self._refresh()
        return self._token  # type: ignore[return-value]

    async def _refresh(self) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._login_url}/services/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            # Salesforce tokens typically live 2 hours
            self._expires_at = time.time() + int(data.get("expires_in", 7200))
