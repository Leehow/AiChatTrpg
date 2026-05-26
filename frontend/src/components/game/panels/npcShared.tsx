/**
 * Shared bits used by both `NpcPanel` (the sidebar grid) and
 * `NpcDetailModal` (the popup card). Kept in its own module so the two
 * sibling files can reach the same type, label dict, and presence pill
 * without a circular import.
 */
import { useI18n } from "../../../i18n";

export type NpcStatus = "alive" | "injured" | "dead" | "unknown";

export interface NpcEntry {
  key: string;
  name: string;
  role?: string;
  portrait_url?: string;
  gender?: string;
  status: NpcStatus;
  description?: string;
  knownFacts?: string[];
  nameRevealed?: boolean;
  lastSeen?: string;
  /** True when the NPC's `last_seen_scene` matches the session's current
   *  scene — i.e. the player should perceive them as in the same room.
   *  Computed by GameShell from `memory_state.current_scene` /
   *  `module_state.scene`. Undefined means we have no scene info yet. */
  isPresent?: boolean;
  /** Currently active TTS voice id (`active_tts_voice` || `tts_voice`). */
  voice?: string;
  /** Backend flag set when the player manually picks a voice — protects
   *  that NPC from being clobbered by `rematch-voices`. Surfaced in the
   *  UI as a small lock hint next to the voice selector. */
  tts_voice_locked?: boolean;
  /** Cached voice intro text from a prior synthesis call. Lets the modal
   *  show what was last spoken without firing a new request. */
  voice_intro_text?: string;
  /** Cached audio URL for the voice intro (served from `data/media/`). */
  voice_intro_audio_url?: string;
  /** NPC was created from a PC backstory bond rather than a GM marker.
   *  Gates the bond-enrich action in the NPC panel. */
  fromBond?: boolean;
  /** Bond NPC is still missing rich profile fields the bond-enrich pass
   *  would fill (description / personality / relationship_dynamic /
   *  voice_card with at least one non-blank entry). Mirrors the backend
   *  `is_bond_npc_unfinished` predicate. */
  needsBondEnrichment?: boolean;
  /** ISO timestamp the last successful bond enrichment stamped. */
  bondEnrichedAt?: string;
}

export interface NpcLabels {
  title: string;
  empty: string;
  close: string;
  description: string;
  knownInfo: string;
  noDescription: string;
  noKnownInfo: string;
  identityUnknown: string;
  identityKnown: string;
  status: Record<NpcStatus, string>;
  presence: { present: string; absent: string };
}

// Keep labels here (instead of i18n keys) until the messages dict has
// proper entries for npc panel — adding them blindly causes the strict
// MessageKey union to reject untyped strings.
const LABELS: Record<string, NpcLabels> = {
  zh: {
    title: "NPC",
    empty: "暂无 NPC",
    close: "关闭",
    description: "描述",
    knownInfo: "PC 已知信息",
    noDescription: "还没有可靠描述。",
    noKnownInfo: "还没有更多已知信息。",
    identityUnknown: "真实姓名未确认",
    identityKnown: "身份已确认",
    status: { alive: "存活", injured: "受伤", dead: "死亡", unknown: "未知" },
    presence: { present: "在场", absent: "不在场" },
  },
  en: {
    title: "NPCs",
    empty: "No NPCs yet",
    close: "Close",
    description: "Description",
    knownInfo: "Known to PC",
    noDescription: "No reliable description yet.",
    noKnownInfo: "No further known information.",
    identityUnknown: "True name unconfirmed",
    identityKnown: "Identity confirmed",
    status: { alive: "Alive", injured: "Injured", dead: "Dead", unknown: "Unknown" },
    presence: { present: "Present", absent: "Absent" },
  },
  ja: {
    title: "NPC",
    empty: "NPC はまだいません",
    close: "閉じる",
    description: "描写",
    knownInfo: "PC の既知情報",
    noDescription: "信頼できる描写はまだありません。",
    noKnownInfo: "追加の既知情報はまだありません。",
    identityUnknown: "本名未確認",
    identityKnown: "身元確認済み",
    status: { alive: "生存", injured: "負傷", dead: "死亡", unknown: "不明" },
    presence: { present: "在場", absent: "不在" },
  },
  de: {
    title: "NSCs",
    empty: "Noch keine NSCs",
    close: "Schließen",
    description: "Beschreibung",
    knownInfo: "Dem SC bekannt",
    noDescription: "Noch keine verlässliche Beschreibung.",
    noKnownInfo: "Noch keine weiteren bekannten Informationen.",
    identityUnknown: "Wahrer Name unbestätigt",
    identityKnown: "Identität bestätigt",
    status: { alive: "Lebt", injured: "Verletzt", dead: "Tot", unknown: "Unbekannt" },
    presence: { present: "Anwesend", absent: "Abwesend" },
  },
  fr: {
    title: "PNJ",
    empty: "Aucun PNJ pour l’instant",
    close: "Fermer",
    description: "Description",
    knownInfo: "Connu du PJ",
    noDescription: "Pas encore de description fiable.",
    noKnownInfo: "Aucune autre information connue.",
    identityUnknown: "Vrai nom non confirmé",
    identityKnown: "Identité confirmée",
    status: { alive: "Vivant", injured: "Blessé", dead: "Mort", unknown: "Inconnu" },
    presence: { present: "Présent", absent: "Absent" },
  },
  es: {
    title: "PNJ",
    empty: "Aún no hay PNJ",
    close: "Cerrar",
    description: "Descripción",
    knownInfo: "Conocido por el PJ",
    noDescription: "Aún no hay una descripción fiable.",
    noKnownInfo: "Aún no hay más información conocida.",
    identityUnknown: "Nombre real sin confirmar",
    identityKnown: "Identidad confirmada",
    status: { alive: "Vivo", injured: "Herido", dead: "Muerto", unknown: "Desconocido" },
    presence: { present: "Presente", absent: "Ausente" },
  },
  ru: {
    title: "NPC",
    empty: "NPC пока нет",
    close: "Закрыть",
    description: "Описание",
    knownInfo: "Известно персонажу",
    noDescription: "Надежного описания пока нет.",
    noKnownInfo: "Других известных сведений пока нет.",
    identityUnknown: "Настоящее имя не подтверждено",
    identityKnown: "Личность подтверждена",
    status: { alive: "Жив", injured: "Ранен", dead: "Мертв", unknown: "Неизв." },
    presence: { present: "Здесь", absent: "Не здесь" },
  },
};

export function useNpcLabels(): NpcLabels {
  const { locale } = useI18n();
  return LABELS[locale] || LABELS.en;
}

export function NpcPresencePill({ present }: { present: boolean }) {
  const labels = useNpcLabels();
  const cls = present
    ? "bg-emerald-500/10 text-emerald-700 border-emerald-500/25"
    : "bg-surface-2 text-text-3 border-border";
  return (
    <div className={`mt-0.5 max-w-full truncate rounded-full border px-1.5 py-[1px] text-[9px] leading-tight ${cls}`}>
      {labels.presence[present ? "present" : "absent"]}
    </div>
  );
}
