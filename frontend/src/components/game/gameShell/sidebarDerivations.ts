import type { SessionDetailDTO } from "../../../api/sessions";
import type { CharacterUISchema } from "../../character_ui/widgets";
import type { ParsedRuleset } from "../../../lib/ruleset/types";
import type { NpcEntry } from "../panels/NpcPanel";
import {
  bondNpcNeedsEnrichment,
  isPcKnownNpc,
  npcPublicLabel,
  publicNpcText,
  readCurrentSceneKey,
  readNpcHp,
  readNpcKnownFacts,
  readNpcStatus,
} from "./sessionHelpers";

export interface PlayerNoteEntry {
  id?: string;
  content: string;
  tags: string[];
  created_at?: string;
  updated_at?: string;
  source?: string;
}

// Player notebook entries written via [ADD_NOTE] markers. Stored under
// memory_state.player_notes[] by services/trpg_ic_markers.py — surfaced
// here so the sidebar's NotebookPanel can render them.
export function derivePlayerNotes(session: SessionDetailDTO | null): PlayerNoteEntry[] {
  const ms = session?.memory_state as Record<string, unknown> | undefined;
  const raw = ms?.player_notes;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((n): n is Record<string, unknown> => !!n && typeof n === "object")
    .map((n) => ({
      id: typeof n.id === "string" ? n.id : undefined,
      content: typeof n.content === "string" ? n.content : "",
      tags: Array.isArray(n.tags)
        ? (n.tags as unknown[]).filter((t): t is string => typeof t === "string")
        : [],
      created_at: typeof n.created_at === "string" ? n.created_at : undefined,
      updated_at: typeof n.updated_at === "string" ? n.updated_at : undefined,
      source: typeof n.source === "string" ? n.source : undefined,
    }))
    .filter((n) => n.content.trim());
}

// NPCs the GM has established (from [CREATE_NPC] markers + the
// post-character-creation auto-extraction). Mapped to the shape the
// NpcPanel renders. Filters out anonymous entries with no name so the
// grid stays tidy.
// The sidebar NPC panel is the PC-known roster: people the character has
// names/descriptions/facts for. It deliberately uses public labels when a
// true name is still hidden.
export function deriveSidebarNpcs(session: SessionDetailDTO | null): NpcEntry[] {
  const ms = session?.memory_state as Record<string, unknown> | undefined;
  const raw = ms?.npcs;
  if (!Array.isArray(raw)) return [];
  // Resolve the PC's current scene key from the same fields the
  // backend's `_current_scene_key` consults, so "在场" matches what
  // mark_seen / scene_runtime saw at marker apply time.
  const currentScene = readCurrentSceneKey(session);
  return raw
    .filter((n): n is Record<string, unknown> => !!n && typeof n === "object")
    .filter(isPcKnownNpc)
    .map((n) => {
      const revealed = n.name_revealed === true;
      const displayName = npcPublicLabel(n, revealed);
      const hp = readNpcHp(n.params);
      const lastSeen = typeof n.last_seen_scene === "string"
        ? n.last_seen_scene.trim()
        : "";
      const isPresent = currentScene !== "" && lastSeen === currentScene;
      const voice =
        (typeof n.active_tts_voice === "string" && n.active_tts_voice)
        || (typeof n.tts_voice === "string" && n.tts_voice)
        || "";
      const introText = typeof n.voice_intro_text === "string" ? n.voice_intro_text : "";
      const introUrl = typeof n.voice_intro_audio_url === "string" ? n.voice_intro_audio_url : "";
      const fromBond = n.from_bond === true;
      const bondEnrichedAt = typeof n.bond_enriched_at === "string" ? n.bond_enriched_at : "";
      return {
        key: typeof n.key === "string" ? n.key : "",
        name: displayName,
        role: typeof n.role === "string" ? n.role : undefined,
        gender: typeof n.gender === "string" ? n.gender : undefined,
        portrait_url:
          typeof n.portrait_url === "string"
            ? n.portrait_url
            : typeof n.avatar_url === "string"
              ? (n.avatar_url as string)
              : undefined,
        status: readNpcStatus(n, hp),
        description: publicNpcText(
          n.public_description,
          n.player_visible_description,
          n.player_visible_summary,
          n.appearance,
          n.description,
          n.summary,
          n.brief,
        ),
        knownFacts: readNpcKnownFacts(n),
        nameRevealed: revealed,
        lastSeen: lastSeen || undefined,
        isPresent,
        voice: voice || undefined,
        tts_voice_locked: n.tts_voice_locked === true,
        voice_intro_text: introText || undefined,
        voice_intro_audio_url: introUrl || undefined,
        fromBond,
        needsBondEnrichment: fromBond && bondNpcNeedsEnrichment(n),
        bondEnrichedAt: bondEnrichedAt || undefined,
      };
    })
    .filter((n) => n.key && n.name);
}

export function derivePcVoice(session: SessionDetailDTO | null): string {
  const pc = (session?.character as Record<string, unknown> | undefined) ?? {};
  const active = typeof pc.active_tts_voice === "string" ? pc.active_tts_voice : "";
  const primary = typeof pc.tts_voice === "string" ? pc.tts_voice : "";
  return active || primary || "";
}

export function deriveCharacterSchema(parsed: ParsedRuleset | null): CharacterUISchema | null {
  const characterUiArtifact = parsed?.character_ui;
  if (
    !characterUiArtifact
    || typeof characterUiArtifact !== "object"
    || !(characterUiArtifact as Record<string, unknown>).package
    || ["compiling", "failed"].includes(
      String((characterUiArtifact as Record<string, unknown>).status || ""),
    )
  ) {
    return null;
  }
  return (characterUiArtifact as Record<string, unknown>).package as CharacterUISchema;
}
