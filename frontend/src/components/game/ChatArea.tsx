import { useCallback, useEffect, useRef, useState } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { useI18n } from "../../i18n";
import { ChatComposer, ComposerIconButton } from "../ChatComposer";
import { D20Icon } from "../dice/DiceIcons";
import {
  Message,
  type ChatMessage,
  type ChatStyle,
  type PendingCheckSummary,
} from "./Message";
import type { TrpgSpeakerProfile } from "../../utils/trpgDialogue";
import type { TrpgSceneHudSnapshot } from "./trpgHudTypes";

interface Props {
  messages: ChatMessage[];
  sessionId?: string | null;
  chatStyle: ChatStyle;
  characterName: string;
  characterInitial: string;
  speakerProfiles?: Record<string, TrpgSpeakerProfile>;
  onSend: (text: string) => void;
  onOpenDice: () => void;
  hasMoreOlder?: boolean;
  loadingOlder?: boolean;
  onLoadOlder?: () => void | Promise<void>;
  // Identifier that changes whenever the player picks a different scene tab.
  // On change we force-scroll to the last message of the (filtered) list and
  // re-arm sticky-to-bottom — opening a past tab lands on its last message,
  // and switching back to live mode resumes following new turns.
  tabKey?: string;
  // GM messages can carry pending [CHECK] placeholders. Clicking "投出"
  // calls back with the GM message id + specific pending check so GameShell
  // can roll 3D dice before firing the resolve continuation turn. While
  // `resolvingPendingId` is set, the matching GM bubble's button shows busy.
  onResolvePending?: (gmMessageId: string, pending: PendingCheckSummary) => void;
  resolvingPendingId?: string | null;
  sceneHudLive?: boolean;
  onSceneHudSnapshotChange?: (snapshot: TrpgSceneHudSnapshot | null) => void;
}

// Pre-fetch older messages once the player scrolls to within this many items
// of the top. 50 is half the page size so the next batch is in flight long
// before the player runs out of buffered content — perceptibly seamless.
const NEAR_TOP_INDEX = 50;
const HUD_BOTTOM_THRESHOLD_PX = 80;
const HUD_SCROLL_DEBOUNCE_MS = 120;

