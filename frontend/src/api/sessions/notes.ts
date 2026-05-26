// Player notes CRUD — backs the floating NotesOverlay and NotebookPanel.
// Notes live under `memory_state.player_notes[]` on the session; the GM
// engine also appends entries here via `[ADD_NOTE]`, so the same shape is
// returned regardless of source. Notes that originate from a marker may
// not carry an id; the UI treats missing-id entries as read-only.

import { apiFetch } from "../http";
import { BASE } from "./base";

export interface PlayerNoteDTO {
  id?: string | null;
  content: string;
  tags?: string[];
  created_at?: string | null;
  updated_at?: string | null;
  source?: "gm" | "player" | string | null;
}

export interface PlayerNoteListResponse {
  notes: PlayerNoteDTO[];
}

export interface PlayerNoteMutationResponse {
  status: string;
  note: PlayerNoteDTO;
}

export interface PlayerNoteDeleteResponse {
  status: string;
}

export interface PlayerNoteCreateBody {
  content: string;
  tags?: string[];
}

export interface PlayerNoteUpdateBody {
  content?: string;
  tags?: string[];
}

export const listSessionNotesAPI = (sessionId: string) =>
  apiFetch<PlayerNoteListResponse>(
    `${BASE}/${encodeURIComponent(sessionId)}/notes`,
  );

export const createSessionNoteAPI = (
  sessionId: string,
  body: PlayerNoteCreateBody,
) =>
  apiFetch<PlayerNoteMutationResponse>(
    `${BASE}/${encodeURIComponent(sessionId)}/notes`,
    { method: "POST", json: body },
  );

export const updateSessionNoteAPI = (
  sessionId: string,
  noteId: string,
  body: PlayerNoteUpdateBody,
) =>
  apiFetch<PlayerNoteMutationResponse>(
    `${BASE}/${encodeURIComponent(sessionId)}/notes/${encodeURIComponent(noteId)}`,
    { method: "POST", json: body },
  );

export const deleteSessionNoteAPI = (
  sessionId: string,
  noteId: string,
) =>
  apiFetch<PlayerNoteDeleteResponse>(
    `${BASE}/${encodeURIComponent(sessionId)}/notes/${encodeURIComponent(noteId)}`,
    { method: "DELETE" },
  );
