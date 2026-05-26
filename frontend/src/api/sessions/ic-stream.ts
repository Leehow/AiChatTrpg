// IC chat stream — drives `run_trpg_turn` server-side. Distinct from the
// character-creation chat: result shape is `{ assistant, diff_summary }`
// instead of a CharacterDraftDTO. Markers (`[ROLL]`, `[SET_SCENE]`, …)
// arrive as their own `marker` events so the UI can render them inline.

import { getStoredToken } from "../http";
import { BASE } from "./base";

export interface IcTurnResult {
  assistant: string;
  diff_summary: {
    memory_updates: number;
    dice_consumed: number;
    scene_transitions: number;
    pc_updated?: boolean;
  };
  thinking_count: number;
  marker_count: number;
}

export interface IcStreamHandlers {
  onThinking?: (content: string) => void;
  onMetadata?: (metadata: Record<string, unknown>) => void;
  onContent?: (delta: string) => void;
  onMarker?: (marker: { kind: string; args: Record<string, unknown>; body: string }) => void;
}

export const streamIcTurnAPI = (
  id: string,
  body: {
    message: string;
    intent?: "resolve" | null;
    pending_check_id?: string | null;
    roll_result?: number | number[] | null;
  },
  handlers: IcStreamHandlers = {},
  signal?: AbortSignal
) =>
  streamIcEndpoint(
    `${BASE}/${encodeURIComponent(id)}/chat-stream`,
    body,
    handlers,
    signal
  );

async function streamIcEndpoint(
  path: string,
  body: unknown,
  handlers: IcStreamHandlers,
  signal?: AbortSignal
): Promise<IcTurnResult> {
  const { fetchEventSource } = await import("@microsoft/fetch-event-source");
  const headers: Record<string, string> = {};
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  return new Promise<IcTurnResult>((resolve, reject) => {
    let resolved = false;
    void fetchEventSource(path, {
      method: "POST",
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
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
        let event: Record<string, unknown>;
        try {
          event = JSON.parse(msg.data) as Record<string, unknown>;
        } catch {
          return;
        }
        const type = event.type;
        if (type === "thinking") {
          handlers.onThinking?.(String(event.content || ""));
        } else if (type === "metadata") {
          handlers.onMetadata?.((event.metadata as Record<string, unknown>) || {});
        } else if (type === "content") {
          handlers.onContent?.(String(event.content || event.delta || ""));
        } else if (type === "marker") {
          const m = event.marker as { kind?: string; args?: Record<string, unknown>; body?: string } | undefined;
          if (m) {
            handlers.onMarker?.({
              kind: String(m.kind || ""),
              args: m.args || {},
              body: String(m.body || ""),
            });
          }
        } else if (type === "done") {
          resolved = true;
          resolve(event.result as IcTurnResult);
        } else if (type === "error") {
          resolved = true;
          reject(new Error(String(event.content || event.message || "ic stream failed")));
        }
      },
      onerror(err) {
        if (!resolved) reject(err);
        throw err;
      },
      onclose() {
        if (!resolved) reject(new Error("stream closed without result"));
      },
    });
  });
}
