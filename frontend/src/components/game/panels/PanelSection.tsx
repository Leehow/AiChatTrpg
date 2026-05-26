import { useState, type MouseEvent, type ReactNode } from "react";

interface Props {
  title: string;
  icon?: string;
  defaultOpen?: boolean;
  /** Convenience for the simple "one button, one label" case. */
  actionLabel?: string;
  onAction?: () => void;
  /** Custom action slot — supersedes `actionLabel` / `onAction` when set.
   *  Clicks inside this slot don't toggle the panel; the slot is responsible
   *  for its own button styling. */
  actions?: ReactNode;
  children: ReactNode;
}

export function PanelSection({
  title,
  icon,
  defaultOpen = true,
  actionLabel,
  onAction,
  actions,
  children,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);
  // Stop clicks inside the actions slot from collapsing the panel.
  const stopToggle = (e: MouseEvent) => e.stopPropagation();
  return (
    // `shrink-0` keeps the section at its natural height inside the
    // flex-column sidebar — without it, flex would compress this section
    // to fit, and the rounded `overflow-hidden` would then silently clip
    // the rest of the content (7000+ px lost, no scrollbar).
    <div className="bg-bg border border-border rounded-xl overflow-hidden shrink-0">
      <div
        onClick={() => setOpen((o) => !o)}
        className="flex items-center px-3 py-2.5 cursor-pointer gap-2 select-none"
      >
        {icon && <span className="text-xs text-text-2">{icon}</span>}
        <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-3 flex-1">
          {title}
        </span>
        {actions ? (
          <span onClick={stopToggle}>{actions}</span>
        ) : onAction ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onAction();
            }}
            className="text-[11px] text-accent font-medium px-1.5 py-0.5 rounded hover:bg-accent-dim"
          >
            {actionLabel || "Edit"}
          </button>
        ) : null}
        <span
          className={[
            "text-text-3 text-[10px] transition-transform",
            open ? "rotate-180" : "",
          ].join(" ")}
        >
          ▼
        </span>
      </div>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}
