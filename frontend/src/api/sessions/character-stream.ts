// SSE helper for character-creation streaming endpoints (start / chat /
// generate). The wire protocol is `thinking` → `metadata` → `content` deltas
// → `done` with a `CharacterDraftDTO` payload, or a terminal `error` event.

import { getStoredToken } from "../http";
import type {
  CharacterDraftDTO,
  CharacterStreamEvent,
  CharacterStreamHandlers,
} from "./character-types";

export async function streamCharacterEndpoint(
  path: string,
  body: unknown,
  handlers: CharacterStreamHandlers,
  signal?: AbortSignal
): Promise<CharacterDraftDTO> {
  const { fetchEventSource } = await import("@microsoft/fetch-event-source");
  const headers: Record<string, string> = {};
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  return new Promise<CharacterDraftDTO>((resolve, reject) => {
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
        let event: CharacterStreamEvent;
        try {
          event = JSON.parse(msg.data) as CharacterStreamEvent;
        } catch {
          return;
        }
        if (event.type === "thinking") {
          handlers.onThinking?.(event.content || "", {
            replaceLast: Boolean(event.replace_last),
          });
        } else if (event.type === "metadata") {
          handlers.onMetadata?.(event.metadata || {});
        } else if (event.type === "content") {
          handlers.onContent?.(event.content || event.delta || "");
        } else if (event.type === "done") {
          resolved = true;
          resolve(event.result);
        } else if (event.type === "error") {
          resolved = true;
          reject(new Error(event.content || event.message || "character stream failed"));
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
