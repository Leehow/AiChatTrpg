import { useCallback, useEffect, useRef, useState } from "react";
import {
  createMessageAPI,
  getSessionAPI,
  listMessagesAPI,
  streamIcTurnAPI,
  type SessionDetailDTO,
} from "../../../api/sessions";
import type { ChatMessage, PendingCheckSummary } from "../Message";
import {
  dtoToChatMessage,
  isInternalContextSystemRow,
  manualRollValueForPending,
  notationForPendingCheck,
  nowTime,
  type ActiveDiceRoll,
  type ManualRollValue,
} from "./messageHelpers";

interface UseGameMessagesArgs {
  sessionId: string;
  setSession: (detail: SessionDetailDTO) => void;
  diceRollLabel: string;
}

interface UseGameMessagesResult {
  messages: ChatMessage[];
  hasMoreOlder: boolean;
  loadingOlder: boolean;
  loadError: string | null;
  activeSceneKey: string | null;
  resolvingPendingId: string | null;
  pendingRoll: ActiveDiceRoll | null;
  setActiveSceneKey: (key: string | null) => void;
  setPendingRoll: (roll: ActiveDiceRoll | null) => void;
  loadOlder: () => Promise<void>;
  sendMessage: (text: string) => Promise<void>;
  startPendingRoll: (
    gmMessageId: string,
    pending: PendingCheckSummary,
  ) => void;
  handlePendingRollResult: (
    roll: Extract<ActiveDiceRoll, { kind: "pending" }>,
    result: { total: number; rolls: number[] },
  ) => Promise<void>;
  handleDiceRoll: (diceType: string, result: number) => Promise<void>;
}