export function ChatArea({
  messages,
  sessionId,
  chatStyle,
  characterName,
  characterInitial,
  speakerProfiles,
  onSend,
  onOpenDice,
  hasMoreOlder = false,
  loadingOlder = false,
  onLoadOlder,
  tabKey,
  onResolvePending,
  resolvingPendingId,
  sceneHudLive = true,
  onSceneHudSnapshotChange,
}: Props) {
  const { t } = useI18n();
  const [input, setInput] = useState("");
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const atBottomRef = useRef(true);
  const [showJumpDown, setShowJumpDown] = useState(false);
  const scrollerRef = useRef<HTMLElement | null>(null);
  const attachedScrollerRef = useRef<HTMLElement | null>(null);
  const hudTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastHudOverrideKeyRef = useRef<string | null>(null);
  const sceneHudLiveRef = useRef(sceneHudLive);
  const onSceneHudSnapshotChangeRef = useRef(onSceneHudSnapshotChange);

  // While the player is parked at the bottom, follow new content — both new
  // turns appended to the array AND streaming tokens that grow the last
  // message in place. virtuoso's `followOutput` only catches new items, so
  // we cover the streaming case explicitly.
  useEffect(() => {
    if (!atBottomRef.current) return;
    if (messages.length === 0) return;
    virtuosoRef.current?.scrollToIndex({
      index: messages.length - 1,
      align: "end",
      behavior: "auto",
    });
  }, [messages]);

  // Scene-tab change: jump to the last message of the new (filtered) list
  // and re-arm sticky-to-bottom. Intentionally NOT depending on `messages`
  // — the auto-stick effect above already handles new content arriving
  // within a tab; this effect only fires on tab identity changes.
  useEffect(() => {
    if (tabKey === undefined) return;
    atBottomRef.current = true;
    setShowJumpDown(false);
    requestAnimationFrame(() => {
      const len = messagesRef.current.length;
      if (len === 0) return;
      virtuosoRef.current?.scrollToIndex({
        index: len - 1,
        align: "end",
        behavior: "auto",
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabKey]);

  // Mirror of `messages` so the tabKey effect can read the latest length
  // without re-firing on every message tick.
  const messagesRef = useRef(messages);
  useEffect(() => { messagesRef.current = messages; }, [messages]);
  useEffect(() => { sceneHudLiveRef.current = sceneHudLive; }, [sceneHudLive]);
  useEffect(() => {
    onSceneHudSnapshotChangeRef.current = onSceneHudSnapshotChange;
  }, [onSceneHudSnapshotChange]);

  const clearHudOverride = useCallback(() => {
    if (lastHudOverrideKeyRef.current === null) return;
    lastHudOverrideKeyRef.current = null;
    onSceneHudSnapshotChangeRef.current?.(null);
  }, []);

  const emitHudOverride = useCallback((
    key: string,
    snapshot: TrpgSceneHudSnapshot,
  ) => {
    if (lastHudOverrideKeyRef.current === key) return;
    lastHudOverrideKeyRef.current = key;
    onSceneHudSnapshotChangeRef.current?.(snapshot);
  }, []);

  const runSceneHudTracking = useCallback(() => {
    if (!onSceneHudSnapshotChangeRef.current) return;
    const el = scrollerRef.current;
    if (!el) {
      clearHudOverride();
      return;
    }

    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (sceneHudLiveRef.current && distanceFromBottom <= HUD_BOTTOM_THRESHOLD_PX) {
      clearHudOverride();
      return;
    }

    const centerId = pickCenterMessageId(el);
    if (!centerId) {
      clearHudOverride();
      return;
    }

    const msgs = messagesRef.current;
    let idx = -1;
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i]?.id === centerId) {
        idx = i;
        break;
      }
    }
    if (idx < 0) return;

    let gmIdx = -1;
    for (let i = idx; i >= 0; i--) {
      if (msgs[i]?.role === "gm") {
        gmIdx = i;
        break;
      }
    }
    if (gmIdx < 0) {
      emitHudOverride(`${centerId}:none`, {
        currentTime: null,
        sceneKey: null,
        sceneName: null,
      });
      return;
    }

    const gm = msgs[gmIdx];
    const sceneKey = gm.sceneKey ?? null;
    const sceneName = gm.sceneName ?? null;
    const currentTime = gm.currentTime ?? null;
    const hasData = Boolean(sceneKey || sceneName || currentTime);
    const timeKey = currentTime ? JSON.stringify(currentTime) : "";
    emitHudOverride(
      `${gm.id}:${hasData ? `${sceneKey || ""}:${sceneName || ""}:${timeKey}` : "miss"}`,
      hasData
        ? { currentTime, sceneKey, sceneName }
        : { currentTime: null, sceneKey: null, sceneName: null },
    );
  }, [clearHudOverride, emitHudOverride]);

  const scheduleSceneHudTracking = useCallback(() => {
    if (hudTimerRef.current) clearTimeout(hudTimerRef.current);
    hudTimerRef.current = setTimeout(runSceneHudTracking, HUD_SCROLL_DEBOUNCE_MS);
  }, [runSceneHudTracking]);

  const setScrollerRef = useCallback((ref: HTMLElement | Window | null) => {
    const next = ref instanceof HTMLElement ? ref : null;
    if (attachedScrollerRef.current === next) return;
    if (attachedScrollerRef.current) {
      attachedScrollerRef.current.removeEventListener("scroll", scheduleSceneHudTracking);
    }
    attachedScrollerRef.current = next;
    scrollerRef.current = next;
    if (next) {
      next.addEventListener("scroll", scheduleSceneHudTracking, { passive: true });
      requestAnimationFrame(scheduleSceneHudTracking);
    }
  }, [scheduleSceneHudTracking]);

  useEffect(() => {
    scheduleSceneHudTracking();
  }, [messages, sceneHudLive, tabKey, scheduleSceneHudTracking]);

  useEffect(() => () => {
    if (hudTimerRef.current) clearTimeout(hudTimerRef.current);
    if (attachedScrollerRef.current) {
      attachedScrollerRef.current.removeEventListener("scroll", scheduleSceneHudTracking);
    }
    clearHudOverride();
  }, [clearHudOverride, scheduleSceneHudTracking]);

  const onAtBottomChange = (atBottom: boolean) => {
    atBottomRef.current = atBottom;
    setShowJumpDown(!atBottom);
  };

  const onRangeChanged = (range: { startIndex: number; endIndex: number }) => {
    if (
      range.startIndex < NEAR_TOP_INDEX
      && hasMoreOlder
      && !loadingOlder
      && onLoadOlder
    ) {
      void onLoadOlder();
    }
  };

  const submit = () => {
    const text = input.trim();
    if (!text) return;
    onSend(text);
    setInput("");
  };

  const jumpToLatest = () => {
    if (messages.length === 0) return;
    virtuosoRef.current?.scrollToIndex({
      index: messages.length - 1,
      align: "end",
      behavior: "smooth",
    });
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0">
      <div className="flex-1 relative min-h-0">
        {messages.length > 0 && (
          <Virtuoso
            ref={virtuosoRef}
            scrollerRef={setScrollerRef}
            className="absolute inset-0"
            data={messages}
            computeItemKey={(_, msg) => msg.id}
            initialTopMostItemIndex={messages.length - 1}
            atBottomStateChange={onAtBottomChange}
            rangeChanged={(range) => {
              onRangeChanged(range);
              scheduleSceneHudTracking();
            }}
            followOutput="auto"
            increaseViewportBy={{ top: 600, bottom: 200 }}
            components={{
              Header: () => (
                <ListHeader
                  hasMoreOlder={hasMoreOlder}
                  loadingOlder={loadingOlder}
                  loadingLabel={t("chatLoadingOlder")}
                  startLabel={t("chatStartOfHistory")}
                />
              ),
              Footer: () => <div className="h-3" />,
            }}
            itemContent={(_, msg) => (
              <div className="px-6" data-message-id={msg.id}>
                {/* flex flex-col is required for `self-end` on the user
                    bubble inside <Message/>; Virtuoso renders each item in
                    its own wrapper, so the alignment context has to live
                    here rather than on the parent list. */}
                <div className="mx-auto w-full max-w-[800px] py-2 flex flex-col">
                  <Message
                    msg={msg}
                    sessionId={sessionId}
                    chatStyle={chatStyle}
                    characterName={characterName}
                    characterInitial={characterInitial}
                    speakerProfiles={speakerProfiles}
                    onResolvePending={
                      onResolvePending && msg.role === "gm" && msg.pendingChecks
                        ? (pending) => onResolvePending(msg.id, pending)
                        : undefined
                    }
                    resolvingPending={resolvingPendingId === msg.id}
                  />
                </div>
              </div>
            )}
          />
        )}
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
        onSubmit={submit}
        placeholder={t("chatPlaceholder")}
        sendTitle={t("chatSend")}
        actionSlot={
          <ComposerIconButton onClick={onOpenDice} title={t("chatRollDice")}>
            <D20Icon size={20} />
          </ComposerIconButton>
        }
      />
    </div>
  );
}

function pickCenterMessageId(el: HTMLElement): string | null {
  const rect = el.getBoundingClientRect();
  const centerY = rect.top + rect.height / 2;
  const nodes = el.querySelectorAll<HTMLElement>("[data-message-id]");
  let bestId: string | null = null;
  let bestDist = Number.POSITIVE_INFINITY;

  nodes.forEach((node) => {
    const r = node.getBoundingClientRect();
    if (r.bottom < rect.top || r.top > rect.bottom) return;
    const midY = r.top + r.height / 2;
    const dist = Math.abs(midY - centerY);
    if (dist < bestDist) {
      bestDist = dist;
      bestId = node.dataset.messageId || null;
    }
  });

  return bestId;
}

function ListHeader({
  hasMoreOlder,
  loadingOlder,
  loadingLabel,
  startLabel,
}: {
  hasMoreOlder: boolean;
  loadingOlder: boolean;
  loadingLabel: string;
  startLabel: string;
}) {
  if (hasMoreOlder) {
    return (
      <div className="text-center py-3 text-[12px] text-text-2 select-none">
        {loadingOlder ? loadingLabel : " "}
      </div>
    );
  }
  return (
    <div className="text-center py-3 text-[11px] text-text-3 select-none">
      {startLabel}
    </div>
  );
}
