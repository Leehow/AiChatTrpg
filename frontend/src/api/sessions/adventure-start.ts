// Adventure-start options + the POST that actually kicks off play.
// Returns SessionDetailDTO with the session marked as started.

import { apiFetch } from "../http";
import { BASE } from "./base";
import type { SessionDetailDTO } from "./core";

export interface AdventureStartUnitDTO {
  index: number;
  unit_id?: string | null;
  title: string;
  kind: string;
  summary: string;
  line_start: number;
  line_end: number;
  section_indexes: number[];
}

export interface AdventureStartOptionsDTO {
  has_module: boolean;
  module_id?: string | null;
  module_title: string;
  semantic_status: string;
  semantic_error: string;
  anchor_type: string;
  progression: string;
  selection_rule: string;
  needs_selection: boolean;
  units: AdventureStartUnitDTO[];
}

export interface AdventureStartBody {
  module_id?: string | null;
  unit_index?: number | null;
  unit_id?: string | null;
}

export const getAdventureStartOptionsAPI = (id: string) =>
  apiFetch<AdventureStartOptionsDTO>(
    `${BASE}/${encodeURIComponent(id)}/adventure-start-options`,
  );

export const startAdventureAPI = (id: string, body: AdventureStartBody) =>
  apiFetch<SessionDetailDTO>(
    `${BASE}/${encodeURIComponent(id)}/adventure-start`,
    { method: "POST", json: body },
  );
