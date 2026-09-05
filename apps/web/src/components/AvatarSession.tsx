"use client";

import { useEffect, useRef, useState } from "react";
import { useAvatarSession } from "@/hooks/useAvatarSession";

const STATE_LABELS: Record<string, string> = {
  idle: "Start a conversation",
  connecting: "Connecting...",
  listening: "Listening",
  thinking: "Thinking...",
  speaking: "Speaking",
  interrupted: "Interrupted",
  error: "Error",
};

const STATE_COLORS: Record<string, string> = {
  idle: "#555",
  connecting: "#f59e0b",
  listening: "#22c55e",
  thinking: "#3b82f6",
  speaking: "#a855f7",
  interrupted: "#f97316",
  error: "#ef4444",
};

export default function AvatarSession() {
  const {
    state,
    userTranscript,
    agentTranscript,
    audioLevel,
    error,
    videoTrack,
    connect,
    interrupt,
    disconnect,
    setMicEnabled,
  } = useAvatarSession();

  const videoRef = useRef<HTMLVideoElement>(null);
  const [micMuted, setMicMuted] = useState(false);

  // Attach LiveKit video track to <video> element
  useEffect(() => {
    if (!videoRef.current) return;
    if (videoTrack) {
      videoTrack.attach(videoRef.current);
      return () => { videoTrack.detach(videoRef.current!); };
    }
  }, [videoTrack]);

  const toggleMic = () => {
    const next = !micMuted;
    setMicMuted(next);
    setMicEnabled(!next);
  };

  const isActive = state !== "idle" && state !== "error";
  const color = STATE_COLORS[state] ?? "#555";

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "1.25rem", width: "100%", maxWidth: 560 }}>

      {/* Avatar video */}
      <div style={{ position: "relative", width: 320, height: 320, borderRadius: 16, background: "#111", border: `2px solid ${color}`, overflow: "hidden", transition: "border-color 0.3s" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{ width: "100%", height: "100%", objectFit: "cover", display: videoTrack ? "block" : "none" }}
        />
        {!videoTrack && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "5rem" }}>
            🤖
          </div>
        )}
      </div>

      {/* State + audio level */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <span style={{ width: 10, height: 10, borderRadius: "50%", background: color, display: "inline-block" }} />
        <span style={{ color, fontSize: "0.9rem" }}>{STATE_LABELS[state] ?? state}</span>
        {state === "listening" && (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 16 }}>
            {[0.3, 0.6, 1.0, 0.6, 0.3].map((scale, i) => (
              <div key={i} style={{
                width: 3,
                height: `${Math.min(100, audioLevel * 600 * scale)}%`,
                minHeight: 2,
                background: "#22c55e",
                borderRadius: 2,
                transition: "height 0.05s",
              }} />
            ))}
          </div>
        )}
      </div>

      {/* Transcripts */}
      {userTranscript && (
        <div style={{ background: "#1a1a1a", borderRadius: 8, padding: "0.75rem 1rem", width: "100%", fontSize: "0.85rem", color: "#aaa" }}>
          <span style={{ color: "#444", fontSize: "0.7rem", display: "block", marginBottom: 4 }}>You</span>
          {userTranscript}
        </div>
      )}
      {agentTranscript && (
        <div style={{ background: "#0f1629", borderRadius: 8, padding: "0.75rem 1rem", width: "100%", fontSize: "0.85rem" }}>
          <span style={{ color: "#444", fontSize: "0.7rem", display: "block", marginBottom: 4 }}>Agent</span>
          {agentTranscript}
        </div>
      )}

      {error && <div style={{ color: "#ef4444", fontSize: "0.85rem" }}>{error}</div>}

      {/* Controls */}
      <div style={{ display: "flex", gap: "0.75rem" }}>
        {!isActive ? (
          <button onClick={connect} style={btn("#22c55e")}>Start</button>
        ) : (
          <>
            <button onClick={toggleMic} style={btn(micMuted ? "#f97316" : "#22c55e")}>
              {micMuted ? "Unmute" : "Mute"}
            </button>
            {state === "speaking" && (
              <button onClick={interrupt} style={btn("#f97316")}>Interrupt</button>
            )}
            <button onClick={disconnect} style={btn("#ef4444")}>End</button>
          </>
        )}
      </div>

      <p style={{ fontSize: "0.7rem", color: "#333" }}>AI-generated avatar · Not a real person</p>
    </div>
  );
}

function btn(color: string) {
  return {
    padding: "0.55rem 1.4rem",
    borderRadius: 8,
    border: `1px solid ${color}`,
    background: "transparent",
    color,
    cursor: "pointer",
    fontSize: "0.875rem",
  } as const;
}
