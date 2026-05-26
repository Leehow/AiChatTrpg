/**
 * TRPG dialogue styling — wrap `「quote」[speak]name[/speak]` runs in styled
 * spans so each speaker gets a distinct, consistent color across the chat.
 *
 * Speaker type classification:
 *   pc        → player character (anchor color)
 *   voice     → off-screen / radio / broadcast
 *   bystander → visible descriptive label like "高瘦工装男人"
 *   npc       → known NPC (hashed into an 18-color palette)
 */

export type TrpgSpeakerType = "pc" | "voice" | "bystander" | "npc" | "unknown";

export interface TrpgSpeakerProfile {
  key?: string;
  displayName?: string;
  canonicalName?: string;
  publicName?: string;
  nameRevealed?: boolean;
  colorIdx?: number;
  avatarUrl?: string;
  voice?: string;
  voiceModel?: string;
  type?: TrpgSpeakerType;
}

export interface StyleTrpgDialogueOptions {
  forceTrpg?: boolean;
  speakerProfiles?: Record<string, TrpgSpeakerProfile>;
}

const VOICE_PATTERN =
  /(声音|广播|电台|无线电|对讲机|喇叭|扩音器|录音|留声机|话筒|麦克风|音响|电话(?!亭)|旁白)/;
const BYSTANDER_PATTERN =
  /(女人|男人|女孩|男孩|大叔|大妈|老妇|老头|老人|少年|少女|女子|男子|女士|先生|路人|陌生|侍者|仆人|卫兵|士兵|商贩|村民|市民|旁观|家伙)/;
export const TRPG_SPEAKER_COLOR_COUNT = 18;

export function getTrpgSpeakerType(name: string): TrpgSpeakerType {
  const n = (name || "").trim();
  if (!n) return "npc";
  if (n.toUpperCase() === "PC") return "pc";
  if (VOICE_PATTERN.test(n)) return "voice";
  if (BYSTANDER_PATTERN.test(n)) return "bystander";
  return "npc";
}

/**
 * FNV-1a hash. CJK characters cluster in U+4E00–U+9FFF, so a naive
 * character-sum modulo collides on short Chinese names. FNV-1a mixes every
 * character into every output bit and gives near-uniform spread.
 */
export function hashSpeakerToColorIdx(name: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < name.length; i++) {
    h ^= name.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) % TRPG_SPEAKER_COLOR_COUNT;
}

const TRPG_BYSTANDER_AVATAR_SVG = (
  "data:image/svg+xml;utf8,"
  + "%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22%23cbd5e1%22%3E"
  + "%3Ccircle%20cx%3D%2212%22%20cy%3D%228%22%20r%3D%224.5%22%2F%3E"
  + "%3Cpath%20d%3D%22M3.75%2020.105a8.25%208.25%200%200116.5%200%20.75.75%200%2001-.437.695A18.683%2018.683%200%200112%2022.5c-2.786%200-5.433-.608-7.812-1.7a.75.75%200%2001-.438-.695z%22%2F%3E"
  + "%3C%2Fsvg%3E"
);

function escapeAttr(value: string): string {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeHtml(value: string): string {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function normalizeKey(value: string): string {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s·•・/／,，、;；:：\-_—|]+/g, "");
}

function getSpeakerProfile(
  name: string,
  npcKey: string,
  profiles: Record<string, TrpgSpeakerProfile> | undefined,
): TrpgSpeakerProfile | undefined {
  if (!profiles) return undefined;
  const candidates = [
    npcKey,
    name,
    normalizeKey(name),
    npcKey ? normalizeKey(npcKey) : "",
  ].filter(Boolean);
  for (const key of candidates) {
    const profile = profiles[key];
    if (profile) return profile;
  }
  return undefined;
}

/**
 * Look up a speaker profile from free-form narration text. Used by the markdown
 * post-pass that tints `<strong>NAME</strong>` to match that speaker's dialogue
 * color. Tries exact, then normalized (case + punctuation stripped) match.
 */
export function findSpeakerProfile(
  text: string,
  profiles: Record<string, TrpgSpeakerProfile> | undefined,
): TrpgSpeakerProfile | undefined {
  if (!profiles) return undefined;
  const trimmed = String(text || "").trim();
  if (!trimmed) return undefined;
  if (profiles[trimmed]) return profiles[trimmed];
  const normalized = normalizeKey(trimmed);
  if (normalized && profiles[normalized]) return profiles[normalized];
  return undefined;
}

const GENERIC_SPEAKER_LABELS = new Set([
  "未知",
  "未标注",
  "陌生人",
  "男人",
  "女人",
  "男子",
  "女子",
  "老人",
  "老兵",
  "司机",
  "医生",
  "祭司",
  "老板",
  "店主",
  "NPC",
  "npc",
]);

function isGenericSpeakerLabel(value: string): boolean {
  const clean = String(value || "").trim();
  if (!clean) return true;
  if (GENERIC_SPEAKER_LABELS.has(clean)) return true;
  return /^(一个|一名|那个|这名)?(陌生|沉默|高瘦|矮胖)?(男人|女人|男子|女子|老人|司机|医生|祭司|店主|老板|路人|村民)$/.test(clean);
}

