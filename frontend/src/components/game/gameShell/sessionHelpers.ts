import type { SessionDetailDTO } from "../../../api/sessions";
import type { CharacterStats } from "../panels/CharacterPanel";
import type { ModuleState } from "../panels/ModulePanel";
import type { MemoryItem } from "../panels/MemoryPanel";
import type { NpcStatus } from "../panels/NpcPanel";
import {
  hashSpeakerToColorIdx,
  TRPG_SPEAKER_COLOR_COUNT,
  type TrpgSpeakerProfile,
} from "../../../utils/trpgDialogue";
import { asRecord, num, str } from "./messageHelpers";

export const CHARACTER_DEFAULT: CharacterStats = {
  name: "Kira Ashwood",
  className: "Investigator",
  level: 1,
  hp: { cur: 11, max: 14 },
  mp: { cur: 0, max: 0 },
  sp: { cur: 7, max: 9 },
  attrs: [
    { name: "STR", val: 50, mod: "" },
    { name: "DEX", val: 65, mod: "" },
    { name: "CON", val: 60, mod: "" },
    { name: "INT", val: 80, mod: "" },
    { name: "POW", val: 55, mod: "" },
    { name: "APP", val: 60, mod: "" },
  ],
};

export const MODULE_DEFAULT: ModuleState = {
  tag: "Freeform",
  title: "—",
  scene: "—",
  desc: "(no module loaded)",
  progress: [false, false, false, false, false],
};

export const MEMORIES_DEFAULT: MemoryItem[] = [];

const SPEAKER_TITLE_GROUPS = [
  ["牧师", "祭司", "神父"],
  ["医生", "医师"],
  ["警长", "警察"],
  ["店主", "老板"],
  ["守卫", "卫兵"],
  ["司机"],
  ["侍者"],
  ["士兵"],
  ["教授"],
  ["老师"],
  ["记者"],
];

export function readCharacter(detail: SessionDetailDTO | null): CharacterStats {
  const c = detail?.character;
  if (!c || typeof c !== "object") return CHARACTER_DEFAULT;
  const raw = c as Record<string, unknown>;
  if (Array.isArray((raw as unknown as CharacterStats).attrs) && (raw as unknown as CharacterStats).hp) {
    return raw as unknown as CharacterStats;
  }

  const identity = asRecord(raw.identity);
  const resources = asRecord(raw.resources);
  const derived = asRecord(raw.derived_values);
  const origin = asRecord(raw.origin);
  const arc = asRecord(origin.arc);
  const name =
    str(raw.display_name) ||
    str(raw.name) ||
    str(raw.character_name) ||
    str(identity.display_name) ||
    str(identity.name) ||
    str(identity.character_name) ||
    str(identity.full_name) ||
    "Unnamed character";
  const className =
    str(raw.className) ||
    str(raw.class_name) ||
    str(identity.occupation) ||
    str(raw.occupation) ||
    str(asRecord(arc.competency).name) ||
    str(asRecord(arc.anomaly).name) ||
    "Character";
  const level =
    num(raw.level) ||
    num(derived.level) ||
    num(asRecord(raw.currency_and_progression).level) ||
    1;

  return {
    name,
    className,
    level,
    hp: readResource(raw.hp, resources.hp, derived.hp, derived.hit_points, 10),
    mp: readOptionalResource(raw.mp, resources.mp, derived.mp, derived.magic_points),
    sp: readOptionalResource(raw.sp, resources.sp, resources.sanity, derived.sanity),
    attrs: readAttrs(raw.attributes),
  };
}

function readResource(...values: unknown[]): { cur: number; max: number } {
  const fallback = values[values.length - 1];
  for (const value of values.slice(0, -1)) {
    if (typeof value === "number") return { cur: value, max: value };
    const rec = asRecord(value);
    const max = num(rec.max) || num(rec.maximum) || num(rec.total) || num(rec.value);
    const cur = num(rec.cur) || num(rec.current) || max;
    if (max) return { cur, max };
  }
  const n = typeof fallback === "number" ? fallback : 10;
  return { cur: n, max: n };
}

