import { useState } from "react";
import { useI18n } from "../../i18n";
import {
  applyCheckSpecAPI,
  compileDiceIRAPI,
  type RulesetDetailDTO,
} from "../../lib/ruleset/api";
import type { DiceIRArtifact } from "../../lib/ruleset/types";

interface Props {
  artifact: DiceIRArtifact | null;
  checkSpec?: Record<string, unknown> | null;
  rulesetId?: string;
  onCompiled?: (artifact: DiceIRArtifact) => void;
  onApplied?: (detail: RulesetDetailDTO) => void;
}

export function DiceEngineTab({
  artifact,
  checkSpec,
  rulesetId,
  onCompiled,
  onApplied,
}: Props) {
  const { t } = useI18n();
  const [compiling, setCompiling] = useState(false);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const triggerCompile = async () => {
    if (!rulesetId) return;
    setCompiling(true);
    setCompileError(null);
    try {
      const result = await compileDiceIRAPI(rulesetId);
      if (result?.package && onCompiled) onCompiled(result.package);
    } catch (err) {
      setCompileError(err instanceof Error ? err.message : String(err));
    } finally {
      setCompiling(false);
    }
  };

  const triggerApply = async (procedureId: string) => {
    if (!rulesetId || !procedureId) return;
    setApplyingId(procedureId);
    setApplyError(null);
    try {
      const detail = await applyCheckSpecAPI(rulesetId, {
        procedure_id: procedureId,
      });
      onApplied?.(detail);
    } catch (err) {
      setApplyError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplyingId(null);
    }
  };

  // Three explicit pre-compiled states: nothing yet, in-flight stub, failed stub.
  if (!artifact || artifact.status === "compiling" || artifact.status === "failed") {
    const isCompiling = artifact?.status === "compiling";
    const isFailed = artifact?.status === "failed";
    return (
      <div className="max-w-[680px] mx-auto px-6 py-12">
        <div className="bg-surface border border-dashed border-border-2 rounded-2xl p-8 text-center">
          <div className="text-3xl mb-3 opacity-60">
            {isCompiling ? "⏳" : isFailed ? "⚠️" : "🎲"}
          </div>
          <div className="text-base font-semibold mb-1.5">
            {isCompiling
              ? t("diceCompilingTitle")
              : isFailed
              ? t("diceFailedTitle")
              : t("diceEmptyTitle")}
          </div>
          <div className="text-sm text-text-2 leading-relaxed mb-4">
            {isCompiling
              ? t("diceCompilingBody")
              : isFailed
              ? t("diceFailedBody")
              : t("diceEmptyBody")}
          </div>
          {!isCompiling && !isFailed && (
            <ul className="text-left text-[12.5px] text-text-3 space-y-1 max-w-md mx-auto mb-5">
              <li>· {t("diceEmptyHint1")}</li>
              <li>· {t("diceEmptyHint2")}</li>
              <li>· {t("diceEmptyHint3")}</li>
            </ul>
          )}
          {isFailed && artifact?.error && (
            <div className="mt-3 mb-4 text-xs text-[var(--accent-text)] bg-accent-dim border border-border rounded-lg p-3 text-left max-w-md mx-auto font-mono">
              {artifact.error}
            </div>
          )}
          {rulesetId && !isCompiling && (
            <button
              onClick={triggerCompile}
              disabled={compiling}
              className="px-5 py-2.5 rounded-xl bg-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              {compiling
                ? t("diceCompiling")
                : isFailed
                ? t("diceRetryButton")
                : t("diceCompileButton")}
            </button>
          )}
          {compileError && (
            <div className="mt-3 text-xs text-[var(--accent-text)] bg-accent-dim border border-border rounded-lg p-3 text-left max-w-md mx-auto">
              {compileError}
            </div>
          )}
        </div>
      </div>
    );
  }

  const compiled = artifact.package?.compiled;
  const specs = compiled?.check_specs || [];
  const appliedProcedureId =
    artifact.applied_check_spec?.procedure_id ||
    findAppliedProcedureId(specs, checkSpec);

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6">
      <div className="bg-surface border border-border rounded-xl p-4 mb-5 flex items-center gap-4 text-[12.5px]">
        <div>
          <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
            {t("diceArtifactSchema")}
          </div>
          <div className="font-medium">{artifact.schema_version}</div>
        </div>
        {artifact.model && (
          <div>
            <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
              {t("diceArtifactModel")}
            </div>
            <div className="font-medium">{artifact.model}</div>
          </div>
        )}
        {compiled?.default_procedure_id && (
          <div>
            <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
              {t("diceArtifactDefault")}
            </div>
            <div className="font-medium">{compiled.default_procedure_id}</div>
          </div>
        )}
        {appliedProcedureId && (
          <div>
            <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
              {t("diceArtifactApplied")}
            </div>
            <div className="font-medium">{appliedProcedureId}</div>
          </div>
        )}
        <div className="ml-auto">
          <Pill ok={compiled?.overall_ok ?? false}>
            {compiled?.overall_ok ? "OK" : "Review"}
          </Pill>
        </div>
      </div>

      <div className="space-y-3">
        {specs.map((spec) => (
          <div
            key={spec.procedure_id}
            className="bg-surface border border-border rounded-xl p-4"
          >
            <div className="flex items-center gap-3 mb-2">
              <div className="font-semibold text-sm flex-1">
                {spec.name || spec.procedure_id}
              </div>
              {spec.primary_family && (
                <span className="text-[10.5px] text-text-3 bg-surface-2 px-2 py-0.5 rounded border border-border">
                  {spec.primary_family}
                </span>
              )}
              <Pill ok={spec.validation?.ok ?? false}>
                {spec.validation?.ok
                  ? spec.validation?.sample_count
                    ? `${spec.validation.sample_count} OK`
                    : "OK"
                  : "Failed"}
              </Pill>
              {rulesetId && (
                <button
                  type="button"
                  onClick={() => void triggerApply(spec.procedure_id)}
                  disabled={
                    applyingId !== null ||
                    appliedProcedureId === spec.procedure_id
                  }
                  className={[
                    "text-[11.5px] font-semibold px-3 py-1 rounded-md border transition",
                    appliedProcedureId === spec.procedure_id
                      ? "border-border bg-surface-2 text-text-3"
                      : "border-accent bg-accent text-white hover:opacity-90",
                    applyingId !== null ? "opacity-60 cursor-progress" : "",
                  ].join(" ")}
                >
                  {appliedProcedureId === spec.procedure_id
                    ? t("diceSpecApplied")
                    : applyingId === spec.procedure_id
                    ? t("diceSpecApplying")
                    : t("diceSpecApply")}
                </button>
              )}
            </div>
            <pre className="whitespace-pre-wrap text-[11.5px] leading-relaxed text-text-2 font-mono bg-surface-2 border border-border rounded-lg p-3 max-h-72 overflow-auto">
              {JSON.stringify(spec.check_spec ?? {}, null, 2)}
            </pre>
          </div>
        ))}
        {applyError && (
          <div className="text-xs text-[var(--accent-text)] bg-accent-dim border border-border rounded-lg p-3">
            {applyError}
          </div>
        )}
      </div>
    </div>
  );
}

function Pill({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={[
        "px-2 py-0.5 rounded text-[10.5px] font-semibold uppercase tracking-wide",
        ok
          ? "bg-[rgba(52,211,153,0.15)] text-[#34d399]"
          : "bg-[rgba(248,113,113,0.15)] text-[#f87171]",
      ].join(" ")}
    >
      {children}
    </span>
  );
}

function findAppliedProcedureId(
  specs: Array<{
    procedure_id?: string;
    check_spec?: Record<string, unknown>;
  }>,
  checkSpec?: Record<string, unknown> | null
): string {
  if (!checkSpec) return "";
  const target = JSON.stringify(checkSpec);
  for (const spec of specs) {
    if (!spec || typeof spec !== "object") continue;
    const entry = spec as {
      procedure_id?: string;
      check_spec?: Record<string, unknown>;
    };
    if (entry.check_spec && JSON.stringify(entry.check_spec) === target) {
      return entry.procedure_id || "";
    }
  }
  return "";
}
