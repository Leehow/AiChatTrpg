import { useCallback, useEffect, useState, type ReactNode } from "react";
import { TopBar } from "./game/TopBar";
import { RoomsPanel, type RoomEntry } from "./game/RoomsPanel";
import { DebugPanel } from "./DebugPanel";
import { useIsMobile } from "../hooks/useIsMobile";
import type { ParsedRuleset } from "../lib/ruleset/types";
import type { MessageSnapshot } from "../lib/debugUiBus";

interface ChromeProps {
  rooms: RoomEntry[];
  activeRoomId: string | null;
  onSelectRoom: (id: string) => void;
  onNewRoom: () => void;
  onDeleteRoom?: (id: string) => void;
  theme: "warm" | "slate";
  onToggleTheme: () => void;
  onLeaveSession: () => void;
  onLogout: () => void;
  userName: string;
  /** When false, debug panel + toggle button are hidden. Players never
   *  see the dev tools or user management. */
  isAdmin: boolean;
  /** Caller's user id, threaded into the users tab so it can mark
   *  "you" and disable destructive operations against self. */
  currentUserId: string;
  onOpenRulesetView: () => void;
  /** When provided, shows the sidebar toggle button in the topbar. */
  onToggleSidebar?: () => void;
  /** Currently focused ruleset for the right-rail debug inspector. */
  debugTarget: ParsedRuleset | null;
  /** Forces the debug panel to a given tab. Bumped via `serial` so repeat
   *  triggers from chain-of-thought "view context" buttons reset the tab.
   *  When `messageSnapshot` is set, the Context tab scopes its render to
   *  that GM message's BP2/BP3 instead of the live ruleset snapshot. */
  debugForceTab?: {
    tab: "context" | "ruleset" | "llm" | "ocr" | "module" | "users";
    serial: number;
    messageSnapshot?: MessageSnapshot;
  };
  /** Right-side area: setup body, ruleset view, or chat column. */
  children: ReactNode;
}

// Common chrome shared across setup / preview / chat: topbar at the top,
// rooms list on the left rail. The screen-specific UI fills the remaining
// space via the children prop.
export function Chrome({
  rooms,
  activeRoomId,
  onSelectRoom,
  onNewRoom,
  onDeleteRoom,
  theme,
  onToggleTheme,
  onLeaveSession,
  onLogout,
  userName,
  isAdmin,
  currentUserId,
  onOpenRulesetView,
  onToggleSidebar,
  debugTarget,
  debugForceTab,
  children,
}: ChromeProps) {
  const isMobile = useIsMobile();
  const [showRooms, setShowRooms] = useState(() => !isMobile);
  const [showDebug, setShowDebug] = useState(() => !isMobile);

  // When the viewport crosses the mobile breakpoint, force-close both
  // rails so the layout doesn't enter mobile mode with two overlays
  // already covering the chat area.
  useEffect(() => {
    if (isMobile) {
      setShowRooms(false);
      setShowDebug(false);
    }
  }, [isMobile]);

  // On mobile only one drawer can be open at a time — opening one
  // closes the other so they don't fight over the same screen.
  const toggleRooms = useCallback(() => {
    setShowRooms((o) => {
      const next = !o;
      if (isMobile && next) setShowDebug(false);
      return next;
    });
  }, [isMobile]);

  const toggleDebug = useCallback(() => {
    setShowDebug((o) => {
      const next = !o;
      if (isMobile && next) setShowRooms(false);
      return next;
    });
  }, [isMobile]);

  const closeAllDrawers = useCallback(() => {
    setShowRooms(false);
    setShowDebug(false);
  }, []);

  const drawerOpen = isMobile && (showRooms || showDebug);
  const activeRoom = rooms.find((r) => r.id === activeRoomId);
  const roomTitle = activeRoom?.name;

  return (
    <div className="flex h-full w-full flex-col bg-bg text-text overflow-hidden">
      <TopBar
        roomTitle={roomTitle}
        onToggleRooms={toggleRooms}
        onToggleSidebar={onToggleSidebar}
        onToggleDebug={isAdmin ? toggleDebug : undefined}
        debugOn={showDebug}
        onToggleTheme={onToggleTheme}
        theme={theme}
        onOpenRulesetView={onOpenRulesetView}
        onLeaveSession={onLeaveSession}
        onLogout={onLogout}
        userName={userName}
        isMobile={isMobile}
      />
      <div className="flex-1 flex overflow-hidden relative">
        <RoomsPanel
          rooms={rooms}
          activeId={activeRoomId}
          visible={showRooms}
          drawerMode={isMobile}
          onSelect={(id) => {
            onSelectRoom(id);
            if (isMobile) setShowRooms(false);
          }}
          onNew={() => {
            onNewRoom();
            if (isMobile) setShowRooms(false);
          }}
          onDelete={onDeleteRoom}
        />
        {children}
        {isAdmin && (
          <DebugPanel
            parsed={debugTarget}
            visible={showDebug}
            drawerMode={isMobile}
            currentUserId={currentUserId}
            sessionId={activeRoomId}
            forceTab={debugForceTab}
          />
        )}
        {drawerOpen && (
          <button
            type="button"
            onClick={closeAllDrawers}
            aria-label="Close drawer"
            className="absolute inset-0 bg-black/40 z-40 cursor-default"
          />
        )}
      </div>
    </div>
  );
}
