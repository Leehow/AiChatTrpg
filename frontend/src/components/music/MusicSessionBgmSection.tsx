/**
 * Session BGM picker — rendered inside `MusicPanel` only when the player
 * is mounted in a real game shell (sessionId is set). Lets the player
 * choose which library tracks should play during this session and lift
 * one back out. Selection lives on the server in
 * `memory_state._settings.bgm_track_ids` via setSessionBgmAPI; the parent
 * MusicPlayer owns the persistence calls and passes us the add/remove
 * handlers, keeping this component pure.
 */
import { useMemo, useState } from "react";
import { useI18n } from "../../i18n";
import type { MusicTrackDTO } from "../../api/music";

interface Props {
  /** Library tracks already in this session's BGM. */
  sessionTracks: MusicTrackDTO[];
  /** All library tracks visible to the user — used to derive the
   *  "addable" picker (visible-but-not-yet-selected). */
  libraryTracks: MusicTrackDTO[];
  busy?: boolean;
  onAdd?: (trackId: string) => void;
  onRemove?: (trackId: string) => void;
}

export function MusicSessionBgmSection({
  sessionTracks,
  libraryTracks,
  busy,
  onAdd,
  onRemove,
}: Props) {
  const { t } = useI18n();
  const [pendingId, setPendingId] = useState("");

  const selectedIds = useMemo(
    () => new Set(sessionTracks.map((s) => s.id)),
    [sessionTracks],
  );
  const candidates = useMemo(
    () => libraryTracks.filter((c) => !selectedIds.has(c.id)),
    [libraryTracks, selectedIds],
  );

  return (
    <div className="border-t border-border px-4 pb-3 pt-3">
      <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-[0.22em] text-text-3">
        <span className="flex items-center gap-2">
          <span>{t("bgmSessionTitle")}</span>
          <span className="font-mono opacity-70">
            ·{String(sessionTracks.length).padStart(2, "0")}
          </span>
        </span>
        {busy && (
          <span className="text-[9.5px] italic normal-case text-text-3">
            {t("bgmSessionSaving")}
          </span>
        )}
      </div>

      {sessionTracks.length === 0 ? (
        <div className="mb-2 text-[11px] italic text-text-3">
          {t("bgmSessionEmpty")}
        </div>
      ) : (
        <ul className="mb-2 space-y-1">
          {sessionTracks.map((track) => (
            <li
              key={track.id}
              className="flex items-center gap-2 rounded-md bg-surface-2/60 px-2 py-1.5"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12px] text-text">
                  {track.title}
                </div>
                <div className="truncate text-[9.5px] uppercase tracking-[0.16em] text-text-3">
                  @{track.owner_username}
                </div>
              </div>
              <button
                type="button"
                onClick={() => onRemove?.(track.id)}
                disabled={busy}
                className="rounded-md border border-border bg-surface px-2 py-1 text-[10px] text-text-2 hover:border-accent hover:text-accent-text disabled:opacity-40 transition-colors"
              >
                {t("bgmSessionRemove")}
              </button>
            </li>
          ))}
        </ul>
      )}

      {candidates.length > 0 ? (
        <div className="flex gap-1.5">
          <select
            value={pendingId}
            onChange={(e) => setPendingId(e.target.value)}
            disabled={busy}
            className="flex-1 rounded-md border border-border bg-input-bg px-2 py-1.5 text-[11px] text-text focus:border-accent focus:outline-none disabled:opacity-40"
          >
            <option value="">{t("bgmSessionAddPlaceholder")}</option>
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title} · @{c.owner_username}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!pendingId || busy}
            onClick={() => {
              if (!pendingId) return;
              onAdd?.(pendingId);
              setPendingId("");
            }}
            className="rounded-md bg-accent px-2.5 py-1.5 text-[11px] font-semibold text-bg disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {t("bgmSessionAdd")}
          </button>
        </div>
      ) : (
        <div className="text-[10.5px] italic text-text-3">
          {t("bgmSessionAddAllInList")}
        </div>
      )}
    </div>
  );
}
