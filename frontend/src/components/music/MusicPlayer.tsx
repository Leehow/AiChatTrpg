import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { createPortal } from "react-dom";
import {
  createMusicFromUrlAPI,
  deleteMusicAPI,
  listMusicAPI,
  updateMusicAPI,
  uploadMusicAPI,
  type MusicTrackDTO,
} from "../../api/music";
import {
  getSessionBgmAPI,
  setSessionBgmAPI,
} from "../../api/sessions";
import { updatePreferencesAPI } from "../../api/auth";
import { getStoredUser } from "../../api/http";
import { useI18n } from "../../i18n";
import { useIsMobile } from "../../hooks/useIsMobile";
import { MUSIC_MOBILE_SLOT_ID } from "../game/RoomsPanel";
import { Eq } from "./MusicTrackList";
import { MusicPanel } from "./MusicPanel";
import {
  PLAYER_STYLES,
  clampSettings,
  loadSettings,
  pickNextIndex,
  saveSettings,
  type PlayerSettings,
} from "./musicState";

// Server-side preferences key for music player settings.
const PREFS_KEY = "music_settings";

function loadInitialSettings(): PlayerSettings {
  // Prefer server-synced preferences (cached in StoredUser) over the local
  // fallback so the same account on a second device picks up choices made
  // elsewhere.
  const user = getStoredUser();
  const fromPrefs = user?.preferences?.[PREFS_KEY];
  if (fromPrefs && typeof fromPrefs === "object") {
    return clampSettings(fromPrefs);
  }
  return loadSettings();
}

interface MusicPlayerProps {
  /** When set, the player fetches the session's BGM selection and
   *  restricts auto-advancement to those tracks. Library uploads stay
   *  global; the same per-user music library is visible either way. */
  sessionId?: string;
}

