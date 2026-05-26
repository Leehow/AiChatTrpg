import { useState, type ReactNode } from "react";

// Reusable layout pieces for the right-rail debug panel. Kept separate
// so each tab (ruleset inspector, LLM tester, …) can share them without
// circular imports.

export function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="bg-bg border border-border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full px-2.5 py-1.5 bg-surface-2 text-[10.5px] font-semibold tracking-[0.06em] uppercase text-text-3 flex items-center gap-2 hover:text-text transition-colors"
      >
        <span className="flex-1 text-left">{title}</span>
        <span
          className={[
            "text-[9px] transition-transform",
            open ? "" : "-rotate-90",
          ].join(" ")}
        >
          ▼
        </span>
      </button>
      {open && <div className="px-2.5 py-2 space-y-1">{children}</div>}
    </div>
  );
}

export function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2 text-[11.5px]">
      <span className="text-text-3 shrink-0 w-[78px] truncate">{label}</span>
      <span
        className={[
          "flex-1 text-text break-all min-w-0",
          mono ? "font-mono text-[11px]" : "",
        ].join(" ")}
      >
        {value}
      </span>
    </div>
  );
}

export function ExpandableRow({
  label,
  value,
  badge,
  mono,
  children,
}: {
  label: string;
  value: string;
  badge?: "ok" | "fail";
  mono?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 text-[11.5px] hover:bg-surface-2 rounded px-1 -mx-1 py-0.5 transition-colors text-left"
      >
        <span className="text-text-3 shrink-0 w-[78px] truncate">{label}</span>
        <span
          className={[
            "flex-1 min-w-0 truncate text-text",
            mono ? "font-mono text-[11px]" : "",
          ].join(" ")}
        >
          {value}
        </span>
        {badge && (
          <span
            className={[
              "px-1 py-0 rounded text-[9.5px] font-semibold uppercase",
              badge === "ok"
                ? "bg-[rgba(52,211,153,0.18)] text-[#34d399]"
                : "bg-[rgba(248,113,113,0.18)] text-[#f87171]",
            ].join(" ")}
          >
            {badge}
          </span>
        )}
        <span
          className={[
            "text-text-3 text-[9px] transition-transform shrink-0",
            open ? "rotate-90" : "",
          ].join(" ")}
        >
          ▶
        </span>
      </button>
      {open && (
        <div className="mt-1 mb-1.5 border border-border rounded-md bg-surface-2 overflow-hidden">
          {children}
        </div>
      )}
    </div>
  );
}

export function Pre({
  text,
  json,
  clip = 20000,
}: {
  text?: string;
  json?: unknown;
  clip?: number;
}) {
  let body = "";
  if (text != null) {
    body = text;
  } else if (json !== undefined) {
    try {
      body = JSON.stringify(json, null, 2);
    } catch {
      body = String(json);
    }
  }
  const truncated = body.length > clip;
  const display = truncated ? body.slice(0, clip) + "\n…" : body;
  return (
    <div className="max-h-[280px] overflow-auto">
      <pre className="text-[10.5px] leading-snug font-mono whitespace-pre-wrap break-words text-text-2 px-2 py-1.5">
        {display || <span className="italic">empty</span>}
      </pre>
      {truncated && (
        <div className="text-[10px] text-text-3 italic px-2 pb-1.5">
          (clipped at {clip.toLocaleString()} chars · full size{" "}
          {body.length.toLocaleString()})
        </div>
      )}
    </div>
  );
}
