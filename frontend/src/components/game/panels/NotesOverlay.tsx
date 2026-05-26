import { useEffect, useMemo, useState } from "react";
import { useI18n } from "../../../i18n";
import {
  createSessionNoteAPI,
  deleteSessionNoteAPI,
  listSessionNotesAPI,
  type PlayerNoteDTO,
  updateSessionNoteAPI,
} from "../../../api/sessions";
import type { PlayerNote } from "./NotebookPanel";

interface Props {
  sessionId: string;
  open: boolean;
  initialNotes: PlayerNote[];
  onClose: () => void;
  onChanged?: () => void;
}

// Floating drawer for the in-game notebook. Slides in from the right and
// reuses the existing sidebar card styling. All mutations go through the
// session_notes endpoints; we keep an internal list so the overlay stays
// responsive while the parent refetches the session JSON.
export function NotesOverlay({
  sessionId, open, initialNotes, onClose, onChanged,
}: Props) {
  const { t } = useI18n();
  const [notes, setNotes] = useState<PlayerNoteDTO[]>(initialNotes);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [draftTags, setDraftTags] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTag, setActiveTag] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setNotes(initialNotes);
  }, [open, initialNotes]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    listSessionNotesAPI(sessionId)
      .then((res) => { if (!cancelled) setNotes(res.notes || []); })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t("notesErrLoadFailed"));
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, sessionId, t]);

  const allTags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of notes) {
      for (const tag of n.tags || []) {
        const key = tag.trim();
        if (!key) continue;
        counts.set(key, (counts.get(key) || 0) + 1);
      }
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([tag]) => tag);
  }, [notes]);

  const ordered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = notes.filter((n) => {
      if (activeTag && !(n.tags || []).includes(activeTag)) return false;
      if (q && !n.content.toLowerCase().includes(q)) return false;
      return true;
    });
    return [...filtered].reverse();
  }, [notes, search, activeTag]);

  if (!open) return null;

  async function handleCreate() {
    const content = draft.trim();
    if (!content) { setError(t("notesErrEmpty")); return; }
    setError("");
    setCreating(true);
    try {
      const tags = parseTagsInput(draftTags);
      const res = await createSessionNoteAPI(sessionId, { content, tags });
      setNotes((prev) => [...prev, res.note]);
      setDraft("");
      setDraftTags("");
      onChanged?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("notesErrSaveFailed"));
    } finally {
      setCreating(false);
    }
  }

  async function saveEdit(noteId: string, content: string, tags: string[]) {
    if (!content.trim()) { setError(t("notesErrEmpty")); return; }
    setError("");
    setSavingId(noteId);
    try {
      const res = await updateSessionNoteAPI(sessionId, noteId, {
        content: content.trim(),
        tags,
      });
      setNotes((prev) => prev.map((n) => (n.id === noteId ? res.note : n)));
      setEditingId(null);
      onChanged?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("notesErrSaveFailed"));
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(noteId: string) {
    if (!noteId) return;
    setError("");
    setSavingId(noteId);
    try {
      await deleteSessionNoteAPI(sessionId, noteId);
      setNotes((prev) => prev.filter((n) => n.id !== noteId));
      if (editingId === noteId) setEditingId(null);
      onChanged?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("notesErrDeleteFailed"));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-[2px]"
      role="dialog"
      aria-label={t("notesOverlayTitle")}
      onClick={onClose}
    >
      <div
        className="h-full w-[min(94vw,420px)] bg-bg border-l border-border shadow-[0_0_32px_var(--shadow-lg)] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <span className="text-[15px]">✎</span>
          <div className="flex-1 min-w-0">
            <div className="text-[14px] font-semibold text-text truncate">{t("notesOverlayTitle")}</div>
            <div className="text-[11px] text-text-3">{t("notesOverlaySub", { n: notes.length })}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-3 hover:text-text px-1.5 py-0.5 text-[18px] leading-none"
            aria-label={t("notesClose")}
          >×</button>
        </div>

        <div className="flex flex-col gap-2 px-4 py-3 border-b border-border">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("notesNewPlaceholder")}
            rows={3}
            className="w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-border text-[12.5px] text-text resize-none focus:outline-none focus:border-accent"
          />
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              type="text"
              value={draftTags}
              onChange={(e) => setDraftTags(e.target.value)}
              placeholder={t("notesTagsPlaceholder")}
              className="flex-1 min-w-[120px] px-2 py-1 rounded-md bg-surface-2 border border-border text-[11.5px] text-text"
            />
            <button
              type="button"
              disabled={creating || !draft.trim()}
              onClick={handleCreate}
              className="px-3 py-1 rounded-md text-[12px] bg-accent-dim text-[var(--accent-text)] hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            >{creating ? t("notesAdding") : t("notesAdd")}</button>
          </div>
        </div>

        <div className="flex flex-col gap-2 px-4 py-2.5 border-b border-border">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("notesSearchPlaceholder")}
            className="w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-border text-[12px] text-text"
          />
          {allTags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <TagChip active={activeTag === null} label={t("notebookAll")} count={notes.length} onClick={() => setActiveTag(null)} />
              {allTags.map((tag) => {
                const count = notes.filter((n) => (n.tags || []).includes(tag)).length;
                return (
                  <TagChip key={tag} active={activeTag === tag} label={tag} count={count}
                    onClick={() => setActiveTag(tag === activeTag ? null : tag)} />
                );
              })}
            </div>
          )}
        </div>

        {error && (
          <div className="text-[12px] text-[#f87171] px-4 py-2 border-b border-border">{error}</div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-2 min-h-0">
          {loading && notes.length === 0 ? (
            <div className="text-[12px] text-text-3 py-4 text-center">{t("notesLoading")}</div>
          ) : ordered.length === 0 ? (
            <div className="text-[12px] text-text-3 py-4 text-center">
              {notes.length === 0 ? t("notebookEmpty") : t("notesNoMatch")}
            </div>
          ) : (
            ordered.map((note, i) => (
              <NoteRow
                key={note.id || `gm-${i}`}
                note={note}
                editing={Boolean(note.id) && editingId === note.id}
                busy={Boolean(note.id) && savingId === note.id}
                onStartEdit={() => note.id && setEditingId(note.id)}
                onCancelEdit={() => setEditingId(null)}
                onSave={(content, tags) => note.id && saveEdit(note.id, content, tags)}
                onDelete={() => note.id && handleDelete(note.id)}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}


interface NoteRowProps {
  note: PlayerNoteDTO;
  editing: boolean;
  busy: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: (content: string, tags: string[]) => void;
  onDelete: () => void;
}

function NoteRow({ note, editing, busy, onStartEdit, onCancelEdit, onSave, onDelete }: NoteRowProps) {
  const { t } = useI18n();
  const [content, setContent] = useState(note.content);
  const [tagsRaw, setTagsRaw] = useState((note.tags || []).join(", "));
  const lockedFromMutation = !note.id || note.source !== "player";

  useEffect(() => {
    if (editing) {
      setContent(note.content);
      setTagsRaw((note.tags || []).join(", "));
    }
  }, [editing, note.content, note.tags]);

  if (editing) {
    return (
      <div className="bg-surface-2 rounded-lg p-2.5 flex flex-col gap-2">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          className="w-full px-2 py-1.5 rounded-md bg-bg border border-border text-[12.5px] text-text resize-none focus:outline-none focus:border-accent"
        />
        <input
          type="text"
          value={tagsRaw}
          onChange={(e) => setTagsRaw(e.target.value)}
          placeholder={t("notesTagsPlaceholder")}
          className="w-full px-2 py-1 rounded-md bg-bg border border-border text-[11.5px] text-text"
        />
        <div className="flex gap-2 justify-end">
          <button type="button" onClick={onCancelEdit}
            className="px-2.5 py-1 rounded-md text-[11.5px] text-text-2 hover:bg-bg">
            {t("notesCancel")}
          </button>
          <button type="button" disabled={busy} onClick={() => onSave(content, parseTagsInput(tagsRaw))}
            className="px-2.5 py-1 rounded-md text-[11.5px] bg-accent-dim text-[var(--accent-text)] hover:opacity-90 disabled:opacity-50">
            {busy ? t("notesSaving") : t("notesSave")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-surface-2 rounded-lg px-2.5 py-1.5 text-[12px] leading-snug text-text-2 flex flex-col gap-1">
      <div className="whitespace-pre-wrap break-words">{note.content}</div>
      <div className="flex flex-wrap items-center gap-1 text-[10.5px] text-text-3">
        {(note.tags || []).map((tag) => (
          <span key={tag} className="px-1.5 rounded bg-bg border border-border">#{tag}</span>
        ))}
        {note.source === "gm" && (
          <span className="px-1.5 rounded bg-bg border border-border opacity-80">{t("notesSourceGm")}</span>
        )}
        {note.created_at && (
          <span className="ml-auto">{formatRelative(note.created_at)}</span>
        )}
        <div className="flex gap-1">
          <button type="button" disabled={lockedFromMutation || busy} onClick={onStartEdit}
            className="px-1.5 py-0.5 rounded text-text-3 hover:text-text hover:bg-bg disabled:opacity-40 disabled:cursor-not-allowed"
            title={lockedFromMutation ? t("notesGmReadOnly") : t("notesEdit")}>
            {t("notesEdit")}
          </button>
          <button type="button" disabled={lockedFromMutation || busy} onClick={onDelete}
            className="px-1.5 py-0.5 rounded text-text-3 hover:text-[#f87171] hover:bg-bg disabled:opacity-40 disabled:cursor-not-allowed"
            title={lockedFromMutation ? t("notesGmReadOnly") : t("notesDelete")}>
            {t("notesDelete")}
          </button>
        </div>
      </div>
    </div>
  );
}


function parseTagsInput(raw: string): string[] {
  return raw
    .split(/[,，;；]/g)
    .map((tag) => tag.trim())
    .filter((tag) => tag.length > 0)
    .slice(0, 16);
}


function TagChip({ active, count, label, onClick }: {
  active: boolean; count: number; label: string; onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick}
      className={[
        "px-2 py-0.5 rounded-full text-[10.5px] border transition-colors",
        active
          ? "bg-accent-dim text-[var(--accent-text)] border-accent-dim"
          : "bg-surface-2 text-text-3 border-border hover:text-text",
      ].join(" ")}>
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
