import { useState } from "react";
import { useI18n } from "../../i18n";
import { UploadZone } from "./UploadZone";
import { getStoredUser } from "../../api/http";
import { parseV6FromFile } from "../../lib/ruleset/parseV6";
import {
  deleteRulesetAPI,
  dtoToParsed,
  setRulesetSharedAPI,
  uploadRulesetFileAPI,
  uploadRulesetAPI,
} from "../../lib/ruleset/api";
import type { SavedListEntry } from "../../lib/ruleset/api";
import type { ParsedRuleset } from "../../lib/ruleset/types";

interface RuleStepProps {
  saved: SavedListEntry[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onUploaded: (parsed: ParsedRuleset, id: string) => void;
  onDeleted: (id: string) => void;
  onShared: (id: string, isShared: boolean) => void;
  onPreview: (id: string) => void;
  /** Open the conversational rule editor — empty / fork / in-place edit. */
  onCreateBlankDraft?: () => void;
  onForkDraft?: (rulesetId: string) => void;
  onInPlaceEdit?: (rulesetId: string) => void;
}

export function RuleStep({
  saved,
  selectedId,
  onSelect,
  onUploaded,
  onDeleted,
  onShared,
  onPreview,
  onCreateBlankDraft,
  onForkDraft,
  onInPlaceEdit,
}: RuleStepProps) {
  const { t, locale } = useI18n();
  const me = getStoredUser();
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = async (file: File) => {
    setError(null);
    setParsing(true);
    try {
      const ext = file.name.split(".").pop()?.toLowerCase() || "";
      const dto =
        ext === "json"
          ? await uploadJsonRuleset(file)
          : await uploadRulesetFileAPI(file, { output_language: locale });
      onUploaded(dtoToParsed(dto), dto.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setParsing(false);
    }
  };

  return (
    <div className="w-full max-w-[680px] anim-slide-right">
      <div className="text-[22px] font-semibold tracking-tight mb-1">
        {t("setupRuleHeading")}
      </div>
      <div className="text-sm text-text-2 mb-7">{t("setupRuleSub")}</div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3 mb-5">
        {onCreateBlankDraft && (
          <NewDraftCard onClick={onCreateBlankDraft} />
        )}
        {saved.map((item) => {
          const owned = !!me && me.id === item.owner_id;
          return (
            <SavedCard
              key={item.id}
              item={item}
              owned={owned}
              selected={selectedId === item.id}
              locale={locale}
              onSelect={() => onSelect(item.id)}
              onPreview={() => onPreview(item.id)}
              onFork={onForkDraft ? () => onForkDraft(item.id) : undefined}
              onInPlaceEdit={
                owned && onInPlaceEdit
                  ? () => onInPlaceEdit(item.id)
                  : undefined
              }
              onDelete={
                owned
                  ? async () => {
                      try {
                        await deleteRulesetAPI(item.id);
                        onDeleted(item.id);
                      } catch (err) {
                        setError(
                          err instanceof Error ? err.message : String(err)
                        );
                      }
                    }
                  : undefined
              }
              onToggleShare={
                owned
                  ? async () => {
                      try {
                        const next = !item.is_shared;
                        await setRulesetSharedAPI(item.id, next);
                        onShared(item.id, next);
                      } catch (err) {
                        setError(
                          err instanceof Error ? err.message : String(err)
                        );
                      }
                    }
                  : undefined
              }
            />
          );
        })}
      </div>

      <UploadZone
        accept=".json,.pdf,.md,.markdown,.txt,application/json,application/pdf,text/plain"
        onFile={handleFile}
        disabled={parsing}
      >
        <div className="text-3xl mb-2">{parsing ? "…" : "⬆"}</div>
        <div className="text-sm text-text-2 leading-relaxed">
          {parsing ? (
            <span>{t("setupParsing")}</span>
          ) : (
            <>
              <strong className="text-accent">{t("uploadRuleStrong")}</strong>
              <br />
              {t("uploadRuleHint")}
            </>
          )}
        </div>
      </UploadZone>

      {error && (
        <div className="mt-3 text-xs text-[var(--accent-text)] bg-accent-dim border border-border rounded-lg p-3">
          {error}
        </div>
      )}
    </div>
  );
}

async function uploadJsonRuleset(file: File) {
  // Validate locally first so a malformed JSON gives an immediate error
  // instead of bouncing off the backend with a 400.
  const localParsed = await parseV6FromFile(file);
  return uploadRulesetAPI(localParsed.raw);
}

interface SavedCardProps {
  item: SavedListEntry;
  owned: boolean;
  selected: boolean;
  locale: string;
  onSelect: () => void;
  onPreview: () => void;
  onFork?: () => void;
  onInPlaceEdit?: () => void;
  onDelete?: () => void;
  onToggleShare?: () => void;
}

function NewDraftCard({ onClick }: { onClick: () => void }) {
  const { t } = useI18n();
  return (
    <div
      onClick={onClick}
      className={[
        "relative bg-surface border-[1.5px] border-dashed rounded-2xl p-4 pt-5 cursor-pointer",
        "transition-[border-color,box-shadow,transform] duration-150",
        "hover:border-accent hover:-translate-y-px hover:shadow-[0_4px_16px_var(--shadow)]",
        "border-border-2 flex flex-col items-center justify-center min-h-[150px]",
      ].join(" ")}
    >
      <span className="text-3xl mb-2 text-accent">＋</span>
      <div className="text-sm font-semibold mb-0.5 text-center">
        {t("draftEntryNewBlank")}
      </div>
      <div className="text-[11px] text-text-3 leading-snug text-center">
        {t("draftEntryNewBlankSub")}
      </div>
    </div>
  );
}

function SavedCard({
  item,
  owned,
  selected,
  locale,
  onSelect,
  onPreview,
  onFork,
  onInPlaceEdit,
  onDelete,
  onToggleShare,
}: SavedCardProps) {
  const { t } = useI18n();
  const date = formatRelative(item.saved_at, locale);
  const shareLabel = item.is_shared
    ? t("setupModuleShared")
    : t("setupModulePrivate");
  const shareTitle = owned
    ? item.is_shared
      ? t("setupModuleSetPrivate")
      : t("setupModuleSetShared")
    : shareLabel;
  return (
    <div
      onClick={onSelect}
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
      <span className="block text-2xl mb-2">⬡</span>
      <div className="text-sm font-semibold mb-0.5 truncate">
        {item.meta.book_title}
      </div>
      <div className="text-xs text-text-2 leading-snug truncate">
        {item.meta.world_mode} · {date}
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onToggleShare?.();
        }}
        disabled={!onToggleShare}
        title={shareTitle}
        className={[
          "mt-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-[0.05em]",
          item.is_shared
            ? "bg-accent-dim text-[var(--accent-text)]"
            : "bg-surface-2 text-text-3",
          onToggleShare ? "cursor-pointer hover:opacity-80" : "cursor-default",
        ].join(" ")}
      >
        {item.is_shared ? "🌐" : "🔒"} {shareLabel}
      </button>
      <div className="mt-3 flex gap-1 flex-wrap">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onPreview();
          }}
          className="text-[11px] text-text-3 hover:text-accent px-1.5 py-0.5 rounded"
        >
          {t("rulesetPreview")}
        </button>
        {onFork && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onFork();
            }}
            className="text-[11px] text-text-3 hover:text-accent px-1.5 py-0.5 rounded"
            title={t("draftEntryForkTitle")}
          >
            {t("draftEntryFork")}
          </button>
        )}
        {onInPlaceEdit && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onInPlaceEdit();
            }}
            className="text-[11px] text-text-3 hover:text-accent px-1.5 py-0.5 rounded"
            title={t("draftEntryInPlaceTitle")}
          >
            {t("draftEntryInPlace")}
          </button>
        )}
        {onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (confirm(t("rulesetDeleteConfirm"))) onDelete();
            }}
            className="text-[11px] text-text-3 hover:text-[var(--accent-text)] px-1.5 py-0.5 rounded ml-auto"
          >
            {t("rulesetDelete")}
          </button>
        )}
      </div>
    </div>
  );
}

// Use Intl.RelativeTimeFormat so every supported locale gets a native
// phrasing without us hand-rolling each one.
function formatRelative(iso: string, locale: string): string {
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return iso;
  const diff = Date.now() - dt.getTime();
  const min = Math.floor(diff / 60_000);
  const hr = Math.floor(diff / 3_600_000);
  const day = Math.floor(diff / 86_400_000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (min < 1) return rtf.format(0, "minute");
  if (min < 60) return rtf.format(-min, "minute");
  if (hr < 24) return rtf.format(-hr, "hour");
  if (day < 7) return rtf.format(-day, "day");
  return dt.toLocaleDateString(locale);
}
