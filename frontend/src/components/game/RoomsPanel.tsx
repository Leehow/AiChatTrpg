import { useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import { useResizableWidth } from "../../hooks/useResizableWidth";

// Portal target id used by MusicPlayer on mobile to mount its button
// inside the rooms drawer instead of the fixed bottom-left corner where
// it overlaps the chat input.
export const MUSIC_MOBILE_SLOT_ID = "chatrpg-music-mobile-slot";

export interface RoomEntry {
  id: string;
  name: string;
  rule: string;
  time: string;
  active: boolean;
  /** True if setup wizard hasn't been completed for this session. */
  draft?: boolean;
  /** "session" (default, omit) or "rule_draft" — surfaced in a separate
   *  "规则草稿" section instead of the regular session list. */
  kind?: "session" | "rule_draft";
}

interface Props {
  rooms: RoomEntry[];
  activeId: string | null;
  visible: boolean;
  /** Mobile mode: overlay (slide-in) instead of in-flow column. */
  drawerMode?: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete?: (id: string) => void;
}

export function RoomsPanel({
  rooms,
  activeId,
  visible,
  drawerMode = false,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  const { t } = useI18n();
  const { width, isDragging, onResizeStart } = useResizableWidth({
    storageKey: "chatrpg.roomsPanelWidth",
    defaultWidth: 210,
    minWidth: 160,
    maxWidth: 480,
    edge: "right",
  });

  // Width comes from inline style so it can be dragged. Transition is
  // suppressed mid-drag to keep the resize handle glued to the cursor.
  // In drawer mode the panel pops out as an overlay with a fixed
  // width and slides via translate-x; the in-flow width animation
  // would otherwise reflow the chat column on every toggle.
  const cls = [
    "bg-surface flex flex-col overflow-hidden h-full",
    drawerMode
      ? "absolute top-0 left-0 bottom-0 z-50 border-r border-border shadow-[4px_0_24px_var(--shadow-md)]"
      : "shrink-0 relative",
    !drawerMode &&
      (isDragging
        ? ""
        : "transition-[width,border-color] duration-[250ms] ease-[cubic-bezier(0.4,0,0.2,1)]"),
    drawerMode && "transition-transform duration-[250ms] ease-[cubic-bezier(0.4,0,0.2,1)]",
    !drawerMode && (visible ? "border-r border-border" : "border-r-0"),
    drawerMode && !visible && "-translate-x-full",
  ]
    .filter(Boolean)
    .join(" ");

  // Three sections, each pre-sorted from the backend so we just split:
  //  1. session drafts (setup wizard incomplete)
  //  2. completed sessions (in-game)
  //  3. rule drafts (the conversational ruleset editor)
  const drafts = rooms.filter((r) => r.kind !== "rule_draft" && r.draft);
  const completed = rooms.filter((r) => r.kind !== "rule_draft" && !r.draft);
  const ruleDrafts = rooms.filter((r) => r.kind === "rule_draft");

  const inlineStyle: React.CSSProperties = drawerMode
    ? { width: "min(82vw, 320px)" }
    : { width: visible ? `${width}px` : 0 };

  return (
    <div
      className={cls}
      style={inlineStyle}
      aria-hidden={!visible}
    >
      <div className="px-3 pt-3 pb-2 flex items-center justify-between border-b border-border shrink-0">
        <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-3">
          {t("roomsTitle")}
        </span>
        <button
          onClick={onNew}
          title={t("roomsNew")}
          className="w-6 h-6 rounded-md bg-accent-dim text-accent hover:bg-accent hover:text-white flex items-center justify-center text-base leading-none transition-colors"
        >
          +
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-0.5">
        {drafts.length > 0 && (
          <div className="text-[10px] font-semibold text-text-3 tracking-[0.08em] uppercase px-2.5 pt-2 pb-1">
            {t("roomsDrafts")}
          </div>
        )}
        {drafts.map((r) => (
          <RoomItem
            key={r.id}
            room={r}
            active={activeId === r.id}
            onClick={() => onSelect(r.id)}
            onDelete={onDelete}
          />
        ))}
        {drafts.length > 0 && completed.length > 0 && (
          <div className="my-2 mx-2.5 border-t border-border" />
        )}
        {completed.length > 0 && (
          <div className="text-[10px] font-semibold text-text-3 tracking-[0.08em] uppercase px-2.5 pt-2 pb-1">
            {t("roomsActive")}
          </div>
        )}
        {completed.map((r) => (
          <RoomItem
            key={r.id}
            room={r}
            active={activeId === r.id}
            onClick={() => onSelect(r.id)}
            onDelete={onDelete}
          />
        ))}
        {(drafts.length > 0 || completed.length > 0) && ruleDrafts.length > 0 && (
          <div className="my-2 mx-2.5 border-t border-border" />
        )}
        {ruleDrafts.length > 0 && (
          <div className="text-[10px] font-semibold text-text-3 tracking-[0.08em] uppercase px-2.5 pt-2 pb-1">
            {t("roomsRuleDrafts")}
          </div>
        )}
        {ruleDrafts.map((r) => (
          <RoomItem
            key={r.id}
            room={r}
            active={activeId === r.id}
            onClick={() => onSelect(r.id)}
            onDelete={onDelete}
          />
        ))}
        {rooms.length === 0 && (
          <div className="text-[12px] text-text-3 px-2.5 py-3 leading-relaxed">
            {t("roomsEmpty")}
          </div>
        )}
      </div>
      {drawerMode && (
        <div
          id={MUSIC_MOBILE_SLOT_ID}
          className="shrink-0 border-t border-border px-3 py-2"
        />
      )}
      {visible && !drawerMode && (
        <div
          onMouseDown={onResizeStart}
          title="Drag to resize"
          className="absolute top-0 right-0 bottom-0 w-1.5 cursor-col-resize hover:bg-accent/40 active:bg-accent/60 transition-colors z-10"
        />
      )}
    </div>
  );
}

function RoomItem({
  room,
  active,
  onClick,
  onDelete,
}: {
  room: RoomEntry;
  active: boolean;
  onClick: () => void;
  onDelete?: (id: string) => void;
}) {
  return (
    <div
      onClick={onClick}
      className={[
        "group relative px-2.5 py-1.5 rounded-lg cursor-pointer border-[1.5px]",
        "transition-colors duration-[120ms] flex items-baseline gap-2",
        active
          ? "bg-accent-dim border-accent"
          : "border-transparent hover:bg-surface-2",
      ].join(" ")}
    >
      <span
        className={[
          "text-[13px] font-semibold truncate flex-1 pr-5",
          active ? "text-[var(--accent-text)]" : "text-text",
        ].join(" ")}
      >
        {room.rule && (
          <span className={active ? "text-[var(--accent-text)]/70 mr-0.5" : "text-text-3 mr-0.5"}>
            {room.rule}
          </span>
        )}
        {room.name}
      </span>
      {onDelete && <DeleteButton onConfirm={() => onDelete(room.id)} />}
    </div>
  );
}

function DeleteButton({ onConfirm }: { onConfirm: () => void }) {
  const { t } = useI18n();
  const [armed, setArmed] = useState(false);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  const disarm = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setArmed(false);
  };

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    if (armed) {
      disarm();
      onConfirm();
      return;
    }
    setArmed(true);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setArmed(false);
    }, 3000);
  };

  if (armed) {
    return (
      <button
        type="button"
        onClick={handleClick}
        onMouseLeave={disarm}
        className="absolute top-1.5 right-1.5 px-2 h-5 rounded bg-red-500 text-white text-[11px] font-semibold leading-none flex items-center justify-center hover:bg-red-600 transition"
      >
        {t("roomDeleteConfirm")}
      </button>
    );
  }

  return (
    <button
      type="button"
      title={t("roomDeleteTitle")}
      onClick={handleClick}
      className="absolute top-1.5 right-1.5 w-5 h-5 rounded text-text-3 hover:text-red-500 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 flex items-center justify-center text-xs leading-none transition-opacity"
    >
      ×
    </button>
  );
}
