import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { getStoredUser } from "../../api/http";
import type { ModuleParseResponse, ModuleSummary } from "../../api/types";
import { useI18n } from "../../i18n";
import { setModule } from "../../lib/module/store";
import { ModuleUploadProgress, type SemanticPollState } from "./ModuleUploadProgress";
import { UploadZone } from "./UploadZone";

interface ModuleStepProps {
  selected: string | null;
  onSelect: (id: string | null) => void;
}

const FREEFORM_ID = "__freeform__";

// Module library — backed by the parsed_modules DB table. The list is
// shared across users (open-source single-instance install assumption);
// only the owner can delete an entry. The most recent upload's full
// payload is also mirrored into localStorage so the debug Module tab
// can render without a follow-up GET.

export function ModuleStep({ selected, onSelect }: ModuleStepProps) {
  const { t } = useI18n();
  const me = getStoredUser();
  const [modules, setModules] = useState<ModuleSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [progressLine, setProgressLine] = useState("");
  const [progressPage, setProgressPage] = useState<{ page: number; total: number } | null>(
    null
  );
  const [stage, setStage] = useState<"ocr" | "toc" | "semantic" | "">("");
  const [tocPreview, setTocPreview] = useState("");
  const [tocChars, setTocChars] = useState(0);
  const [semanticPoll, setSemanticPoll] = useState<SemanticPollState | null>(null);
  const semanticTimer = useRef<number | null>(null);

  async function refresh() {
    try {
      const list = await api.listModules();
      setModules(list);
      setListError(null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => () => stopSemanticPoll(), []);

  function stopSemanticPoll() {
    if (semanticTimer.current !== null) {
      window.clearInterval(semanticTimer.current);
      semanticTimer.current = null;
    }
  }

  function semanticSnapshot(mod: ModuleParseResponse): SemanticPollState {
    const steps = mod.semantic_steps || [];
    const structure = mod.semantic_structure || {};
    const sections = Array.isArray(structure.sections) ? structure.sections.length : 0;
    const playable = Array.isArray(structure.playable_units)
      ? structure.playable_units.length
      : Array.isArray(structure.playable)
        ? structure.playable.length
        : 0;
    const last = steps[steps.length - 1];
    return {
      id: mod.id,
      status: mod.semantic_status,
      summary: mod.semantic_error || last?.summary || "",
      steps: steps.length,
      sections,
      playable,
      error: mod.semantic_error || "",
    };
  }

  function pollSemanticParse(id: string) {
    stopSemanticPoll();
    const tick = async () => {
      try {
        const updated = await api.getModule(id);
        setModule(updated);
        const snapshot = semanticSnapshot(updated);
        setSemanticPoll(snapshot);
        if (updated.semantic_status !== "running") {
          stopSemanticPoll();
          await refresh();
        }
      } catch (e) {
        setSemanticPoll((prev) =>
          prev
            ? {
                ...prev,
                status: "error",
                summary: e instanceof Error ? e.message : String(e),
                error: e instanceof Error ? e.message : String(e),
              }
            : prev
        );
        stopSemanticPoll();
      }
    };
    void tick();
    semanticTimer.current = window.setInterval(() => void tick(), 2500);
  }

  async function handleFile(file: File) {
    setUploadError(null);
    setUploading(true);
    setProgressLine("");
    setProgressPage(null);
    setStage("ocr");
    setTocPreview("");
    setTocChars(0);
    setSemanticPoll(null);
    stopSemanticPoll();
    try {
      const res = await api.parseModuleStream(file, {
        onLog: (line) => setProgressLine(line),
        onProgress: (page, total, line) => {
          setProgressPage({ page, total });
          if (line) setProgressLine(line);
        },
        onStage: (st) => {
          if (st === "toc") setStage("toc");
          if (st === "semantic") setStage("semantic");
        },
        onTocChunk: (delta, total) => {
          setTocChars(total);
          setTocPreview((prev) => (prev + delta).slice(-600));
        },
      });
      setModule(res); // mirror to localStorage for the debug tab
      setSemanticPoll(semanticSnapshot(res));
      await refresh();
      onSelect(res.id);
      if (res.semantic_status === "running") {
        pollSemanticParse(res.id);
      }
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      setProgressLine("");
      setProgressPage(null);
      setStage("");
      setTocPreview("");
      setTocChars(0);
    }
  }

  async function deleteOne(id: string) {
    if (!window.confirm(t("setupModuleDeleteConfirm"))) return;
    try {
      await api.deleteModule(id);
      if (selected === id) onSelect(null);
      if (semanticPoll?.id === id) setSemanticPoll(null);
      setModule(null);
      await refresh();
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    }
  }

  async function toggleShared(m: ModuleSummary) {
    try {
      const updated = await api.setModuleShared(m.id, !m.is_shared);
      setModules((prev) => prev.map((row) => (row.id === m.id ? updated : row)));
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    }
  }

  async function selectAndPreview(m: ModuleSummary) {
    onSelect(m.id);
    // Refresh the preview cache so the Module debug tab can show full content.
    try {
      const full = await api.getModule(m.id);
      setModule(full);
    } catch {
      // Non-fatal — selection still works without the preview cache.
    }
  }

  return (
    <div className="w-full max-w-[680px] anim-slide-right">
      <div className="text-[22px] font-semibold tracking-tight mb-1">
        {t("setupModuleHeading")}
      </div>
      <div className="text-sm text-text-2 mb-7">{t("setupModuleSub")}</div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3 mb-5">
        <Card
          icon="✎"
          name={t("setupModuleFreeform")}
          desc={t("setupModuleFreeformDesc")}
          selected={selected === FREEFORM_ID}
          onClick={() => onSelect(FREEFORM_ID)}
        />
        {modules.map((m) => {
          const owned = !!me && me.id === m.owner_id;
          return (
            <Card
              key={m.id}
              icon="📖"
              name={titleOf(m.filename)}
              desc={`${m.toc_entries} ${t("setupModuleTocCount")} · ${
                m.chars
              } ${t("setupModuleCharsCount")}`}
              selected={selected === m.id}
              isShared={m.is_shared}
              shareLabel={
                m.is_shared ? t("setupModuleShared") : t("setupModulePrivate")
              }
              shareTitle={
                owned
                  ? m.is_shared
                    ? t("setupModuleSetPrivate")
                    : t("setupModuleSetShared")
                  : undefined
              }
              onToggleShare={owned ? () => void toggleShared(m) : undefined}
              onClick={() => void selectAndPreview(m)}
              onClear={owned ? () => void deleteOne(m.id) : undefined}
            />
          );
        })}
      </div>

      {listError && (
        <div className="mb-3 text-[12px] text-[#f87171] py-2 px-3 bg-[rgba(248,113,113,0.1)] rounded border border-[rgba(248,113,113,0.3)] break-words">
          {listError}
        </div>
      )}

      <UploadZone
        accept=".pdf,.docx,.doc,.pptx,.xlsx,.md,.markdown,.txt,.png,.jpg,.jpeg"
        onFile={handleFile}
        disabled={uploading}
      >
        <div className="text-3xl mb-2 opacity-40">⬆</div>
        <div className="text-sm text-text-2 leading-relaxed">
          <strong className="text-text">
            {uploading
              ? t("setupModuleUploading")
              : t("setupModuleUploadStrong")}
          </strong>
          <br />
          <span className="text-text-3">
            {uploading ? t("setupModuleUploadingHint") : t("setupModuleUploadHint")}
          </span>
        </div>
      </UploadZone>

      <ModuleUploadProgress
        uploading={uploading}
        semanticPoll={semanticPoll}
        stage={stage}
        tocChars={tocChars}
        progressPage={progressPage}
        tocPreview={tocPreview}
        progressLine={progressLine}
      />

      {uploadError && (
        <div className="mt-3 text-[12px] text-[#f87171] py-2 px-3 bg-[rgba(248,113,113,0.1)] rounded border border-[rgba(248,113,113,0.3)] break-words">
          {uploadError}
        </div>
      )}
    </div>
  );
}

// Strip the file extension for display (per user feedback: prefer the
// full filename like "血色公路" over an LLM-shortened tag).
function titleOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(0, dot) : filename;
}

function Card({
  icon,
  name,
  desc,
  selected,
  onClick,
  onClear,
  isShared,
  shareLabel,
  shareTitle,
  onToggleShare,
}: {
  icon: string;
  name: string;
  desc: string;
  selected: boolean;
  onClick: () => void;
  onClear?: () => void;
  isShared?: boolean;
  shareLabel?: string;
  shareTitle?: string;
  onToggleShare?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={[
        "relative bg-surface border-[1.5px] rounded-2xl p-4 pt-5 cursor-pointer",
        "transition-[border-color,box-shadow,transform] duration-150",
        "hover:border-border-2 hover:-translate-y-px hover:shadow-[0_4px_16px_var(--shadow)]",
        selected
          ? "border-accent shadow-[0_0_0_3px_var(--accent-dim)]"
          : "border-border",
      ].join(" ")}
    >
      {selected && (
        <div className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full bg-accent text-white flex items-center justify-center text-[11px]">
          ✓
        </div>
      )}
      {onClear && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClear();
          }}
          className="absolute top-2.5 left-2.5 text-text-3 hover:text-[#f87171] text-[14px] leading-none"
          aria-label="Delete module"
          title="Delete"
        >
          ×
        </button>
      )}
      <span className="block text-2xl mb-2">{icon}</span>
      <div className="text-sm font-semibold mb-0.5 truncate" title={name}>
        {name}
      </div>
      <div className="text-xs text-text-2 leading-snug">{desc}</div>
      {shareLabel && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleShare?.();
          }}
          disabled={!onToggleShare}
          title={shareTitle || shareLabel}
          className={[
            "mt-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-[0.05em]",
            isShared
              ? "bg-accent-dim text-[var(--accent-text)]"
              : "bg-surface-2 text-text-3",
            onToggleShare ? "cursor-pointer hover:opacity-80" : "cursor-default",
          ].join(" ")}
        >
          {isShared ? "🌐" : "🔒"} {shareLabel}
        </button>
      )}
    </div>
  );
}