export function MusicPlayer({ sessionId }: MusicPlayerProps = {}) {
  const { t: tr } = useI18n();
  const [tracks, setTracks] = useState<MusicTrackDTO[]>([]);
  const [activeIdx, setActiveIdx] = useState<number>(-1);
  const [playing, setPlaying] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [compact, setCompact] = useState(true);
  const [settings, setSettings] = useState<PlayerSettings>(() => loadInitialSettings());
  const [urlInput, setUrlInput] = useState("");
  const [titleInput, setTitleInput] = useState("");
  const [isPublicInput, setIsPublicInput] = useState(true);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [sessionTrackIds, setSessionTrackIds] = useState<string[]>([]);
  const [sessionBgmBusy, setSessionBgmBusy] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const isMobile = useIsMobile();
  const [mobileSlot, setMobileSlot] = useState<HTMLElement | null>(null);

  // On mobile, portal into RoomsPanel's slot so the play button doesn't
  // overlap the chat input. The slot only exists when the drawer-mode
  // RoomsPanel is mounted; poll briefly in case mount order races.
  useEffect(() => {
    if (!isMobile) {
      setMobileSlot(null);
      return;
    }
    const find = () => document.getElementById(MUSIC_MOBILE_SLOT_ID);
    const initial = find();
    if (initial) {
      setMobileSlot(initial);
      return;
    }
    const t = window.setTimeout(() => setMobileSlot(find()), 0);
    return () => window.clearTimeout(t);
  }, [isMobile]);

  // Click outside the player → shrink back to the play-button-only state.
  useEffect(() => {
    if (compact && !expanded) return;
    const handler = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setExpanded(false);
        setCompact(true);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [compact, expanded]);

  // Persist settings: localStorage immediately (so a refresh restores
  // them without waiting on the network), then debounced push to the
  // server preferences blob so the same account picks them up on other
  // devices. The first render is just the loaded initial value; skip the
  // server write so we don't echo what we just read.
  const skipFirstPushRef = useRef(true);
  const pushTimerRef = useRef<number | null>(null);
  useEffect(() => {
    saveSettings(settings);
    if (skipFirstPushRef.current) {
      skipFirstPushRef.current = false;
      return;
    }
    if (pushTimerRef.current != null) {
      window.clearTimeout(pushTimerRef.current);
    }
    pushTimerRef.current = window.setTimeout(() => {
      pushTimerRef.current = null;
      void updatePreferencesAPI({ [PREFS_KEY]: settings }).catch((err) => {
        console.warn("[chatrpg] persist music settings failed:", err);
      });
    }, 500);
    return () => {
      if (pushTimerRef.current != null) {
        window.clearTimeout(pushTimerRef.current);
        pushTimerRef.current = null;
      }
    };
  }, [settings]);

  const refresh = useCallback(async () => {
    try {
      setTracks(await listMusicAPI());
    } catch (err) {
      console.warn("[chatrpg] list music failed:", err);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Pull the session's BGM selection whenever the player is mounted in a
  // game screen. When no sessionId is set (admin/library context), the
  // selection stays empty and the player falls back to the full library.
  useEffect(() => {
    if (!sessionId) {
      setSessionTrackIds([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const data = await getSessionBgmAPI(sessionId);
        if (!cancelled) setSessionTrackIds(data.track_ids);
      } catch (err) {
        if (!cancelled) {
          console.warn("[chatrpg] load session bgm failed:", err);
          setSessionTrackIds([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = settings.volume;
    audio.playbackRate = settings.speed;
  }, [settings.volume, settings.speed]);

  const activeTrack = activeIdx >= 0 ? tracks[activeIdx] : undefined;

  // Map from id → track / library-index. Backed by the user's visible
  // library; used to look up selected session BGM ids without scanning.
  const trackById = useMemo(() => {
    const byTrack = new Map<string, MusicTrackDTO>();
    const byIndex = new Map<string, number>();
    tracks.forEach((t, i) => {
      byTrack.set(t.id, t);
      byIndex.set(t.id, i);
    });
    return { byTrack, byIndex };
  }, [tracks]);

  // Indices into `tracks` that the player is allowed to auto-advance
  // through. With no session-scoped selection (admin context, or the
  // session hasn't picked any tracks) it stays the full library. When a
  // session selection exists, we walk `sessionTrackIds` in user-chosen
  // order (the backend preserves selection order in `track_ids`), drop
  // any ids that don't resolve to a visible library row, and keep that
  // order for both display and auto-advance. Direct clicks on a library
  // row still play that row.
  const playableIndexes = useMemo(() => {
    if (!sessionId || sessionTrackIds.length === 0) {
      return tracks.map((_, i) => i);
    }
    const result: number[] = [];
    for (const id of sessionTrackIds) {
      const idx = trackById.byIndex.get(id);
      if (idx !== undefined) result.push(idx);
    }
    return result;
  }, [tracks, sessionId, sessionTrackIds, trackById]);

  useEffect(() => {
    if (activeIdx >= tracks.length) {
      setActiveIdx(tracks.length > 0 ? 0 : -1);
    }
  }, [tracks.length, activeIdx]);

  const playIndex = useCallback((idx: number) => {
    if (idx < 0) return;
    setActiveIdx(idx);
    setPlaying(true);
  }, []);

  const togglePlay = useCallback(() => {
    if (tracks.length === 0) {
      setExpanded(true);
      return;
    }
    if (activeIdx < 0) {
      // Session selection is configured but none of its ids resolve to a
      // visible library row — don't silently start playing a global
      // track the user didn't pick. Expand the panel so the player can
      // see/fix their selection, and surface the reason.
      if (
        sessionId
        && sessionTrackIds.length > 0
        && playableIndexes.length === 0
      ) {
        setExpanded(true);
        setErrorMsg(tr("bgmSessionMissingFromLibrary"));
        return;
      }
      const start = playableIndexes[0] ?? 0;
      playIndex(start);
      return;
    }
    setPlaying((p) => !p);
  }, [
    tracks.length,
    activeIdx,
    sessionId,
    sessionTrackIds.length,
    playableIndexes,
    playIndex,
    tr,
  ]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing && activeTrack) {
      audio.play().catch((err) => {
        console.warn("[chatrpg] audio play failed:", err);
        setPlaying(false);
        setErrorMsg("Playback blocked or source invalid");
      });
    } else {
      audio.pause();
    }
  }, [playing, activeTrack?.url]);

  const handleEnded = useCallback(() => {
    if (!settings.loop) {
      setPlaying(false);
      return;
    }
    if (playableIndexes.length === 0) {
      setPlaying(false);
      return;
    }
    // Advance through the playable subset (session BGM when active, else
    // the full library). If the current track isn't in the subset (e.g.
    // user clicked a library row while session selection is set), treat
    // it as position -1 → first subset track plays next.
    const currentPos = playableIndexes.indexOf(activeIdx);
    const nextPos = pickNextIndex(
      currentPos,
      playableIndexes.length,
      settings.shuffle,
    );
    if (nextPos < 0) {
      setPlaying(false);
      return;
    }
    playIndex(playableIndexes[nextPos]);
  }, [activeIdx, playableIndexes, settings.shuffle, settings.loop, playIndex]);

  const submitUrl = useCallback(async () => {
    const url = urlInput.trim();
    if (!url) return;
    setBusy(true);
    setErrorMsg(null);
    try {
      await createMusicFromUrlAPI({ url, title: titleInput.trim(), is_public: isPublicInput });
      setUrlInput("");
      setTitleInput("");
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Add failed");
    } finally {
      setBusy(false);
    }
  }, [urlInput, titleInput, isPublicInput, refresh]);

  const submitUpload = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      setBusy(true);
      setErrorMsg(null);
      try {
        await uploadMusicAPI(file, { title: titleInput.trim(), is_public: isPublicInput });
        setTitleInput("");
        await refresh();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setBusy(false);
      }
    },
    [titleInput, isPublicInput, refresh],
  );

  const togglePublic = useCallback(
    async (t: MusicTrackDTO) => {
      try {
        await updateMusicAPI(t.id, { is_public: !t.is_public });
        await refresh();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : "Update failed");
      }
    },
    [refresh],
  );

  const removeTrack = useCallback(
    async (t: MusicTrackDTO) => {
      if (!confirm(`删除曲目 "${t.title}"？`)) return;
      try {
        await deleteMusicAPI(t.id);
        await refresh();
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : "Delete failed");
      }
    },
    [refresh],
  );

  const groupedTracks = useMemo(() => {
    const mine: MusicTrackDTO[] = [];
    const others: MusicTrackDTO[] = [];
    for (const t of tracks) {
      if (t.is_mine) mine.push(t);
      else others.push(t);
    }
    return { mine, others };
  }, [tracks]);

  // The session's BGM tracks in user-chosen order. We walk `sessionTrackIds`
  // (which the backend preserves in selection order) and look each one up
  // in the visible library; any id that no longer resolves to a row is
  // silently dropped from the display list (the id stays in
  // `sessionTrackIds` so the server-side selection isn't clobbered).
  const sessionTracks = useMemo(() => {
    const out: MusicTrackDTO[] = [];
    for (const id of sessionTrackIds) {
      const t = trackById.byTrack.get(id);
      if (t) out.push(t);
    }
    return out;
  }, [trackById, sessionTrackIds]);

  const persistSessionBgm = useCallback(
    async (nextIds: string[]) => {
      if (!sessionId) return;
      const prev = sessionTrackIds;
      setSessionTrackIds(nextIds);
      setSessionBgmBusy(true);
      try {
        const data = await setSessionBgmAPI(sessionId, { track_ids: nextIds });
        setSessionTrackIds(data.track_ids);
      } catch (err) {
        console.warn("[chatrpg] save session bgm failed:", err);
        setSessionTrackIds(prev);
        setErrorMsg(err instanceof Error ? err.message : "Save BGM failed");
      } finally {
        setSessionBgmBusy(false);
      }
    },
    [sessionId, sessionTrackIds],
  );

  const addSessionTrack = useCallback(
    (trackId: string) => {
      if (!sessionId || sessionTrackIds.includes(trackId)) return;
      void persistSessionBgm([...sessionTrackIds, trackId]);
    },
    [sessionId, sessionTrackIds, persistSessionBgm],
  );

  const removeSessionTrack = useCallback(
    (trackId: string) => {
      if (!sessionId) return;
      void persistSessionBgm(sessionTrackIds.filter((id) => id !== trackId));
    },
    [sessionId, sessionTrackIds, persistSessionBgm],
  );

  const portalActive = isMobile && mobileSlot != null;
  const wrapperCls = portalActive
    ? "relative z-40 select-none"
    : "fixed bottom-4 left-4 z-40 select-none";
  const content = (
    <div ref={rootRef} className={wrapperCls} style={{ fontFamily: "inherit" }}>
      <style>{PLAYER_STYLES}</style>
      <audio
        ref={audioRef}
        src={activeTrack?.url || undefined}
        onEnded={handleEnded}
        onError={() => {
          if (playing) setErrorMsg("Failed to load audio source");
          setPlaying(false);
        }}
      />

      {expanded && (
        <MusicPanel
          tracks={tracks}
          groupedTracks={groupedTracks}
          activeId={activeTrack?.id}
          playing={playing}
          settings={settings}
          busy={busy}
          errorMsg={errorMsg}
          urlInput={urlInput}
          titleInput={titleInput}
          isPublicInput={isPublicInput}
          fileInputRef={fileInputRef}
          onTitleInput={setTitleInput}
          onUrlInput={setUrlInput}
          onIsPublicInput={setIsPublicInput}
          onSettings={setSettings}
          onCollapse={() => setExpanded(false)}
          onSubmitUrl={() => void submitUrl()}
          onSubmitUpload={(e) => void submitUpload(e)}
          onPlay={playIndex}
          onTogglePublic={togglePublic}
          onDelete={removeTrack}
          sessionScoped={!!sessionId}
          sessionTracks={sessionTracks}
          sessionBgmBusy={sessionBgmBusy}
          onAddSessionTrack={addSessionTrack}
          onRemoveSessionTrack={removeSessionTrack}
        />
      )}

      <div
        onClick={() => {
          if (compact) setCompact(false);
        }}
        className={`flex items-center rounded-full border py-1.5 pl-2 pr-2 text-text transition-all duration-300 ease-out ${
          compact
            ? "cursor-pointer border-transparent bg-transparent"
            : "border-border bg-surface"
        }`}
        style={{
          boxShadow: compact
            ? "0 0 0 0 rgba(0,0,0,0), inset 0 0 0 0 rgba(0,0,0,0)"
            : "0 6px 18px var(--shadow-md), inset 0 1px 0 var(--surface-2)",
        }}
      >
        <button
          aria-label={playing ? "暂停" : "播放"}
          onClick={togglePlay}
          className={`flex h-9 w-9 items-center justify-center rounded-full bg-accent text-bg transition-transform hover:scale-105 active:scale-95 ${
            playing ? "chatrpg-mp-pulse" : ""
          }`}
          style={{ boxShadow: "0 0 0 3px var(--accent-dim)" }}
        >
          {playing ? (
            compact ? (
              <Eq className="h-3.5" />
            ) : (
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor">
                <rect x="6" y="5" width="4" height="14" rx="1" />
                <rect x="14" y="5" width="4" height="14" rx="1" />
              </svg>
            )
          ) : (
            <svg viewBox="0 0 24 24" className="h-4 w-4 translate-x-[1px]" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>
        <div
          className={`flex items-center overflow-hidden transition-all duration-300 ease-[cubic-bezier(.2,.8,.2,1)] ${
            compact ? "max-w-0 ml-0 opacity-0" : "max-w-[260px] ml-2 opacity-100"
          }`}
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
            className="flex min-w-0 cursor-pointer items-center gap-2 pr-1 text-left"
          >
            {playing ? (
              <Eq className="h-3 text-accent" />
            ) : (
              <span className="block h-1.5 w-1.5 rounded-full bg-text-3" />
            )}
            <div className="min-w-0 max-w-[180px]">
              <div className="truncate text-[12px] font-medium text-text">
                {activeTrack?.title ?? "未选择"}
              </div>
              {activeTrack && (
                <div className="truncate text-[9.5px] uppercase tracking-[0.18em] text-text-3">
                  @{activeTrack.owner_username}
                </div>
              )}
            </div>
          </button>
          <button
            aria-label={expanded ? "收起" : "展开"}
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
            className="ml-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-text-2 hover:bg-accent-dim hover:text-accent-text transition-colors"
          >
            <svg
              viewBox="0 0 24 24"
              className={`h-4 w-4 transition-transform ${expanded ? "" : "rotate-180"}`}
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6 15l6-6 6 6" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );

  return portalActive ? createPortal(content, mobileSlot!) : content;
}
