/**
 * Per-message post-processing timeline. Polls the backend until the
 * `phase3_complete` event lands, then stops. Mirrors ChatLab's
 * TrpgPostprocessDebug.vue: collapsible, compact, monospace, with
 * spinner-while-running and check-when-done indicators.
 *
 * Mounted under each GM message in [Message.tsx]. Does nothing for
 * messages without an id or before any step has been recorded — the
 * component is invisible until the backend writes its first event.
 */

import { useEffect, useRef, useState } from "react";
import { useI18n, type MessageKey } from "../../i18n";
import {
  getMessagePostprocessStepsAPI,
  type PostprocessStepDTO,
} from "../../api/sessions";

interface Props {
  sessionId?: string | null;
  messageId: string;
}

const FAST_POLL_LIMIT = 60;
const FAST_POLL_MS = 1500;
const SLOW_POLL_MS = 5000;

const STEP_LABEL_KEYS: Record<string, MessageKey> = {
  action_board_warm: "ppStepActionBoardWarm",
  runtime_state_persist: "ppStepRuntimeStatePersist",
  routine_events: "ppStepRoutineEvents",
  npc_text_sync: "ppStepNpcTextSync",
  intent_planner: "ppStepIntentPlanner",
  portrait_generation: "ppStepPortraitGeneration",
  post_visible_error: "ppStepPostVisibleError",
  phase3_complete: "ppStepPhase3Complete",
};

function dedupe(steps: PostprocessStepDTO[]): PostprocessStepDTO[] {
  const map = new Map<string, PostprocessStepDTO>();
  for (const s of steps) {
    map.set(s.name, s);
  }
  return Array.from(map.values());
}

function formatDuration(ms: number): string {
  if (ms <= 0) return "";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

export function PostprocessSteps({ sessionId, messageId }: Props) {
  const { t } = useI18n();
  const [steps, setSteps] = useState<PostprocessStepDTO[]>([]);
  const [done, setDone] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const pollCountRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (!sessionId || !messageId) return;
    cancelledRef.current = false;
    pollCountRef.current = 0;
    setSteps([]);
    setDone(false);

    const clearTimer = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const poll = async () => {
      if (cancelledRef.current) return;
      try {
        const data = await getMessagePostprocessStepsAPI(sessionId, messageId);
        if (cancelledRef.current) return;
        setSteps(data.steps || []);
        setDone(Boolean(data.done));
        if (data.done) {
          clearTimer();
          return;
        }
      } catch {
        // Swallow — UI shows the last known state until next poll.
      }
      if (cancelledRef.current) return;
      pollCountRef.current += 1;
      const delay =
        pollCountRef.current < FAST_POLL_LIMIT ? FAST_POLL_MS : SLOW_POLL_MS;
      timerRef.current = setTimeout(() => {
        void poll();
      }, delay);
    };

    void poll();

    return () => {
      cancelledRef.current = true;
      clearTimer();
    };
  }, [sessionId, messageId]);

  const visible = dedupe(steps).filter((s) => s.name !== "phase3_complete");
  if (visible.length === 0) return null;

  const completeEvent = steps.find(
    (s) => s.name === "phase3_complete" && s.status === "done",
  );
  const totalLabel = completeEvent
    ? formatDuration(completeEvent.duration_ms || 0)
    : "";
  const hasRunning = visible.some((s) => s.status !== "done");
  const slowMode = !done && pollCountRef.current >= FAST_POLL_LIMIT;

  return (
    <div className="mt-1 pt-1.5 border-t border-border/50" data-no-screenshot>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 py-0.5 select-none w-full text-left"
      >
        <span className="w-0.5 h-3.5 bg-accent/70 inline-block" />
        <span className="text-[10px] font-mono uppercase tracking-widest text-text-3">
          {t("ppPhase3Title")}
          {totalLabel ? ` (${totalLabel})` : null}
          {!done && (
            <span className="inline-block w-1.5 h-1.5 bg-accent rounded-full animate-pulse ml-1.5 align-middle" />
          )}
        </span>
        <span className="text-[10px] text-text-3 ml-auto">
          {expanded ? "▼" : "▶"}
        </span>
      </button>

      {expanded && (
        <ol className="mt-1 pl-2.5 border-l border-border space-y-0.5 text-xs font-mono text-text-3">
          {visible.map((step) => {
            const labelKey = STEP_LABEL_KEYS[step.name];
            const label = labelKey ? t(labelKey) : step.name;
            const dur = formatDuration(step.duration_ms || 0);
            return (
              <li key={step.name} className="flex items-center gap-2">
                {step.status === "done" ? (
                  <span className="text-emerald-500 flex-shrink-0">✓</span>
                ) : (
                  <span className="inline-block w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin flex-shrink-0" />
                )}
                <span className="flex-1 truncate text-[11px]">{label}</span>
                {step.status === "done" && dur && (
                  <span className="text-[10px] text-text-3 tabular-nums flex-shrink-0">
                    {dur}
                  </span>
                )}
                {step.detail && (
                  <span className="text-[10px] text-text-3 truncate max-w-[160px]">
                    {step.detail}
                  </span>
                )}
              </li>
            );
          })}
          {!done && hasRunning && (
            <li className="flex items-center gap-2 text-text-3">
              <span className="inline-block w-3 h-3 border-2 border-border border-t-transparent rounded-full animate-spin flex-shrink-0" />
              <span className="text-[11px]">
                {slowMode ? t("ppStillBackground") : t("ppProcessing")}
              </span>
            </li>
          )}
        </ol>
      )}
    </div>
  );
}
