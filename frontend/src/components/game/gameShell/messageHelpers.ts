import type { MessageDTO } from "../../../api/sessions";
import type { DiceType } from "../../dice/DiceIcons";
import type { ChatMessage, PendingCheckSummary } from "../Message";
import type { TrpgHudCurrentTime } from "../trpgHudTypes";
import { buildBuckets } from "../SceneTabs";

export type ManualRollValue = number | number[];

export type ActiveDiceRoll =
  | { kind: "free"; diceType: DiceType; notation: string }
  | {
      kind: "pending";
      gmMessageId: string;
      pending: PendingCheckSummary;
      notation: string;
    };

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function str(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function formatStamp(d: Date): string {
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

export function timeFromIso(iso: string): string {
  return formatStamp(new Date(iso));
}

export function nowTime(): string {
  return formatStamp(new Date());
}

export function normalizeDiceNotation(raw: string): string {
  const text = (raw || "").trim().toLowerCase();
  if (!text) return "";
  const normalized = text.replace(/\s+/g, "");
  if (!/^\d*d\d+([+-]\d+)?$/.test(normalized)) return "";
  return normalized.startsWith("d") ? `1${normalized}` : normalized;
}

export function notationForPendingCheck(pending: PendingCheckSummary): string {
  const pool = normalizeDiceNotation(pending.pool || "");
  if (pool) return pool;
  const engine = (pending.engine || "").toLowerCase();
  if (engine === "pbta_2d6") return "2d6";
  if (engine.includes("d100") || engine.includes("coc") || engine.includes("brp")) {
    return "1d100";
  }
  if (engine === "d20_vs_dc" || pending.target != null) return "1d20";
  return "1d20";
}

export function diceCountFromNotation(notation: string): number {
  const match = normalizeDiceNotation(notation).match(/^(\d*)d\d+/);
  if (!match) return 1;
  const rawCount = match[1] ? Number.parseInt(match[1], 10) : 1;
  return Number.isFinite(rawCount) && rawCount > 0 ? rawCount : 1;
}

export function manualRollValueForPending(
  pending: PendingCheckSummary,
  notation: string,
  result: { total: number; rolls: number[] },
): ManualRollValue {
  const engine = (pending.engine || "").toLowerCase();
  const count = diceCountFromNotation(notation);
  if ((engine === "pbta_2d6" || count > 1) && result.rolls.length > 1) {
    return result.rolls;
  }
  return result.total;
}

// Human-readable real-world gap between two ISO timestamps. Used by the
// scene-tab separator row to label how long the player was away before
// re-entering this scene. Granularities chosen to be readable at a glance
// without a translator: minutes / hours / days.
export function formatGap(fromIso: string, toIso: string): string {
  const a = Date.parse(fromIso);
  const b = Date.parse(toIso);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return "";
  const ms = b - a;
  const min = Math.round(ms / 60_000);
  if (min < 60) return `${min} min`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} h`;
  const days = Math.round(hr / 24);
  return `${days} d`;
}

// system rows that exist purely as LLM-context payload (e.g. the result of
// a `[SEARCH_RULES]` lookup) — chat history needs them so the next IC turn
// sees the rule excerpt, but the player's chat view should not show them.
export function isInternalContextSystemRow(m: MessageDTO): boolean {
  if (m.role !== "system") return false;
  const src = (m.metadata ?? {}) as { source?: unknown };
  return typeof src.source === "string" && src.source === "search_rules";
}

export function readHudCurrentTime(value: unknown): TrpgHudCurrentTime | null {
  const rec = asRecord(value);
  const day = rec.day;
  const clock = str(rec.clock);
  const date = str(rec.date);
  const period = str(rec.period);
  const out: TrpgHudCurrentTime = {};
  if (typeof day === "number" && Number.isFinite(day)) out.day = day;
  else if (typeof day === "string" && day.trim()) out.day = day.trim();
  if (clock) out.clock = clock;
  if (date) out.date = date;
  if (period) out.period = period;
  return Object.keys(out).length > 0 ? out : null;
}

function deriveBp123mStep(metadata: Record<string, unknown> | null): string | null {
  const meta = asRecord(metadata);
  const projection = asRecord(meta.context_cache_projection);
  if (Object.keys(projection).length === 0) return null;
  const snapshotState =
    meta.bp_snapshot && typeof meta.bp_snapshot === "object"
      ? "ready"
      : "legacy_missing";
  const projectionName = str(projection.projection) || "layered_prompt_v1";
  const error = str(projection.error);
  if (error) {
    return `[BP123M] snapshot=${snapshotState} | projection=${projectionName} | error=${error.slice(0, 160)}`;
  }
  const parts = [
    `snapshot=${snapshotState}`,
    `projection=${projectionName}`,
    `blocks=${num(projection.block_count)}`,
    `tokens=${num(projection.token_estimate)}`,
  ];
  const hash = str(projection.prefix_hash).slice(0, 12);
  const visibility = str(projection.visibility_signature).slice(0, 12);
  if (hash) parts.push(`hash=${hash}`);
  if (visibility) parts.push(`visibility=${visibility}`);
  return `[BP123M] ${parts.join(" | ")}`;
}

function deriveCacheStep(metadata: Record<string, unknown> | null): string | null {
  const meta = asRecord(metadata);
  const cache = asRecord(meta.cache_metrics);
  if (Object.keys(cache).length === 0) return null;

  const provider = str(cache.prompt_provider) || "?";
  const model = str(cache.prompt_model) || "?";
  if (cache.usage_available === false) {
    return `[cache] provider=${provider} model=${model} | usage=unavailable`;
  }

  const input = num(cache.input_tokens);
  const output = num(cache.output_tokens);
  const cached = num(cache.cached_tokens);
  const ratio =
    typeof cache.cache_hit_ratio === "number" &&
    Number.isFinite(cache.cache_hit_ratio)
      ? `${(cache.cache_hit_ratio * 100).toFixed(1)}%`
      : "?";
  return `[cache] provider=${provider} model=${model} | input=${input} | output=${output} | cached=${cached} | hit=${ratio}`;
}

function appendDerivedThinkingSteps(
  steps: string[] | undefined,
  derived: string[]
): string[] | undefined {
  if (derived.length === 0) return steps;
  const out = [...(steps ?? [])];
  for (const step of derived) {
    const prefix = step.startsWith("[cache]")
      ? "[cache]"
      : step.startsWith("[BP123M]")
        ? "[BP123M]"
        : step;
    if (!out.some((existing) => existing.startsWith(prefix))) {
      out.push(step);
    }
  }
  return out.length > 0 ? out : steps;
}

export function dtoToChatMessage(m: MessageDTO): ChatMessage {
  const baseMeta = (m.metadata ?? {}) as {
    phase?: string;
    scene_key?: string | null;
    scene_name?: string | null;
    current_time?: unknown;
    pending_checks?: unknown;
    thinking_steps?: unknown;
  };
  const sceneFields = {
    createdAt: m.created_at,
    phase: typeof baseMeta.phase === "string" ? baseMeta.phase : undefined,
    sceneKey: typeof baseMeta.scene_key === "string" ? baseMeta.scene_key : null,
    sceneName: typeof baseMeta.scene_name === "string" ? baseMeta.scene_name : null,
    currentTime: readHudCurrentTime(baseMeta.current_time),
  };
  if (m.role === "dice") {
    const meta = (m.metadata ?? {}) as {
      type?: string;
      result?: number;
      dc?: number;
    };
    return {
      id: m.id,
      role: "dice",
      type: meta.type ?? "Roll",
      result: typeof meta.result === "number" ? meta.result : 0,
      dc: typeof meta.dc === "number" ? meta.dc : 0,
      time: timeFromIso(m.created_at),
      ...sceneFields,
    };
  }
  // Pull persisted Chain of Thought back off metadata.thinking_steps. Only
  // GM messages carry these; user/system rows never have them.
  const rawSteps = (m.metadata as { thinking_steps?: unknown } | null)
    ?.thinking_steps;
  const thinkingSteps =
    m.role === "gm" && Array.isArray(rawSteps)
      ? (rawSteps as unknown[])
          .map((s) => (typeof s === "string" ? s : ""))
          .filter((s): s is string => !!s)
      : undefined;
  const derivedThinkingSteps =
    m.role === "gm"
      ? [deriveBp123mStep(m.metadata), deriveCacheStep(m.metadata)].filter(
          (s): s is string => !!s
        )
      : [];
  const finalThinkingSteps = appendDerivedThinkingSteps(
    thinkingSteps,
    derivedThinkingSteps
  );
  // BP3 inputs frozen at GM-reply time — lets the debug panel render the
  // context this exact turn was generated from instead of live state.
  const rawSnapshot = (m.metadata as { bp_snapshot?: unknown } | null)
    ?.bp_snapshot;
  const bpSnapshot =
    m.role === "gm" && rawSnapshot && typeof rawSnapshot === "object"
      ? (rawSnapshot as ChatMessage["bpSnapshot"])
      : undefined;
  const pendingChecks =
    m.role === "gm" && Array.isArray(baseMeta.pending_checks)
      ? (baseMeta.pending_checks as unknown[])
          .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
          .map((p) => ({
            id: String(p.id ?? ""),
            engine: typeof p.engine === "string" ? p.engine : undefined,
            skill: typeof p.skill === "string" ? p.skill : undefined,
            value: typeof p.value === "number" ? p.value : null,
            difficulty:
              typeof p.difficulty === "string" ? p.difficulty : undefined,
            target: typeof p.target === "number" ? p.target : null,
            pool: typeof p.pool === "string" ? p.pool : undefined,
            bonus: typeof p.bonus === "number" ? p.bonus : undefined,
            penalty: typeof p.penalty === "number" ? p.penalty : undefined,
            reason: typeof p.reason === "string" ? p.reason : undefined,
            resolved: p.resolved === true,
          }))
          .filter((p) => p.id)
      : undefined;
  return {
    id: m.id,
    role: m.role as ChatMessage["role"],
    text: m.content,
    time: m.role === "system" ? undefined : timeFromIso(m.created_at),
    metadata: m.metadata,
    thinkingSteps: finalThinkingSteps,
    pendingChecks,
    bpSnapshot,
    ...sceneFields,
  };
}

// Filter the timeline by the selected scene tab. null = follow latest, in
// which case we always show the most recent scene's messages — that way
// new turns slide in without the player toggling anything. Streaming
// optimistic placeholders (no createdAt yet) are always shown so the GM
// bubble appears immediately while a turn is in flight. When a scene was
// re-entered, we splice in a synthetic separator row at each return so the
// gap (where the player went meanwhile) is obvious instead of looking like
// a teleport.
export function filterDisplayedMessages(
  messages: ChatMessage[],
  activeSceneKey: string | null,
  labels: {
    guide: string;
    unnamed: string;
    returnSeparator: (vars: { duration: string; scene: string }) => string;
  },
): ChatMessage[] {
  if (messages.length === 0) return messages;
  const buckets = buildBuckets(messages, {
    guide: labels.guide,
    unnamed: labels.unnamed,
  });
  if (buckets.length <= 1) return messages;
  const latestKey = buckets[buckets.length - 1].key;
  const targetKey = activeSceneKey ?? latestKey;
  const target =
    buckets.find((b) => b.key === targetKey) ?? buckets[buckets.length - 1];

  const returnByStartId = new Map<string, string>();
  for (let i = 1; i < target.visits.length; i++) {
    const v = target.visits[i];
    returnByStartId.set(v.startMessageId, v.prevLeftAt);
  }

  const filtered: ChatMessage[] = [];
  for (const m of messages) {
    if (!target.messageIds.has(m.id) && m.createdAt) continue;
    const gapFrom = returnByStartId.get(m.id);
    if (gapFrom && m.createdAt) {
      filtered.push({
        id: `__sep__:${target.key}:${m.id}`,
        role: "system",
        text: labels.returnSeparator({
          duration: formatGap(gapFrom, m.createdAt),
          scene: target.label,
        }),
      });
    }
    filtered.push(m);
  }
  return filtered;
}
