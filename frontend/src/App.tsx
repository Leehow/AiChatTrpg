import { useCallback, useEffect, useRef, useState } from "react";
import { Admin } from "./components/Admin";
import { Chrome } from "./components/Chrome";
import { LoginPage } from "./components/LoginPage";
import { SetupFlow, type SetupResult } from "./components/setup/SetupFlow";
import { GameShell } from "./components/game/GameShell";
import { MusicPlayer } from "./components/music/MusicPlayer";
import { RulesetView } from "./components/ruleset/RulesetView";
import {
  subscribeOpenDebugTab,
  type DebugTab,
  type MessageSnapshot,
} from "./lib/debugUiBus";
import { dtoToParsed, getRulesetAPI } from "./lib/ruleset/api";
import type { ParsedRuleset } from "./lib/ruleset/types";
import type { RoomEntry } from "./components/game/RoomsPanel";
import { ApiError } from "./api/http";
import { updatePreferencesAPI } from "./api/auth";
import {
  createSessionAPI,
  deleteSessionAPI,
  listSessionsAPI,
  updateSessionAPI,
  type SessionDetailDTO,
  type SessionSummaryDTO,
} from "./api/sessions";
import {
  createDraftAPI,
  deleteDraftAPI,
  listDraftsAPI,
  type DraftSummaryDTO,
} from "./api/ruleset-drafts";
import { EditorShell } from "./components/rule-editor/EditorShell";
import { useAuthGate, usePathname, useTheme } from "./app/hooks";
import {
  draftToRoom,
  summaryFromDetail,
  summaryToRoom,
} from "./app/roomMappers";
import { EMPTY_SETUP_STATE, type Screen } from "./app/screen";
import { usePreviewRuleset } from "./app/usePreviewRuleset";

