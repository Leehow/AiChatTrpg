// Session CRUD + message list/create + per-message postprocess steps.
// See backend/routes/sessions.py and backend/routes/session_flow_routes.py.

import { apiFetch } from "../http";
import { BASE } from "./base";

export interface SetupStateDTO {
  step: number;
  ruleset_id: string | null;
  module_id: string | null;
  module_title: string | null;
  start_unit_index?: number | null;
  start_unit_id?: string | null;
  start_unit_title?: string | null;
  completed: boolean;
}

export interface SessionSummaryDTO {
  id: string;
  title: string;
  // Null while the user is still in the setup wizard for a draft.
  ruleset_id: string | null;
  ruleset_title: string;
  ruleset_short_name: string | null;
  archived: boolean;
  title_auto: boolean;
  setup_state: SetupStateDTO;
  last_active_at: string;
  created_at: string;
  updated_at: string;
}

export interface SessionDetailDTO extends SessionSummaryDTO {
  character: Record<string, unknown>;
  module_state: Record<string, unknown>;
  memory_state: Record<string, unknown>;
  narrative_summary: string;
  last_summarized_msg_count: number;
  dice_history: Array<Record<string, unknown>>;
  narrative_style: string;
  difficulty_style: string;
}

export interface SessionCreateBody {
  // Optional: omit to create a blank draft that the setup wizard fills.
  ruleset_id?: string;
  title?: string;
  character?: Record<string, unknown>;
}

export interface SessionUpdateBody {
  title?: string;
  title_auto?: boolean;
  ruleset_id?: string | null;
  setup_state?: Partial<SetupStateDTO>;
  archived?: boolean;
  character?: Record<string, unknown>;
  module_state?: Record<string, unknown>;
  memory_state?: Record<string, unknown>;
  narrative_summary?: string;
  last_summarized_msg_count?: number;
  dice_history?: Array<Record<string, unknown>>;
  narrative_style?: string;
  difficulty_style?: string;
}

export interface MessageDTO {
  id: string;
  session_id: string;
  role: "user" | "gm" | "system" | "dice";
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface MessageListDTO {
  items: MessageDTO[];
  total: number;
  has_more: boolean;
}

export interface MessageCreateBody {
  role: MessageDTO["role"];
  content: string;
  metadata?: Record<string, unknown>;
}

export const listSessionsAPI = () =>
  apiFetch<SessionSummaryDTO[]>(BASE);

export const createSessionAPI = (body: SessionCreateBody) =>
  apiFetch<SessionDetailDTO>(BASE, { method: "POST", json: body });

export const getSessionAPI = (id: string) =>
  apiFetch<SessionDetailDTO>(`${BASE}/${encodeURIComponent(id)}`);

export const updateSessionAPI = (id: string, body: SessionUpdateBody) =>
  apiFetch<SessionDetailDTO>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PUT",
    json: body,
  });

export const deleteSessionAPI = (id: string) =>
  apiFetch<{ ok: boolean }>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const listMessagesAPI = (
  id: string,
  opts: { limit?: number; before_id?: string } = {}
) => {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.before_id) params.set("before_id", opts.before_id);
  const qs = params.toString();
  return apiFetch<MessageListDTO>(
    `${BASE}/${encodeURIComponent(id)}/messages${qs ? `?${qs}` : ""}`
  );
};

export const createMessageAPI = (id: string, body: MessageCreateBody) =>
  apiFetch<MessageDTO>(`${BASE}/${encodeURIComponent(id)}/messages`, {
    method: "POST",
    json: body,
  });

// Per-GM-message post-processing timeline. Backend records step events
// (`action_board_warm`, `runtime_state_persist`, `routine_events`,
// `npc_text_sync`, `intent_planner`, `portrait_generation`,
// `phase3_complete`) into the message's metadata as the background
// pipeline runs. The PostprocessSteps component polls this until
// `done=true`.

export interface PostprocessStepDTO {
  name: string;
  status: string; // "running" | "done"
  duration_ms: number;
  detail: string;
  ts: string;
}

export interface PostprocessStepsResponseDTO {
  steps: PostprocessStepDTO[];
  done: boolean;
}

export const getMessagePostprocessStepsAPI = (
  sessionId: string,
  messageId: string,
) =>
  apiFetch<PostprocessStepsResponseDTO>(
    `${BASE}/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}/postprocess-steps`,
  );
