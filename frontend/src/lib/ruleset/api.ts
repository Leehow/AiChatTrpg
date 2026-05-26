// HTTP client for the /api/rulesets endpoints. Auth/Authorization handling,
// error unwrap, and token storage all live in api/http.ts.

import { ApiError, apiFetch, getStoredToken } from "../../api/http";
import type { ParsedRuleset, V6RawArtifact } from "./types";
import { parseV6 } from "./parseV6";

const BASE = "/api/rulesets";

export interface RulesetSummaryDTO {
  id: string;
  owner_id: string;
  is_shared: boolean;
  book_id: string;
  book_title: string;
  world_mode: string;
  has_dice_ir: boolean;
  has_check_spec: boolean;
  has_character_ui: boolean;
  created_at: string;
  updated_at: string;
}

export interface RulesetDetailDTO extends RulesetSummaryDTO {
  parsed_v6: V6RawArtifact;
  dice_ir: ParsedRuleset["dice_ir"];
  check_spec: Record<string, unknown> | null;
  character_ui: Record<string, unknown> | null;
}

// Re-export ApiError so callers that imported it from here keep compiling.
export { ApiError } from "../../api/http";

export async function listRulesetsAPI(): Promise<RulesetSummaryDTO[]> {
  return apiFetch<RulesetSummaryDTO[]>(BASE);
}

export async function getRulesetAPI(id: string): Promise<RulesetDetailDTO> {
  return apiFetch<RulesetDetailDTO>(`${BASE}/${encodeURIComponent(id)}`);
}

export async function uploadRulesetAPI(
  artifact: V6RawArtifact
): Promise<RulesetDetailDTO> {
  return apiFetch<RulesetDetailDTO>(BASE, {
    method: "POST",
    json: { artifact },
  });
}

export async function uploadRulesetFileAPI(
  file: File,
  opts: { output_language?: string } = {}
): Promise<RulesetDetailDTO> {
  const form = new FormData();
  form.append("file", file);
  if (opts.output_language) form.append("output_language", opts.output_language);

  const headers: Record<string, string> = {};
  const token = getStoredToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}/file`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!res.ok) {
    throw new ApiError(await readError(res), res.status);
  }
  return (await res.json()) as RulesetDetailDTO;
}

export async function deleteRulesetAPI(id: string): Promise<void> {
  await apiFetch<unknown>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function setRulesetSharedAPI(
  id: string,
  isShared: boolean
): Promise<RulesetSummaryDTO> {
  return apiFetch<RulesetSummaryDTO>(
    `${BASE}/${encodeURIComponent(id)}/share`,
    {
      method: "POST",
      json: { is_shared: isShared },
    }
  );
}

// Cached on the ruleset row after first call; LLM-derived (e.g. "coc",
// "dnd"). Used to compose the room-name prefix `[coc]<module>`.
export async function getRulesetShortNameAPI(
  id: string
): Promise<{ short_name: string }> {
  return apiFetch<{ short_name: string }>(
    `${BASE}/${encodeURIComponent(id)}/short-name`
  );
}

export interface CompileOptions {
  model?: string;
  base_url?: string;
  api_key?: string;
  output_language?: string;
  save?: boolean;
}

export async function compileDiceIRAPI(
  id: string,
  opts: CompileOptions = {}
): Promise<{ ok: boolean; package: ParsedRuleset["dice_ir"] }> {
  return apiFetch<{ ok: boolean; package: ParsedRuleset["dice_ir"] }>(
    `${BASE}/${encodeURIComponent(id)}/dice-ir/compile`,
    {
      method: "POST",
      json: { save: true, ...opts },
    }
  );
}

export async function applyCheckSpecAPI(
  id: string,
  body: { procedure_id?: string; check_spec?: Record<string, unknown> } = {}
): Promise<RulesetDetailDTO> {
  return apiFetch<RulesetDetailDTO>(
    `${BASE}/${encodeURIComponent(id)}/dice-ir/apply`,
    {
      method: "POST",
      json: body,
    }
  );
}

export interface CompileCharacterUIOptions {
  model?: string;
  base_url?: string;
  api_key?: string;
  /** 'zh' | 'en' | a chatrpg-style language hint ('Chinese'/'English'); the
   *  backend normalises it. Controls section titles + field labels in the
   *  emitted schema; field VALUES come from the card data and are not
   *  affected. */
  output_language?: string;
  save?: boolean;
}

export async function compileCharacterUIAPI(
  id: string,
  opts: CompileCharacterUIOptions = {}
): Promise<{
  ok: boolean;
  ruleset_id: string;
  artifact_saved: boolean;
  package: Record<string, unknown>;
  output_language?: string | null;
}> {
  return apiFetch(
    `${BASE}/${encodeURIComponent(id)}/character-ui/compile`,
    {
      method: "POST",
      json: { save: true, ...opts },
    }
  );
}

// Adapter: backend DTO → ParsedRuleset (the shape consumed by the UI). We
// re-run the local parser on the stored raw artifact rather than mapping
// section-by-section, so any future parser improvements (e.g. a new
// section) automatically apply to existing rulesets without a re-upload.
export function dtoToParsed(dto: RulesetDetailDTO): ParsedRuleset {
  const parsed = parseV6(dto.parsed_v6);
  // dice_ir from the dedicated column overrides whatever was embedded in
  // parsed_v6, since the column is what gets updated by the compile endpoint.
  return {
    ...parsed,
    dice_ir: dto.dice_ir ?? parsed.dice_ir,
    check_spec: dto.check_spec ?? null,
    character_ui: dto.character_ui ?? null,
  };
}

export interface SavedListEntry {
  id: string;
  owner_id: string;
  is_shared: boolean;
  saved_at: string;
  meta: ParsedRuleset["meta"];
}

export function dtoToSavedEntry(dto: RulesetSummaryDTO): SavedListEntry {
  return {
    id: dto.id,
    owner_id: dto.owner_id,
    is_shared: dto.is_shared,
    saved_at: dto.updated_at,
    meta: {
      book_id: dto.book_id,
      book_title: dto.book_title,
      world_mode: dto.world_mode,
    },
  };
}

async function readError(res: Response): Promise<string> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      detail = String((body as { detail: unknown }).detail);
    }
  } catch {
    // ignore
  }
  return detail;
}
