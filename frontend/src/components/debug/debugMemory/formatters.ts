import type { CheckLogDTO, TurnTraceDTO } from "../../../api/sessions";
import {
  displayValue,
  numberValue,
  readArray,
  readObject,
  readStringArray,
  truncate,
} from "./utils";

export function checkLogToDiceEntry(log: CheckLogDTO): Record<string, unknown> {
  return {
    check_log_id: log.id,
    message_id: log.message_id,
    expression: log.trace.roll_expression ?? log.engine,
    engine: log.engine,
    procedure_id: log.procedure_id,
    actor_id: log.actor_id,
    result: log.trace.roll_total ?? log.trace.roll ?? null,
    request: log.request,
    result_detail: log.result,
    warnings: log.warnings,
    skill: log.skill,
    value: log.request.value,
    difficulty: log.request.difficulty,
    reason: log.request.reason ?? log.trace.reason,
    time: log.created_at,
    source: log.source,
    seed: log.seed,
    roll_trace: log.roll_trace,
    trace: log.trace,
  };
}

export function formatTurnTraceSummary(trace: TurnTraceDTO): string {
  const summary = trace.parsed_contract_summary || {};
  const diff = readObject(summary.diff_summary);
  const auto = readObject(summary.auto_memory_v2);
  const pieces = [
    trace.player_input ? truncate(trace.player_input, 36) : "",
    `mem ${displayValue(auto.proposed ?? trace.memory_proposal_count)}/${trace.committed_memory_ids.length}`,
    `markers ${displayValue(summary.marker_count)}`,
    Object.keys(diff).length ? `diff ${Object.keys(diff).length}` : "",
  ];
  return pieces.filter(Boolean).join(" · ");
}

export function formatTraceChecks(trace: TurnTraceDTO): string {
  const summary = trace.parsed_contract_summary || {};
  const checks = readArray(summary.check_logs);
  if (checks.length === 0) return "—";
  return checks
    .slice(0, 4)
    .map((raw) => {
      const item = readObject(raw);
      return [
        item.procedure_id,
        item.engine,
        item.seed ? `seed=${String(item.seed).slice(0, 8)}` : "",
      ].filter(Boolean).join("/");
    })
    .join(" · ");
}

export function formatTraceStructured(trace: TurnTraceDTO): string {
  const summary = trace.parsed_contract_summary || {};
  const structured = readObject(summary.structured_events);
  const events = readArray(structured.events);
  const errors = readArray(structured.errors);
  if (!events.length && !errors.length) return "—";
  return `${events.length} events${errors.length ? ` · ${errors.length} errors` : ""}`;
}

export function formatTraceCache(trace: TurnTraceDTO): string {
  const metrics = trace.cache_metrics || {};
  const provider = displayValue(metrics.prompt_provider);
  const model = displayValue(metrics.prompt_model);
  const prefix = trace.context_prefix_hash ? trace.context_prefix_hash.slice(0, 10) : "";
  return [provider, model, prefix ? `prefix=${prefix}` : ""]
    .filter((v) => v && v !== "—")
    .join(" · ") || "—";
}

export function formatTraceContextBlocks(trace: TurnTraceDTO): string {
  const projection = readObject(trace.parsed_contract_summary.context_cache_projection);
  const prefix = displayValue(projection.prefix_block_count);
  const pinned = displayValue(projection.pinned_block_count);
  const dynamic = displayValue(projection.dynamic_block_count);
  const ids = Array.isArray(trace.retrieved_context_block_ids)
    ? trace.retrieved_context_block_ids.length
    : readArray(projection.block_version_ids).length;
  if (prefix === "—" && pinned === "—" && dynamic === "—" && ids === 0) return "—";
  return [`ids=${ids}`, `p=${prefix}`, `mid=${pinned}`, `tail=${dynamic}`].join(" · ");
}

export function formatTraceContextProjection(trace: TurnTraceDTO): string {
  const projection = readObject(trace.parsed_contract_summary.context_cache_projection);
  const cacheKey = String(projection.cache_key ?? trace.context_cache_key ?? "").trim();
  const tokenEstimate = displayValue(projection.token_estimate);
  const blockCount = displayValue(projection.block_count);
  return [
    cacheKey ? truncate(cacheKey, 48) : "",
    blockCount !== "—" ? `blocks=${blockCount}` : "",
    tokenEstimate !== "—" ? `tokens≈${tokenEstimate}` : "",
  ].filter(Boolean).join(" · ") || "—";
}

export function formatTraceKnowledge(trace: TurnTraceDTO): string {
  const summary = trace.parsed_contract_summary || {};
  const candidates = [
    readObject(summary.knowledge_profile),
    readObject(summary.npc_knowledge),
    readObject(readObject(summary.npc_runtime_read).knowledge_profile),
    readObject(readObject(summary.npc_post_visible_work).knowledge_profile),
  ].filter((item) => Object.keys(item).length > 0);
  const knowledge = candidates[0] || {};
  const profileCount = displayValue(knowledge.profile_count);
  const visible = displayValue(knowledge.visible_memory_count);
  const withheld = displayValue(knowledge.withheld_memory_count);
  const leaks = displayValue(
    summary.knowledge_leak_blocked
      ?? readObject(summary.npc_post_visible_work).knowledge_leak_blocked,
  );
  if ([profileCount, visible, withheld, leaks].every((value) => value === "—")) return "—";
  return [
    profileCount !== "—" ? `profiles=${profileCount}` : "",
    visible !== "—" ? `visible=${visible}` : "",
    withheld !== "—" ? `withheld=${withheld}` : "",
    leaks !== "—" ? `blocked=${leaks}` : "",
  ].filter(Boolean).join(" · ");
}

