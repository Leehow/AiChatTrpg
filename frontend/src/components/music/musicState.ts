export const SETTINGS_KEY = "chatrpg.music.settings";
export const SPEED_OPTIONS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];

export interface PlayerSettings {
  volume: number;
  speed: number;
  shuffle: boolean;
  // When false, playback stops after the current track ends instead of
  // advancing to the next one.
  loop: boolean;
  // TTS playback rate, applied per-segment in useMessageTts based on
  // backend-supplied `kind` ("narrator" vs "dialogue").
  narratorSpeed: number;
  dialogueSpeed: number;
}

export const DEFAULT_SETTINGS: PlayerSettings = {
  volume: 0.7,
  speed: 1.0,
  shuffle: false,
  loop: true,
  narratorSpeed: 1.0,
  dialogueSpeed: 1.0,
};

export function clampSettings(value: unknown): PlayerSettings {
  if (!value || typeof value !== "object") return DEFAULT_SETTINGS;
  const parsed = value as Partial<PlayerSettings>;
  return {
    volume:
      typeof parsed.volume === "number" && parsed.volume >= 0 && parsed.volume <= 1
        ? parsed.volume
        : DEFAULT_SETTINGS.volume,
    speed:
      typeof parsed.speed === "number" && SPEED_OPTIONS.includes(parsed.speed)
        ? parsed.speed
        : DEFAULT_SETTINGS.speed,
    shuffle: parsed.shuffle === true,
    loop: parsed.loop === undefined ? DEFAULT_SETTINGS.loop : parsed.loop === true,
    narratorSpeed:
      typeof parsed.narratorSpeed === "number"
      && SPEED_OPTIONS.includes(parsed.narratorSpeed)
        ? parsed.narratorSpeed
        : DEFAULT_SETTINGS.narratorSpeed,
    dialogueSpeed:
      typeof parsed.dialogueSpeed === "number"
      && SPEED_OPTIONS.includes(parsed.dialogueSpeed)
        ? parsed.dialogueSpeed
        : DEFAULT_SETTINGS.dialogueSpeed,
  };
}

export function loadSettings(): PlayerSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return clampSettings(JSON.parse(raw));
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(s: PlayerSettings) {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {
    // ignore quota errors
  }
}

/** Read just the TTS playback speeds. Lightweight for use inside hooks
 * that don't otherwise care about the music player state. */
export function getTtsSpeeds(): { narrator: number; dialogue: number } {
  const s = loadSettings();
  return { narrator: s.narratorSpeed, dialogue: s.dialogueSpeed };
}

export function pickNextIndex(
  current: number,
  total: number,
  shuffle: boolean,
): number {
  if (total <= 0) return -1;
  if (total === 1) return 0;
  if (!shuffle) return (current + 1) % total;
  let next = current;
  while (next === current) next = Math.floor(Math.random() * total);
  return next;
}

export const PLAYER_STYLES = `
@keyframes chatrpg-mp-eq { 0%,100% { transform: scaleY(0.32); } 50% { transform: scaleY(1); } }
.chatrpg-mp-eq-bar { animation: chatrpg-mp-eq 0.9s ease-in-out infinite; transform-origin: bottom; }
.chatrpg-mp-eq-bar:nth-child(2) { animation-delay: 0.18s; }
.chatrpg-mp-eq-bar:nth-child(3) { animation-delay: 0.36s; }
@keyframes chatrpg-mp-rise { from { opacity: 0; transform: translateY(8px) scale(0.985); } to { opacity: 1; transform: none; } }
.chatrpg-mp-card { animation: chatrpg-mp-rise 0.22s cubic-bezier(.2,.8,.2,1) both; }
@keyframes chatrpg-mp-ring { 0% { box-shadow: 0 0 0 0 var(--accent-dim); } 70% { box-shadow: 0 0 0 8px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
.chatrpg-mp-pulse { animation: chatrpg-mp-ring 1.6s ease-out infinite; }
`;
