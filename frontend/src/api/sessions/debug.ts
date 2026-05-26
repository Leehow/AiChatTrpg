// Read-only inspection endpoints: context snapshot, check logs, turn traces,
// public memory view, NPC runtime debug. Backed by
// backend/routes/session_debug_routes.py.

import { apiFetch } from "../http";
import { BASE } from "./base";

export interface ContextSnapshotBP1DTO {
  ruleset_title: string;
  ruleset_world_mode: string;
  core_rules: string;
  sheet_template: string;
  sheet_guide: string;
  scene_guide: string;
  module_title: string | null;
  module_text: string;
}

export interface ContextSnapshotBP2DTO {
  module_state?: Record<string, unknown>;
  scenes: Array<Record<string, unknown>>;
  npcs: Array<Record<string, unknown>>;
  plot_threads: Array<Record<string, unknown>>;
  world_facts: Array<Record<string, unknown>>;
  narrative_summary: string;
}

export interface ContextSnapshotBP3DTO {
  chat: Array<Record<string, unknown>>;
  pc: Record<string, unknown> | null;
  draft_card: Record<string, unknown> | null;
  ready: boolean;
  dice_history: Array<Record<string, unknown>>;
}

export interface ContextSnapshotDTO {
  bp1: ContextSnapshotBP1DTO;
  bp2: ContextSnapshotBP2DTO;
  bp3: ContextSnapshotBP3DTO;
}

export async function fetchContextSnapshot(
  sessionId: string,
): Promise<ContextSnapshotDTO> {
  return apiFetch<ContextSnapshotDTO>(
    `${BASE}/${encodeURIComponent(sessionId)}/context-snapshot`,
  );
}

export interface CheckLogDTO {
  id: string;
  session_id: string;
  message_id: string | null;
  actor_id: string;
  procedure_id: string;
  engine: string;
  skill: string;
  seed: string;
  source: string;
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  roll_trace: Record<string, unknown>;
  trace: Record<string, unknown>;
  warnings: string[];
  created_at: string;
}

export interface CheckLogListDTO {
  items: CheckLogDTO[];
  total: number;
  has_more: boolean;
}

export interface TurnTraceDTO {
  id: string;
  turn_id: string;
  session_id: string;
  campaign_id: string;
  player_input: string;
  context_cache_key: string;
  context_prefix_hash: string;
  retrieved_context_block_ids: string[];
  visibility_signature: string;
  model_raw_output: Record<string, unknown>;
  parsed_contract_summary: Record<string, unknown>;
  state_change_ids: string[];
  memory_proposal_count: number;
  committed_memory_ids: string[];
  rejected_memory_count: number;
  audit_warnings: Array<Record<string, unknown>>;
  cache_metrics: Record<string, unknown>;
  created_at: string;
}

export interface TurnTraceListDTO {
  items: TurnTraceDTO[];
  total: number;
  has_more: boolean;
}

export interface PublicRelationshipDTO {
  npc_id: string;
  summary: string;
  confidence: number;
  known_reasons: string[];
}

export interface PublicClueDTO {
  clue_id: string | null;
  title: string;
  status: string;
  points_to: string[];
  summary: string;
}

export interface PublicMemoryViewDTO {
  relationships: PublicRelationshipDTO[];
  clues: PublicClueDTO[];
  open_threads: string[];
  remembered_facts: string[];
}

export interface NpcRuntimeDebugDTO {
  counts: Record<string, number>;
  planner_latest: Record<string, unknown>;
  planner_runs: Array<Record<string, unknown>>;
  action_board: Record<string, unknown>;
  action_cards: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  sample_memories: Array<Record<string, unknown>>;
}

export const listCheckLogsAPI = (id: string, limit = 50) =>
  apiFetch<CheckLogListDTO>(
    `${BASE}/${encodeURIComponent(id)}/check-logs?limit=${encodeURIComponent(String(limit))}`,
  );

export const listTurnTracesAPI = (id: string, limit = 25) =>
  apiFetch<TurnTraceListDTO>(
    `${BASE}/${encodeURIComponent(id)}/turn-traces?limit=${encodeURIComponent(String(limit))}`,
  );

export const getPublicMemoryViewAPI = (id: string) =>
  apiFetch<PublicMemoryViewDTO>(
    `${BASE}/${encodeURIComponent(id)}/memory-public-view`,
  );

export const getNpcRuntimeDebugAPI = (id: string) =>
  apiFetch<NpcRuntimeDebugDTO>(
    `${BASE}/${encodeURIComponent(id)}/npc-runtime-debug`,
  );
