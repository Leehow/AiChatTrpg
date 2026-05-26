// Visual card for a tool call — name, args preview, result/error badge,
// undo button when the call produced an edit.

import { useState } from "react";
import { useI18n } from "../../i18n";
import { undoDraftEditAPI } from "../../api/ruleset-drafts";
import type { ChatToolCall } from "./chatTypes";

interface Props {
  call: ChatToolCall;
  onUndo?: (editId: string) => void;
}

export function ToolCallCard({ call, onUndo }: Props) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [undoing, setUndoing] = useState(false);

  const status = call.status;
  const errorMsg =
    status === "error" && call.result
      ? String((call.result as { message?: string }).message || "error")
      : null;

  const argsPretty = (() => {
    try {
      const parsed = JSON.parse(call.argsBuf || "{}");
      return JSON.stringify(parsed, null, 2);
    } catch {
      return call.argsBuf || "";
    }
  })();

  const resultPretty = call.result
    ? JSON.stringify(call.result, null, 2)
    : "";

  return (
    <div
      className={[
        "self-start max-w-[90%] rounded-xl border text-[12px]",
        "transition-colors",
        status === "running"
          ? "bg-surface border-border-2"
          : status === "error"
          ? "bg-red-500/5 border-red-500/30"
          : "bg-surface border-border",
      ].join(" ")}
    >
      <div
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 px-3 py-2 cursor-pointer"
      >
        <span
          className={[
            "w-2 h-2 rounded-full shrink-0",
            status === "running"
              ? "bg-accent animate-pulse"
              : status === "error"
              ? "bg-red-500"
              : "bg-emerald-500",
          ].join(" ")}
        />
        <span className="font-mono font-semibold text-[12px]">
          {call.toolName}
        </span>
        {status === "running" && (
          <span className="text-text-3 text-[11px]">
            {t("draftAgentToolRunning")}
          </span>
        )}
        {errorMsg && (
          <span className="text-red-500 text-[11px] truncate ml-2">
            {errorMsg}
          </span>
        )}
        {call.editId && onUndo && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (call.editId && onUndo && !undoing) {
                setUndoing(true);
                onUndo(call.editId);
              }
            }}
            disabled={undoing}
            className="ml-auto text-[11px] text-text-3 hover:text-accent px-1.5 py-0.5 rounded disabled:opacity-50"
          >
            {undoing ? t("draftAgentUndoing") : t("draftAgentUndo")}
          </button>
        )}
        <span
          className={[
            "ml-auto text-text-3 transition-transform",
            expanded ? "rotate-90" : "",
            call.editId ? "ml-2" : "",
          ].join(" ")}
        >
          ▶
        </span>
      </div>
      {expanded && (
        <div className="border-t border-border px-3 py-2 flex flex-col gap-2">
          <div>
            <div className="text-[10px] uppercase tracking-[0.05em] text-text-3 mb-1">
              args
            </div>
            <pre className="text-[11px] bg-bg p-2 rounded overflow-x-auto whitespace-pre-wrap break-words max-h-[260px]">
              {argsPretty || "(empty)"}
            </pre>
          </div>
          {resultPretty && (
            <div>
              <div className="text-[10px] uppercase tracking-[0.05em] text-text-3 mb-1">
                result
              </div>
              <pre className="text-[11px] bg-bg p-2 rounded overflow-x-auto whitespace-pre-wrap break-words max-h-[260px]">
                {resultPretty}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export async function performUndo(
  draftId: string,
  editId: string,
): Promise<Record<string, unknown>> {
  const res = await undoDraftEditAPI(draftId, editId);
  return res.parsed_v6_after;
}
