import type { MusicTrackDTO } from "../../api/music";

export const Eq = ({ className = "h-3" }: { className?: string }) => (
  <span className={`flex items-end gap-[2px] ${className}`} aria-hidden>
    <span className="chatrpg-mp-eq-bar block h-full w-[2px] rounded-[1px] bg-current" />
    <span className="chatrpg-mp-eq-bar block h-full w-[2px] rounded-[1px] bg-current" />
    <span className="chatrpg-mp-eq-bar block h-full w-[2px] rounded-[1px] bg-current" />
  </span>
);

interface Props {
  label: string;
  tracks: MusicTrackDTO[];
  activeId: string | undefined;
  playing: boolean;
  onPlay: (idx: number) => void;
  onTogglePublic?: (t: MusicTrackDTO) => void;
  onDelete?: (t: MusicTrackDTO) => void;
}

export function MusicTrackList({
  label,
  tracks,
  activeId,
  playing,
  onPlay,
  onTogglePublic,
  onDelete,
}: Props) {
  if (tracks.length === 0) return null;
  return (
    <div className="border-t border-border px-3 py-3">
      <div className="mb-2 flex items-center gap-2 px-1 text-[10px] uppercase tracking-[0.22em] text-text-3">
        <span>{label}</span>
        <span className="font-mono opacity-70">
          ·{String(tracks.length).padStart(2, "0")}
        </span>
      </div>
      <ul className="space-y-1">
        {tracks.map((t, idx) => (
          <TrackRow
            key={t.id}
            track={t}
            idx={idx}
            isActive={t.id === activeId}
            playing={playing}
            onPlay={onPlay}
            onTogglePublic={onTogglePublic}
            onDelete={onDelete}
          />
        ))}
      </ul>
    </div>
  );
}

function TrackRow({
  track: t,
  idx,
  isActive,
  playing,
  onPlay,
  onTogglePublic,
  onDelete,
}: {
  track: MusicTrackDTO;
  idx: number;
  isActive: boolean;
  playing: boolean;
  onPlay: (idx: number) => void;
  onTogglePublic?: (t: MusicTrackDTO) => void;
  onDelete?: (t: MusicTrackDTO) => void;
}) {
  return (
    <li
      className={`group flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors ${
        isActive ? "bg-accent-dim" : "hover:bg-surface-2"
      }`}
      style={isActive ? { boxShadow: "inset 3px 0 0 var(--accent)" } : undefined}
    >
      <button
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors ${
          isActive
            ? "bg-accent text-bg"
            : "bg-surface-2 text-text-2 group-hover:bg-accent group-hover:text-bg"
        }`}
        aria-label="播放"
        onClick={() => onPlay(idx)}
      >
        {isActive && playing ? (
          <Eq className="h-3" />
        ) : (
          <svg viewBox="0 0 24 24" className="h-3 w-3 translate-x-[1px]" fill="currentColor">
            <path d="M8 5v14l11-7z" />
          </svg>
        )}
      </button>
      <div className="min-w-0 flex-1">
        <div
          className={`truncate text-[12px] ${
            isActive ? "font-semibold text-accent-text" : "text-text"
          }`}
        >
          {t.title}
        </div>
        <div className="truncate text-[9.5px] uppercase tracking-[0.16em] text-text-3">
          @{t.owner_username} · {t.source_type === "upload" ? "FILE" : "URL"}
        </div>
      </div>
      {onTogglePublic && (
        <button
          className={`flex h-6 items-center gap-1 rounded-full px-2 text-[9.5px] uppercase tracking-wider transition-colors hover:opacity-80 ${
            t.is_public ? "bg-secondary-dim text-secondary" : "bg-surface-2 text-text-3"
          }`}
          onClick={() => onTogglePublic(t)}
          title={t.is_public ? "切换为私有" : "切换为公开"}
        >
          {t.is_public ? (
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          )}
          {t.is_public ? "公开" : "私有"}
        </button>
      )}
      {onDelete && (
        <button
          className="flex h-6 w-6 items-center justify-center rounded-full text-text-3 opacity-0 transition-opacity hover:bg-surface-2 hover:text-text group-hover:opacity-100"
          onClick={() => onDelete(t)}
          title="删除"
        >
          <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
            <path d="M10 11v6M14 11v6" />
          </svg>
        </button>
      )}
    </li>
  );
}