function readOptionalResource(...values: unknown[]): { cur: number; max: number } | undefined {
  for (const value of values) {
    if (typeof value === "number") return { cur: value, max: value };
    const rec = asRecord(value);
    const max = num(rec.max) || num(rec.maximum) || num(rec.total) || num(rec.value);
    const cur = num(rec.cur) || num(rec.current) || max;
    if (max) return { cur, max };
  }
  return undefined;
}

function readAttrs(value: unknown): CharacterStats["attrs"] {
  const rec = asRecord(value);
  const items = Object.entries(rec).slice(0, 6).map(([name, raw]) => {
    const nested = asRecord(raw);
    const val = num(raw) || num(nested.value) || num(nested.full) || num(nested.max_qa);
    return { name: name.toUpperCase().slice(0, 8), val, mod: "" };
  }).filter((item) => item.val > 0);
  return items.length ? items : CHARACTER_DEFAULT.attrs;
}

// NPC params come in two shapes:
//   1. chargen path → flat int: `params.hp = 12`
//   2. GM marker path → dict: `params.hp = {current: 0}` (max often missing
//      because [UPDATE_NPC_PARAMS] only writes the field that changed)
// Keep this internal to derive a coarse condition; the player-facing sidebar
// must never expose raw HP numbers for NPCs.
export function readNpcHp(params: unknown): { current: number; max?: number } | undefined {
  const rec = asRecord(params);
  const raw = rec.hp;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return { current: raw, max: raw };
  }
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    const hasCur = typeof r.current === "number" || typeof r.cur === "number";
    const hasMax = typeof r.max === "number" || typeof r.maximum === "number";
    if (!hasCur && !hasMax) return undefined;
    const current = hasCur ? num(r.current) || num(r.cur) : num(r.max) || num(r.maximum);
    const max = hasMax ? num(r.max) || num(r.maximum) : undefined;
    return { current, max };
  }
  return undefined;
}

function textLooksPrivate(value: string): boolean {
  const lowered = value.toLowerCase();
  return [
    "secret",
    "true identity",
    "real goal",
    "hidden",
    "forbidden",
    "gm note",
    "keeper note",
    "秘密",
    "真实身份",
    "真正目标",
    "隐藏",
    "幕后",
    "核心秘密",
  ].some((marker) => lowered.includes(marker));
}

export function publicNpcText(...values: unknown[]): string | undefined {
  for (const value of values) {
    const text = str(value);
    if (text && !textLooksPrivate(text)) return text;
  }
  return undefined;
}

function pushKnownFact(items: string[], value: unknown) {
  const text = str(value);
  if (!text || textLooksPrivate(text)) return;
  if (!items.includes(text)) items.push(text);
}

function pushKnownFactList(items: string[], value: unknown) {
  if (!Array.isArray(value)) return;
  for (const raw of value) {
    if (typeof raw === "string") {
      pushKnownFact(items, raw);
      continue;
    }
    const rec = asRecord(raw);
    pushKnownFact(items, rec.text || rec.content || rec.summary || rec.fact || rec.description);
  }
}

