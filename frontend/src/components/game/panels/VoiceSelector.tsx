/**
 * Compact voice picker reused by both the player-character card and the
 * NPC detail modal. Renders nothing if no voices are available — the
 * caller decides whether to hide its surrounding section in that case.
 *
 * The dropdown lists voices fetched from `/api/media/voices`; the play
 * button hits `/api/media/tts` for a short preview clip.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../../../api/client";
import type { MediaVoice } from "../../../api/types";
import { useI18n, type MessageKey } from "../../../i18n";

interface Props {
  voices: MediaVoice[];
  current: string;
  provider: string;
  model: string;
  /** Persists the new voice. Resolves once the server confirms; the
   *  selector shows a "saving…" hint until it does. */
  onChange: (voice: string) => Promise<void>;
  /** "Use auto-assigned voice" placeholder label. NPC voices are
   *  auto-assigned; PC voices start blank — the wording differs so we
   *  let the caller supply it. */
  emptyLabel?: string;
  disabled?: boolean;
}

export function VoiceSelector({
  voices,
  current,
  provider,
  model,
  onChange,
  emptyLabel,
  disabled,
}: Props) {
  const { t } = useI18n();
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(
    () => () => {
      audioRef.current?.pause();
      audioRef.current = null;
    },
    [],
  );

  if (voices.length === 0) return null;

  const knownIds = new Set(voices.map((v) => v.id));
  // The auto-assigner can stamp a voice id that is no longer in the
  // current catalogue (provider switched, custom voice removed). Show
  // it as a stub option so the user sees what's effectively in use
  // instead of the dropdown silently snapping to the placeholder.
  const showStub = current !== "" && !knownIds.has(current);

  async function handlePick(value: string) {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      await onChange(value);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handlePreview() {
    if (!current || previewing) return;
    audioRef.current?.pause();
    setPreviewing(current);
    setError(null);
    try {
      const result = await api.synthesizeMediaSpeech({
        provider,
        model,
        text: t("debugMediaPreviewDialogueText"),
        voice: current,
        audio_format: "mp3",
        language: "auto",
      });
      const src = result.audio_data_uri || result.audio_url;
      if (!src) throw new Error(t("debugMediaPreviewNoAudio"));
      const audio = new Audio(src);
      audioRef.current = audio;
      audio.onended = () => setPreviewing(null);
      audio.onerror = () => setPreviewing(null);
      await audio.play();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPreviewing(null);
    }
  }

  return (
    <div>
      <div className="flex items-center gap-1.5">
        <select
          value={current}
          disabled={disabled || saving}
          onChange={(e) => void handlePick(e.target.value)}
          className="min-w-0 flex-1 px-2 py-1.5 bg-surface border border-border rounded text-[12px] text-text outline-none focus:border-accent disabled:opacity-50"
        >
          <option value="">{emptyLabel || t("voiceSelectorAuto")}</option>
          {showStub && (
            <option value={current}>{current}</option>
          )}
          {voices.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voiceSelectLabel(voice, t)}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void handlePreview()}
          disabled={!current || !!previewing || disabled}
          title={t("debugMediaPreview")}
          className="h-[30px] w-[34px] shrink-0 rounded border border-border bg-surface text-[12px] text-text hover:border-accent disabled:opacity-40"
        >
          {previewing ? "…" : "▶"}
        </button>
      </div>
      {saving && (
        <div className="mt-1 text-[10.5px] text-text-3">
          {t("debugMediaVoiceSaving")}
        </div>
      )}
      {error && (
        <div className="mt-1 text-[10.5px] text-[#f87171] break-words">
          {error}
        </div>
      )}
    </div>
  );
}

function voiceSelectLabel(
  voice: MediaVoice,
  t: (key: MessageKey, vars?: Record<string, string | number>) => string,
): string {
  const main =
    voice.name && voice.name !== voice.id
      ? `${voice.name} · ${voice.id}`
      : voice.id;
  const parts: string[] = [];
  const gender = voice.gender.trim().toLowerCase();
  if (gender === "female") parts.push(t("debugMediaGenderFemale"));
  else if (gender === "male") parts.push(t("debugMediaGenderMale"));
  else if (voice.gender.trim()) parts.push(voice.gender.trim());
  if (voice.description.trim()) parts.push(voice.description.trim());
  if (voice.languages.length) parts.push(voice.languages.join("/"));
  const meta = parts.join(" · ");
  return meta ? `${main} · ${meta}` : main;
}
