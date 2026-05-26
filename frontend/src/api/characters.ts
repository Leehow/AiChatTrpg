import { apiFetch } from "./http";

export interface CharacterPoolItemDTO {
  id: string;
  ruleset_id: string;
  ruleset_title: string;
  ruleset_short_name: string | null;
  name: string;
  source: string;
  source_session_id: string | null;
  character: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CharacterPoolCreateBody {
  ruleset_id: string;
  character: Record<string, unknown>;
  source?: string;
  source_session_id?: string | null;
}

const BASE = "/api/characters";

export const listCharacterPoolAPI = (opts: { ruleset_id?: string | null } = {}) => {
  const params = new URLSearchParams();
  if (opts.ruleset_id) params.set("ruleset_id", opts.ruleset_id);
  const qs = params.toString();
  return apiFetch<CharacterPoolItemDTO[]>(`${BASE}${qs ? `?${qs}` : ""}`);
};

export const createCharacterPoolAPI = (body: CharacterPoolCreateBody) =>
  apiFetch<CharacterPoolItemDTO>(BASE, { method: "POST", json: body });