export function readNpcKnownFacts(npc: Record<string, unknown>): string[] {
  const items: string[] = [];
  const playerKnowledge = asRecord(npc.player_knowledge);
  const publicFields: Array<[string, unknown]> = [
    ["称呼", npc.player_known_name || npc.public_name || npc.display_name || npc.claimed_name || npc.known_as],
    ["关系", playerKnowledge.public_relationship || playerKnowledge.relationship || npc.public_relationship],
    ["可见态度", playerKnowledge.visible_attitude || npc.visible_attitude],
    ["上次互动", playerKnowledge.last_interaction_summary || npc.last_interaction_summary],
    ["已知身份", playerKnowledge.known_as || npc.known_as],
  ];
  for (const [label, value] of publicFields) {
    const text = str(value);
    if (text && !textLooksPrivate(text)) pushKnownFact(items, `${label}：${text}`);
  }

  pushKnownFactList(items, npc.player_known_facts);
  pushKnownFactList(items, npc.public_facts);
  pushKnownFactList(items, npc.revealed_facts);

  const innerState = asRecord(npc.inner_state);
  const visibleState = publicNpcText(
    innerState.visible_behavior,
    innerState.visible_mood,
    innerState.surface_mood,
    innerState.emotional_state,
  );
  if (visibleState) pushKnownFact(items, `可见状态：${visibleState}`);

  return items.slice(0, 8);
}

export function npcPublicLabel(npc: Record<string, unknown>, revealed: boolean): string {
  const trueName = str(npc.name);
  const knownName =
    str(npc.player_known_name)
    || str(npc.public_name)
    || str(npc.display_name)
    || str(npc.claimed_name)
    || str(npc.known_as);
  if (revealed && trueName) return trueName;
  return (
    knownName
    || publicNpcText(
      npc.public_description,
      npc.player_visible_description,
      npc.player_visible_summary,
      npc.appearance,
      npc.role,
      npc.description,
      npc.summary,
      npc.brief,
    )
    || ""
  );
}

// Mirror backend `is_bond_npc_unfinished` so the panel's "Enrich" action
// shows iff at least one bond NPC is still missing rich profile fields.
// Aligns with services/trpg_npc/bond_enrichment.py:52 (`_is_blank`) +
// :66 (`_has_voice_card`) + :87 (`is_bond_npc_unfinished`). For the
// three profile fields, blank = null/undefined, blank string, empty
// list, or empty plain object — matching backend `_is_blank`.
function isBondProfileFieldBlank(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "string") return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length === 0;
  return false;
}

export function bondNpcNeedsEnrichment(npc: Record<string, unknown>): boolean {
  for (const key of ["description", "personality", "relationship_dynamic"]) {
    if (isBondProfileFieldBlank(npc[key])) return true;
  }
  const card = npc.voice_card;
  if (!card || typeof card !== "object" || Array.isArray(card)) return true;
  const entries = Object.values(card as Record<string, unknown>);
  if (entries.length === 0) return true;
  const meaningful = entries.some((v) => {
    if (typeof v === "string") return v.trim().length > 0;
    if (Array.isArray(v)) return v.some((item) => typeof item === "string" && item.trim().length > 0);
    return false;
  });
  return !meaningful;
}

export function readCurrentSceneKey(session: { module_state?: unknown; memory_state?: unknown } | null | undefined): string {
  // Mirrors backend `_current_scene_key` so the sidebar's "在场" check
  // agrees with what `mark_seen` stamped on `last_seen_scene`. Order:
  // module_state.scene → memory_state.world_facts.current_scene →
  // memory_state.current_scene.
  const module = asRecord(session?.module_state);
  const moduleScene = str(module.scene);
  if (moduleScene && moduleScene !== "—") return moduleScene;
  const memory = asRecord(session?.memory_state);
  const facts = asRecord(memory.world_facts);
  const factsScene = str(facts.current_scene);
  if (factsScene) return factsScene;
  return str(memory.current_scene);
}

