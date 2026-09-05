"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Room, RoomEvent, RemoteTrack, Track } from "livekit-client";
import { createSession, closeSession, type SessionBootstrap } from "@/lib/session";
import { MicrophoneCapture } from "@/lib/audio/microphone";
import { VoiceActivityDetector } from "@/lib/audio/vad";
import { PCMPlayer } from "@/lib/audio/pcm-player";

export type AvatarState =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

export interface AvatarSessionHook {
  state: AvatarState;
  userTranscript: string;
  agentTranscript: string;
  audioLevel: number;
  error: string | null;
  videoTrack: RemoteTrack | null;
  connect: () => Promise<void>;
  interrupt: () => void;
  disconnect: () => Promise<void>;
  setMicEnabled: (enabled: boolean) => void;
}

export function useAvatarSession(): AvatarSessionHook {
  const [state, setState] = useState<AvatarState>("idle");
  const [userTranscript, setUserTranscript] = useState("");
  const [agentTranscript, setAgentTranscript] = useState("");
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [videoTrack, setVideoTrack] = useState<RemoteTrack | null>(null);

  const sessionRef = useRef<SessionBootstrap | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const roomRef = useRef<Room | null>(null);
  const micRef = useRef<MicrophoneCapture | null>(null);
  const vadRef = useRef<VoiceActivityDetector | null>(null);
  const playerRef = useRef<PCMPlayer | null>(null);
  const generationRef = useRef(0);
  const micEnabledRef = useRef(true);

  // ── WebSocket send helper ────────────────────────────────────────────────
  const sendWS = useCallback((payload: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  // ── Connect ──────────────────────────────────────────────────────────────
  const connect = useCallback(async () => {
    try {
      setState("connecting");
      setError(null);

      const session = await createSession();
      sessionRef.current = session;
      generationRef.current = 0;

      // ── LiveKit WebRTC room ──────────────────────────────────────────────
      const room = new Room();
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Video) setVideoTrack(track);
      });
      room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Video) setVideoTrack(null);
      });

      await room.connect(session.livekit_url, session.livekit_token);

      // ── WebSocket control channel ────────────────────────────────────────
      const ws = new WebSocket(session.websocket_url);
      wsRef.current = ws;

      playerRef.current = new PCMPlayer(24000, 1);

      ws.onmessage = (event) => {
        // Binary frame = PCM audio from TTS
        if (event.data instanceof ArrayBuffer) {
          playerRef.current?.feed(event.data);
          return;
        }
        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then(buf => playerRef.current?.feed(buf));
          return;
        }
        const msg = JSON.parse(event.data);
        console.debug("[ws]", msg.type, msg);
        switch (msg.type) {
          case "session.ready":
            setState("listening");
            // Start mic only now — prevents VAD firing during connecting phase
            _startMic().catch(err => {
              console.error("Mic start failed:", err);
              setError("Microphone unavailable: " + err.message);
              setState("error");
            });
            break;
          case "transcript.partial":
            setUserTranscript(msg.text ?? "");
            break;
          case "transcript.final":
            setUserTranscript(msg.text ?? "");
            setState("thinking");
            break;
          case "agent.thinking":
            setState("thinking");
            break;
          case "avatar.speaking":
            setState("speaking");
            setAgentTranscript(msg.text ?? "");
            break;
          case "avatar.turn.complete":
            setState("listening");
            break;
          case "turn.cancelled":
            generationRef.current = msg.generation ?? generationRef.current;
            setState("listening");
            break;
          case "session.error":
            setError(msg.message ?? "Unknown error");
            setState("error");
            break;
        }
      };

      ws.onerror = () => {
        setError("WebSocket connection error");
        setState("error");
      };

    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to connect");
      setState("error");
    }
  }, []);

  // ── Start microphone + VAD ───────────────────────────────────────────────
  const _startMic = useCallback(async () => {
    const mic = new MicrophoneCapture();
    const vad = new VoiceActivityDetector({ threshold: 0.02, speechFrames: 5, silenceFrames: 40 });
    micRef.current = mic;
    vadRef.current = vad;

    vad.onSpeechStart = () => {
      if (!micEnabledRef.current) return;
      generationRef.current += 1;
      console.debug("[vad] speech.started generation:", generationRef.current);
      sendWS({
        type: "speech.started",
        session_id: sessionRef.current?.session_id,
        turn_id: `turn_${Date.now()}`,
        generation: generationRef.current,
      });
    };

    vad.onSpeechEnd = () => {
      if (!micEnabledRef.current) return;
      console.debug("[vad] speech.ended");
      sendWS({
        type: "speech.ended",
        session_id: sessionRef.current?.session_id,
        generation: generationRef.current,
      });
    };

    vad.onAudioLevel = (level) => setAudioLevel(level);

    mic.onFrame = (pcm: ArrayBuffer) => {
      if (!micEnabledRef.current) return;
      vad.processFrame(pcm);
      // Send raw PCM to gateway for STT
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(pcm);
      }
    };

    await mic.start();
  }, [sendWS]);

  // ── Interrupt ────────────────────────────────────────────────────────────
  const interrupt = useCallback(() => {
    playerRef.current?.stop();
    playerRef.current = new PCMPlayer(24000, 1);
    generationRef.current += 1;
    sendWS({
      type: "turn.interrupt",
      session_id: sessionRef.current?.session_id,
      generation: generationRef.current,
    });
    setState("interrupted");
  }, [sendWS]);

  // ── Mute / unmute ────────────────────────────────────────────────────────
  const setMicEnabled = useCallback((enabled: boolean) => {
    micEnabledRef.current = enabled;
    if (!enabled) {
      vadRef.current?.reset();
      sendWS({
        type: "speech.ended",
        session_id: sessionRef.current?.session_id,
        generation: generationRef.current,
      });
    }
  }, [sendWS]);

  // ── Disconnect ───────────────────────────────────────────────────────────
  const disconnect = useCallback(async () => {
    micRef.current?.stop();
    playerRef.current?.stop();
    wsRef.current?.close();
    await roomRef.current?.disconnect();
    if (sessionRef.current) {
      await closeSession(sessionRef.current.session_id);
    }
    micRef.current = null;
    wsRef.current = null;
    roomRef.current = null;
    sessionRef.current = null;
    setState("idle");
    setUserTranscript("");
    setAgentTranscript("");
    setAudioLevel(0);
    setVideoTrack(null);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      micRef.current?.stop();
      wsRef.current?.close();
      roomRef.current?.disconnect();
    };
  }, []);

  return {
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
  };
}
