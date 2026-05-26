// EditorShell — top-level page for /drafts/{draftId}.
// Fetches the draft, manages live updates, hosts the 3-pane layout
// (toolbar / left preview / chat placeholder), and wires the toolbar
// buttons to backend endpoints.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useI18n } from "../../i18n";
import { ApiError } from "../../api/http";
import { useResizableWidth } from "../../hooks/useResizableWidth";
import {
  compileDraftDesignAPI,
  deleteDraftAPI,
  getDraftAPI,
  promoteDraftAPI,
  recompileDraftCharacterUIAPI,
  recompileDraftDiceAPI,
  undoDraftEditAPI,
  type DraftDetailDTO,
} from "../../api/ruleset-drafts";
import type {
  ParsedRuleset,
  V6ParameterFamily,
  V6RawArtifact,
  V6RulePackage,
} from "../../lib/ruleset/types";
import { EditorChatPane } from "./EditorChatPane";
import { EditorDesignSidebar, type TabId } from "./EditorDesignSidebar";
import { EditorToolbar } from "./EditorToolbar";

interface Props {
  draftId: string;
  onLeave: () => void;
  onPromoted?: (rulesetId: string) => void;
  onDeleted?: (draftId: string) => void;
  /** Called after the agent applies an edit; lets the parent refresh
   *  its drafts list so sidebar / banner titles stay in sync. */
  onEdited?: () => void;
}

export function EditorShell({
  draftId,
  onLeave,
  onPromoted,
  onDeleted,
  onEdited,
}: Props) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<DraftDetailDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("main");
  const {
    width: previewWidth,
    isDragging: previewDragging,
    onResizeStart: onPreviewResizeStart,
  } = useResizableWidth({
    storageKey: "chatrpg.editorPreviewWidth",
    defaultWidth: 320,
    minWidth: 240,
    maxWidth: 560,
    edge: "right",
  });

  const reload = useCallback(async () => {
    try {
      const d = await getDraftAPI(draftId);
      setDraft(d);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [draftId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const parsed: ParsedRuleset | null = useMemo(() => {
    if (!draft) return null;
    return draftToParsed(draft.parsed_v6 as unknown as V6RawArtifact);
  }, [draft]);

  if (error && !draft) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-sm text-[var(--accent-text)]">
        {error}
      </div>
    );
  }
  if (!draft || !parsed) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-sm text-text-2">
        {t("draftLoading")}
      </div>
    );
  }

  const badge: "blank" | "fork" | "in-place" = draft.target_ruleset_id
    ? "in-place"
    : draft.base_ruleset_id
    ? "fork"
    : "blank";

  const guardedAction = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <EditorToolbar
        draftTitle={draft.title}
        hasTarget={!!draft.target_ruleset_id}
        needsDiceCompile={draft.needs_dice_compile}
        needsCharacterUiCompile={draft.needs_character_ui_compile}
        busy={busy}
        previewCollapsed={previewCollapsed}
        onTogglePreview={() => setPreviewCollapsed((v) => !v)}
        onLeave={onLeave}
        onRecompileDice={() =>
          guardedAction(async () => {
            await recompileDraftDiceAPI(draft.id);
            await reload();
          })
        }
        onRecompileCharacterUi={() =>
          guardedAction(async () => {
            await recompileDraftCharacterUIAPI(draft.id);
            await reload();
          })
        }
        onPromoteNew={() =>
          guardedAction(async () => {
            const newTitle =
              window.prompt(
                t("draftPromptNewTitle"),
                draft.title || t("draftUntitled"),
              ) ?? null;
            if (newTitle === null) return;
            const res = await promoteDraftAPI(draft.id, {
              mode: "new",
              new_title: newTitle.trim() || null,
            });
            onPromoted?.(res.ruleset_id);
            window.alert(t("draftPromotedNewToast"));
          })
        }
        onPromoteTarget={() =>
          guardedAction(async () => {
            if (!window.confirm(t("draftPromoteTargetConfirm"))) return;
            const res = await promoteDraftAPI(draft.id, { mode: "target" });
            onPromoted?.(res.ruleset_id);
            window.alert(t("draftPromotedTargetToast"));
          })
        }
        onDelete={() =>
          guardedAction(async () => {
            await deleteDraftAPI(draft.id);
            onDeleted?.(draft.id);
            onLeave();
          })
        }
        onExport={() => {
          const data = JSON.stringify(draft.parsed_v6, null, 2);
          const blob = new Blob([data], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `${draft.title || "draft"}.v6.json`;
          a.click();
          URL.revokeObjectURL(url);
        }}
      />
      <div className="flex-1 flex min-h-0 overflow-hidden">
        <aside
          className={[
            "relative shrink-0 overflow-hidden flex flex-col",
            previewDragging
              ? ""
              : "transition-[width,border-color] duration-[250ms] ease-[cubic-bezier(0.4,0,0.2,1)]",
            previewCollapsed ? "border-r-0" : "border-r border-border",
          ].join(" ")}
          style={{ width: previewCollapsed ? 0 : `${previewWidth}px` }}
        >
          <EditorDesignSidebar
            draft={draft}
            parsed={parsed}
            draftTitle={draft.title}
            badge={badge}
            activeTab={activeTab}
            onTabChange={setActiveTab}
            compiling={compiling}
            onCompile={() =>
              guardedAction(async () => {
                if (compiling) return;
                setCompiling(true);
                try {
                  const res = await compileDraftDesignAPI(draft.id);
                  setDraft((prev) =>
                    prev
                      ? {
                          ...prev,
                          parsed_v6: res.parsed_v6_after,
                          validation_report: res.validation_report,
                          design_phase: res.design_phase,
                          needs_dice_compile: res.needs_dice_compile,
                          needs_character_ui_compile:
                            res.needs_character_ui_compile,
                        }
                      : prev,
                  );
                  await reload();
                  if (res.status === "success") onEdited?.();
                } finally {
                  setCompiling(false);
                }
              })
            }
          />
          {!previewCollapsed && (
            <div
              onMouseDown={onPreviewResizeStart}
              title="Drag to resize"
              className="absolute top-0 right-0 bottom-0 w-1.5 cursor-col-resize hover:bg-accent/40 active:bg-accent/60 transition-colors z-10"
            />
          )}
        </aside>
        <div className="flex-1 min-w-0 flex flex-col">
          <EditorChatPane
            draft={draft}
            activeTab={activeTab}
            onParsedChange={(parsedAfter) => {
              setDraft((prev) =>
                prev
                  ? {
                      ...prev,
                      parsed_v6: parsedAfter,
                    }
                  : prev,
              );
            }}
            onEditApplied={() => {
              // Pull fresh metadata (needs_*_compile flags update on apply).
              void reload();
              onEdited?.();
            }}
            onUndoEdit={async (editId) => {
              try {
                const res = await undoDraftEditAPI(draft.id, editId);
                setDraft((prev) =>
                  prev
                    ? { ...prev, parsed_v6: res.parsed_v6_after }
                    : prev,
                );
                await reload();
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e));
              }
            }}
            onDiceStateChanged={() => {
              // Dice agent persisted into parsed_v6.dice_ir; re-fetch
              // the draft so the left preview shows the new procedure.
              void reload();
            }}
            onDesignStateChanged={(ev) => {
              // Live updates straight from SSE. Reload happens via
              // edit_applied (when the same agent turn applied a draft
              // edit) or after the turn closes; here we patch
              // design_phase and (if carried) blueprint.id so the
              // panel chips swap immediately.
              setDraft((prev) => {
                if (!prev) return prev;
                const nextPhase = ev.design_phase || prev.design_phase;
                if (!ev.blueprint_id) {
                  return { ...prev, design_phase: nextPhase };
                }
                const prevState = prev.design_state || {};
                const prevBlueprint =
                  (prevState as Record<string, unknown>).blueprint;
                const blueprint = {
                  ...(prevBlueprint && typeof prevBlueprint === "object"
                    ? (prevBlueprint as Record<string, unknown>)
                    : {}),
                  id: ev.blueprint_id,
                };
                return {
                  ...prev,
                  design_phase: nextPhase,
                  design_state: {
                    ...(prevState as Record<string, unknown>),
                    blueprint,
                  },
                };
              });
            }}
            onValidationReport={(report) => {
              setDraft((prev) =>
                prev ? { ...prev, validation_report: report } : prev,
              );
            }}
          />
        </div>
      </div>
      {error && (
        <div className="px-4 py-2 text-xs text-[var(--accent-text)] bg-accent-dim border-t border-border">
          {error}
        </div>
      )}
    </div>
  );
}