export default function App() {
  const path = usePathname();
  const [theme, toggleTheme] = useTheme();
  const { user, signIn, signOut } = useAuthGate();

  const [screen, setScreen] = useState<Screen>({
    kind: "setup",
    sessionId: "",
    initial: EMPTY_SETUP_STATE,
  });
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [debugForceTab, setDebugForceTab] = useState<
    {
      tab: DebugTab;
      serial: number;
      messageSnapshot?: MessageSnapshot;
    } | undefined
  >(undefined);
  useEffect(() => {
    return subscribeOpenDebugTab((tab, messageSnapshot) => {
      setDebugForceTab((prev) => ({
        tab,
        serial: (prev?.serial ?? 0) + 1,
        messageSnapshot,
      }));
    });
  }, []);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [previewRuleset, setPreviewRuleset] = usePreviewRuleset(screen);
  const [setupActiveRuleset, setSetupActiveRuleset] =
    useState<ParsedRuleset | null>(null);
  const [drafts, setDrafts] = useState<DraftSummaryDTO[]>([]);

  const refreshDrafts = useCallback(async (): Promise<void> => {
    try {
      const list = await listDraftsAPI();
      setDrafts(list);
    } catch (err) {
      console.warn("[chatrpg] list drafts failed:", err);
    }
  }, []);

  // /drafts/{id} → editor screen. Mirrors the /admin handling but reuses
  // the screen state machine so Chrome (rooms sidebar etc.) stays mounted.
  useEffect(() => {
    const m = path.match(/^\/drafts\/([^/]+)\/?$/);
    if (!m) return;
    const draftId = m[1];
    setScreen((prev) =>
      prev.kind === "editor" && prev.draftId === draftId
        ? prev
        : { kind: "editor", draftId },
    );
    setActiveSessionId(draftId);
  }, [path]);

  // Load sessions from backend whenever the user logs in.
  const refreshSessions = useCallback(async (): Promise<SessionSummaryDTO[]> => {
    try {
      const list = await listSessionsAPI();
      setSessions(list);
      return list;
    } catch (err) {
      console.warn("[chatrpg] list sessions failed:", err);
      return [];
    }
  }, []);

  // Stable void-returning wrapper to hand to SetupFlow. Without
  // useCallback, every App render produced a fresh function identity,
  // which cascaded through SetupFlow's useCallbacks and triggered a
  // PUT → refreshSessions → re-render → PUT loop (visible as flicker
  // on the room list).
  const handleSessionsChanged = useCallback((): void => {
    void refreshSessions();
  }, [refreshSessions]);

  // Tracks which user has had their post-login resume attempted, and
  // whether that attempt has finished. The persist effect below waits on
  // `done` so the very first activeSessionId transition (resume) doesn't
  // race-clobber the saved pref with `null`.
  const resumeStateRef = useRef<{ userId: string | null; done: boolean }>({
    userId: null,
    done: false,
  });

  useEffect(() => {
    if (!user) {
      resumeStateRef.current = { userId: null, done: false };
      setSessions([]);
      setDrafts([]);
      setActiveSessionId(null);
      setScreen({ kind: "setup", sessionId: "", initial: EMPTY_SETUP_STATE });
      return;
    }
    // Only resume once per logged-in user — preference writes update the
    // `user` reference (via setStoredAuth) and would otherwise re-trigger.
    if (resumeStateRef.current.userId === user.id) return;
    resumeStateRef.current = { userId: user.id, done: false };
    void refreshDrafts();
    void (async () => {
      try {
        const list = await refreshSessions();
        // If the URL is /drafts/{id}, the path-watching effect below already
        // routes to the editor — don't clobber it with a session resume.
        if (/^\/drafts\/[^/]+\/?$/.test(window.location.pathname)) {
          return;
        }
        const savedId = user.preferences?.last_active_session_id ?? null;
        const saved = savedId ? list.find((s) => s.id === savedId) : null;
        if (saved) {
          // Drafts → resume the wizard; finished rooms → drop into game.
          if (!saved.setup_state.completed || !saved.ruleset_id) {
            setActiveSessionId(saved.id);
            setScreen({
              kind: "setup",
              sessionId: saved.id,
              initial: saved.setup_state,
            });
            return;
          }
          try {
            const dto = await getRulesetAPI(saved.ruleset_id);
            setActiveSessionId(saved.id);
            setScreen({
              kind: "game",
              sessionId: saved.id,
              ruleset: dtoToParsed(dto),
            });
            return;
          } catch (err) {
            console.warn(
              "[chatrpg] resume saved room failed, falling back to draft:",
              err
            );
          }
        }
        // Fallback: resume the most-recent draft, same as before.
        const firstDraft = list.find((s) => !s.setup_state.completed);
        if (firstDraft) {
          setActiveSessionId(firstDraft.id);
          setScreen({
            kind: "setup",
            sessionId: firstDraft.id,
            initial: firstDraft.setup_state,
          });
        }
      } finally {
        resumeStateRef.current.done = true;
      }
    })();
  }, [user, refreshSessions, refreshDrafts]);

  // Persist activeSessionId → user.preferences.last_active_session_id so a
  // refresh re-enters the same room. Skipped while logged out so logout
  // doesn't clear the saved id (b: 不清空). Skipped until resume finishes
  // so the first render's null state doesn't clobber the saved id.
  useEffect(() => {
    if (!user) return;
    if (!resumeStateRef.current.done) return;
    const desired = activeSessionId ?? null;
    const current = user.preferences?.last_active_session_id ?? null;
    if (desired === current) return;
    void updatePreferencesAPI({ last_active_session_id: desired }).catch(
      (err) =>
        console.warn(
          "[chatrpg] persist last_active_session_id failed:",
          err
        )
    );
  }, [user, activeSessionId]);

  const enterGame = useCallback(
    (sessionId: string, ruleset: ParsedRuleset) => {
      setActiveSessionId(sessionId);
      setScreen({ kind: "game", sessionId, ruleset });
    },
    []
  );

  // Setup wizard finished → mark the draft session as completed and enter
  // the game. We always operate on a session row that already exists
  // (the draft created when "+" was pressed).
  const finishSetup = useCallback(
    async (sessionId: string, result: SetupResult) => {
      try {
        await updateSessionAPI(sessionId, {
          ruleset_id: result.rulesetId,
          setup_state: { step: 2, completed: true },
        });
        await refreshSessions();
        enterGame(sessionId, result.ruleset);
      } catch (err) {
        console.error("[chatrpg] finish setup failed:", err);
        alert(err instanceof Error ? err.message : "Failed to finish setup");
      }
    },
    [enterGame, refreshSessions]
  );

  // Click "+" → instantly persist a blank draft so progress survives
  // refresh, then drop the user into the wizard with that draft's id.
  const startNewDraft = useCallback(async () => {
    try {
      const created: SessionDetailDTO = await createSessionAPI({});
      // Prepend so the new draft is visible immediately, even before
      // the next refresh round-trip.
      setSessions((prev) => [summaryFromDetail(created), ...prev]);
      setActiveSessionId(created.id);
      setScreen({
        kind: "setup",
        sessionId: created.id,
        initial: created.setup_state,
      });
    } catch (err) {
      console.error("[chatrpg] create draft session failed:", err);
      alert(err instanceof Error ? err.message : "Failed to create draft");
    }
  }, []);

  // Setup-flow asked to materialise a draft for the ruleset the user just
  // picked, instead of forcing them through the "+" button. We create a
  // blank draft (so setup_state.completed stays false) and then update it
  // with the chosen ruleset + step=1 so the wizard advances onto modules.
  const createDraftForRuleset = useCallback(
    async (rulesetId: string): Promise<void> => {
      const blank: SessionDetailDTO = await createSessionAPI({});
      const updated: SessionDetailDTO = await updateSessionAPI(blank.id, {
        ruleset_id: rulesetId,
        setup_state: {
          step: 1,
          ruleset_id: rulesetId,
          module_id: null,
          module_title: null,
          completed: false,
        },
      });
      setSessions((prev) => [summaryFromDetail(updated), ...prev]);
      setActiveSessionId(updated.id);
      setScreen({
        kind: "setup",
        sessionId: updated.id,
        initial: updated.setup_state,
      });
    },
    []
  );

  const navigateToEditor = useCallback((draftId: string) => {
    window.history.pushState({}, "", `/drafts/${draftId}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
    setActiveSessionId(draftId);
    setScreen({ kind: "editor", draftId });
  }, []);

  const leaveEditor = useCallback(() => {
    window.history.pushState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
    setActiveSessionId(null);
    setScreen({ kind: "setup", sessionId: "", initial: EMPTY_SETUP_STATE });
  }, []);

  const createBlankDraft = useCallback(async () => {
    try {
      const d = await createDraftAPI({});
      await refreshDrafts();
      navigateToEditor(d.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create draft");
    }
  }, [navigateToEditor, refreshDrafts]);

  const forkDraftFromRuleset = useCallback(
    async (rulesetId: string) => {
      try {
        const d = await createDraftAPI({ base_ruleset_id: rulesetId });
        await refreshDrafts();
        navigateToEditor(d.id);
      } catch (err) {
        alert(err instanceof Error ? err.message : "Failed to fork");
      }
    },
    [navigateToEditor, refreshDrafts]
  );

  const inPlaceEditRuleset = useCallback(
    async (rulesetId: string) => {
      try {
        const d = await createDraftAPI({ target_ruleset_id: rulesetId });
        await refreshDrafts();
        navigateToEditor(d.id);
      } catch (err) {
        alert(err instanceof Error ? err.message : "Failed to start edit");
      }
    },
    [navigateToEditor, refreshDrafts]
  );

  const onSelectRoom = useCallback(
    async (id: string) => {
      // Rule drafts take precedence so a session and draft id collision
      // (theoretically possible since both use uuid) routes to the editor.
      const draftHit = drafts.find((d) => d.id === id);
      if (draftHit) {
        navigateToEditor(draftHit.id);
        return;
      }
      const summary = sessions.find((s) => s.id === id);
      if (!summary) return;
      // Drafts (or rows missing a ruleset) → resume the wizard.
      if (!summary.setup_state.completed || !summary.ruleset_id) {
        setActiveSessionId(id);
        setScreen({
          kind: "setup",
          sessionId: id,
          initial: summary.setup_state,
        });
        return;
      }
      try {
        const dto = await getRulesetAPI(summary.ruleset_id);
        enterGame(id, dtoToParsed(dto));
      } catch (err) {
        console.error("[chatrpg] load session ruleset failed:", err);
      }
    },
    [drafts, enterGame, navigateToEditor, sessions]
  );

  if (!user) {
    return <LoginPage onLoggedIn={signIn} />;
  }

  if (path.startsWith("/admin")) {
    return (
      <div className="flex h-full w-full">
        <Admin />
        <MusicPlayer />
      </div>
    );
  }

  const onOpenRulesetView = () => {
    if (screen.kind === "game") {
      // Look up the ruleset id from the current session. Drafts won't
      // reach this branch (game screen requires a finished session).
      const summary = sessions.find((s) => s.id === screen.sessionId);
      if (summary && summary.ruleset_id) {
        setScreen({
          kind: "preview",
          rulesetId: summary.ruleset_id,
          from: "game",
        });
      }
    }
  };

  const onLeaveSession = () => {
    setActiveSessionId(null);
    setScreen({ kind: "setup", sessionId: "", initial: EMPTY_SETUP_STATE });
  };

  const debugTarget: ParsedRuleset | null =
    screen.kind === "preview"
      ? previewRuleset
      : screen.kind === "game"
      ? screen.ruleset
      : setupActiveRuleset;

  const rooms: RoomEntry[] = [
    ...sessions.map((s) => summaryToRoom(s, activeSessionId)),
    ...drafts.map((d) => draftToRoom(d, activeSessionId)),
  ];

  return (
    <Chrome
      debugTarget={debugTarget}
      rooms={rooms}
      activeRoomId={activeSessionId}
      onSelectRoom={onSelectRoom}
      onNewRoom={() => void startNewDraft()}
      onDeleteRoom={async (id) => {
        // Rule drafts and sessions live in different tables, so route
        // delete based on which list owns the id. A 404 from either
        // endpoint means the row is already gone server-side — treat
        // it as success and just resync local state.
        const isDraft = drafts.some((d) => d.id === id);
        try {
          if (isDraft) {
            await deleteDraftAPI(id);
          } else {
            await deleteSessionAPI(id);
          }
        } catch (err) {
          if (!(err instanceof ApiError) || err.status !== 404) {
            console.error("[chatrpg] delete failed:", err);
            return;
          }
          // 404 → fall through to local cleanup below.
        }
        if (id === activeSessionId) {
          setActiveSessionId(null);
          setScreen({
            kind: "setup",
            sessionId: "",
            initial: EMPTY_SETUP_STATE,
          });
        }
        if (isDraft) {
          await refreshDrafts();
        } else {
          await refreshSessions();
        }
      }}
      theme={theme}
      onToggleTheme={toggleTheme}
      onLeaveSession={onLeaveSession}
      onLogout={signOut}
      userName={user.name}
      isAdmin={user.role === "admin"}
      currentUserId={user.id}
      onOpenRulesetView={onOpenRulesetView}
      onToggleSidebar={
        screen.kind === "game" ? () => setSidebarOpen((o) => !o) : undefined
      }
      debugForceTab={debugForceTab}
    >
      {screen.kind === "setup" && (
        <SetupFlow
          sessionId={screen.sessionId || null}
          initial={screen.initial}
          onComplete={(result) =>
            screen.sessionId
              ? void finishSetup(screen.sessionId, result)
              : void startNewDraft().then(() => {
                  // Edge case: setup opened without a draft (legacy entry
                  // path). Fall through; user will hit "+" to create one.
                })
          }
          onCreateDraft={createDraftForRuleset}
          onPreviewRuleset={(id) =>
            setScreen({ kind: "preview", rulesetId: id, from: "setup" })
          }
          onActiveRulesetChanged={setSetupActiveRuleset}
          onSessionsChanged={handleSessionsChanged}
          onCreateBlankRuleDraft={createBlankDraft}
          onForkRuleDraft={forkDraftFromRuleset}
          onInPlaceEditRuleset={inPlaceEditRuleset}
        />
      )}

      {screen.kind === "editor" && (
        <EditorShell
          draftId={screen.draftId}
          onLeave={leaveEditor}
          onPromoted={() => {
            void refreshSessions();
          }}
          onDeleted={() => {
            void refreshDrafts();
          }}
          onEdited={() => {
            void refreshDrafts();
          }}
        />
      )}

      {screen.kind === "preview" && previewRuleset && (
        <RulesetView
          parsed={previewRuleset}
          rulesetId={screen.rulesetId}
          onDiceIRChanged={(artifact) =>
            setPreviewRuleset((prev) =>
              prev ? { ...prev, dice_ir: artifact ?? null } : prev
            )
          }
          onRulesetChanged={(detail) => setPreviewRuleset(dtoToParsed(detail))}
          onClose={() => {
            if (screen.from === "game" && activeSessionId) {
              const summary = sessions.find((s) => s.id === activeSessionId);
              if (summary && previewRuleset) {
                setScreen({
                  kind: "game",
                  sessionId: activeSessionId,
                  ruleset: previewRuleset,
                });
                return;
              }
            }
            setScreen({
              kind: "setup",
              sessionId: "",
              initial: EMPTY_SETUP_STATE,
            });
          }}
        />
      )}

      {screen.kind === "game" && (
        <GameShell
          sessionId={screen.sessionId}
          parsed={screen.ruleset}
          theme={theme}
          sidebarOpen={sidebarOpen}
          onCloseSidebar={() => setSidebarOpen(false)}
          onOpenRulesetView={onOpenRulesetView}
        />
      )}
      <MusicPlayer
        sessionId={screen.kind === "game" ? screen.sessionId : undefined}
      />
    </Chrome>
  );
}
