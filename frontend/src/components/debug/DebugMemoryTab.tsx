import { useEffect, useState } from "react";
import { useI18n } from "../../i18n";
import {
  getNpcRuntimeDebugAPI,
  getSessionAPI,
  getPublicMemoryViewAPI,
  listCheckLogsAPI,
  listTurnTracesAPI,
  type CheckLogDTO,
  type NpcRuntimeDebugDTO,
  type PublicMemoryViewDTO,
  type SessionDetailDTO,
  type TurnTraceDTO,
} from "../../api/sessions";
import { ExpandableRow, Pre, Row, Section } from "./primitives";
import { EmptyHint } from "./debugMemory/EmptyHint";
import {
  checkLogToDiceEntry,
  readBackgroundPlannerCards,
} from "./debugMemory/formatters";
import {
  formatElapsed,
  isRecord,
  pickKey,
  pickName,
  readArray,
  readObject,
  truncate,
} from "./debugMemory/utils";
import {
  NpcActionCardsSection,
  NpcPlannerSection,
} from "./debugMemory/sections/PlannerSections";
import { PublicViewSection } from "./debugMemory/sections/PublicViewSection";
import { TurnTracesSection } from "./debugMemory/sections/TurnTracesSection";
import { DiceSection } from "./debugMemory/sections/DiceSection";

interface Props {
  sessionId: string | null;
}

