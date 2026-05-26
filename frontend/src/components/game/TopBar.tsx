import { useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n, type Locale } from "../../i18n";
import { LOCALE_META } from "../../i18n/messages";

interface Props {
  /** Active room title — surfaced in the topbar center so the player
   *  knows which session they're in without opening the rooms drawer. */
  roomTitle?: string;
  onToggleRooms: () => void;
  onToggleSidebar?: () => void;
  onToggleDebug?: () => void;
  debugOn?: boolean;
  onToggleTheme: () => void;
  theme: "warm" | "slate";
  onOpenRulesetView: () => void;
  onLeaveSession: () => void;
  onLogout: () => void;
  userName: string;
  isMobile?: boolean;
}

export function TopBar({
  roomTitle,
  onToggleRooms,
  onToggleSidebar,
  onToggleDebug,
  debugOn,
  onToggleTheme,
  theme,
  onOpenRulesetView,
  onLeaveSession,
  onLogout,
  userName,
  isMobile = false,
}: Props) {
  const { t } = useI18n();
  return (
    <header className="flex items-center h-10 px-2 md:px-4 border-b border-border bg-surface shrink-0 gap-1 md:gap-3 z-10">
      <IconButton onClick={onToggleRooms} title={t("topbarToggleRooms")}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <rect x="1" y="2" width="5.5" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
          <rect x="8.5" y="2" width="5.5" height="5" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
          <rect x="8.5" y="9" width="5.5" height="5" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </IconButton>
      {onToggleSidebar && (
        <IconButton onClick={onToggleSidebar} title={t("topbarToggleSidebar")}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="3" width="14" height="1.5" rx="0.75" fill="currentColor" />
            <rect x="1" y="7.25" width="14" height="1.5" rx="0.75" fill="currentColor" />
            <rect x="1" y="11.5" width="14" height="1.5" rx="0.75" fill="currentColor" />
          </svg>
        </IconButton>
      )}
      <div className="flex items-center gap-2 min-w-0 shrink-0">
        <img
          src={
            theme === "slate"
              ? "/logo/chatrpg-logo-dark-transparent.png"
              : "/logo/chatrpg-logo-warm-transparent.png"
          }
          alt=""
          aria-hidden="true"
          className="h-5 w-5 shrink-0 object-contain"
        />
        <div className="text-base font-semibold tracking-tight hidden sm:block">
          Chat<span className="text-accent">RPG</span>
        </div>
      </div>
      {/* Active room name — replaces the prior ruleset book_title so the
          player sees which session is in focus, not which rulebook backs
          it. Falls back to nothing when no room is active (setup flow). */}
      {roomTitle && (
        <div className="text-sm font-medium text-text truncate min-w-0 flex-1 ml-1">
          {roomTitle}
        </div>
      )}
      {/* Right-side actions: debug stays out front (admin-only) so devs can
          toggle the inspector with one click; everything else collapses
          into the overflow menu to keep the bar uncluttered. */}
      <div className="ml-auto flex gap-1 md:gap-2 items-center">
        {onToggleDebug && (
          <button
            type="button"
            onClick={onToggleDebug}
            title={t("topbarDebug")}
            className={[
              "w-8 h-8 rounded-lg flex items-center justify-center text-xs font-mono shrink-0",
              "transition-colors",
              debugOn
                ? "bg-accent-dim text-accent"
                : "text-text-2 hover:bg-surface-2 hover:text-text",
            ].join(" ")}
          >
            {"</>"}
          </button>
        )}
        <OverflowMenu
          theme={theme}
          onToggleTheme={onToggleTheme}
          onLeaveSession={onLeaveSession}
          onLogout={onLogout}
          onOpenRulesetView={onOpenRulesetView}
          userName={userName}
          isMobile={isMobile}
        />
      </div>
    </header>
  );
}

