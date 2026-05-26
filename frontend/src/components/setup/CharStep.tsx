import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import {
  listCharacterPoolAPI,
  type CharacterPoolItemDTO,
} from "../../api/characters";
import {
  confirmCharacterAPI,
  getAdventureStartOptionsAPI,
  getCharacterDraftAPI,
  importCharacterDraftAPI,
  startAdventureAPI,
  streamCharacterChatAPI,
  streamCharacterGenerateAPI,
  streamCharacterStartAPI,
  updateSessionAPI,
  type AdventureStartOptionsDTO,
  type CharacterDraftDTO,
  type CharacterDraftMessageDTO,
} from "../../api/sessions";
import {
  CharacterDraftCard,
  Dot,
  EntryChooser,
  AdventureStartSelector,
  PoolModal,
  ReadyCallout,
  SetupChatMessage,
  extractCharacterTitle,
} from "./CharStepUI";
import { ChatComposer } from "../ChatComposer";
import { WaitingHint } from "../game/WaitingHint";
import {
  appendAssistantContent as appendAssistantContentTo,
  appendAssistantThinking as appendAssistantThinkingTo,
  mergeAssistantMetadata as mergeAssistantMetadataTo,
} from "./charStep/messageBuilders";
import { useChatScroll } from "./charStep/useChatScroll";

interface CharStepProps {
  sessionId: string | null;
  rulesetId: string | null;
  moduleId: string | null;
  moduleTitle: string | null;
  onDone: () => void;
  onSessionsChanged?: () => void | Promise<void>;
}

type EntryMode = "create" | "imported" | "pool";

