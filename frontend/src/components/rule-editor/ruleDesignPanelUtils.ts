// Derivers that pull the rule-design panel's view-model out of a
// DraftDetailDTO. The DTO carries `design_state` and `validation_report`
// as opaque dicts (stable shape lives in the backend P0.1/P0.6 schemas);
// these helpers turn them into the small set of typed bits the panel
// renders. Kept separate from RuleDesignPanel.tsx so the component file
// stays focused on layout.

import type { DraftDetailDTO } from "../../api/ruleset-drafts";

export type DesignIssueSeverity = "blocking" | "warning" | "info";

export interface DesignIssueView {
  code: string;
  severity: DesignIssueSeverity;
  message: string;
  path: string;
  hint: string;
}

export interface IssueBuckets {
  blocking: DesignIssueView[];
  warnings: DesignIssueView[];
  info: DesignIssueView[];
  total: number;
}

export interface SlotProgressView {
  required: string[];
  filled: string[];
  missing: string[];
  drafting: string[];
  progress: number;
  hasRequired: boolean;
}

export interface BlueprintView {
  id: string;
  label: string;
}

export interface CompileStateView {
  status: "idle" | "running" | "success" | "failed";
  canCompile: boolean;
  error: string;
}

const KNOWN_COMPILE_STATUSES = ["idle", "running", "success", "failed"] as const;

export function derivePhase(draft: DraftDetailDTO): string {
  const top = (draft.design_phase || "").trim();
  if (top) return top;
  const state = draft.design_state as Record<string, unknown> | undefined;
  const inner = typeof state?.phase === "string" ? (state.phase as string) : "";
  return inner || "intake";
}

export function deriveBlueprint(draft: DraftDetailDTO): BlueprintView {
  const state = draft.design_state as Record<string, unknown> | undefined;
  const bp = (state?.blueprint as Record<string, unknown> | undefined) || {};
  const id = typeof bp.id === "string" ? bp.id.trim() : "";
  return { id, label: id };
}

export function deriveSlotProgress(draft: DraftDetailDTO): SlotProgressView {
  const report = draft.validation_report as Record<string, unknown> | undefined;
  const slots = (report?.slots as Record<string, unknown> | undefined) || {};
  const required = stringList(slots.required);
  const filled = stringList(slots.filled);
  const missing = stringList(slots.missing);
  const drafting = stringList(slots.drafting);
  const raw = typeof slots.progress === "number" ? slots.progress : 0;
  const progress = Math.max(0, Math.min(1, raw));
  return {
    required,
    filled,
    missing,
    drafting,
    progress,
    hasRequired: required.length > 0,
  };
}

export function deriveCompileState(draft: DraftDetailDTO): CompileStateView {
  const state = draft.design_state as Record<string, unknown> | undefined;
  const compile = (state?.compile as Record<string, unknown> | undefined) || {};
  const rawStatus = typeof compile.status === "string" ? compile.status : "idle";
  const status = (
    KNOWN_COMPILE_STATUSES.includes(rawStatus as typeof KNOWN_COMPILE_STATUSES[number])
      ? rawStatus
      : "idle"
  ) as CompileStateView["status"];
  const error = typeof compile.error === "string" ? compile.error : "";
  const report = draft.validation_report as Record<string, unknown> | undefined;
  const canCompile = Boolean(report?.can_compile);
  return { status, canCompile, error };
}

export function deriveIssues(draft: DraftDetailDTO): IssueBuckets {
  const report = draft.validation_report as Record<string, unknown> | undefined;
  const blocking = readIssues(report?.blocking, "blocking");
  const warnings = readIssues(report?.warnings, "warning");
  const info = readIssues(report?.info, "info");
  return {
    blocking,
    warnings,
    info,
    total: blocking.length + warnings.length + info.length,
  };
}

function readIssues(raw: unknown, severity: DesignIssueSeverity): DesignIssueView[] {
  if (!Array.isArray(raw)) return [];
  const out: DesignIssueView[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const r = item as Record<string, unknown>;
    out.push({
      code: typeof r.code === "string" ? r.code : "",
      severity:
        r.severity === "blocking" || r.severity === "warning" || r.severity === "info"
          ? r.severity
          : severity,
      message: typeof r.message === "string" ? r.message : "",
      path: Array.isArray(r.path) ? r.path.map((seg) => String(seg)).join(".") : "",
      hint: typeof r.hint === "string" ? r.hint : "",
    });
  }
  return out;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((x): x is string => typeof x === "string");
}
