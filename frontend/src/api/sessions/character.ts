// Character-creation API wrappers (draft, start, chat, generate, confirm,
// import, clear) plus the character/NPC narrative-translation endpoints.
// SSE flows delegate to streamCharacterEndpoint in character-stream.ts.

import { apiFetch } from "../http";
import { BASE } from "./base";
import { streamCharacterEndpoint } from "./character-stream";
import type {
  CharacterDraftDTO,
  CharacterStreamHandlers,
} from "./character-types";
import type { SessionDetailDTO } from "./core";

/** Translate the session's character JSON values to a target language.
 *  Persists the translated character back into the session and returns
 *  the refreshed detail. Section titles + field labels are controlled
 *  by the character_ui compiler and are not affected by this call.
 *
 *  `language` is a free-form code (`zh`, `en`, `ja`, …); the backend
 *  normalises it and feeds it to the GM model. The supported list lives
 *  in `lib/character_languages.SUPPORTED_LANGUAGES`. */
export const translateCharacterAPI = (id: string, language: string) =>
  apiFetch<SessionDetailDTO>(
    `${BASE}/${encodeURIComponent(id)}/character/translate`,
    {
      method: "POST",
      json: { language },
    },
  );

/** Translate every NPC's narrative fields in `memory_state.npcs[]` to
 *  the given language. Numeric stats / params / portrait URLs / voice
 *  IDs / visibility flags are preserved; only `name`, `player_known_name`,
 *  `role`, `description`, `summary`, `motivation`, `personality`,
 *  `appearance`, `voice_hint`, and `dialogue_style` are rewritten by the
 *  GM model. One LLM call covers the whole roster. */
export const translateNpcsAPI = (id: string, language: string) =>
  apiFetch<SessionDetailDTO>(
    `${BASE}/${encodeURIComponent(id)}/npcs/translate`,
    {
      method: "POST",
      json: { language },
    },
  );

export const getCharacterDraftAPI = (id: string) =>
  apiFetch<CharacterDraftDTO>(
    `${BASE}/${encodeURIComponent(id)}/character-draft`
  );

export const startCharacterCreationAPI = (id: string) =>
  apiFetch<CharacterDraftDTO>(
    `${BASE}/${encodeURIComponent(id)}/character-start`,
    { method: "POST" }
  );

export const streamCharacterStartAPI = (
  id: string,
  body: { language?: string } | undefined,
  handlers: CharacterStreamHandlers = {},
  signal?: AbortSignal
) =>
  streamCharacterEndpoint(
    `${BASE}/${encodeURIComponent(id)}/character-start-stream`,
    body,
    handlers,
    signal
  );

export const sendCharacterChatAPI = (
  id: string,
  body: { message: string; language?: string }
) =>
  apiFetch<CharacterDraftDTO>(
    `${BASE}/${encodeURIComponent(id)}/character-chat`,
    { method: "POST", json: body }
  );

export const streamCharacterChatAPI = (
  id: string,
  body: { message: string; language?: string },
  handlers: CharacterStreamHandlers = {},
  signal?: AbortSignal
) =>
  streamCharacterEndpoint(
    `${BASE}/${encodeURIComponent(id)}/character-chat-stream`,
    body,
    handlers,
    signal
  );

export const importCharacterDraftAPI = (
  id: string,
  body: {
    character: Record<string, unknown>;
    source?: "uploaded" | "pool";
    pool_id?: string | null;
  }
) =>
  apiFetch<CharacterDraftDTO>(
    `${BASE}/${encodeURIComponent(id)}/character-import`,
    { method: "POST", json: body }
  );

export const generateCharacterAPI = (
  id: string,
  body: { mode?: "auto" | "from_chat"; seed?: string; language?: string }
) =>
  apiFetch<CharacterDraftDTO>(
    `${BASE}/${encodeURIComponent(id)}/character-generate`,
    { method: "POST", json: body }
  );

export const streamCharacterGenerateAPI = (
  id: string,
  body: { mode?: "auto" | "from_chat"; seed?: string; language?: string },
  handlers: CharacterStreamHandlers = {},
  signal?: AbortSignal
) =>
  streamCharacterEndpoint(
    `${BASE}/${encodeURIComponent(id)}/character-generate-stream`,
    body,
    handlers,
    signal
  );

export const confirmCharacterAPI = (id: string) =>
  apiFetch<CharacterDraftDTO>(
    `${BASE}/${encodeURIComponent(id)}/character-confirm`,
    { method: "POST" }
  );

export const clearCharacterDraftAPI = (id: string) =>
  apiFetch<CharacterDraftDTO>(
    `${BASE}/${encodeURIComponent(id)}/character-draft`,
    { method: "DELETE" }
  );
