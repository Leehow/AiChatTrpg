// Ruleset draft endpoints -- see backend/routes/ruleset_drafts.py.

import { apiFetch, getStoredToken } from "./http";

export interface DraftSummaryDTO {
  id: string;
  owner_id: string;
  title: string;
  base_ruleset_id: string | null;
  target_ruleset_id: string | null;
  needs_dice_compile: boolean;
  needs_character_ui_compile: boolean;
  // Design-state-first authoring phase (P0.1). Small enough to ship in
  // list views; the heavier `design_state` / `validation_report` blobs
  // are exposed on DraftDetailDTO instead.
  design_phase: string;
  created_at: string;
  updated_at: string;
}

export interface DraftMessageDTO {
  id: string;
  seq: number;
  role: "user" | "assistant" | "tool";
  content: Record<string, unknown>;
  created_at: string;
}

export interface DraftEditDTO {
  id: string;
  message_id: string | null;
  ops: Array<Record<string, unknown>>;
  diff: Array<Record<string, unknown>>;
  undone: boolean;
  created_at: string;
}

export interface DraftDetailDTO extends DraftSummaryDTO {
  parsed_v6: Record<string, unknown>;
  // Design-state-first authoring artifact + latest validator output.
  // Empty defaults keep legacy drafts loadable.
  design_state: Record<string, unknown>;
  validation_report: Record<string, unknown>;
  messages: DraftMessageDTO[];
  edits: DraftEditDTO[];
}

export interface CreateDraftBody {
  base_ruleset_id?: string | null;
  target_ruleset_id?: string | null;
  title?: string | null;
}

export interface ApplyPatchBody {
  ops: Array<Record<string, unknown>>;
}

export interface ApplyPatchResponseDTO {
  edit_id: string;
  diff: Array<Record<string, unknown>>;
  needs_dice_compile: boolean;
  needs_character_ui_compile: boolean;
  parsed_v6_after: Record<string, unknown>;
}

export interface UndoEditResponseDTO {
  new_edit_id: string;
  parsed_v6_after: Record<string, unknown>;
}

export interface PromoteBody {
  mode: "new" | "target";
  new_title?: string | null;
}

export interface PromoteResponseDTO {
  ruleset_id: string;
  mode: "new" | "target";
}

export interface RecompileResponseDTO {
  ok: boolean;
  parsed_v6_after: Record<string, unknown>;
}

export interface CompileDesignResponseDTO {
  status: "success" | "blocked";
  edit_id: string | null;
  parsed_v6_after: Record<string, unknown>;
  validation_report: Record<string, unknown>;
  sections_emitted: string[];
  ready_blockers: string[];
  needs_dice_compile: boolean;
  needs_character_ui_compile: boolean;
  design_phase: string;
  error: string | null;
}

const BASE = "/api/ruleset-drafts";

export const listDraftsAPI = () => apiFetch<DraftSummaryDTO[]>(BASE);

export const createDraftAPI = (body: CreateDraftBody) =>
  apiFetch<DraftDetailDTO>(BASE, { method: "POST", json: body });

export const getDraftAPI = (id: string) =>
  apiFetch<DraftDetailDTO>(`${BASE}/${encodeURIComponent(id)}`);

export const listDraftMessagesAPI = (
  id: string,
  after_seq = 0,
  kind: "main" | "dice" = "main",
) =>
  apiFetch<DraftMessageDTO[]>(
    `${BASE}/${encodeURIComponent(id)}/messages` +
      `?after_seq=${after_seq}&kind=${kind}`,
  );

export const deleteDraftAPI = (id: string) =>
  apiFetch<{ ok: boolean }>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const applyDraftPatchAPI = (id: string, body: ApplyPatchBody) =>
  apiFetch<ApplyPatchResponseDTO>(
    `${BASE}/${encodeURIComponent(id)}/apply`,
    { method: "POST", json: body },
  );

export const undoDraftEditAPI = (draftId: string, editId: string) =>
  apiFetch<UndoEditResponseDTO>(
    `${BASE}/${encodeURIComponent(draftId)}/edits/${encodeURIComponent(editId)}/undo`,
    { method: "POST" },
  );

export const promoteDraftAPI = (id: string, body: PromoteBody) =>
  apiFetch<PromoteResponseDTO>(
    `${BASE}/${encodeURIComponent(id)}/promote`,
    { method: "POST", json: body },
  );

export const recompileDraftDiceAPI = (id: string) =>
  apiFetch<RecompileResponseDTO>(
    `${BASE}/${encodeURIComponent(id)}/recompile/dice`,
    { method: "POST" },
  );

export const recompileDraftCharacterUIAPI = (id: string) =>
  apiFetch<RecompileResponseDTO>(
    `${BASE}/${encodeURIComponent(id)}/recompile/character-ui`,
    { method: "POST" },
  );

export const compileDraftDesignAPI = (id: string) =>
  apiFetch<CompileDesignResponseDTO>(
    `${BASE}/${encodeURIComponent(id)}/compile-design`,
    { method: "POST" },
  );


// ---------------------------------------------------------------------------
// Agent message stream (SSE)
// ---------------------------------------------------------------------------

