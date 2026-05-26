// Per-message TTS stream — segments arrive as `tts_segment` events with
// preassembled audio_url chunks; `done` carries the merged audio_url (or
// the list of failed segment indices when partial). `segment_error` is
// per-segment (non-fatal unless `fatal=true`); `error` aborts the stream.

import { getStoredToken } from "../http";
import { BASE } from "./base";

export type MessageTtsEvent =
  | {
      type: "tts_plan";
      message_id?: string;
      total?: number;
      segments?: Array<Record<string, unknown>>;
    }
  | {
      type: "tts_segment";
      segment: number;
      speaker?: string;
      kind?: string;
      voice?: string;
      provider?: string;
      model?: string;
      audio_url?: string;
      mime_type?: string;
      format?: string;
    }
  | {
      type: "segment_error";
      segment?: number;
      speaker?: string;
      message?: string;
      fatal?: boolean;
    }
  | {
      type: "done";
      message_id?: string;
      total?: number;
      audio_url?: string;
      audio_expires_at?: string | null;
      failed_segments?: number[];
    }
  | { type: "error"; message?: string; content?: string };

export interface MessageTtsStreamHandlers {
  onPlan?: (event: Extract<MessageTtsEvent, { type: "tts_plan" }>) => void;
  onSegment?: (event: Extract<MessageTtsEvent, { type: "tts_segment" }>) => void;
  onSegmentError?: (event: Extract<MessageTtsEvent, { type: "segment_error" }>) => void;
  onDone?: (event: Extract<MessageTtsEvent, { type: "done" }>) => void;
}

export const streamMessageTtsAPI = (
  sessionId: string,
  messageId: string,
  body: { text?: string | null } = {},
  handlers: MessageTtsStreamHandlers = {},
  signal?: AbortSignal,
) =>
  streamMessageTtsEndpoint(
    `${BASE}/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}/tts/stream`,
    body,
    handlers,
    signal,
  );

async function streamMessageTtsEndpoint(
  path: string,
  body: unknown,
  handlers: MessageTtsStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const { fetchEventSource } = await import("@microsoft/fetch-event-source");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  return new Promise<void>((resolve, reject) => {
    let resolved = false;
    void fetchEventSource(path, {
      method: "POST",
      headers,
      body: JSON.stringify(body ?? {}),
      signal,
      openWhenHidden: true,
      async onopen(res) {
        if (!res.ok) {
          let detail = `${res.status} ${res.statusText}`;
          try {
            const payload = await res.json();
            if (payload && typeof payload === "object" && "detail" in payload) {
              detail = String((payload as { detail: unknown }).detail);
            }
          } catch {
            // ignore
          }
          reject(new Error(detail));
          throw new Error(detail);
        }
      },
      onmessage(msg) {
        if (!msg.data) return;
        let event: MessageTtsEvent;
        try {
          event = JSON.parse(msg.data) as MessageTtsEvent;
        } catch {
          return;
        }
        if (event.type === "tts_plan") {
          handlers.onPlan?.(event);
        } else if (event.type === "tts_segment") {
          handlers.onSegment?.(event);
        } else if (event.type === "segment_error") {
          handlers.onSegmentError?.(event);
        } else if (event.type === "done") {
          handlers.onDone?.(event);
          resolved = true;
          resolve();
        } else if (event.type === "error") {
          resolved = true;
          reject(new Error(String(event.message || event.content || "TTS stream failed")));
        }
      },
      onerror(err) {
        if (!resolved) reject(err);
        throw err;
      },
      onclose() {
        if (!resolved) reject(new Error("TTS stream closed without completion"));
      },
    });
  });
}