export function isPcKnownNpc(npc: Record<string, unknown>): boolean {
  if (npc.gm_only === true || npc.hidden_from_player === true || npc.player_visible === false) {
    return false;
  }
  // Each branch below requires positive evidence the PC actually
  // encountered or learned facts about this NPC. `name_revealed=true`
  // alone is NOT sufficient — a name can leak via document, hearsay or
  // backstory mention without the PC ever meeting the person; those
  // belong in the debug roster, not the player-facing sidebar.
  if (str(npc.last_seen_scene)) return true;
  if (Array.isArray(npc.actions) && npc.actions.length > 0) return true;
  if (npc.from_bond === true) return true;
  const source = str(npc.source);
  if (source === "dialogue_speaker" || source === "character_intake") return true;
  if (Array.isArray(npc.player_known_facts) && npc.player_known_facts.length > 0) return true;
  if (Array.isArray(npc.revealed_facts) && npc.revealed_facts.length > 0) return true;
  const playerKnowledge = asRecord(npc.player_knowledge);
  if (
    str(playerKnowledge.known_as)
    || str(playerKnowledge.last_interaction_summary)
    || str(playerKnowledge.visible_attitude)
    || str(playerKnowledge.public_relationship)
  ) {
    return true;
  }
  return false;
}

export function readNpcStatus(npc: Record<string, unknown>, hp: { current: number; max?: number } | undefined): NpcStatus {
  const params = asRecord(npc.params);
  const physicalState = asRecord(npc.physical_state);
  const runtimeState = asRecord(npc.runtime_state_v2);
  const statusText = [
    npc.status,
    params.status,
    physicalState.status,
    runtimeState.status,
    params.condition,
    physicalState.condition,
  ].map((value) => str(value).toLowerCase()).filter(Boolean).join(" ");

  if (/(dead|deceased|killed|corpse|死亡|死了|尸体|阵亡)/i.test(statusText)) return "dead";
  if (/(wounded|injured|hurt|bleeding|down|unconscious|incapacitated|受伤|负伤|流血|重伤|轻伤|昏迷|倒地|倒下|失去行动)/i.test(statusText)) {
    return "injured";
  }
  if (/(alive|active|healthy|normal|living|存活|活着|正常|清醒)/i.test(statusText)) return "alive";

  if (hp) {
    if (hp.current <= 0) return "dead";
    if (hp.max && hp.current < hp.max) return "injured";
    return "alive";
  }
  return "alive";
}

function normalizeSpeakerKey(value: string): string {
  return value.trim().toLowerCase().replace(/[\s·•・/／,，、;；:：\-_—|]+/g, "");
}

function looksLikeImageUrl(value: string): boolean {
  return /^(https?:|data:image\/|blob:|\/)/i.test(value.trim());
}

function firstImageUrl(...values: unknown[]): string | undefined {
  for (const value of values) {
    const text = str(value);
    if (text && looksLikeImageUrl(text)) return text;
  }
  return undefined;
}

function addSpeakerProfile(
  profiles: Record<string, TrpgSpeakerProfile>,
  key: string,
  profile: TrpgSpeakerProfile,
) {
  const clean = key.trim();
  if (!clean) return;
  profiles[clean] = profile;
  const normalized = normalizeSpeakerKey(clean);
  if (normalized) profiles[normalized] = profile;
}

function cjkNameChunks(value: string): string[] {
  const chunks = value.match(/[一-鿿]{2,}/g) || [];
  return Array.from(new Set(chunks.filter((chunk) => chunk.length >= 2)));
}

function titleAliasesForNpc(
  trueName: string,
  knownName: string,
  npc: Record<string, unknown>,
): string[] {
  const titleText = [
    knownName,
    npc.role,
    npc.occupation,
    npc.public_description,
    npc.player_visible_description,
    npc.appearance,
    npc.description,
    npc.summary,
    npc.portrait_prompt,
  ].map((value) => str(value)).join(" ");
  const titles = new Set<string>();
  for (const group of SPEAKER_TITLE_GROUPS) {
    if (group.some((title) => titleText.includes(title))) {
      for (const title of group) titles.add(title);
    }
  }
  if (titles.size === 0) return [];
  const chunks = cjkNameChunks(trueName);
  const aliases: string[] = [];
  for (const chunk of chunks) {
    for (const title of titles) {
      aliases.push(`${chunk}${title}`);
    }
  }
  return aliases;
}