// Live mirror of `session.memory_state` + `module_state` + `dice_history` +
// `character`. This is the GM's authoritative game memory: what scenes are
// known, who's been met, what plot threads are open, what facts the world
// has learned, what time/scene we're in, what dice were rolled.
//
// On every focus we refetch the session (no websocket yet); the IC pipeline
// updates these fields on each turn so polling on tab open is enough.
export function DebugMemoryTab({ sessionId }: Props) {
  const { t } = useI18n();
  const [data, setData] = useState<SessionDetailDTO | null>(null);
  const [checkLogs, setCheckLogs] = useState<CheckLogDTO[]>([]);
  const [turnTraces, setTurnTraces] = useState<TurnTraceDTO[]>([]);
  const [publicView, setPublicView] = useState<PublicMemoryViewDTO | null>(null);
  const [npcRuntime, setNpcRuntime] = useState<NpcRuntimeDebugDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    if (!sessionId) {
      setData(null);
      setCheckLogs([]);
      setTurnTraces([]);
      setPublicView(null);
      setNpcRuntime(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [detail, logs, traces, memoryView, runtimeDebug] = await Promise.all([
          getSessionAPI(sessionId),
          listCheckLogsAPI(sessionId, 50).catch(() => null),
          listTurnTracesAPI(sessionId, 25).catch(() => null),
          getPublicMemoryViewAPI(sessionId).catch(() => null),
          getNpcRuntimeDebugAPI(sessionId).catch(() => null),
        ]);
        if (cancelled) return;
        setData(detail);
        setCheckLogs(logs?.items ?? []);
        setTurnTraces(traces?.items ?? []);
        setPublicView(memoryView);
        setNpcRuntime(runtimeDebug);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Load failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, refreshTick]);

  if (!sessionId) {
    return (
      <div className="text-[12px] italic text-text-3 px-1 py-2">
        {t("debugMemoryNoSession")}
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-[12px] text-[#f87171] px-1 py-2">{error}</div>
    );
  }
  if (loading && !data) {
    return (
      <div className="text-[12px] italic text-text-3 px-1 py-2">
        {t("debugMemoryLoading")}
      </div>
    );
  }
  if (!data) return null;

  const memory = (data.memory_state ?? {}) as Record<string, unknown>;
  const moduleState = (data.module_state ?? {}) as Record<string, unknown>;
  const character = (data.character ?? {}) as Record<string, unknown>;
  const diceHistory = Array.isArray(data.dice_history) ? data.dice_history : [];
  const diceEntries = checkLogs.length > 0
    ? checkLogs.map(checkLogToDiceEntry)
    : diceHistory.slice(-50).reverse();

  const scenes = readArray(memory.scenes);
  const npcs = readArray(memory.npcs);
  const plotThreads = readArray(memory.plot_threads);
  const worldFacts = memory.world_facts;
  const narrative = typeof memory.narrative === "string" ? memory.narrative : "";
  const playerNotes = readArray(memory.player_notes);
  const recentEvents = readArray(memory.recent_events);
  const discoveries = readArray(memory.player_discoveries);
  const plannerState = readObject(memory._npc_background_planner_v2);
  const memoryPlannerLatest = readObject(plannerState.latest);
  const runtimePlannerLatest = readObject(npcRuntime?.planner_latest);
  const plannerLatest = Object.keys(memoryPlannerLatest).length > 0
    ? memoryPlannerLatest
    : runtimePlannerLatest;
  const memoryPlannerAllRuns = readArray(plannerState.runs).filter(isRecord);
  const runtimePlannerAllRuns = readArray(npcRuntime?.planner_runs).filter(isRecord);
  const plannerAllRuns = memoryPlannerAllRuns.length > 0
    ? memoryPlannerAllRuns
    : runtimePlannerAllRuns;
  const plannerRuns = plannerAllRuns.slice(-5).reverse();
  const memoryPlannerCards = readBackgroundPlannerCards(readObject(memory._npc_action_board_v2));
  const runtimePlannerCards = readBackgroundPlannerCards(readObject(npcRuntime?.action_board));
  const plannerCards = memoryPlannerCards.length > 0
    ? memoryPlannerCards
    : runtimePlannerCards;

  const elapsedMinutes = Number(moduleState.elapsed_minutes ?? 0) || 0;
  const dayCount = Number(moduleState.day_count ?? 1) || 1;
  const inGameTime = String(moduleState.in_game_time ?? "—");
  const objective = String(moduleState.objective ?? "—");

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 px-0.5">
        <span className="text-[10.5px] uppercase tracking-[0.06em] text-text-3 font-semibold">
          {t("debugMemoryTitle")}
        </span>
        <button
          type="button"
          onClick={() => setRefreshTick((n) => n + 1)}
          className="text-[10.5px] text-text-3 hover:text-text px-1.5 py-0.5 rounded hover:bg-surface-2 transition-colors"
        >
          {t("debugMemoryRefresh")}
        </button>
      </div>

      <Section title={t("debugMemorySecOverview")}>
        <Row label={t("debugMemoryNarrSummary")} value={truncate(data.narrative_summary || "—", 80)} />
        <Row label={t("debugMemorySummarizedAt")} value={String(data.last_summarized_msg_count ?? 0)} />
        <Row
          label={t("debugMemoryScene")}
          value={String(moduleState.scene ?? "—")}
          mono
        />
        <Row
          label={t("debugMemorySceneReason")}
          value={String(moduleState.scene_reason ?? "—")}
        />
        <Row
          label={t("debugMemoryDay")}
          value={`${t("debugMemoryDayPrefix")} ${dayCount} · ${inGameTime}`}
          mono
        />
        <Row
          label={t("debugMemoryElapsed")}
          value={formatElapsed(elapsedMinutes)}
          mono
        />
        <Row label={t("debugMemoryObjective")} value={truncate(objective, 80)} />
      </Section>

      <Section title={`${t("debugMemorySecScenes")} (${scenes.length})`}>
        {scenes.length === 0 ? (
          <EmptyHint />
        ) : (
          scenes.map((s, i) => (
            <ExpandableRow
              key={`scene-${i}`}
              label={`#${i + 1}`}
              value={pickName(s) || `scene_${i}`}
            >
              <Pre json={s} />
            </ExpandableRow>
          ))
        )}
      </Section>

      <Section title={`${t("debugMemorySecNPCs")} (${npcs.length})`}>
        {npcs.length === 0 ? (
          <EmptyHint />
        ) : (
          npcs.map((n, i) => (
            <ExpandableRow
              key={`npc-${i}`}
              label={pickName(n) || `npc_${i}`}
              value={pickKey(n) || ""}
              mono
            >
              <Pre json={n} />
            </ExpandableRow>
          ))
        )}
      </Section>

      <NpcPlannerSection
        plannerLatest={plannerLatest}
        plannerRuns={plannerRuns}
        plannerAllRunsCount={plannerAllRuns.length}
      />

      <NpcActionCardsSection plannerCards={plannerCards} />

      <Section title={`${t("debugMemorySecEvents")} (${recentEvents.length})`}>
        {recentEvents.length === 0 ? (
          <EmptyHint />
        ) : (
          [...recentEvents].reverse().slice(0, 12).map((e, i) => {
            const ev = e as Record<string, unknown>;
            return (
              <Row
                key={`event-${i}`}
                label={`#${recentEvents.length - i}`}
                value={String(ev.summary ?? "")}
              />
            );
          })
        )}
      </Section>

      <PublicViewSection publicView={publicView} />

      <TurnTracesSection turnTraces={turnTraces} />

      <Section title={`${t("debugMemorySecDiscoveries")} (${discoveries.length})`}>
        {discoveries.length === 0 ? (
          <EmptyHint />
        ) : (
          [...discoveries].reverse().slice(0, 12).map((d, i) => {
            const dd = d as Record<string, unknown>;
            return (
              <Row
                key={`discovery-${i}`}
                label={`#${discoveries.length - i}`}
                value={String(dd.summary ?? "")}
              />
            );
          })
        )}
      </Section>

      <Section title={`${t("debugMemorySecPlots")} (${plotThreads.length})`}>
        {plotThreads.length === 0 ? (
          <EmptyHint />
        ) : (
          plotThreads.map((p, i) => (
            <ExpandableRow
              key={`plot-${i}`}
              label={`#${i + 1}`}
              value={pickName(p) || pickKey(p) || `plot_${i}`}
            >
              <Pre json={p} />
            </ExpandableRow>
          ))
        )}
      </Section>

      <Section title={t("debugMemorySecWorld")}>
        {!worldFacts || (typeof worldFacts === "object" && !Array.isArray(worldFacts) && Object.keys(worldFacts as object).length === 0) ? (
          <EmptyHint />
        ) : (
          <Pre json={worldFacts} />
        )}
      </Section>

      {narrative && (
        <Section title={t("debugMemorySecNarrative")}>
          <Pre text={narrative} />
        </Section>
      )}

      <Section title={`${t("debugMemorySecNotes")} (${playerNotes.length})`}>
        {playerNotes.length === 0 ? (
          <EmptyHint />
        ) : (
          [...playerNotes].reverse().map((n, i) => {
            const note = n as Record<string, unknown>;
            const tags = Array.isArray(note.tags) ? (note.tags as string[]) : [];
            return (
              <ExpandableRow
                key={`note-${i}`}
                label={`#${playerNotes.length - i}`}
                value={truncate(String(note.content ?? ""), 70) +
                  (tags.length ? ` [${tags.join(", ")}]` : "")}
              >
                <Pre json={note} />
              </ExpandableRow>
            );
          })
        )}
      </Section>

      <DiceSection diceEntries={diceEntries} />

      <Section title={t("debugMemorySecCharacter")}>
        {Object.keys(character).length === 0 ? (
          <EmptyHint />
        ) : (
          <Pre json={character} clip={4000} />
        )}
      </Section>
    </div>
  );
}