export type AgentEvent =
  | { type: "user_message_saved"; message_id: string }
  | { type: "message_started"; message_id: string; role: "assistant" }
  | { type: "text_delta"; delta: string }
  | {
      type: "tool_call_started";
      call_id: string;
      tool_name: string;
      index: number;
    }
  | { type: "tool_call_delta"; call_id: string; args_delta: string }
  | {
      type: "tool_result";
      call_id: string;
      tool_name: string;
      result: Record<string, unknown>;
      edit_id?: string | null;
    }
  | {
      type: "edit_applied";
      edit_id: string;
      diff: Array<Record<string, unknown>>;
      parsed_v6_after: Record<string, unknown>;
      needs_dice_compile: boolean;
      needs_character_ui_compile: boolean;
    }
  | {
      // Emitted by P0.6 design-state writes (set_*, apply_blueprint, etc.).
      // Carries the new phase, a lightweight design summary, the edit id,
      // and the JSON-patch diff. `blueprint_id` and `sections_seeded` are
      // only present on apply_blueprint payloads.
      type: "design_state_changed";
      design_phase: string;
      design_summary: Record<string, unknown>;
      edit_id: string | null;
      diff: Array<Record<string, unknown>>;
      blueprint_id?: string;
      sections_seeded?: string[];
    }
  | {
      // Emitted by every design-state write tool and compile_design.
      // `validation_report` matches backend ValidationReport (blocking /
      // warnings / info / slots / can_compile / ready_blockers).
      type: "validation_report";
      validation_report: Record<string, unknown>;
      can_compile: boolean;
    }
  | {
      // Emitted by the main-agent dice bridge (`request_dice_compile`)
      // after a successful compile + apply. Mirrors the dice agent's
      // dice_state_changed so the frontend reloads the dice preview.
      type: "dice_state_changed";
    }
  | {
      // Additive progress event emitted by the main-agent dice bridge
      // alongside dice_state_changed. `source` is one of
      // "direct" | "codeact" | "fallback_compile_one" |
      // "fallback_codeact_failed". `fallback_reason` is populated for
      // the fallback sources.
      type: "dice_compile_progress";
      source: string;
      primitive_calls: number;
      iters: number;
      fallback_reason?: string | null;
    }
  | {
      type: "message_completed";
      message_id: string;
      text?: string;
      tool_calls?: Array<Record<string, unknown>>;
    }
  | {
      type: "turn_done";
      stop_reason: "end_turn" | "max_iters" | "error" | "length";
      error?: string;
    };

export interface DraftAgentHandlers {
  onEvent: (event: AgentEvent) => void;
  onError?: (err: Error) => void;
}

// ---- dice agent stream (separate endpoint, in-memory history) ----

// Same event set as the main agent. `dice_state_changed` flows over
// both streams (dice agent: from `design_dice_procedure`; main agent:
// from `request_dice_compile`).
export type DiceAgentEvent = AgentEvent;

export interface DiceAgentHandlers {
  onEvent: (event: DiceAgentEvent) => void;
  onError?: (err: Error) => void;
}

export async function streamDiceAgentMessage(
  draftId: string,
  text: string,
  history: Array<Record<string, unknown>>,
  handlers: DiceAgentHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const { fetchEventSource } = await import("@microsoft/fetch-event-source");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  return new Promise<void>((resolve, reject) => {
    let resolved = false;
    void fetchEventSource(
      `${BASE}/${encodeURIComponent(draftId)}/dice-agent/messages`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({ text, history }),
        signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) {
            let detail = `${res.status} ${res.statusText}`;
            try {
              const payload = await res.json();
              if (
                payload &&
                typeof payload === "object" &&
                "detail" in payload
              ) {
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
          let event: DiceAgentEvent;
          try {
            event = JSON.parse(msg.data) as DiceAgentEvent;
          } catch {
            return;
          }
          handlers.onEvent(event);
          if (event.type === "turn_done") {
            resolved = true;
            if (event.stop_reason === "error" && event.error) {
              reject(new Error(event.error));
              return;
            }
            resolve();
          }
        },
        onerror(err) {
          if (!resolved) {
            handlers.onError?.(
              err instanceof Error ? err : new Error(String(err)),
            );
            reject(err);
          }
          throw err;
        },
        onclose() {
          if (!resolved) reject(new Error("Stream closed without turn_done"));
        },
      },
    );
  });
}


export async function streamDraftAgentMessage(
  draftId: string,
  text: string,
  handlers: DraftAgentHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const { fetchEventSource } = await import("@microsoft/fetch-event-source");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  return new Promise<void>((resolve, reject) => {
    let resolved = false;
    void fetchEventSource(
      `${BASE}/${encodeURIComponent(draftId)}/messages`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({ text }),
        signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) {
            let detail = `${res.status} ${res.statusText}`;
            try {
              const payload = await res.json();
              if (
                payload &&
                typeof payload === "object" &&
                "detail" in payload
              ) {
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
          let event: AgentEvent;
          try {
            event = JSON.parse(msg.data) as AgentEvent;
          } catch {
            return;
          }
          handlers.onEvent(event);
          if (event.type === "turn_done") {
            resolved = true;
            if (event.stop_reason === "error" && event.error) {
              reject(new Error(event.error));
              return;
            }
            resolve();
          }
        },
        onerror(err) {
          if (!resolved) {
            handlers.onError?.(
              err instanceof Error ? err : new Error(String(err)),
            );
            reject(err);
          }
          throw err;
        },
        onclose() {
          if (!resolved) reject(new Error("Stream closed without turn_done"));
        },
      },
    );
  });
}