export function formatPlannerKnowledge(run: Record<string, unknown>): string {
  const knowledge = readObject(run.knowledge_profile);
  if (Object.keys(knowledge).length === 0) return "—";
  return [
    `profiles=${displayValue(knowledge.profile_count)}`,
    `visible=${displayValue(knowledge.visible_memory_count)}`,
    `withheld=${displayValue(knowledge.withheld_memory_count)}`,
    `loaded=${displayValue(knowledge.loaded_memory_count)}`,
  ].join(" · ");
}

export function formatPlannerLeaks(run: Record<string, unknown>): string {
  const warnings = displayValue(run.knowledge_leak_warning_count);
  const blocked = displayValue(run.knowledge_leak_blocked);
  const transformed = displayValue(run.secret_guard_transformed);
  const secretBlocked = displayValue(run.secret_guard_blocked);
  if ([warnings, blocked, transformed, secretBlocked].every((value) => value === "—")) return "—";
  return [
    `warn=${warnings}`,
    `blocked=${blocked}`,
    `guard=${transformed}/${secretBlocked}`,
  ].join(" · ");
}

export function formatDiceSummary(
  entry: Record<string, unknown>,
  trace: Record<string, unknown>,
): string {
  const result = displayValue(entry.result ?? trace.roll_total ?? trace.roll);
  const tier = displayValue(
    readObject(entry.result_detail).tier_label
      ?? readObject(entry.result_detail).tier
      ?? trace.tier_label
      ?? trace.tier,
  );
  const reason = String(entry.reason ?? trace.reason ?? "").trim();
  return [
    `= ${result}`,
    tier !== "—" ? tier : "",
    reason ? truncate(reason, 42) : "",
  ].filter(Boolean).join(" · ");
}

export function formatTier(
  resultDetail: Record<string, unknown>,
  trace: Record<string, unknown>,
): string {
  const tier = displayValue(resultDetail.tier_label ?? resultDetail.tier ?? trace.tier_label ?? trace.tier);
  const passed = resultDetail.passed ?? trace.passed;
  if (passed === true) return `${tier} · pass`;
  if (passed === false) return `${tier} · fail`;
  return tier;
}

export function readHouseRules(trace: Record<string, unknown>): string[] {
  const axes = readObject(trace.result_axes);
  const house = readObject(axes._house_rules);
  return readStringArray(house.ids);
}

export function summarizeDiceRequest(request: Record<string, unknown>): string {
  return [
    request.procedure_id,
    request.skill,
    request.value == null ? "" : `value=${String(request.value)}`,
    request.difficulty,
  ].filter(Boolean).map(String).join(" · ") || "json";
}

export function formatStringList(v: unknown): string {
  const items = readStringArray(v);
  if (items.length === 0) return "—";
  const shown = items.slice(0, 6);
  return shown.join(", ") + (items.length > shown.length ? ` +${items.length - shown.length}` : "");
}

export function formatPlannerStatus(run: Record<string, unknown>): string {
  const status = displayValue(run.status);
  const skipped = String(run.skipped ?? "").trim();
  return skipped ? `${status} · ${skipped}` : status;
}

export interface BackgroundPlannerCard {
  sceneId: string;
  cardId: string;
  npcId: string;
  basedOnTurnId: number;
  validUntilTurn: number;
  priority: number;
  intent: string;
  actionType: string;
  triggers: string[];
  raw: Record<string, unknown>;
}

export function readBackgroundPlannerCards(board: Record<string, unknown>): BackgroundPlannerCard[] {
  const scenes = readObject(board.scenes);
  const cards: BackgroundPlannerCard[] = [];
  for (const [sceneId, rawCards] of Object.entries(scenes)) {
    for (const raw of readArray(rawCards)) {
      const card = readObject(raw);
      if (Object.keys(card).length === 0) continue;
      const metadata = readObject(card.metadata);
      const preferred = readObject(card.preferred_action);
      const gmFacing = readObject(preferred.gm_facing);
      if (metadata.planner !== "llm_background" && gmFacing.planner !== "llm_background") {
        continue;
      }
      cards.push({
        sceneId,
        cardId: displayValue(card.card_id),
        npcId: displayValue(card.npc_id),
        basedOnTurnId: numberValue(card.based_on_turn_id),
        validUntilTurn: numberValue(card.valid_until_turn),
        priority: numberValue(card.priority),
        intent: displayValue(preferred.intent || card.motivation),
        actionType: displayValue(preferred.action_type),
        triggers: readTriggerLabels(card.trigger_conditions),
        raw: card,
      });
    }
  }
  return cards.sort((a, b) => {
    if (b.basedOnTurnId !== a.basedOnTurnId) {
      return b.basedOnTurnId - a.basedOnTurnId;
    }
    return b.priority - a.priority;
  });
}

function readTriggerLabels(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.map((item) => {
    if (typeof item === "string") return item.trim();
    const raw = readObject(item);
    if (Object.keys(raw).length === 0) return "";
    const eventType = String(raw.event_type ?? raw.type ?? "").trim();
    const topic = String(raw.topic_tag ?? raw.topic ?? raw.tag ?? "").trim();
    const actor = String(raw.actor_id ?? raw.actor ?? "").trim();
    const targets = readStringArray(raw.target_ids).join(",");
    return [eventType, topic, actor, targets ? `→${targets}` : ""]
      .filter(Boolean)
      .join(":");
  }).filter(Boolean);
}