function chooseDisplayName(rawName: string, profile: TrpgSpeakerProfile | undefined): string {
  const name = String(rawName || "").trim();
  const profileName = String(profile?.displayName || "").trim();
  if (!profileName) return name;
  if (!name) return profileName;
  if (profile?.nameRevealed && profile.canonicalName) return profile.canonicalName;
  if (profileName !== name && isGenericSpeakerLabel(profileName) && !isGenericSpeakerLabel(name)) {
    return name;
  }
  return profileName;
}

function speakerColorAnchor(
  rawName: string,
  npcKey: string,
  profile: TrpgSpeakerProfile | undefined,
): string {
  return (
    profile?.key
    || npcKey
    || profile?.canonicalName
    || profile?.publicName
    || profile?.displayName
    || rawName
    || "npc"
  );
}

function renderDialogueSpan(
  quote: string,
  name: string,
  emotion: string,
  npcKey: string,
  inferred: boolean,
  options: StyleTrpgDialogueOptions,
): string {
  const profile = getSpeakerProfile(name, npcKey, options.speakerProfiles);
  const displayName = chooseDisplayName(name, profile);
  const type = profile?.type || getTrpgSpeakerType(displayName);
  const colorIdx = type === "npc"
    ? (typeof profile?.colorIdx === "number"
      ? profile.colorIdx
      : hashSpeakerToColorIdx(speakerColorAnchor(name, npcKey, profile)))
    : type === "bystander"
      ? hashSpeakerToColorIdx(npcKey || displayName) % 3
      : 0;
  const safeName = escapeAttr(displayName);
  const safeQuote = escapeHtml(quote);
  const safeEmotion = escapeAttr(emotion);
  const safeKey = escapeAttr(npcKey || profile?.key || "");
  const safeVoice = escapeAttr(profile?.voice || "");
  const safeVoiceModel = escapeAttr(profile?.voiceModel || "");
  const avatarUrl = profile?.avatarUrl || "";
  const needsFallback = !avatarUrl && type !== "voice" && type !== "unknown";
  const avatarHtml = avatarUrl
    ? `<img class="trpg-speaker-avatar" src="${escapeAttr(avatarUrl)}" alt="${safeName}" onerror="this.style.display='none'" />`
    : needsFallback
      ? `<img class="trpg-speaker-avatar trpg-speaker-avatar--silhouette" src="${TRPG_BYSTANDER_AVATAR_SVG}" alt="${safeName}" />`
      : "";
  const hasAvatarAttr = avatarUrl ? ' data-has-avatar="1"' : "";
  const emotionAttr = safeEmotion ? ` data-emotion="${safeEmotion}"` : "";
  const keyAttr = safeKey ? ` data-npc-key="${safeKey}"` : "";
  const voiceAttr = safeVoice ? ` data-voice="${safeVoice}"` : "";
  const voiceModelAttr = safeVoiceModel ? ` data-voice-model="${safeVoiceModel}"` : "";
  return (
    `<span class="trpg-dialogue" data-speaker-type="${type}"` +
    ` data-color-idx="${colorIdx}" data-speaker="${safeName}"` +
    ` data-speaker-source="${inferred ? "inferred" : "tag"}"` +
    `${emotionAttr}${keyAttr}${voiceAttr}${voiceModelAttr}${hasAvatarAttr}>` +
    `${avatarHtml}「${safeQuote}」</span>`
  );
}

/**
 * Replace `「quote」[speak]name[/speak]` runs with styled spans.
 *
 * Only runs that have an attached `[speak]` tag get the dialogue
 * treatment (avatar, speaker color, name badge). Untagged `「...」`
 * pass through as plain corner-bracketed text — corner brackets are
 * sometimes used by the GM for non-speech content (a name on a
 * document, text on a sign, a quoted phrase) and we do not want to
 * impersonate the previous speaker on such runs.
 *
 * The tag accepts optional `:emotion` and `:npc_key` modifiers (set by
 * the backend speaker_resolver). The key drives portrait/profile
 * lookup while emotion is preserved as metadata for future voice
 * playback.
 */
export function styleTrpgDialogue(
  text: string,
  optionsOrForce: StyleTrpgDialogueOptions | boolean = false,
): string {
  if (!text) return text;
  const options: StyleTrpgDialogueOptions = typeof optionsOrForce === "boolean"
    ? { forceTrpg: optionsOrForce }
    : optionsOrForce;

  return text.replace(
    /「([^」]*)」(?:\[speak(?::([\w-]*))?(?::([\w.-]+))?\]([\s\S]+?)\[\/speak\])?/g,
    (match, quote, rawEmotion, rawKey, rawName) => {
      if (!rawName) {
        // Untagged 「...」 — leave it alone. The corner brackets stay
        // visible so the GM's narrative phrasing reads naturally,
        // but no avatar / color / speaker badge attaches.
        return match;
      }
      const name = String(rawName).trim();
      const emotion = String(rawEmotion || "").trim();
      const npcKey = String(rawKey || "").trim();
      return renderDialogueSpan(quote, name, emotion, npcKey, false, options);
    },
  );
}