// Draft-tolerant V6 → ParsedRuleset converter. Unlike `lib/ruleset/parseV6`,
// this never throws on empty `core_rules` — blank drafts are valid.
function draftToParsed(raw: V6RawArtifact): ParsedRuleset {
  const scenarios: V6RulePackage[] = Array.isArray(raw.rule_packages)
    ? raw.rule_packages
        .filter((p): p is V6RulePackage =>
          Boolean(p && typeof p === "object" && (p as V6RulePackage).package_id),
        )
        .map((p) => ({
          package_id: String(p.package_id),
          filename: p.filename,
          content: typeof p.content === "string" ? p.content : "",
          raw: typeof p.raw === "string" ? p.raw : undefined,
          excerpt_stats: p.excerpt_stats,
          error: p.error,
        }))
    : [];
  const parameters: V6ParameterFamily[] = Array.isArray(raw.parameter_families)
    ? raw.parameter_families
        .filter((f): f is V6ParameterFamily =>
          Boolean(f && typeof f === "object" && (f as V6ParameterFamily).family_id),
        )
        .map((f) => ({
          family_id: String(f.family_id),
          filename: f.filename,
          json: f.json,
          content: f.content,
          raw: f.raw,
          should_remain_markdown: f.should_remain_markdown,
          error: f.error,
        }))
    : [];
  return {
    meta: {
      book_id: String(raw.book_id || ""),
      book_title: String(raw.book_title || ""),
      world_mode: String(raw.world_mode || ""),
      output_language: raw.output_language,
      parsed_at: raw.parsed_at,
      model: raw.model,
      stats: raw.stats,
    },
    core: {
      rules_markdown: typeof raw.core_rules === "string" ? raw.core_rules : "",
      companion: raw.companion?.content
        ? {
            filename: raw.companion.filename || "companion.md",
            content: raw.companion.content,
          }
        : undefined,
    },
    scenarios,
    parameters,
    character_sheet: raw.character_sheet,
    dice_ir: raw.dice_ir ?? null,
    check_spec: null,
    character_ui: null,
    raw,
  };
}
