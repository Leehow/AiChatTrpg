import { useState, type ChangeEvent, type ReactNode, type RefObject } from "react";
import type { MusicTrackDTO } from "../../api/music";
import { MusicSessionBgmSection } from "./MusicSessionBgmSection";
import { MusicTrackList } from "./MusicTrackList";
import { SPEED_OPTIONS, type PlayerSettings } from "./musicState";

type PanelTab = "music" | "voice";

const SpeedPills = ({
  value,
  onChange,
}: {
  value: number;
  onChange: (n: number) => void;
}) => (
  <div className="flex flex-1 gap-1 rounded-lg border border-border bg-surface-2 p-[2px]">
    {SPEED_OPTIONS.map((sp) => {
      const active = Math.abs(value - sp) < 0.001;
      return (
        <button
          key={sp}
          onClick={() => onChange(sp)}
          className={`flex-1 rounded-md py-1 font-mono text-[10px] transition-colors ${
            active
              ? "bg-accent font-bold text-bg shadow-sm"
              : "bg-transparent text-text-2 hover:text-accent-text"
          }`}
        >
          {sp}×
        </button>
      );
    })}
  </div>
);

const Toggle = ({ on }: { on: boolean }) => (
  <span
    className={`flex h-[18px] w-[30px] items-center rounded-full p-[2px] transition-colors ${
      on ? "bg-accent" : "bg-surface-2 border border-border"
    }`}
  >
    <span
      className={`block h-[12px] w-[12px] rounded-full bg-bg shadow-sm transition-transform ${
        on ? "translate-x-[12px]" : ""
      }`}
    />
  </span>
);

const SectionDivider = ({ label }: { label: string }) => (
  <div className="flex items-center gap-2 pb-1 text-[10px] uppercase tracking-[0.22em] text-text-3">
    <span className="h-px flex-1 bg-border" />
    <span>{label}</span>
    <span className="h-px flex-1 bg-border" />
  </div>
);

