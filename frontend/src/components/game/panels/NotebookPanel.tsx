import { useMemo, useState } from "react";
import { useI18n } from "../../../i18n";
import { PanelSection } from "./PanelSection";

export interface PlayerNote {
  id?: string;
  content: string;
  tags?: string[];
  created_at?: string;
  updated_at?: string | null;
  // `gm` for [ADD_NOTE]-generated entries, `player` for user-created notes.
  // Forwarded through to NotesOverlay so its lock logic (only "player" notes
  // are editable) survives a session refresh.
  source?: "gm" | "player" | string | null;
}

interface Props {
  notes: PlayerNote[];
  /** Opens the floating notes overlay for create/edit/delete. The sidebar
   *  panel remains the read-only summary; full CRUD lives in the overlay. */
  onOpen?: () => void;
}

// In-fiction notebook readout. Player notes get appended whenever the GM
// emits `[ADD_NOTE]` after the player explicitly writes/records something.
// Sidebar panel collapses by default; expanded view shows newest-first
// cards with content + tag chips + relative timestamp. Optional tag filter
// lets the player narrow on a single label.
export function NotebookPanel({ notes, onOpen }: Props) {
  const { t } = useI18n();
  const [activeTag, setActiveTag] = useState<string | null>(null);

  const allTags = useMemo(() => {
    const set = new Map<string, number>();
    for (const n of notes) {
      for (const tag of n.tags || []) {
        const key = tag.trim();
        if (!key) continue;
        set.set(key, (set.get(key) || 0) + 1);
      }
    }
    return Array.from(set.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([tag]) => tag);
  }, [notes]);

  const filtered = useMemo(() => {
    if (!activeTag) return notes;
    return notes.filter((n) => (n.tags || []).includes(activeTag));
  }, [notes, activeTag]);

  // Newest first.
  const ordered = useMemo(() => {
    return [...filtered].reverse();
  }, [filtered]);

  return (
    <PanelSection
      title={`${t("panelNotebook")} (${notes.length})`}
      icon="✎"
      defaultOpen={false}
      actions={
        onOpen ? (
          <button
            type="button"
            onClick={onOpen}
            className="text-[11px] text-accent font-medium px-1.5 py-0.5 rounded hover:bg-accent-dim"
          >
            {t("notesPanelOpen")}
          </button>
        ) : undefined
      }
    >
      {notes.length === 0 ? (
        <div className="flex flex-col gap-2 py-2">
          <div className="text-[12px] text-text-3">
            {t("notebookEmpty")}
          </div>
          {onOpen && (
            <button
              type="button"
              onClick={onOpen}
              className="self-start text-[11.5px] px-2 py-1 rounded-md bg-surface-2 border border-border text-text-2 hover:text-text"
            >
              {t("notesAdd")}
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {allTags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <TagChip
                active={activeTag === null}
                count={notes.length}
                label={t("notebookAll")}
                onClick={() => setActiveTag(null)}
              />
              {allTags.map((tag) => {
                const count = notes.filter(
                  (n) => (n.tags || []).includes(tag),
                ).length;
                return (
                  <TagChip
                    key={tag}
                    active={activeTag === tag}
                    count={count}
                    label={tag}
                    onClick={() => setActiveTag(tag === activeTag ? null : tag)}
                  />
                );
              })}
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            {ordered.map((note, i) => (
              <NoteCard key={note.id || `note-${i}`} note={note} />
            ))}
          </div>
        </div>
      )}
    </PanelSection>
  );
}


function NoteCard({ note }: { note: PlayerNote }) {
  return (
    <div className="bg-surface-2 rounded-lg px-2.5 py-1.5 text-[12px] leading-snug text-text-2 flex flex-col gap-1">
      <div className="whitespace-pre-wrap break-words">{note.content}</div>
      {(note.tags && note.tags.length > 0) || note.created_at ? (
        <div className="flex flex-wrap items-center gap-1 text-[10.5px] text-text-3">
          {(note.tags || []).map((tag) => (
            <span
              key={tag}
              className="px-1.5 rounded bg-bg border border-border"
            >
              #{tag}
            </span>
          ))}
          {note.created_at && (
            <span className="ml-auto">{formatRelative(note.created_at)}</span>
          )}
        </div>
      ) : null}
    </div>
  );
}


function TagChip({
  active, count, label, onClick,
}: { active: boolean; count: number; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "px-2 py-0.5 rounded-full text-[10.5px]",
        "border transition-colors",
        active
          ? "bg-accent-dim text-[var(--accent-text)] border-accent-dim"
          : "bg-surface-2 text-text-3 border-border hover:text-text",
      ].join(" ")}
    >
      {label} <span className="opacity-60">{count}</span>
    </button>
  );
}


function formatRelative(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const diff = Date.now() - d.getTime();
    const min = Math.floor(diff / 60000);
    if (min < 1) return "just now";
    if (min < 60) return `${min}m`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h`;
    const day = Math.floor(hr / 24);
    return `${day}d`;
  } catch {
    return "";
  }
}
