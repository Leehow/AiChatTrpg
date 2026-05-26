// Voice assignment / intro synthesis / NPC rematch / bond NPC enrichment.
// All endpoints mutate `memory_state` server-side and return the refreshed
// session detail (or a small wrapper around it).

import { apiFetch } from "../http";
import { BASE } from "./base";
import type { SessionDetailDTO } from "./core";

export interface VoiceAssignBody {
  voice: string;
  /** TTS provider the chosen voice belongs to — stamped onto
   *  `tts_voice_provider` so the runtime knows which catalogue the id
   *  came from when it later resolves the active voice. */
  provider?: string;
  /** TTS model name (e.g. `qwen3-tts-flash`, `gemini-2.5-pro-preview-tts`).
   *  Stamped onto `tts_voice_model` for the same reason. */
  model?: string;
}

export const setCharacterVoiceAPI = (id: string, body: VoiceAssignBody) =>
  apiFetch<SessionDetailDTO>(
    `${BASE}/${encodeURIComponent(id)}/character/voice`,
    {
      method: "POST",
      json: body,
    },
  );

export const setNpcVoiceAPI = (
  id: string,
  npcKey: string,
  body: VoiceAssignBody,
) =>
  apiFetch<SessionDetailDTO>(
    `${BASE}/${encodeURIComponent(id)}/npcs/${encodeURIComponent(npcKey)}/voice`,
    {
      method: "POST",
      json: body,
    },
  );

// Voice intro — synthesises a short in-character introduction for either
// the PC or a single NPC. `cached=true` means the server reused an
// existing audio file because the signature (provider/model/voice) still
// matches; `force=true` bypasses the cache.

export interface VoiceIntroResponse {
  text: string;
  audio_url: string;
  provider: string;
  model: string;
  voice: string;
  cached: boolean;
}

export const synthesizeCharacterVoiceIntroAPI = (
  id: string,
  body: { force?: boolean } = {},
) =>
  apiFetch<VoiceIntroResponse>(
    `${BASE}/${encodeURIComponent(id)}/character/voice-intro`,
    { method: "POST", json: body },
  );

export const synthesizeNpcVoiceIntroAPI = (
  id: string,
  npcKey: string,
  body: { force?: boolean } = {},
) =>
  apiFetch<VoiceIntroResponse>(
    `${BASE}/${encodeURIComponent(id)}/npcs/${encodeURIComponent(npcKey)}/voice-intro`,
    { method: "POST", json: body },
  );

// NPC rematch — clears NPC voices and re-runs the auto assignment.
// `skip_locked` (default true) keeps NPCs whose `tts_voice_locked` flag
// is set by manual selection out of the rematch entirely. The only way
// to also reassign locked NPCs is `force: true` — passing
// `skip_locked: false` on its own is not an override path; the server
// still respects the lock unless `force` is set.

export interface NpcRematchVoicesResponse {
  session: SessionDetailDTO;
  rematched: number;
  skipped_locked: number;
}

export const rematchNpcVoicesAPI = (
  id: string,
  body: { skip_locked?: boolean; force?: boolean } = {},
) =>
  apiFetch<NpcRematchVoicesResponse>(
    `${BASE}/${encodeURIComponent(id)}/npcs/rematch-voices`,
    { method: "POST", json: body },
  );

// Bond NPC enrichment — fills description/personality/relationship_dynamic
// and a voice_card for every `from_bond` NPC in the session that is still
// missing those rich fields. Returns 200 even when no NPC is eligible.
// `force=true` re-runs against already-enriched bond NPCs.

export interface BondNpcEnrichResponse {
  session: SessionDetailDTO;
  eligible: number;
  enriched: number;
  skipped: number;
  enriched_npc_keys: string[];
  skipped_npc_keys: string[];
  errors: string[];
}

export const enrichBondNpcsAPI = (
  id: string,
  body: { force?: boolean; limit?: number | null } = {},
) =>
  apiFetch<BondNpcEnrichResponse>(
    `${BASE}/${encodeURIComponent(id)}/bond-npcs/enrich`,
    { method: "POST", json: body },
  );
