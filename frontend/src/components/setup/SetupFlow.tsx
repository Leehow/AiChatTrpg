import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import { StepHeader } from "./StepHeader";
import { RuleStep } from "./RuleStep";
import { ModuleStep } from "./ModuleStep";
import { CharStep } from "./CharStep";
import { api } from "../../api/client";
import { loadModule } from "../../lib/module/store";
import {
  dtoToParsed,
  dtoToSavedEntry,
  getRulesetAPI,
  getRulesetShortNameAPI,
  listRulesetsAPI,
  type SavedListEntry,
} from "../../lib/ruleset/api";
import {
  updateSessionAPI,
  type SetupStateDTO,
} from "../../api/sessions";
import type { ParsedRuleset } from "../../lib/ruleset/types";

export interface SetupResult {
  ruleset: ParsedRuleset;
  rulesetId: string;
  moduleId: string | null;
}

interface SetupFlowProps {
  // Null when there is no draft yet (e.g. fresh login with zero rooms).
  // Wizard interactions in that mode skip persistence; the draft is
  // materialised lazily when the user advances past the ruleset step.
  sessionId: string | null;
  initial: SetupStateDTO;
  onComplete: (result: SetupResult) => void;
  // Materialise a draft for the selected ruleset and advance to step 1.
  // Only invoked when the user clicks Continue on step 0 with no session.
  onCreateDraft?: (rulesetId: string) => Promise<void>;
  onPreviewRuleset: (id: string) => void;
  onActiveRulesetChanged?: (parsed: ParsedRuleset | null) => void;
  onSessionsChanged?: () => void | Promise<void>;
  /** Open the conversational rule editor — empty draft, fork, or in-place. */
  onCreateBlankRuleDraft?: () => void;
  onForkRuleDraft?: (rulesetId: string) => void;
  onInPlaceEditRuleset?: (rulesetId: string) => void;
}

const PERSIST_DEBOUNCE_MS = 300;

function normalizeStep(
  step: number,
  rulesetId: string | null,
  moduleId: string | null
): number {
  const clamped = Math.max(0, Math.min(2, Number.isFinite(step) ? step : 0));
  if (!rulesetId) return 0;
  if (clamped > 1 && !moduleId) return 1;
  return clamped;
}

// `[coc]血色公路` style. Backend keeps `title_auto`; once a future rename
// UI flips it false the App layer will stop scheduling these writes —
// for now there's no rename UI so auto-overwrite is always desired.
function buildTitle(short: string | null, moduleTitle: string | null): string {
  const tag = short ? `[${short}]` : "";
  return `${tag}${moduleTitle ?? ""}`;
}

