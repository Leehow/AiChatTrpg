import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import type { ParsedRuleset } from "../lib/ruleset/types";
import type { MessageSnapshot } from "../lib/debugUiBus";
import { useResizableWidth } from "../hooks/useResizableWidth";
import { DebugContextTab } from "./debug/DebugContextTab";
import { DebugLLMTab } from "./debug/DebugLLMTab";
import { DebugMemoryTab } from "./debug/DebugMemoryTab";
import { DebugModuleTab } from "./debug/DebugModuleTab";
import { DebugOCRTab } from "./debug/DebugOCRTab";
import { DebugRulesetTab } from "./debug/DebugRulesetTab";
import { DebugUsersTab } from "./debug/DebugUsersTab";

type Tab = "context" | "ruleset" | "llm" | "ocr" | "module" | "memory" | "users";

interface DebugPanelProps {
  parsed: ParsedRuleset | null;
  visible: boolean;
  /** Mobile mode: overlay (slide-in from right) instead of in-flow column. */
  drawerMode?: boolean;
  /** Logged-in admin's id, used by the users tab to mark/disable self. */
  currentUserId: string;
  /** Active session/draft id — null when the user is not inside a room. */
  sessionId: string | null;
  /** When set, force-switch to a tab (used by external "view context" links).
   *  Accepts a serial bump alongside the tab name so repeat clicks re-trigger.
   *  `messageSnapshot` (when present + tab="context") scopes the Context tab
   *  to that GM message's BP2/BP3 instead of the live snapshot. */
  forceTab?: { tab: Tab; serial: number; messageSnapshot?: MessageSnapshot };
}

// Right-rail dev inspector. Admin-only — App.tsx skips rendering this
// for non-admin sessions.
export function DebugPanel({
  parsed,
  visible,
  drawerMode = false,
  currentUserId,
  sessionId,
  forceTab,
}: DebugPanelProps) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("ruleset");
  useEffect(() => {
    if (forceTab) setTab(forceTab.tab);
  }, [forceTab]);
  const { width, isDragging, onResizeStart } = useResizableWidth({
    storageKey: "chatrpg.debugPanelWidth",
    defaultWidth: 340,
    minWidth: 260,
    maxWidth: 720,
    edge: "left",
  });

  const cls = [
    "bg-surface flex flex-col h-full overflow-hidden",
    drawerMode
      ? "absolute top-0 right-0 bottom-0 z-50 border-l border-border shadow-[-4px_0_24px_var(--shadow-md)]"
      : "shrink-0 relative",
    !drawerMode &&
      (isDragging
        ? ""
        : "transition-[width,border-color] duration-[250ms] ease-[cubic-bezier(0.4,0,0.2,1)]"),
    drawerMode && "transition-transform duration-[250ms] ease-[cubic-bezier(0.4,0,0.2,1)]",
    !drawerMode && (visible ? "border-l border-border" : "border-l-0"),
    drawerMode && !visible && "translate-x-full",
  ]
    .filter(Boolean)
    .join(" ");

  const inlineStyle: React.CSSProperties = drawerMode
    ? { width: "min(92vw, 380px)" }
    : { width: visible ? `${width}px` : 0 };

  const contextScopedToMessage =
    tab === "context" && forceTab?.tab === "context" && !!forceTab.messageSnapshot;
  let badge: string;
  if (tab === "context") {
    if (!sessionId) badge = "no session";
    else badge = contextScopedToMessage ? "@msg" : "live";
  }
  else if (tab === "ruleset") badge = parsed ? "loaded" : "empty";
  else if (tab === "llm") badge = "llm";
  else if (tab === "ocr") badge = "ocr";
  else if (tab === "module") badge = "module";
  else if (tab === "memory") badge = sessionId ? "live" : "no session";
  else badge = "users";

  return (
    <aside className={cls} style={inlineStyle}>
      {visible && !drawerMode && (
        <div
          onMouseDown={onResizeStart}
          title="Drag to resize"
          className="absolute top-0 left-0 bottom-0 w-1.5 cursor-col-resize hover:bg-accent/40 active:bg-accent/60 transition-colors z-10"
        />
      )}
      <div className="px-3 pt-3 pb-2 border-b border-border shrink-0 flex items-center gap-2">
        <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-3">
          {t("debugPanelTitle")}
        </span>
        <div className="flex gap-1 ml-1 flex-wrap">
          <TabButton
            active={tab === "context"}
            onClick={() => setTab("context")}
          >
            {t("debugTabContext")}
          </TabButton>
          <TabButton
            active={tab === "ruleset"}
            onClick={() => setTab("ruleset")}
          >
            {t("debugTabRuleset")}
          </TabButton>
          <TabButton active={tab === "llm"} onClick={() => setTab("llm")}>
            {t("debugTabLLM")}
          </TabButton>
          <TabButton active={tab === "ocr"} onClick={() => setTab("ocr")}>
            {t("debugTabOCR")}
          </TabButton>
          <TabButton active={tab === "module"} onClick={() => setTab("module")}>
            {t("debugTabModule")}
          </TabButton>
          <TabButton active={tab === "memory"} onClick={() => setTab("memory")}>
            {t("debugTabMemory")}
          </TabButton>
          <TabButton active={tab === "users"} onClick={() => setTab("users")}>
            {t("debugTabUsers")}
          </TabButton>
        </div>
        <span
          className={[
            "ml-auto px-1.5 py-0.5 rounded text-[10px] font-mono",
            tab === "ruleset" && parsed
              ? "bg-accent-dim text-[var(--accent-text)]"
              : "bg-surface-2 text-text-3",
          ].join(" ")}
        >
          {badge}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 min-h-0">
        {tab === "context" && (
          <DebugContextTab
            sessionId={sessionId}
            messageSnapshot={
              forceTab?.tab === "context" ? forceTab.messageSnapshot : undefined
            }
            messageSnapshotSerial={
              forceTab?.tab === "context" ? forceTab.serial : 0
            }
          />
        )}
        {tab === "ruleset" && <DebugRulesetTab parsed={parsed} />}
        {tab === "llm" && <DebugLLMTab />}
        {tab === "ocr" && <DebugOCRTab />}
        {tab === "module" && <DebugModuleTab />}
        {tab === "memory" && <DebugMemoryTab sessionId={sessionId} />}
        {tab === "users" && <DebugUsersTab currentUserId={currentUserId} />}
      </div>
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "px-2 py-0.5 rounded text-[10.5px] font-semibold tracking-[0.04em] uppercase transition-colors",
        active
          ? "bg-accent-dim text-[var(--accent-text)]"
          : "text-text-3 hover:text-text hover:bg-surface-2",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
