import type { ModuleParseResponse } from "../../api/types";
import { useI18n } from "../../i18n";

export interface SemanticPollState {
  id: string;
  status: ModuleParseResponse["semantic_status"];
  summary: string;
  steps: number;
  sections: number;
  playable: number;
  error: string;
}

interface ModuleUploadProgressProps {
  uploading: boolean;
  semanticPoll: SemanticPollState | null;
  stage: "ocr" | "toc" | "semantic" | "";
  tocChars: number;
  progressPage: { page: number; total: number } | null;
  tocPreview: string;
  progressLine: string;
}

export function ModuleUploadProgress({
  uploading,
  semanticPoll,
  stage,
  tocChars,
  progressPage,
  tocPreview,
  progressLine,
}: ModuleUploadProgressProps) {
  const { t } = useI18n();
  if (!uploading && !semanticPoll) return null;

  return (
    <div className="mt-3 border border-border rounded-lg overflow-hidden">
      <div className="px-3 py-1.5 bg-surface-2 flex items-center justify-between text-[11px]">
        <span className="text-text-2 font-mono uppercase tracking-[0.05em]">
          {semanticPoll
            ? semanticStatusLabel(semanticPoll.status, {
                running: t("setupModuleSemanticRunning"),
                done: t("setupModuleSemanticDone"),
                error: t("setupModuleSemanticError"),
              })
            : stage === "semantic"
              ? t("setupModuleStageSemantic")
              : stage === "toc"
                ? t("setupModuleStageToc")
                : t("setupModuleStageOcr")}
        </span>
        {semanticPoll && (
          <span className="text-text-3 font-mono">
            {t("setupModuleSemanticSteps").replace("{n}", String(semanticPoll.steps))}
          </span>
        )}
        {!semanticPoll && stage === "toc" && tocChars > 0 && (
          <span className="text-text-3 font-mono">
            {tocChars} {t("setupModuleCharsCount")}
          </span>
        )}
        {!semanticPoll && stage === "ocr" && progressPage && progressPage.total > 0 && (
          <span className="text-text-3">
            {progressPage.page} / {progressPage.total} ·{" "}
            {Math.round((progressPage.page / progressPage.total) * 100)}%
          </span>
        )}
      </div>
      {!semanticPoll && stage === "ocr" && progressPage && progressPage.total > 0 && (
        <div className="h-1 bg-surface-2 overflow-hidden">
          <div
            className="h-full bg-accent transition-[width] duration-200"
            style={{ width: `${(progressPage.page / progressPage.total) * 100}%` }}
          />
        </div>
      )}
      {semanticPoll && semanticPoll.status === "running" && (
        <div className="h-1 bg-surface-2 overflow-hidden">
          <div className="h-full w-1/2 bg-accent animate-pulse" />
        </div>
      )}
      {semanticPoll && (
        <div className="px-3 py-2 text-[11px] bg-surface space-y-1">
          <div className={semanticPoll.error ? "text-[#f87171]" : "text-text"}>
            {semanticPoll.summary || t("setupModuleStageSemantic")}
          </div>
          <div className="text-text-3 font-mono">
            {t("setupModuleSemanticCounts")
              .replace("{sections}", String(semanticPoll.sections))
              .replace("{playable}", String(semanticPoll.playable))}
          </div>
        </div>
      )}
      {!semanticPoll && stage === "toc" && tocPreview && (
        <pre className="px-3 py-2 text-[10.5px] text-text font-mono whitespace-pre-wrap break-words bg-surface max-h-[140px] overflow-auto">
          {tocPreview}
        </pre>
      )}
      {!semanticPoll && stage === "ocr" && progressLine && (
        <pre className="px-3 py-2 text-[10.5px] text-text-3 font-mono whitespace-pre-wrap break-words bg-surface max-h-[80px] overflow-auto">
          {progressLine}
        </pre>
      )}
    </div>
  );
}

function semanticStatusLabel(
  status: ModuleParseResponse["semantic_status"],
  labels: { running: string; done: string; error: string }
): string {
  if (status === "done") return labels.done;
  if (status === "error") return labels.error;
  return labels.running;
}
