// RuleDesignPanel -- operational status panel rendered above the main
// rule-design chat. Reads phase, blueprint, slot progress, validation
// issues, and compile status off the current DraftDetailDTO. Updates as
// the parent refreshes draft state in response to P0.6 SSE events
// (`design_state_changed`, `validation_report`) and on edit_applied
// reloads.
//
// The panel does not own state -- it is a pure view of `draft` plus a
// compile button that calls back to the parent.

import { useState } from "react";
import type { DraftDetailDTO } from "../../api/ruleset-drafts";
import { useI18n, type MessageKey } from "../../i18n";
import {
  deriveBlueprint,
  deriveCompileState,
  deriveIssues,
  derivePhase,
  deriveSlotProgress,
  type CompileStateView,
  type DesignIssueView,
  type IssueBuckets,
  type SlotProgressView,
} from "./ruleDesignPanelUtils";

interface Props {
  draft: DraftDetailDTO;
  compiling: boolean;
  onCompile: () => void;
}

export function RuleDesignPanel({ draft, compiling, onCompile }: Props) {
  const { t } = useI18n();
  const phase = derivePhase(draft);
  const blueprint = deriveBlueprint(draft);
  const slots = deriveSlotProgress(draft);
  const compile = deriveCompileState(draft);
  const issues = deriveIssues(draft);
  const stale =
    Boolean(draft.needs_dice_compile) || Boolean(draft.needs_character_ui_compile);

  const [showAllIssues, setShowAllIssues] = useState(false);

  return (
    <div
      className="shrink-0 border-b border-border bg-surface px-3 py-2 flex flex-col gap-2"
      data-testid="rule-design-panel"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip label={t("ruleDesignPhase")} value={phaseLabel(phase, t)} />
        <Chip
          label={t("ruleDesignBlueprint")}
          value={blueprint.id ? blueprint.label : t("ruleDesignNoBlueprint")}
          mono
          dim={!blueprint.id}
        />
        <SlotChip slots={slots} />
        <CompileChip compile={compile} />
        {stale && <StaleChip />}
        <div className="flex-1" />
        <button
          type="button"
          onClick={onCompile}
          disabled={compiling}
          className={[
            "h-7 px-3 rounded text-[11px] font-semibold uppercase transition-colors",
            compiling
              ? "bg-surface-2 text-text-3 cursor-wait"
              : compile.canCompile
              ? "bg-accent text-white hover:bg-accent/90"
              : "bg-surface-2 text-text-2 hover:bg-accent-dim hover:text-[var(--accent-text)]",
          ].join(" ")}
          title={
            compile.canCompile
              ? t("ruleDesignCompileReadyTitle")
              : t("ruleDesignCompileBlockedTitle")
          }
        >
          {compiling ? t("ruleDesignCompiling") : t("ruleDesignCompileAction")}
        </button>
      </div>

      {issues.total > 0 && (
        <IssuesList
          issues={issues}
          expanded={showAllIssues}
          onToggle={() => setShowAllIssues((v) => !v)}
        />
      )}

      {compile.status === "failed" && compile.error && (
        <div className="text-[11px] text-[var(--accent-text)] bg-accent-dim border border-border rounded px-2 py-1 font-mono break-words">
          {compile.error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chips
// ---------------------------------------------------------------------------

function Chip({
  label,
  value,
  mono,
  dim,
}: {
  label: string;
  value: string;
  mono?: boolean;
  dim?: boolean;
}) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-border",
        dim ? "bg-surface-2 text-text-3" : "bg-surface-2 text-text",
      ].join(" ")}
    >
      <span className="text-text-3 uppercase text-[10px]">
        {label}
      </span>
      <span className={mono ? "font-mono" : ""}>{value}</span>
    </span>
  );
}

function SlotChip({ slots }: { slots: SlotProgressView }) {
  const { t } = useI18n();
  if (!slots.hasRequired) {
    return <Chip label={t("ruleDesignSlots")} value="-" dim />;
  }
  const filled = slots.filled.length;
  const total = slots.required.length;
  const pct = Math.round(slots.progress * 100);
  const complete = filled === total && total > 0;
  return (
    <span
      className="inline-flex items-center gap-2 text-[11px] px-1.5 py-0.5 rounded border border-border bg-surface-2"
      title={
        slots.missing.length
          ? t("ruleDesignSlotsMissingTitle", {
              items: slots.missing.join(", "),
            })
          : t("ruleDesignSlotsCompleteTitle")
      }
    >
      <span className="text-text-3 uppercase text-[10px]">
        {t("ruleDesignSlots")}
      </span>
      <span className="font-mono">
        {filled}/{total}
      </span>
      <span className="w-16 h-1.5 rounded-full bg-surface overflow-hidden">
        <span
          className={[
            "block h-full rounded-full",
            complete ? "bg-green-500" : "bg-accent",
          ].join(" ")}
          style={{ width: `${pct}%` }}
        />
      </span>
    </span>
  );
}

function CompileChip({ compile }: { compile: CompileStateView }) {
  const { t } = useI18n();
  const dot = COMPILE_DOT[compile.status];
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] px-1.5 py-0.5 rounded border border-border bg-surface-2">
      <span className="text-text-3 uppercase text-[10px]">
        {t("ruleDesignCompile")}
      </span>
      <span className={["w-2 h-2 rounded-full shrink-0", dot].join(" ")} />
      <span>{t(COMPILE_STATUS_LABEL_KEYS[compile.status])}</span>
      {!compile.canCompile && (
        <span className="text-text-3 text-[10px] uppercase">
          {t("ruleDesignCompileBlocked")}
        </span>
      )}
    </span>
  );
}

