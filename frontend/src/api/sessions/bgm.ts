// Session BGM — selection of music tracks scoped to a single TRPG session.
// Backed by `memory_state._settings.bgm_track_ids[]` server-side; the GET
// returns the materialised MusicTrackOut rows so the UI doesn't need to
// cross-reference the global `/api/music` list.

import { apiFetch } from "../http";
import { BASE } from "./base";

export interface MusicTrackOutDTO {
  id: string;
  title: string;
  source_type: "url" | "upload";
  url: string;
  is_public: boolean;
  owner_id: string;
  owner_username: string;
  is_mine: boolean;
  created_at: string;
  updated_at: string;
}

export interface SessionBgmResponse {
  track_ids: string[];
  tracks: MusicTrackOutDTO[];
}

export const getSessionBgmAPI = (id: string) =>
  apiFetch<SessionBgmResponse>(
    `${BASE}/${encodeURIComponent(id)}/bgm`,
  );

export const setSessionBgmAPI = (
  id: string,
  body: { track_ids: string[] },
) =>
  apiFetch<SessionBgmResponse>(
    `${BASE}/${encodeURIComponent(id)}/bgm/selection`,
    { method: "POST", json: body },
  );