export function CharStep({
  sessionId,
  rulesetId,
  moduleId,
  moduleTitle,
  onDone,
  onSessionsChanged,
}: CharStepProps) {
  const { t, locale } = useI18n();
  const [entry, setEntry] = useState<EntryMode | null>(null);
  const [resumeChecked, setResumeChecked] = useState(false);
  const [poolOpen, setPoolOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [messages, setMessages] = useState<CharacterDraftMessageDTO[]>([]);
  const [ready, setReady] = useState(false);
  const [input, setInput] = useState("");
  const [character, setCharacter] = useState<Record<string, unknown> | null>(null);
  const [poolItems, setPoolItems] = useState<CharacterPoolItemDTO[]>([]);
  const [loadingDraft, setLoadingDraft] = useState(false);
  const [loadingPool, setLoadingPool] = useState(false);
  const [sending, setSending] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [loadingStartOptions, setLoadingStartOptions] = useState(false);
  const [startOptions, setStartOptions] = useState<AdventureStartOptionsDTO | null>(null);
  const [selectedStartUnit, setSelectedStartUnit] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const charImportInputRef = useRef<HTMLInputElement | null>(null);
  const { scrollRef, atBottomRef, showJumpDown, jumpToLatest } = useChatScroll({
    active: entry === "create",
  });

  const characterTitle = useMemo(
    () => (character ? extractCharacterTitle(character) : ""),
    [character]
  );

  const applyDraft = useCallback((draft: CharacterDraftDTO) => {
    setMessages(draft.messages || []);
    setReady(Boolean(draft.ready));
    setCharacter(draft.character || null);
  }, []);

  const appendAssistantContent = useCallback((content: string) => {
    setMessages((prev) => appendAssistantContentTo(prev, content));
  }, []);

  const appendAssistantThinking = useCallback(
    (step: string, options?: { replaceLast?: boolean }) => {
      setMessages((prev) => appendAssistantThinkingTo(prev, step, options));
    },
    [],
  );

  const mergeAssistantMetadata = useCallback((metadata: Record<string, unknown>) => {
    if (!metadata || Object.keys(metadata).length === 0) return;
    if (metadata.create_character_ready === true) setReady(true);
    setMessages((prev) => mergeAssistantMetadataTo(prev, metadata));
  }, []);

  const ensureDraftReady = useCallback(async () => {
    if (!sessionId) throw new Error(t("setupCharNoSession"));
    if (!rulesetId) throw new Error(t("setupCharNoRuleset"));
    await updateSessionAPI(sessionId, {
      ruleset_id: rulesetId,
      setup_state: {
        step: 2,
        ruleset_id: rulesetId,
        module_id: moduleId,
        module_title: moduleTitle,
      },
    });
  }, [moduleId, moduleTitle, rulesetId, sessionId, t]);

  const refreshPool = useCallback(async () => {
    if (!rulesetId) {
      setPoolItems([]);
      return;
    }
    setLoadingPool(true);
    try {
      const items = await listCharacterPoolAPI({ ruleset_id: rulesetId });
      setPoolItems(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingPool(false);
    }
  }, [rulesetId]);

  // Detect a resumed session: if the persisted draft already has chat history
  // or a character, jump straight into the "create" branch instead of the
  // entry chooser. Otherwise we'd briefly flash the chooser before useEffect
  // pulled state in.
  useEffect(() => {
    if (!sessionId || !rulesetId) {
      setResumeChecked(true);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const draft = await getCharacterDraftAPI(sessionId);
        if (cancelled) return;
        if ((draft.messages?.length ?? 0) > 0 || draft.character) {
          applyDraft(draft);
          setEntry("create");
        }
      } catch (err) {
        console.warn("[chatrpg] resume draft check failed:", err);
      } finally {
        if (!cancelled) setResumeChecked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applyDraft, rulesetId, sessionId]);

  // Stream the opening prologue when the user picks the "create" entry. The
  // resume path above already filled `messages` so we only stream when both
  // entry === "create" AND there's nothing yet.
  useEffect(() => {
    if (entry !== "create" || !sessionId || !rulesetId) return;
    if (messages.length > 0 || character) return;
    let cancelled = false;
    const controller = new AbortController();
    setLoadingDraft(true);
    setError(null);
    void (async () => {
      try {
        await ensureDraftReady();
        const draft = await streamCharacterStartAPI(
          sessionId,
          { language: locale },
          {
            onThinking: (step, options) => {
              if (!cancelled) appendAssistantThinking(step, options);
            },
            onMetadata: (metadata) => {
              if (!cancelled) mergeAssistantMetadata(metadata);
            },
            onContent: (content) => {
              if (!cancelled) appendAssistantContent(content);
            },
          },
          controller.signal
        );
        if (!cancelled) applyDraft(draft);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoadingDraft(false);
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry, sessionId, rulesetId]);

  useEffect(() => {
    void refreshPool();
  }, [refreshPool]);

  useEffect(() => {
    if (!sessionId || !character) {
      setStartOptions(null);
      setSelectedStartUnit(null);
      return;
    }
    let cancelled = false;
    setLoadingStartOptions(true);
    void (async () => {
      try {
        const options = await getAdventureStartOptionsAPI(sessionId);
        if (cancelled) return;
        setStartOptions(options);
        const first = options.units?.[0]?.index;
        setSelectedStartUnit(typeof first === "number" ? first : null);
      } catch (err) {
        if (!cancelled) {
          console.warn("[chatrpg] load adventure start options failed:", err);
          setStartOptions(null);
          setSelectedStartUnit(null);
        }
      } finally {
        if (!cancelled) setLoadingStartOptions(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [character, sessionId]);

  useEffect(() => {
    if (!atBottomRef.current) return;
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, ready, sending, generating]);

  async function handleSend() {
    const text = input.trim();
    if (!text || sending || generating || confirming) return;
    setInput("");
    setError(null);
    setSending(true);
    setReady(false);
    setCharacter(null);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text, created_at: new Date().toISOString() },
    ]);
    try {
      await ensureDraftReady();
      const draft = await streamCharacterChatAPI(sessionId!, {
        message: text,
        language: locale,
      }, {
        onThinking: appendAssistantThinking,
        onMetadata: mergeAssistantMetadata,
        onContent: appendAssistantContent,
      });
      applyDraft(draft);
      void onSessionsChanged?.();
    } catch (err) {
      setInput(text);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  async function handleGenerate() {
    if (generating || sending || confirming) return;
    setError(null);
    setGenerating(true);
    try {
      await ensureDraftReady();
      const seed = input.trim();
      setInput("");
      const draft = await streamCharacterGenerateAPI(
        sessionId!,
        {
          mode: "from_chat",
          seed,
          language: locale,
        },
        {
          onThinking: appendAssistantThinking,
          onMetadata: mergeAssistantMetadata,
          onContent: appendAssistantContent,
        }
      );
      applyDraft(draft);
      void onSessionsChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  async function handleConfirmAndEnter() {
    if (!character || confirming || sending || generating || loadingStartOptions || startWaitingForParse) return;
    setError(null);
    setConfirming(true);
    try {
      await ensureDraftReady();
      const draft = await confirmCharacterAPI(sessionId!);
      applyDraft(draft);
      await startAdventureAPI(sessionId!, {
        module_id: startOptions?.module_id ?? moduleId,
        unit_index: selectedStartUnit,
        unit_id: startOptions?.units.find((u) => u.index === selectedStartUnit)?.unit_id ?? null,
      });
      await refreshPool();
      await onSessionsChanged?.();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setConfirming(false);
    }
  }

  // Import + reuse share the same path: take an existing character and place it
  // into the review/start panel. The player can still choose the module's
  // starting location/task/chapter before entering IC mode.
  async function importIntoDraft(payload: {
    character: Record<string, unknown>;
    source: "uploaded" | "pool";
    pool_id?: string;
  }) {
    setError(null);
    setImporting(true);
    try {
      await ensureDraftReady();
      const imported = await importCharacterDraftAPI(sessionId!, payload);
      applyDraft(imported);
      setEntry("create");
      await refreshPool();
      await onSessionsChanged?.();
    } catch (err) {
      setEntry(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setImporting(false);
    }
  }

  function triggerImport() {
    setError(null);
    charImportInputRef.current?.click();
  }

  async function handleUploadFile(file: File) {
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as Record<string, unknown>;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(t("setupCharUploadError"));
      }
      setEntry("imported");
      await importIntoDraft({ character: parsed, source: "uploaded" });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("setupCharUploadError"));
    }
  }

  async function handleImportInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (event.target) event.target.value = "";
    if (!file) return;
    await handleUploadFile(file);
  }

  async function openPool() {
    if (!rulesetId) {
      setError(t("setupCharNoRuleset"));
      return;
    }
    setPoolOpen(true);
    await refreshPool();
  }

  async function handlePoolPick(item: CharacterPoolItemDTO) {
    setPoolOpen(false);
    setEntry("pool");
    await importIntoDraft({
      character: item.character,
      source: "pool",
      pool_id: item.id,
    });
  }

  const startWaitingForParse = Boolean(
    startOptions?.has_module
    && (startOptions.semantic_status === "pending" || startOptions.semantic_status === "running")
  );
  const busy = sending || generating || confirming || loadingStartOptions;

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0 w-full">
      {entry === "create" ? (
        <>
          {error && (
            <div className="shrink-0 px-6 pt-3 pb-2">
              <div className="max-w-[1080px] mx-auto text-[12px] text-[#f87171] py-2 px-3 bg-[rgba(248,113,113,0.1)] rounded border border-[rgba(248,113,113,0.3)] break-words">
                {error}
              </div>
            </div>
          )}

          <div className="flex-1 relative min-h-0">
            <div ref={scrollRef} className="absolute inset-0 overflow-y-auto px-6 py-4">
            <div className="max-w-[1080px] mx-auto space-y-3">
              {loadingDraft && messages.length === 0 ? (
                <div className="min-h-[240px] flex items-center justify-center text-center text-sm text-text-3">
                  {t("setupCharOpening")}
                </div>
              ) : (
                messages.map((msg, idx) => (
                  <SetupChatMessage
                    key={`${msg.created_at || idx}-${idx}`}
                    msg={msg}
                    sessionId={sessionId}
                  />
                ))
              )}

              {ready && !character && !loadingDraft && (
                <ReadyCallout
                  generating={generating}
                  onGenerate={() => void handleGenerate()}
                />
              )}

              {character && !loadingDraft && (
                <div className="rounded-xl border border-accent bg-accent-dim px-4 py-3 text-sm text-[var(--accent-text)]">
                  <div className="font-semibold mb-1">{t("setupCharGeneratedTitle")}</div>
                  <div className="text-xs leading-relaxed">{t("setupCharGeneratedBody")}</div>
                </div>
              )}

              {character && (
                <CharacterDraftCard
                  character={character}
                  title={characterTitle}
                  generating={generating}
                  confirming={confirming}
                  confirmDisabled={startWaitingForParse || loadingStartOptions}
                  extra={
	                    <AdventureStartSelector
	                      options={startOptions}
	                      loading={loadingStartOptions}
	                      selectedIndex={selectedStartUnit}
	                      disabled={busy}
	                      onSelect={setSelectedStartUnit}
	                    />
	                  }
	                  onGenerate={() => void handleGenerate()}
	                  onConfirm={() => void handleConfirmAndEnter()}
	                />
              )}

              {(sending || generating) && <WaitingHint />}
            </div>
            </div>
            {showJumpDown && (
              <button
                type="button"
                onClick={jumpToLatest}
                title={t("chatJumpToLatest")}
                aria-label={t("chatJumpToLatest")}
                className="absolute right-5 bottom-5 w-9 h-9 rounded-full bg-surface border border-border-2 shadow-[0_4px_14px_var(--shadow-md)] flex items-center justify-center text-text-2 hover:bg-accent hover:text-white hover:border-accent active:scale-95 transition-all"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
            )}
          </div>

          <ChatComposer
            value={input}
            onChange={setInput}
            onSubmit={() => void handleSend()}
            placeholder={t("setupCharChatPlaceholder")}
            sendTitle={sending ? t("setupCharSending") : t("setupCharSend")}
            disabled={!sessionId || busy}
            sending={sending}
          />
        </>
      ) : (
        <div className="flex-1 overflow-y-auto px-6 py-9 flex flex-col items-center">
          <div className="w-full max-w-[1080px] anim-slide-right">
            <div className="text-[22px] font-semibold tracking-tight mb-1">
              {t("setupCharHeading")}
            </div>
            <div className="text-sm text-text-2 mb-5">{t("setupCharSub")}</div>

            {error && (
              <div className="mb-3 text-[12px] text-[#f87171] py-2 px-3 bg-[rgba(248,113,113,0.1)] rounded border border-[rgba(248,113,113,0.3)] break-words">
                {error}
              </div>
            )}

            {!resumeChecked && (
              <div className="text-sm text-text-3 py-12 text-center">
                {t("setupCharOpening")}
              </div>
            )}

            {resumeChecked && entry === null && (
              <EntryChooser
                onCreate={() => setEntry("create")}
                onImport={triggerImport}
                onPool={() => void openPool()}
              />
            )}

            {resumeChecked && (entry === "imported" || entry === "pool") && importing && (
              <div className="bg-surface border border-border rounded-xl p-6 text-center">
                <div className="flex items-center justify-center gap-2 text-sm text-text-2">
                  <Dot delay={0} />
                  <Dot delay={0.2} />
                  <Dot delay={0.4} />
                  <span className="ml-2">{t("setupCharImporting")}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <input
        ref={charImportInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={(e) => void handleImportInputChange(e)}
      />

      {poolOpen && (
        <PoolModal
          items={poolItems}
          loading={loadingPool}
          onClose={() => setPoolOpen(false)}
          onPick={(item) => void handlePoolPick(item)}
          onRefresh={() => void refreshPool()}
        />
      )}
    </div>
  );
}