export function SetupFlow({
  sessionId,
  initial,
  onComplete,
  onCreateDraft,
  onPreviewRuleset,
  onActiveRulesetChanged,
  onSessionsChanged,
  onCreateBlankRuleDraft,
  onForkRuleDraft,
  onInPlaceEditRuleset,
}: SetupFlowProps) {
  const { t } = useI18n();
  const [step, setStep] = useState(() =>
    normalizeStep(initial.step, initial.ruleset_id, initial.module_id)
  );
  const [saved, setSaved] = useState<SavedListEntry[]>([]);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(
    initial.ruleset_id
  );
  const [parsedCache, setParsedCache] = useState<Record<string, ParsedRuleset>>({});
  const [moduleId, setModuleId] = useState<string | null>(initial.module_id);
  const [moduleTitle, setModuleTitle] = useState<string | null>(
    initial.module_title
  );
  // Per-ruleset short-name cache so we don't keep hitting the LLM as the
  // user toggles between rulesets in the picker.
  const [shortNames, setShortNames] = useState<Record<string, string>>({});
  // True while we're materialising a draft on Continue (step 0 → 1 with
  // no sessionId yet). Disables the Continue button to avoid double-create.
  const [creatingDraft, setCreatingDraft] = useState(false);

  // When the wizard is reopened on a different session, sync local state
  // from the new initial. Without this, switching from one draft to
  // another would keep the old wizard state visible.
  const lastSessionRef = useRef<string | null>(sessionId);
  useEffect(() => {
    if (lastSessionRef.current !== sessionId) {
      lastSessionRef.current = sessionId;
      setStep(normalizeStep(initial.step, initial.ruleset_id, initial.module_id));
      setSelectedRuleId(initial.ruleset_id);
      setModuleId(initial.module_id);
      setModuleTitle(initial.module_title);
    }
  }, [sessionId, initial]);

  const refreshSaved = async () => {
    try {
      const items = await listRulesetsAPI();
      setSaved(items.map(dtoToSavedEntry));
    } catch (err) {
      console.warn("[chatrpg] list rulesets failed:", err);
    }
  };

  useEffect(() => {
    void refreshSaved();
  }, []);

  // Auto-pick first ruleset only when the user has nothing chosen yet.
  // For a resumed draft, `initial.ruleset_id` is already set so we skip.
  useEffect(() => {
    if (!selectedRuleId && saved.length > 0) {
      setSelectedRuleId(saved[0].id);
    }
  }, [saved, selectedRuleId]);

  // Mirror selected ruleset into the debug panel.
  useEffect(() => {
    if (!selectedRuleId) {
      onActiveRulesetChanged?.(null);
      return;
    }
    if (parsedCache[selectedRuleId]) {
      onActiveRulesetChanged?.(parsedCache[selectedRuleId]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const dto = await getRulesetAPI(selectedRuleId);
        const parsed = dtoToParsed(dto);
        if (cancelled) return;
        setParsedCache((c) => ({ ...c, [selectedRuleId]: parsed }));
        onActiveRulesetChanged?.(parsed);
      } catch (err) {
        if (!cancelled) console.warn("[chatrpg] preview fetch failed:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRuleId]);

  const selectedDiceStatus = selectedRuleId
    ? parsedCache[selectedRuleId]?.dice_ir?.status
    : undefined;

  // Poll the selected ruleset every 5s while its dice_ir is in the
  // "compiling" stub state, so the right-rail status flips from
  // "compiling" → "compiled"/"failed" without a manual refresh.
  useEffect(() => {
    if (!selectedRuleId) return;
    const cached = parsedCache[selectedRuleId];
    const status = cached?.dice_ir?.status;
    if (status !== "compiling") return;
    let cancelled = false;
    const handle = window.setInterval(async () => {
      if (cancelled) return;
      try {
        const dto = await getRulesetAPI(selectedRuleId);
        if (cancelled) return;
        const parsed = dtoToParsed(dto);
        const nextStatus = parsed.dice_ir?.status;
        setParsedCache((c) => ({ ...c, [selectedRuleId]: parsed }));
        onActiveRulesetChanged?.(parsed);
        if (nextStatus !== "compiling") {
          window.clearInterval(handle);
        }
      } catch (err) {
        console.warn("[chatrpg] dice_ir poll failed:", err);
      }
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRuleId, selectedDiceStatus]);

  // Lazy-fetch the short name for the current ruleset; caches per-id.
  useEffect(() => {
    if (!selectedRuleId || shortNames[selectedRuleId]) return;
    let cancelled = false;
    void (async () => {
      try {
        const { short_name } = await getRulesetShortNameAPI(selectedRuleId);
        if (!cancelled && short_name) {
          setShortNames((c) => ({ ...c, [selectedRuleId]: short_name }));
        }
      } catch (err) {
        console.warn("[chatrpg] short-name fetch failed:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedRuleId, shortNames]);

  // -- Debounced persistence -----------------------------------------------
  // Each setup change schedules one PUT after a quiet period. We coalesce
  // the body so quick step toggles don't burst the API.
  const persistTimerRef = useRef<number | null>(null);
  const pendingBodyRef = useRef<{
    setup_state: Partial<SetupStateDTO>;
    title?: string;
    ruleset_id?: string | null;
  }>({ setup_state: {} });

  const flushPersist = useCallback(async () => {
    if (!sessionId) return;
    const body = pendingBodyRef.current;
    pendingBodyRef.current = { setup_state: {} };
    if (
      Object.keys(body.setup_state).length === 0 &&
      body.title === undefined &&
      body.ruleset_id === undefined
    ) {
      return;
    }
    try {
      await updateSessionAPI(sessionId, body);
      void onSessionsChanged?.();
    } catch (err) {
      console.warn("[chatrpg] persist setup_state failed:", err);
    }
  }, [sessionId, onSessionsChanged]);

  const schedulePersist = useCallback(
    (
      patch: Partial<SetupStateDTO>,
      title?: string,
      topLevelRulesetId?: string | null
    ) => {
      if (!sessionId) return;
      pendingBodyRef.current.setup_state = {
        ...pendingBodyRef.current.setup_state,
        ...patch,
      };
      if (title !== undefined) pendingBodyRef.current.title = title;
      if (topLevelRulesetId !== undefined) {
        pendingBodyRef.current.ruleset_id = topLevelRulesetId;
      }
      if (persistTimerRef.current !== null) {
        window.clearTimeout(persistTimerRef.current);
      }
      persistTimerRef.current = window.setTimeout(() => {
        persistTimerRef.current = null;
        void flushPersist();
      }, PERSIST_DEBOUNCE_MS);
    },
    [sessionId, flushPersist]
  );

  // Repair impossible persisted states such as step=2 without a ruleset.
  // That state renders an empty character panel because the character stream
  // correctly refuses to start without rules context.
  useEffect(() => {
    const next = normalizeStep(step, selectedRuleId, moduleId);
    if (next === step) return;
    setStep(next);
    schedulePersist({ step: next });
  }, [moduleId, schedulePersist, selectedRuleId, step]);

  // Keep the top-level session ruleset in sync during setup, not only when
  // the wizard finishes. Room summaries and character creation both rely on
  // the server knowing the selected rulebook.
  useEffect(() => {
    if (!selectedRuleId) return;
    schedulePersist({ ruleset_id: selectedRuleId }, undefined, selectedRuleId);
  }, [schedulePersist, selectedRuleId]);

  // Flush any pending persist when the wizard unmounts so a fast click
  // through the steps doesn't lose the last patch.
  useEffect(() => {
    return () => {
      if (persistTimerRef.current !== null) {
        window.clearTimeout(persistTimerRef.current);
        void flushPersist();
      }
    };
  }, [flushPersist]);

  // -- Auto-title rewrites -------------------------------------------------
  // Re-derive the room title whenever the ruleset short name or module
  // title changes. We only overwrite when it still matches the auto
  // pattern, so a user-edited title isn't clobbered.
  const currentShort = selectedRuleId ? shortNames[selectedRuleId] : undefined;
  useEffect(() => {
    if (!sessionId) return;
    // We don't have direct read access to the persisted title here — to
    // avoid an extra GET round-trip, optimistically write whenever we
    // *might* still own the title. The backend keeps `title_auto`; if the
    // user has manually edited, callers will have flipped it false and
    // App.tsx would simply not propagate this through. For now, always
    // schedule the write — the backend is the source of truth.
    const next = buildTitle(currentShort ?? null, moduleTitle ?? null);
    if (next.length === 0) return;
    schedulePersist({}, next);
  }, [sessionId, currentShort, moduleTitle, schedulePersist]);

  // -- Step transitions -----------------------------------------------------
  const handleSelectRuleset = (id: string) => {
    setSelectedRuleId(id);
    schedulePersist({ ruleset_id: id, step }, undefined, id);
  };

  const handleSelectModule = useCallback(
    (id: string | null) => {
      setModuleId(id);
      // Module title comes from the LLM (extract-title) for a real upload,
      // or stays null for the freeform default. We resolve it asynchronously
      // and then persist.
      if (!id) {
        setModuleTitle(null);
        schedulePersist({ module_id: null, module_title: null, step });
        return;
      }
      if (id === "__freeform__") {
        setModuleTitle(null);
        schedulePersist({
          module_id: id,
          module_title: null,
          step,
        });
        return;
      }
      const cached = loadModule();
      const parsed = cached?.id === id ? cached : null;
      if (parsed) {
        // Optimistic title from the filename so the room name updates
        // instantly; LLM-cleaned title overwrites once it's back.
        const fallback = parsed.filename.replace(/\.[^.]+$/, "");
        setModuleTitle(fallback);
        schedulePersist({
          module_id: id,
          module_title: fallback,
          step,
        });
        void (async () => {
          try {
            // Prefer the persisted-row path so the backend caches the
            // LLM result on the parsed_modules row. Fall back to the
            // one-shot path for legacy parses without an id.
            const { title } = parsed.id === id
              ? await api.extractModuleTitle({ moduleId: id })
              : await api.extractModuleTitle({
                  filename: parsed.filename,
                  markdown: parsed.markdown,
                });
            if (title) {
              setModuleTitle(title);
              schedulePersist({ module_title: title });
            }
          } catch (err) {
            console.warn("[chatrpg] extract-title failed:", err);
          }
        })();
      } else {
        schedulePersist({ module_id: id, step });
        void (async () => {
          try {
            const full = await api.getModule(id);
            const fallback = full.filename.replace(/\.[^.]+$/, "");
            setModuleTitle(fallback);
            schedulePersist({
              module_id: id,
              module_title: fallback,
              step,
            });
            const { title } = await api.extractModuleTitle({ moduleId: id });
            if (title) {
              setModuleTitle(title);
              schedulePersist({ module_title: title });
            }
          } catch (err) {
            console.warn("[chatrpg] load module title failed:", err);
          }
        })();
      }
    },
    [schedulePersist, step]
  );

  const setStepPersisted = (next: number) => {
    const normalized = normalizeStep(next, selectedRuleId, moduleId);
    setStep(normalized);
    schedulePersist({
      step: normalized,
      ...(selectedRuleId ? { ruleset_id: selectedRuleId } : {}),
      module_id: moduleId,
      module_title: moduleTitle,
    }, undefined, selectedRuleId ?? undefined);
  };

  const canNext =
    step === 0
      ? Boolean(selectedRuleId)
      : step === 1
      ? Boolean(selectedRuleId && moduleId)
      : Boolean(selectedRuleId);

  const next = () => {
    if (!canNext || creatingDraft) return;
    // Step 0 → 1 with no draft yet: materialise one for the chosen
    // ruleset. App.tsx pushes the new sessionId + step=1 down via
    // setScreen, so we don't need to call setStepPersisted here.
    if (step === 0 && !sessionId && selectedRuleId && onCreateDraft) {
      setCreatingDraft(true);
      void onCreateDraft(selectedRuleId)
        .catch((err) => {
          console.error("[chatrpg] create draft on continue failed:", err);
          alert(err instanceof Error ? err.message : "Failed to create draft");
        })
        .finally(() => {
          setCreatingDraft(false);
        });
      return;
    }
    if (step < 2) {
      setStepPersisted(step + 1);
      return;
    }
    void finalize();
  };

  const finalize = async () => {
    if (!selectedRuleId) return;
    let parsed = parsedCache[selectedRuleId];
    if (!parsed) {
      try {
        const dto = await getRulesetAPI(selectedRuleId);
        parsed = dtoToParsed(dto);
        setParsedCache((c) => ({ ...c, [selectedRuleId]: parsed! }));
      } catch (err) {
        // B3: don't silently swallow — surface the failure so the user
        // isn't stuck on a button that does nothing. The most common
        // cause is parseV6 rejecting incomplete content (e.g. empty
        // core_rules), which now also fails fast at promote (B1) but a
        // legacy ruleset may still hit this path.
        console.error("[chatrpg] load ruleset failed:", err);
        const msg = err instanceof Error ? err.message : String(err);
        alert(`Failed to load ruleset: ${msg}`);
        return;
      }
    }
    // Flush any pending wizard updates before entering the game so
    // setup_state on the server matches what the user just confirmed.
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current);
      persistTimerRef.current = null;
      await flushPersist();
    }
    onComplete({ ruleset: parsed, rulesetId: selectedRuleId, moduleId });
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden anim-fade-in bg-bg min-w-0">
      <div className="flex items-center justify-center gap-3 px-4 py-1.5 border-b border-border shrink-0">
        <StepHeader step={step} />
      </div>

      {step === 2 ? (
        <CharStep
          key={sessionId ?? "no-session"}
          sessionId={sessionId}
          rulesetId={selectedRuleId}
          moduleId={moduleId}
          moduleTitle={moduleTitle}
          onDone={finalize}
          onSessionsChanged={onSessionsChanged}
        />
      ) : (
        <div className="flex-1 flex overflow-hidden">
          <button
            type="button"
            onClick={() => step > 0 && setStepPersisted(step - 1)}
            disabled={step === 0}
            aria-label={t("setupBack")}
            className={[
              "shrink-0 w-20 md:w-24 flex flex-col items-center justify-center gap-2",
              "bg-surface-2/40 border-r border-border text-text-2",
              "hover:bg-surface-2 hover:text-accent transition-colors",
              "disabled:opacity-0 disabled:pointer-events-none",
            ].join(" ")}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            <span className="text-xs font-medium">{t("setupBack")}</span>
          </button>
          <div className="flex-1 overflow-y-auto px-6 py-9 flex flex-col items-center">
            {step === 0 && (
              <RuleStep
                saved={saved}
                selectedId={selectedRuleId}
                onSelect={handleSelectRuleset}
                onUploaded={(parsed, id) => {
                  setParsedCache((c) => ({ ...c, [id]: parsed }));
                  setSelectedRuleId(id);
                  if (sessionId) schedulePersist({ ruleset_id: id, step }, undefined, id);
                  void refreshSaved();
                }}
                onDeleted={(id) => {
                  if (selectedRuleId === id) {
                    setSelectedRuleId(null);
                    schedulePersist({ ruleset_id: null, step: 0 }, undefined, null);
                    setStep(0);
                  }
                  setParsedCache((c) => {
                    const next = { ...c };
                    delete next[id];
                    return next;
                  });
                  void refreshSaved();
                }}
                onShared={(id, isShared) => {
                  setSaved((prev) =>
                    prev.map((row) =>
                      row.id === id ? { ...row, is_shared: isShared } : row
                    )
                  );
                }}
                onPreview={onPreviewRuleset}
                onCreateBlankDraft={onCreateBlankRuleDraft}
                onForkDraft={onForkRuleDraft}
                onInPlaceEdit={onInPlaceEditRuleset}
              />
            )}
            {step === 1 && (
              <ModuleStep selected={moduleId} onSelect={handleSelectModule} />
            )}
          </div>
          <button
            type="button"
            onClick={next}
            disabled={!canNext || creatingDraft}
            aria-label={t("setupContinue")}
            className={[
              "shrink-0 w-20 md:w-24 flex flex-col items-center justify-center gap-2",
              "bg-accent-dim border-l border-border text-accent",
              "hover:bg-accent hover:text-white transition-colors",
              "disabled:opacity-40 disabled:cursor-not-allowed",
              "disabled:hover:bg-accent-dim disabled:hover:text-accent",
            ].join(" ")}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span className="text-xs font-medium">{t("setupContinue")}</span>
          </button>
        </div>
      )}
    </div>
  );
}
