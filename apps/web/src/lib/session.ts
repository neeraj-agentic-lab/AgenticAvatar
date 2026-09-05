const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL?.replace(/^ws/, "http") ?? "http://localhost:8000";

export interface SessionBootstrap {
  session_id: string;
  websocket_url: string;
  livekit_url: string;
  livekit_token: string;
  expires_at: string;
}

export async function createSession(avatarId = "default"): Promise<SessionBootstrap> {
  const res = await fetch(`${GATEWAY_URL}/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ avatar_id: avatarId, locale: "en-US" }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  return res.json();
}

export async function closeSession(sessionId: string): Promise<void> {
  await fetch(`${GATEWAY_URL}/v1/sessions/${sessionId}`, { method: "DELETE" });
}
