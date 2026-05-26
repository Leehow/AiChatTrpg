import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  type TouchEvent as ReactTouchEvent,
} from "react";
import { useI18n } from "../i18n";

export interface ChatComposerProps {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  disabled?: boolean;
  sending?: boolean;
  /** Extra action button rendered just left of the send button (e.g. dice). */
  actionSlot?: ReactNode;
  /** Tooltip for the send button. */
  sendTitle?: string;
  /** Inner row max width. */
  maxWidth?: number | string;
}

const MAX_HEIGHT_COLLAPSED = 160;
const MIN_HEIGHT_EXPANDED = 84;
const MIN_HEIGHT_DRAG = 60;

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  placeholder,
  disabled,
  sending,
  actionSlot,
  sendTitle,
  maxWidth = "800px",
}: ChatComposerProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [expandedHeight, setExpandedHeight] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const mirrorRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const buttonGroupRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef({ startY: 0, startH: 0, active: false });
  const [multiline, setMultiline] = useState(false);

  const canSend = !disabled && !sending && value.trim().length > 0;
  // Stack the button row under the textarea once content wraps or the editor
  // is in expanded mode — avoids the dead gutter on the right.
  const stackButtons = multiline || expanded;

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_COLLAPSED)}px`;
  };

  useEffect(() => {
    if (!expanded) autoResize();
  }, [value, expanded]);

  // Detect wrap via a hidden mirror div sized to the **row-mode** textarea
  // width (= container width minus the button group). Symmetric threshold:
  // text wraps at row-width ⇒ multiline; fits at row-width ⇒ single-line.
  // Because the mirror's width is independent of the current layout, the
  // result is stable — once col mode kicks in it stays until content shrinks
  // enough to actually fit row-mode again.
  const measure = useCallback(() => {
    const container = containerRef.current;
    const mirror = mirrorRef.current;
    if (!container || !mirror) return;
    const buttonWidth = buttonGroupRef.current?.offsetWidth ?? 0;
    // Inner flex has px-2 (16) + gap-1 (4) between textarea and buttons.
    const rowWidth = Math.max(40, container.clientWidth - 16 - 4 - buttonWidth);
    mirror.style.width = `${rowWidth}px`;
    setMultiline(mirror.scrollHeight > 40);
  }, []);

  useEffect(() => {
    measure();
  }, [value, measure]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(container);
    if (buttonGroupRef.current) ro.observe(buttonGroupRef.current);
    return () => ro.disconnect();
  }, [measure]);

  const toggleExpanded = () => {
    setExpanded((prev) => {
      const next = !prev;
      if (next) setExpandedHeight(null);
      return next;
    });
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (expanded) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (canSend) onSubmit();
      } else if (e.key === "Escape") {
        e.preventDefault();
        setExpanded(false);
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSubmit();
    }
  };

  // Drag-to-resize for the expanded editor. Listeners are attached to the
  // document so the user can drag past the handle without losing the grab.
  const onDragMove = (e: globalThis.MouseEvent | globalThis.TouchEvent) => {
    if (!dragRef.current.active) return;
    if ("touches" in e) e.preventDefault();
    const cy = "touches" in e
      ? e.touches[0]?.clientY ?? dragRef.current.startY
      : e.clientY;
    const delta = dragRef.current.startY - cy;
    const newH = Math.max(
      MIN_HEIGHT_DRAG,
      Math.min(dragRef.current.startH + delta, window.innerHeight * 0.7),
    );
    setExpandedHeight(newH);
  };
  const onDragEnd = () => {
    dragRef.current.active = false;
    document.removeEventListener("mousemove", onDragMove);
    document.removeEventListener("mouseup", onDragEnd);
    document.removeEventListener("touchmove", onDragMove);
    document.removeEventListener("touchend", onDragEnd);
  };
  const onDragStart = (e: ReactMouseEvent | ReactTouchEvent) => {
    if (!expanded) return;
    e.preventDefault();
    const cy = "touches" in e ? e.touches[0]?.clientY ?? 0 : e.clientY;
    dragRef.current = {
      active: true,
      startY: cy,
      startH: textareaRef.current?.offsetHeight ?? MIN_HEIGHT_EXPANDED,
    };
    document.addEventListener("mousemove", onDragMove);
    document.addEventListener("mouseup", onDragEnd);
    document.addEventListener("touchmove", onDragMove, { passive: false });
    document.addEventListener("touchend", onDragEnd);
  };

  useEffect(() => {
    return () => {
      document.removeEventListener("mousemove", onDragMove);
      document.removeEventListener("mouseup", onDragEnd);
      document.removeEventListener("touchmove", onDragMove);
      document.removeEventListener("touchend", onDragEnd);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const widthStyle = typeof maxWidth === "number" ? `${maxWidth}px` : maxWidth;

  return (
    <div className="bg-bg px-4 pt-0 pb-3 shrink-0">
      <div className="mx-auto" style={{ maxWidth: widthStyle }}>
        <div
          ref={containerRef}
          className={[
            "relative rounded-2xl border bg-input-bg transition-shadow",
            "border-border focus-within:border-accent",
            "focus-within:shadow-[0_0_0_3px_var(--accent-dim)]",
          ].join(" ")}
        >
          {expanded && (
            <div
              className="absolute top-0 left-0 right-0 h-3 cursor-ns-resize flex items-center justify-center group z-10"
              onMouseDown={onDragStart}
              onTouchStart={onDragStart}
            >
              <div className="w-12 h-1 rounded-full bg-accent-dim group-hover:bg-accent transition-colors" />
            </div>
          )}

          <div
            ref={mirrorRef}
            aria-hidden
            className="invisible pointer-events-none absolute left-0 top-0 px-2 py-1.5 text-sm leading-relaxed whitespace-pre-wrap break-words"
          >
            {value}
          </div>

          <div
            className={[
              "flex items-end gap-1 px-2 pb-1.5",
              expanded ? "pt-4" : "pt-1.5",
              stackButtons ? "flex-col" : "",
            ].join(" ")}
          >
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKey}
              rows={expanded ? 3 : 1}
              placeholder={placeholder}
              disabled={disabled || sending}
              style={{
                height: expanded && expandedHeight ? `${expandedHeight}px` : undefined,
              }}
              className={[
                "min-w-0 bg-transparent border-0 px-2 py-1.5 text-sm text-text outline-none resize-none leading-relaxed disabled:opacity-50",
                "placeholder:whitespace-nowrap placeholder:overflow-hidden placeholder:text-ellipsis",
                stackButtons ? "w-full" : "flex-1 self-stretch",
                expanded ? "min-h-[84px]" : "min-h-[28px] max-h-[160px]",
              ].join(" ")}
            />

            <div
              ref={buttonGroupRef}
              className="flex items-center gap-1 shrink-0"
            >
              {expanded && (
                <span className="text-xs text-text-3 mr-1 hidden sm:inline">
                  {t("composerExpandedHint")}
                </span>
              )}

              {actionSlot}

              <button
                type="button"
                onClick={toggleExpanded}
                title={expanded ? t("composerCollapse") : t("composerExpand")}
                className="w-9 h-9 rounded-xl text-text-3 hover:bg-surface-2 hover:text-text flex items-center justify-center transition-colors shrink-0"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  {expanded ? (
                    <path d="M5.5 1v3.5H2M8.5 1v3.5H12M5.5 13v-3.5H2M8.5 13v-3.5H12" />
                  ) : (
                    <path d="M2 5V2h3M9 2h3v3M2 9v3h3M9 12h3V9" />
                  )}
                </svg>
              </button>

              <button
                type="button"
                onClick={() => canSend && onSubmit()}
                disabled={!canSend}
                title={sendTitle}
                className="w-9 h-9 rounded-xl bg-accent text-white hover:opacity-90 active:scale-95 disabled:opacity-40 transition flex items-center justify-center shrink-0"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M2 8L14 2L8 14L7 9L2 8Z"
                    stroke="white"
                    strokeWidth="1.5"
                    strokeLinejoin="round"
                    fill="none"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ComposerIconButton({
  onClick,
  title,
  disabled,
  children,
}: {
  onClick: () => void;
  title?: string;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="w-9 h-9 rounded-xl text-text-2 hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-base shrink-0"
    >
      {children}
    </button>
  );
}