function OverflowMenu({
  theme,
  onToggleTheme,
  onLeaveSession,
  onLogout,
  onOpenRulesetView,
  userName,
  isMobile,
}: {
  theme: "warm" | "slate";
  onToggleTheme: () => void;
  onLeaveSession: () => void;
  onLogout: () => void;
  onOpenRulesetView: () => void;
  userName: string;
  isMobile: boolean;
}) {
  const { t, locale, setLocale } = useI18n();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on outside click + Escape — simplest pattern that doesn't pull in
  // a positioning library. Headless solutions feel heavy for one menu.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => setOpen(false);
  const item = (
    label: string,
    onClick: () => void,
    icon: ReactNode,
    active = false,
  ) => (
    <button
      type="button"
      onClick={() => {
        onClick();
        close();
      }}
      className={[
        "w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors text-left",
        active
          ? "bg-accent-dim text-[var(--accent-text)]"
          : "text-text-2 hover:bg-surface-2 hover:text-text",
      ].join(" ")}
    >
      <span className="w-4 h-4 flex items-center justify-center text-base shrink-0">
        {icon}
      </span>
      <span className="truncate">{label}</span>
    </button>
  );

  const localeOptions = Object.entries(LOCALE_META) as Array<
    [Locale, { nativeLabel: string }]
  >;

  return (
    <div ref={wrapRef} className="relative">
      <IconButton onClick={() => setOpen((o) => !o)} title={t("topbarMenu")}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="8" cy="8" r="2.2" />
          <path d="M13.2 9.6a1 1 0 0 0 .2 1.1l.04.04a1.2 1.2 0 1 1-1.7 1.7l-.04-.04a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.92V13.3a1.2 1.2 0 1 1-2.4 0v-.06a1 1 0 0 0-.66-.92 1 1 0 0 0-1.1.2l-.04.04a1.2 1.2 0 1 1-1.7-1.7l.04-.04a1 1 0 0 0 .2-1.1 1 1 0 0 0-.92-.6H2.7a1.2 1.2 0 1 1 0-2.4h.06a1 1 0 0 0 .92-.66 1 1 0 0 0-.2-1.1l-.04-.04a1.2 1.2 0 1 1 1.7-1.7l.04.04a1 1 0 0 0 1.1.2H6.4a1 1 0 0 0 .6-.92V2.7a1.2 1.2 0 1 1 2.4 0v.06a1 1 0 0 0 .6.92 1 1 0 0 0 1.1-.2l.04-.04a1.2 1.2 0 1 1 1.7 1.7l-.04.04a1 1 0 0 0-.2 1.1V6.4a1 1 0 0 0 .92.6H13.3a1.2 1.2 0 1 1 0 2.4h-.06a1 1 0 0 0-.92.6Z" />
        </svg>
      </IconButton>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-64 bg-surface border border-border rounded-lg shadow-[0_8px_24px_var(--shadow-md)] py-1 z-50 overflow-hidden">
          {userName && (
            <div className="px-3 py-2 text-xs text-text-3 border-b border-border truncate">
              {userName}
            </div>
          )}
          <div className="px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-text-3 mb-1.5">
              {t("language")}
            </div>
            <div className="flex flex-wrap gap-1">
              {localeOptions.map(([code, meta]) => {
                const active = code === locale;
                return (
                  <button
                    key={code}
                    type="button"
                    onClick={() => setLocale(code)}
                    className={`px-2 py-0.5 rounded text-xs font-medium transition ${
                      active
                        ? "bg-accent text-white"
                        : "bg-surface-2 text-text-3 hover:text-text hover:bg-border"
                    }`}
                    aria-pressed={active}
                  >
                    {meta.nativeLabel}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="my-1 border-t border-border" />
          {item(t("topbarTheme"), onToggleTheme, theme === "warm" ? "🌙" : "☀")}
          {!isMobile && item(t("topbarRuleset"), onOpenRulesetView, "⬡")}
          {item(t("topbarLeave"), onLeaveSession, "↩")}
          {item(t("topbarLogout"), onLogout, "⏻")}
        </div>
      )}
    </div>
  );
}

function IconButton({
  onClick,
  title,
  children,
}: {
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-text-2 hover:bg-surface-2 hover:text-text transition-colors"
    >
      {children}
    </button>
  );
}