const COMPILE_DOT: Record<CompileStateView["status"], string> = {
  idle: "bg-text-3",
  running: "bg-accent animate-pulse",
  success: "bg-green-500",
  failed: "bg-red-500",
};

function StaleChip() {
  const { t } = useI18n();
  return (
    <span
      className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-accent-dim text-[var(--accent-text)]"
      title={t("ruleDesignStaleTitle")}
    >
      {t("ruleDesignStale")}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Issues
// ---------------------------------------------------------------------------

const SUMMARY_LIMIT = 3;

function IssuesList({
  issues,
  expanded,
  onToggle,
}: {
  issues: IssueBuckets;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const ordered = [...issues.blocking, ...issues.warnings, ...issues.info];
  const visible = expanded ? ordered : ordered.slice(0, SUMMARY_LIMIT);
  const hidden = ordered.length - visible.length;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 text-[11px]">
        <span className="text-text-3 uppercase text-[10px]">
          {t("ruleDesignIssues")}
        </span>
        <Counter
          label={t("ruleDesignIssueBlock")}
          count={issues.blocking.length}
          tone="red"
        />
        <Counter
          label={t("ruleDesignIssueWarn")}
          count={issues.warnings.length}
          tone="amber"
        />
        <Counter
          label={t("ruleDesignIssueInfo")}
          count={issues.info.length}
          tone="muted"
        />
        {ordered.length > SUMMARY_LIMIT && (
          <button
            type="button"
            onClick={onToggle}
            className="ml-auto text-[10px] uppercase text-text-2 hover:text-[var(--accent-text)]"
          >
            {expanded
              ? t("ruleDesignCollapse")
              : t("ruleDesignShowMore", { n: hidden })}
          </button>
        )}
      </div>
      <ul className="flex flex-col gap-0.5">
        {visible.map((iss, idx) => (
          <IssueRow key={`${iss.code}-${idx}`} issue={iss} />
        ))}
      </ul>
    </div>
  );
}

function IssueRow({ issue }: { issue: DesignIssueView }) {
  return (
    <li
      className="flex items-start gap-2 text-[11px] px-2 py-1 rounded bg-surface-2"
      title={issue.hint || undefined}
    >
      <span
        className={[
          "shrink-0 mt-0.5 w-1.5 h-1.5 rounded-full",
          ISSUE_DOT[issue.severity],
        ].join(" ")}
      />
      <span className="font-mono text-text-3 shrink-0">{issue.code}</span>
      <span className="text-text break-words min-w-0">{issue.message}</span>
      {issue.path && (
        <span className="ml-auto font-mono text-text-3 truncate max-w-[40%]">
          {issue.path}
        </span>
      )}
    </li>
  );
}

const ISSUE_DOT: Record<DesignIssueView["severity"], string> = {
  blocking: "bg-red-500",
  warning: "bg-amber-500",
  info: "bg-text-3",
};

const COMPILE_STATUS_LABEL_KEYS: Record<CompileStateView["status"], MessageKey> = {
  idle: "ruleDesignCompileIdle",
  running: "ruleDesignCompileRunning",
  success: "ruleDesignCompileSuccess",
  failed: "ruleDesignCompileFailed",
};

const PHASE_LABEL_KEYS: Record<string, MessageKey> = {
  intake: "ruleDesignPhaseIntake",
  blueprint_selection: "ruleDesignPhaseBlueprintSelection",
  core_loop: "ruleDesignPhaseCoreLoop",
  character_model: "ruleDesignPhaseCharacterModel",
  resolution_model: "ruleDesignPhaseResolutionModel",
  procedures: "ruleDesignPhaseProcedures",
  catalogs: "ruleDesignPhaseCatalogs",
  playtest: "ruleDesignPhasePlaytest",
  ready: "ruleDesignPhaseReady",
};

function phaseLabel(
  phase: string,
  t: (key: MessageKey, vars?: Record<string, string | number>) => string,
) {
  const key = PHASE_LABEL_KEYS[phase];
  return key ? t(key) : phase;
}

function Counter({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "red" | "amber" | "muted";
}) {
  if (count === 0) {
    return (
      <span className="text-[10px] uppercase text-text-3">
        {label} 0
      </span>
    );
  }
  const cls =
    tone === "red"
      ? "text-red-500"
      : tone === "amber"
      ? "text-amber-500"
      : "text-text-2";
  return (
    <span
      className={[
        "text-[10px] uppercase font-semibold",
        cls,
      ].join(" ")}
    >
      {label} {count}
    </span>
  );
}
