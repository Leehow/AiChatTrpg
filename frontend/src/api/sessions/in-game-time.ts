// Force-set in-game clock + quick delta-based advance.
// `forceInGameTimeAPI` is the override path (gear icon in the TRPG scene
// HUD); `advanceInGameTimeAPI` powers the "+10m / +1h" nudges.
// Response shape is shared.

import { apiFetch } from "../http";
import { BASE } from "./base";

export interface ForceInGameTimeBody {
  day: number;
  clock: string; // HH:MM 24h
  date?: string;
}

export interface ForceInGameTimeResponse {
  day: number;
  clock: string;
  period: string; // morning|afternoon|evening|night
  date?: string | null;
  elapsed_minutes: number;
}

export const forceInGameTimeAPI = (
  id: string,
  body: ForceInGameTimeBody,
) =>
  apiFetch<ForceInGameTimeResponse>(
    `${BASE}/${encodeURIComponent(id)}/in-game-time`,
    { method: "POST", json: body }
  );

export interface AdvanceInGameTimeBody {
  minutes: number;
  reason?: string;
}

export const advanceInGameTimeAPI = (
  id: string,
  body: AdvanceInGameTimeBody,
) =>
  apiFetch<ForceInGameTimeResponse>(
    `${BASE}/${encodeURIComponent(id)}/advance-time`,
    { method: "POST", json: body },
  );