const Collapsible = ({
  label,
  icon,
  open,
  onToggle,
  children,
}: {
  label: string;
  icon: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) => (
  <div className="border-t border-border">
    <button
      type="button"
      onClick={onToggle}
      className={`group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${
        open ? "bg-surface-2/60" : "hover:bg-surface-2/50"
      }`}
    >
      <span
        className={`flex h-7 w-7 items-center justify-center rounded-lg transition-colors ${
          open ? "bg-accent text-bg" : "bg-accent-dim text-accent-text group-hover:bg-accent group-hover:text-bg"
        }`}
      >
        {icon}
      </span>
      <span className="flex-1 text-[13px] font-medium text-text">{label}</span>
      <svg
        viewBox="0 0 24 24"
        className={`h-4 w-4 shrink-0 text-text-3 transition-transform ${open ? "rotate-180" : ""}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>
    {open && <div className="px-4 pb-4 pt-2">{children}</div>}
  </div>
);

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);

const SlidersIcon = () => (
  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="4" y1="21" x2="4" y2="14" />
    <line x1="4" y1="10" x2="4" y2="3" />
    <line x1="12" y1="21" x2="12" y2="12" />
    <line x1="12" y1="8" x2="12" y2="3" />
    <line x1="20" y1="21" x2="20" y2="16" />
    <line x1="20" y1="12" x2="20" y2="3" />
    <line x1="1" y1="14" x2="7" y2="14" />
    <line x1="9" y1="8" x2="15" y2="8" />
    <line x1="17" y1="16" x2="23" y2="16" />
  </svg>
);

interface Props {
  tracks: MusicTrackDTO[];
  groupedTracks: { mine: MusicTrackDTO[]; others: MusicTrackDTO[] };
  activeId: string | undefined;
  playing: boolean;
  settings: PlayerSettings;
  busy: boolean;
  errorMsg: string | null;
  urlInput: string;
  titleInput: string;
  isPublicInput: boolean;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onTitleInput: (v: string) => void;
  onUrlInput: (v: string) => void;
  onIsPublicInput: (v: boolean) => void;
  onSettings: (updater: (s: PlayerSettings) => PlayerSettings) => void;
  onCollapse: () => void;
  onSubmitUrl: () => void;
  onSubmitUpload: (e: ChangeEvent<HTMLInputElement>) => void;
  onPlay: (idx: number) => void;
  onTogglePublic: (t: MusicTrackDTO) => void;
  onDelete: (t: MusicTrackDTO) => void;
  /** Session-scoped BGM controls — present only when the player is
   *  mounted inside a game shell with a real session id. */
  sessionScoped?: boolean;
  sessionTracks?: MusicTrackDTO[];
  sessionBgmBusy?: boolean;
  onAddSessionTrack?: (trackId: string) => void;
  onRemoveSessionTrack?: (trackId: string) => void;
}

const inputCls =
  "w-full rounded-lg border border-border bg-input-bg px-3 py-2 text-sm text-text " +
  "placeholder:text-text-3 focus:border-accent focus:outline-none transition-colors";

export function MusicPanel(p: Props) {
  const [tab, setTab] = useState<PanelTab>("music");
  const [addOpen, setAddOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const volumePct = Math.round(p.settings.volume * 100);
  const tabBtnCls = (active: boolean) =>
    `relative pb-1 text-[12px] tracking-wide transition-colors ${
      active ? "text-text" : "text-text-3 hover:text-text-2"
    }`;
  return (
    <div
      className="chatrpg-mp-card mb-3 w-[22rem] max-w-full max-h-[72vh] overflow-y-auto rounded-2xl border border-border bg-surface text-text"
      style={{ boxShadow: "0 18px 36px var(--shadow-md), inset 0 1px 0 var(--surface-2)" }}
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-4">
          <span className="block h-1.5 w-1.5 rounded-full bg-accent" />
          <button onClick={() => setTab("music")} className={tabBtnCls(tab === "music")}>
            音乐
            {tab === "music" && (
              <span className="absolute -bottom-[13px] left-0 right-0 h-[2px] bg-accent" />
            )}
          </button>
          <button onClick={() => setTab("voice")} className={tabBtnCls(tab === "voice")}>
            朗读
            {tab === "voice" && (
              <span className="absolute -bottom-[13px] left-0 right-0 h-[2px] bg-accent" />
            )}
          </button>
        </div>
        <button
          className="text-[10px] uppercase tracking-[0.22em] text-text-3 hover:text-text transition-colors"
          onClick={p.onCollapse}
        >
          收起
        </button>
      </div>

      {tab === "voice" && (
        <div className="space-y-4 px-4 pb-5 pt-4">
          <SectionDivider label="朗读速度" />
          <div className="flex items-center gap-3">
            <span className="w-12 shrink-0 text-[10px] uppercase tracking-[0.22em] text-text-3">
              旁白
            </span>
            <SpeedPills
              value={p.settings.narratorSpeed}
              onChange={(v) => p.onSettings((s) => ({ ...s, narratorSpeed: v }))}
            />
          </div>
          <div className="flex items-center gap-3">
            <span className="w-12 shrink-0 text-[10px] uppercase tracking-[0.22em] text-text-3">
              NPC
            </span>
            <SpeedPills
              value={p.settings.dialogueSpeed}
              onChange={(v) => p.onSettings((s) => ({ ...s, dialogueSpeed: v }))}
            />
          </div>
          <p className="text-[11px] italic leading-relaxed text-text-3">
            调节 GM 旁白与 NPC 对白的朗读速度。下一段播放时即时生效，无需重新生成。
          </p>
        </div>
      )}

      {tab === "music" && (
      <>
      {p.sessionScoped && (
        <MusicSessionBgmSection
          sessionTracks={p.sessionTracks ?? []}
          libraryTracks={p.tracks}
          busy={p.sessionBgmBusy}
          onAdd={p.onAddSessionTrack}
          onRemove={p.onRemoveSessionTrack}
        />
      )}
      <Collapsible
        label="添加曲目"
        icon={<PlusIcon />}
        open={addOpen}
        onToggle={() => setAddOpen((v) => !v)}
      >
      <div className="space-y-2 pt-1">
        <input
          type="text"
          value={p.titleInput}
          onChange={(e) => p.onTitleInput(e.target.value)}
          placeholder="标题（可选）"
          className={inputCls}
        />
        <input
          type="text"
          value={p.urlInput}
          onChange={(e) => p.onUrlInput(e.target.value)}
          placeholder="https:// 或 http://"
          className={inputCls}
        />
        <button
          type="button"
          onClick={() => p.onIsPublicInput(!p.isPublicInput)}
          className="flex items-center gap-2 text-[11px] tracking-wide text-text-2 hover:text-text"
        >
          <Toggle on={p.isPublicInput} />
          <span>{p.isPublicInput ? "其他玩家可见" : "仅自己可见"}</span>
        </button>
        <div className="flex gap-2 pt-1">
          <button
            className="flex-1 rounded-lg bg-accent px-3 py-2 text-xs font-semibold tracking-wide text-bg disabled:opacity-40 hover:opacity-90 transition-opacity"
            disabled={p.busy || !p.urlInput.trim()}
            onClick={p.onSubmitUrl}
          >
            添加 URL
          </button>
          <button
            className="flex-1 rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs font-semibold tracking-wide text-text hover:border-accent hover:bg-accent-dim hover:text-accent-text disabled:opacity-40 transition-colors"
            disabled={p.busy}
            onClick={() => p.fileInputRef.current?.click()}
          >
            上传文件
          </button>
          <input
            ref={p.fileInputRef}
            type="file"
            accept="audio/*"
            className="hidden"
            onChange={p.onSubmitUpload}
          />
        </div>
        {p.errorMsg && (
          <div className="rounded-md border border-border bg-surface-2 px-2 py-1 text-[11px] text-text-2">
            ⚠ {p.errorMsg}
          </div>
        )}
      </div>
      </Collapsible>

      <Collapsible
        label="播放设置"
        icon={<SlidersIcon />}
        open={settingsOpen}
        onToggle={() => setSettingsOpen((v) => !v)}
      >
      <div className="space-y-3 pt-1">
        <div className="flex items-center gap-3">
          <span className="w-12 shrink-0 text-[10px] uppercase tracking-[0.22em] text-text-3">
            音量
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={p.settings.volume}
            onChange={(e) => p.onSettings((s) => ({ ...s, volume: Number(e.target.value) }))}
            className="flex-1 accent-accent"
          />
          <span className="w-9 text-right font-mono text-[11px] tabular-nums text-text-2">
            {volumePct}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-12 shrink-0 text-[10px] uppercase tracking-[0.22em] text-text-3">
            速度
          </span>
          <SpeedPills
            value={p.settings.speed}
            onChange={(v) => p.onSettings((s) => ({ ...s, speed: v }))}
          />
        </div>
        <button
          onClick={() => p.onSettings((s) => ({ ...s, shuffle: !s.shuffle }))}
          className="flex w-full items-center justify-between text-[11px] tracking-wide text-text-2 hover:text-text"
        >
          <span className="flex items-center gap-2">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="16 3 21 3 21 8" />
              <line x1="4" y1="20" x2="21" y2="3" />
              <polyline points="21 16 21 21 16 21" />
              <line x1="15" y1="15" x2="21" y2="21" />
              <line x1="4" y1="4" x2="9" y2="9" />
            </svg>
            <span>{p.settings.shuffle ? "乱序播放" : "顺序播放"}</span>
          </span>
          <Toggle on={p.settings.shuffle} />
        </button>
        <button
          onClick={() => p.onSettings((s) => ({ ...s, loop: !s.loop }))}
          className="flex w-full items-center justify-between text-[11px] tracking-wide text-text-2 hover:text-text"
        >
          <span className="flex items-center gap-2">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="17 1 21 5 17 9" />
              <path d="M3 11V9a4 4 0 0 1 4-4h14" />
              <polyline points="7 23 3 19 7 15" />
              <path d="M21 13v2a4 4 0 0 1-4 4H3" />
            </svg>
            <span>{p.settings.loop ? "循环播放" : "单次播放"}</span>
          </span>
          <Toggle on={p.settings.loop} />
        </button>
      </div>
      </Collapsible>

      <MusicTrackList
        label="我的曲目"
        tracks={p.groupedTracks.mine}
        activeId={p.activeId}
        playing={p.playing}
        onPlay={(idx) => p.onPlay(p.tracks.indexOf(p.groupedTracks.mine[idx]))}
        onTogglePublic={p.onTogglePublic}
        onDelete={p.onDelete}
      />
      <MusicTrackList
        label="其他玩家公开"
        tracks={p.groupedTracks.others}
        activeId={p.activeId}
        playing={p.playing}
        onPlay={(idx) => p.onPlay(p.tracks.indexOf(p.groupedTracks.others[idx]))}
      />
      {p.tracks.length === 0 && (
        <div className="px-4 pb-4 pt-1 text-center text-[11px] italic text-text-3">
          曲库为空 · 通过上方添加 URL 或上传一段音频开始
        </div>
      )}
      </>
      )}
    </div>
  );
}
