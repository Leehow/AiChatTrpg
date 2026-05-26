import { useCallback, useEffect, useRef, useState } from "react";
import { streamMessageTtsAPI, type MessageTtsEvent } from "../api/sessions";
import { getTtsSpeeds } from "../components/music/musicState";

interface QueuedSegment {
  url: string;
  kind: string; // "narrator" | "dialogue" | other → narrator speed
}

type TtsStatus = "idle" | "loading" | "streaming" | "playing" | "error";

interface UseMessageTtsOptions {
  sessionId?: string | null;
  messageId: string;
  text: string;
  enabled?: boolean;
}

let stopActivePlayback: (() => void) | null = null;

export function useMessageTts({
  sessionId,
  messageId,
  text,
  enabled = true,
}: UseMessageTtsOptions) {
  const [status, setStatus] = useState<TtsStatus>("idle");
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const queueRef = useRef<Map<number, QueuedSegment>>(new Map());
  const skippedRef = useRef<Set<number>>(new Set());
  const nextSegmentRef = useRef(1);
  const totalSegmentsRef = useRef(0);
  const playingRef = useRef(false);
  const streamDoneRef = useRef(false);
  const playNextRef = useRef<() => void>(() => {});

  const cleanupAudio = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.src = "";
      audio.onended = null;
      audio.onerror = null;
      audioRef.current = null;
    }
    playingRef.current = false;
  }, []);

  const resetRuntime = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    cleanupAudio();
    queueRef.current.clear();
    skippedRef.current.clear();
    nextSegmentRef.current = 1;
    totalSegmentsRef.current = 0;
    streamDoneRef.current = false;
  }, [cleanupAudio]);

  const stop = useCallback(() => {
    resetRuntime();
    setStatus("idle");
    setError("");
    if (stopActivePlayback === stop) {
      stopActivePlayback = null;
    }
  }, [resetRuntime]);

  const advanceSkipped = useCallback(() => {
    while (skippedRef.current.has(nextSegmentRef.current)) {
      skippedRef.current.delete(nextSegmentRef.current);
      nextSegmentRef.current += 1;
    }
  }, []);

  const maybeComplete = useCallback(() => {
    const total = totalSegmentsRef.current;
    if (
      streamDoneRef.current
      && !playingRef.current
      && total > 0
      && nextSegmentRef.current > total
    ) {
      setStatus("idle");
      if (stopActivePlayback === stop) {
        stopActivePlayback = null;
      }
    }
  }, [stop]);

  playNextRef.current = () => {
    if (playingRef.current) return;
    advanceSkipped();
    const next = nextSegmentRef.current;
    const seg = queueRef.current.get(next);
    if (!seg) {
      maybeComplete();
      return;
    }
    queueRef.current.delete(next);
    nextSegmentRef.current += 1;
    playingRef.current = true;
    const audio = new Audio(seg.url);
    audioRef.current = audio;
    audio.preload = "auto";
    // Apply per-segment playback rate. Read fresh on each segment so
    // changing the rate from the music player tab affects the next
    // segment without restarting the whole TTS stream.
    const speeds = getTtsSpeeds();
    audio.playbackRate = seg.kind === "dialogue" ? speeds.dialogue : speeds.narrator;
    audio.onended = () => {
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
      playingRef.current = false;
      playNextRef.current();
    };
    audio.onerror = () => {
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
      playingRef.current = false;
      setStatus("error");
      setError("Audio playback failed");
      playNextRef.current();
    };
    void audio.play()
      .then(() => setStatus("playing"))
      .catch((err: unknown) => {
        if (audioRef.current === audio) {
          audioRef.current = null;
        }
        playingRef.current = false;
        setStatus("error");
        setError(err instanceof Error ? err.message : "Audio playback failed");
      });
  };

  const handleSegment = useCallback((event: Extract<MessageTtsEvent, { type: "tts_segment" }>) => {
    const index = Number(event.segment || 0);
    const url = String(event.audio_url || "");
    if (!index || !url) return;
    queueRef.current.set(index, { url, kind: String(event.kind || "narrator") });
    setStatus((prev) => (prev === "playing" ? "playing" : "streaming"));
    playNextRef.current();
  }, []);

  const handleSegmentError = useCallback((event: Extract<MessageTtsEvent, { type: "segment_error" }>) => {
    const index = Number(event.segment || 0);
    if (index) {
      skippedRef.current.add(index);
    }
    if (event.fatal) {
      setError(String(event.message || "TTS segment failed"));
      setStatus("error");
    }
    playNextRef.current();
  }, []);

  const toggle = useCallback(() => {
    if (!enabled || !sessionId || !messageId || !text.trim()) return;
    if (status === "loading" || status === "streaming" || status === "playing") {
      stop();
      return;
    }

    stopActivePlayback?.();
    resetRuntime();
    setError("");
    setStatus("loading");
    stopActivePlayback = stop;

    const controller = new AbortController();
    abortRef.current = controller;
    void streamMessageTtsAPI(
      sessionId,
      messageId,
      { text },
      {
        onPlan: (event) => {
          totalSegmentsRef.current = Number(event.total || event.segments?.length || 0);
          setStatus("streaming");
        },
        onSegment: handleSegment,
        onSegmentError: handleSegmentError,
        onDone: (event) => {
          totalSegmentsRef.current = Number(event.total || totalSegmentsRef.current || 0);
          streamDoneRef.current = true;
          playNextRef.current();
          maybeComplete();
        },
      },
      controller.signal,
    ).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : "TTS stream failed");
      setStatus("error");
      if (stopActivePlayback === stop) {
        stopActivePlayback = null;
      }
    });
  }, [
    enabled,
    sessionId,
    messageId,
    text,
    status,
    stop,
    resetRuntime,
    handleSegment,
    handleSegmentError,
    maybeComplete,
  ]);

  useEffect(() => stop, [stop]);

  return {
    status,
    error,
    playing: status === "playing",
    busy: status === "loading" || status === "streaming" || status === "playing",
    toggle,
    stop,
  };
}