export function useGameMessages({
  sessionId,
  setSession,
  diceRollLabel,
}: UseGameMessagesArgs): UseGameMessagesResult {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hasMoreOlder, setHasMoreOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  // Tracks the GM message id whose pending check is currently being
  // resolved. While set, the "投出" button on that bubble flips to a
  // disabled "投骰中…" state and a stray double-click is a no-op.
  const [resolvingPendingId, setResolvingPendingId] = useState<string | null>(
    null,
  );
  // Selected scene tab. null = follow latest. The player can browse history
  // by picking a non-latest scene; sending a message snaps back to latest so
  // their turn is visible.
  const [activeSceneKey, setActiveSceneKey] = useState<string | null>(null);
  const [pendingRoll, setPendingRoll] = useState<ActiveDiceRoll | null>(null);

  // Mirror of `messages` for use inside `loadOlder` without re-creating the
  // callback on every message tick (which would re-render ChatArea each turn).
  const messagesRef = useRef<ChatMessage[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Load session detail + most recent 100 messages whenever the session
  // changes. Older history is paged in via `loadOlder` once the player
  // scrolls near the top.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [detail, list] = await Promise.all([
          getSessionAPI(sessionId),
          listMessagesAPI(sessionId, { limit: 100 }),
        ]);
        if (cancelled) return;
        setSession(detail);
        setMessages(list.items.filter((m) => !isInternalContextSystemRow(m)).map(dtoToChatMessage));
        setHasMoreOlder(list.has_more);
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "Load failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, setSession]);

  const loadOlder = useCallback(async () => {
    if (loadingOlder) return;
    const buffer = messagesRef.current;
    const oldestId = buffer[0]?.id;
    if (!oldestId) return;
    setLoadingOlder(true);
    try {
      const list = await listMessagesAPI(sessionId, {
        limit: 100,
        before_id: oldestId,
      });
      const older = list.items.filter((m) => !isInternalContextSystemRow(m)).map(dtoToChatMessage);
      if (older.length > 0) {
        setMessages((prev) => [...older, ...prev]);
      }
      setHasMoreOlder(list.has_more);
    } catch (err) {
      console.warn("[chatrpg] load older messages failed:", err);
    } finally {
      setLoadingOlder(false);
    }
  }, [sessionId, loadingOlder]);

  const sendMessage = useCallback(
    async (text: string) => {
      // Snap back to "follow latest" so the player's new turn isn't filtered
      // out by a history-browsing tab they left selected.
      setActiveSceneKey(null);
      const userTmpId = `tmp-user-${Date.now()}`;
      const gmTmpId = `tmp-gm-${Date.now()}`;
      const userOptimistic: ChatMessage = {
        id: userTmpId,
        role: "user",
        text,
        time: nowTime(),
      };
      const gmStreaming: ChatMessage = {
        id: gmTmpId,
        role: "gm",
        text: "",
        time: nowTime(),
      };
      setMessages((prev) => [...prev, userOptimistic, gmStreaming]);
      try {
        await streamIcTurnAPI(
          sessionId,
          { message: text },
          {
            onThinking: (step) => {
              if (!step) return;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === gmTmpId
                    ? { ...m, thinkingSteps: [...(m.thinkingSteps ?? []), step] }
                    : m
                )
              );
            },
            onContent: (delta) => {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === gmTmpId
                    ? { ...m, text: (m.text ?? "") + delta }
                    : m
                )
              );
            },
          }
        );
        // Refresh from server so the optimistic rows pick up real IDs and
        // any state-diff changes (memory, dice, scene) reflect in the
        // session row used by the sidebar. Re-anchors to the latest 100 —
        // any older history loaded via scroll-up is dropped, since the
        // player just sent a new turn (so they're back at the bottom).
        const [detail, list] = await Promise.all([
          getSessionAPI(sessionId),
          listMessagesAPI(sessionId, { limit: 100 }),
        ]);
        setSession(detail);
        setMessages(list.items.filter((m) => !isInternalContextSystemRow(m)).map(dtoToChatMessage));
        setHasMoreOlder(list.has_more);
      } catch (err) {
        const message = err instanceof Error ? err.message : "unknown error";
        setMessages((prev) =>
          prev
            .filter((m) => m.id !== gmTmpId)
            .map((m) =>
              m.id === userTmpId
                ? {
                    ...m,
                    role: "system",
                    text: `Failed to send: ${message}`,
                    time: undefined,
                  }
                : m
            )
        );
      }
    },
    [sessionId, setSession]
  );

  const resolvePendingFor = useCallback(
    async (
      gmMessageId: string,
      pendingCheckId?: string,
      rollResult?: ManualRollValue,
    ) => {
      if (resolvingPendingId) return;
      setActiveSceneKey(null);
      setResolvingPendingId(gmMessageId);
      const startedAt = Date.now();
      const gmTmpId = `tmp-gm-${Date.now()}`;
      const gmStreaming: ChatMessage = {
        id: gmTmpId,
        role: "gm",
        text: "",
        time: nowTime(),
      };
      setMessages((prev) => [...prev, gmStreaming]);
      try {
        await streamIcTurnAPI(
          sessionId,
          {
            message: "",
            intent: "resolve",
            pending_check_id: pendingCheckId,
            roll_result: rollResult,
          },
          {
            onThinking: (step) => {
              if (!step) return;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === gmTmpId
                    ? { ...m, thinkingSteps: [...(m.thinkingSteps ?? []), step] }
                    : m
                )
              );
            },
            onContent: (delta) => {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === gmTmpId
                    ? { ...m, text: (m.text ?? "") + delta }
                    : m
                )
              );
            },
          }
        );
        // Refresh from server: the prior GM message was mutated server-side
        // (placeholder → [dice] block, pending_checks[*].resolved=true) and
        // we want optimistic ids replaced by real ones.
        const [detail, list] = await Promise.all([
          getSessionAPI(sessionId),
          listMessagesAPI(sessionId, { limit: 100 }),
        ]);
        setSession(detail);
        setMessages(list.items.filter((m) => !isInternalContextSystemRow(m)).map(dtoToChatMessage));
        setHasMoreOlder(list.has_more);
      } catch (err) {
        // Resolve has two halves: (1) backend rolls + commits the dice msg +
        // mutates the prior GM message, then (2) the GM continuation streams
        // back. Half (1) commits even if the SSE drops mid-(2) — e.g. a
        // backend reload, network blip, or the server-side LLM call timing
        // out partway through. Refresh from server first so we can tell
        // these cases apart: if the dice landed, no error popup is needed —
        // the player just needs to send a free-form continuation. Show an
        // error toast only when nothing committed at all.
        try {
          const [detail, list] = await Promise.all([
            getSessionAPI(sessionId),
            listMessagesAPI(sessionId, { limit: 100 }),
          ]);
          const isFresh = (iso: string | undefined) => {
            const ts = iso ? Date.parse(iso) : Number.NaN;
            return Number.isFinite(ts) && ts >= startedAt - 5_000;
          };
          const visibleItems = list.items.filter((m) => !isInternalContextSystemRow(m));
          const dicePersisted = visibleItems.some(
            (m) => m.role === "dice" && isFresh(m.created_at),
          );
          const gmContinuationPersisted = visibleItems.some(
            (m) => m.role === "gm" && isFresh(m.created_at),
          );
          setSession(detail);
          setMessages(visibleItems.map(dtoToChatMessage));
          setHasMoreOlder(list.has_more);
          if (!dicePersisted) {
            const message = err instanceof Error ? err.message : "unknown error";
            setMessages((prev) =>
              prev.concat([
                {
                  id: `tmp-sys-${Date.now()}`,
                  role: "system",
                  text: `Roll failed: ${message}`,
                },
              ])
            );
          } else if (!gmContinuationPersisted) {
            const message = err instanceof Error ? err.message : "unknown error";
            setMessages((prev) =>
              prev.concat([
                {
                  id: `tmp-sys-${Date.now()}`,
                  role: "system",
                  text: `Roll resolved, but GM continuation failed: ${message}`,
                },
              ])
            );
          }
        } catch {
          const message = err instanceof Error ? err.message : "unknown error";
          setMessages((prev) =>
            prev
              .filter((m) => m.id !== gmTmpId)
              .concat([
                {
                  id: `tmp-sys-${Date.now()}`,
                  role: "system",
                  text: `Roll failed: ${message}`,
                },
              ])
          );
        }
      } finally {
        setResolvingPendingId(null);
      }
    },
    [resolvingPendingId, sessionId, setSession],
  );

  const startPendingRoll = useCallback(
    (gmMessageId: string, pending: PendingCheckSummary) => {
      if (resolvingPendingId || pendingRoll) return;
      const notation = notationForPendingCheck(pending);
      setActiveSceneKey(null);
      setPendingRoll({
        kind: "pending",
        gmMessageId,
        pending,
        notation,
      });
    },
    [pendingRoll, resolvingPendingId],
  );

  const handlePendingRollResult = useCallback(
    async (
      roll: Extract<ActiveDiceRoll, { kind: "pending" }>,
      result: { total: number; rolls: number[] },
    ) => {
      const manualRoll = manualRollValueForPending(
        roll.pending,
        roll.notation,
        result,
      );
      await resolvePendingFor(roll.gmMessageId, roll.pending.id, manualRoll);
    },
    [resolvePendingFor],
  );

  const handleDiceRoll = useCallback(
    async (diceType: string, result: number) => {
      const meta = { type: `${diceType} ${diceRollLabel}`, result, dc: 0 };
      const optimistic: ChatMessage = {
        id: `tmp-${Date.now()}`,
        role: "dice",
        type: meta.type,
        result,
        dc: 0,
        time: nowTime(),
      };
      setMessages((prev) => [...prev, optimistic]);
      try {
        const persisted = await createMessageAPI(sessionId, {
          role: "dice",
          content: `${meta.type}=${result}`,
          metadata: meta,
        });
        setMessages((prev) =>
          prev.map((m) => (m.id === optimistic.id ? dtoToChatMessage(persisted) : m))
        );
      } catch (err) {
        console.warn("[chatrpg] persist dice roll failed:", err);
      }
    },
    [sessionId, diceRollLabel]
  );

  return {
    messages,
    hasMoreOlder,
    loadingOlder,
    loadError,
    activeSceneKey,
    resolvingPendingId,
    pendingRoll,
    setActiveSceneKey,
    setPendingRoll,
    loadOlder,
    sendMessage,
    startPendingRoll,
    handlePendingRollResult,
    handleDiceRoll,
  };
}