function allocateSpeakerColor(anchor: string, used: Set<number>): number {
  const base = hashSpeakerToColorIdx(anchor || "npc");
  for (let offset = 0; offset < TRPG_SPEAKER_COLOR_COUNT; offset += 1) {
    const idx = (base + offset) % TRPG_SPEAKER_COLOR_COUNT;
    if (!used.has(idx)) {
      used.add(idx);
      return idx;
    }
  }
  return base;
}

export function buildSpeakerProfiles(
  detail: SessionDetailDTO | null,
  characterName: string,
): Record<string, TrpgSpeakerProfile> {
  const profiles: Record<string, TrpgSpeakerProfile> = {};
  const usedNpcColors = new Set<number>();
  const pc = asRecord(detail?.character);
  const identity = asRecord(pc.identity);
  const appearance = asRecord(pc.appearance);
  const pcDisplay =
    characterName
    || str(pc.display_name)
    || str(pc.name)
    || str(pc.character_name)
    || str(identity.display_name)
    || str(identity.name)
    || str(identity.character_name)
    || "PC";
  const pcProfile: TrpgSpeakerProfile = {
    displayName: pcDisplay,
    avatarUrl: firstImageUrl(
      pc.portrait_url,
      pc.avatar_url,
      pc.image_url,
      pc.portrait,
      identity.portrait_url,
      identity.avatar_url,
      appearance.portrait_url,
      appearance.avatar_url,
    ),
    voice: str(pc.active_tts_voice) || str(pc.tts_voice) || str(pc.voice),
    voiceModel: str(pc.tts_voice_model) || str(pc.voice_model),
    type: "pc",
  };
  addSpeakerProfile(profiles, "PC", pcProfile);
  addSpeakerProfile(profiles, pcDisplay, pcProfile);

  const memory = asRecord(detail?.memory_state);
  const npcs = Array.isArray(memory.npcs) ? memory.npcs : [];
  for (const rawNpc of npcs) {
    const npc = asRecord(rawNpc);
    const key = str(npc.key) || str(npc.id);
    const trueName = str(npc.name) || str(npc.full_name);
    const knownName =
      str(npc.player_known_name)
      || str(npc.public_name)
      || str(npc.display_name)
      || str(npc.claimed_name)
      || str(npc.known_as);
    const revealed = npc.name_revealed === true;
    const displayName =
      (revealed ? (trueName || knownName) : (knownName || trueName))
      || key;
    if (!displayName && !key) continue;
    const colorAnchor = key || trueName || knownName || displayName;
    const profile: TrpgSpeakerProfile = {
      key: key || undefined,
      displayName: displayName || key,
      canonicalName: trueName || undefined,
      publicName: knownName || undefined,
      nameRevealed: revealed,
      colorIdx: allocateSpeakerColor(colorAnchor, usedNpcColors),
      avatarUrl: firstImageUrl(
        npc.portrait_url,
        npc.avatar_url,
        npc.image_url,
        npc.image,
        npc.portrait,
      ),
      voice: str(npc.active_tts_voice) || str(npc.tts_voice) || str(npc.voice),
      voiceModel: str(npc.tts_voice_model) || str(npc.voice_model),
      type: "npc",
    };
    const aliasCandidates = [
      key,
      displayName,
      trueName,
      knownName,
      str(npc.public_name),
      str(npc.display_name),
      str(npc.player_known_name),
      str(npc.claimed_name),
      str(npc.known_as),
      str(npc.short_name),
      str(npc.nickname),
      ...titleAliasesForNpc(trueName, knownName, npc),
    ];
    for (const alias of aliasCandidates) {
      if (alias) addSpeakerProfile(profiles, alias, profile);
    }
    const aliases = npc.aliases;
    if (Array.isArray(aliases)) {
      for (const alias of aliases) {
        const text = str(alias);
        if (text) addSpeakerProfile(profiles, text, profile);
      }
    }
  }

  return profiles;
}
