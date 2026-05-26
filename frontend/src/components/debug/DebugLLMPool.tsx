import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type {
  MediaSettings,
  MediaVoice,
  MediaVoiceListResponse,
  PoolEntry,
  PoolRole,
  PoolView,
} from "../../api/types";
import { useI18n, type MessageKey } from "../../i18n";

// Single source of truth for the role rows rendered below — adding a
// new role means appending one entry here plus a matching i18n key.
// `badge` is the small icon shown on each pool row to flag which role
// the entry currently holds.
const ROLE_DEFS: ReadonlyArray<{
  role: PoolRole;
  labelKey: MessageKey;
  badge: string;
  setter: (entry: PoolEntry) => Promise<PoolView>;
  view: (p: PoolView) => PoolEntry | null;
}> = [
  {
    role: "default",
    labelKey: "debugLlmPoolDefault",
    badge: "★",
    setter: api.setPoolDefault,
    view: (p) => p.default,
  },
  {
    role: "fast",
    labelKey: "debugLlmPoolFast",
    badge: "⚡",
    setter: api.setPoolFast,
    view: (p) => p.fast,
  },
  {
    role: "dialogue",
    labelKey: "debugLlmPoolDialogue",
    badge: "🗣",
    setter: api.setPoolDialogue,
    view: (p) => p.dialogue,
  },
  {
    role: "avatar",
    labelKey: "debugLlmPoolAvatar",
    badge: "👤",
    setter: api.setPoolAvatar,
    view: (p) => p.avatar,
  },
  {
    role: "illustration",
    labelKey: "debugLlmPoolIllustration",
    badge: "🖼",
    setter: api.setPoolIllustration,
    view: (p) => p.illustration,
  },
  {
    role: "narration",
    labelKey: "debugLlmPoolNarration",
    badge: "🎙",
    setter: api.setPoolNarration,
    view: (p) => p.narration,
  },
];

interface Props {
  // Current LLM-tab form values — used by the "Add to pool" button.
  // api_key + base_url are persisted to admin_config so other parts of
  // the app pick the same auth up.
  current: {
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
  };
  // Click on a pool row → load its (provider, model) back into the
  // form so the user can re-test it without retyping.
  onPickPool?: (entry: PoolEntry) => void;
}

// Pool register: a manual "add what works" list with one entry marked
// as default. The default is the model the rest of chatrpg uses for
// the GM, so the dropdown at the bottom is the actual switch.
export function DebugLLMPool({ current, onPickPool }: Props) {
  const { t } = useI18n();
  const [pool, setPool] = useState<PoolView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const p = await api.getModelPool();
        if (!cancelled) setPool(p);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function run<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    if (!current.model.trim() || !current.provider) return;
    const p = await run(() => api.addToPool(current));
    if (p) setPool(p);
  }

  async function remove(entry: PoolEntry) {
    const p = await run(() => api.removeFromPool(entry));
    if (p) setPool(p);
  }

  async function setRole(
    role: PoolRole,
    provider: string,
    model: string
  ) {
    const def = ROLE_DEFS.find((d) => d.role === role);
    if (!def) return;
    const p = await run(() => def.setter({ provider, model }));
    if (p) setPool(p);
  }

  const entries = pool?.entries ?? [];
  const trimmedModel = current.model.trim();
  const alreadyInPool = entries.some(
    (e) => e.provider === current.provider && e.model === trimmedModel
  );
  const canAdd = !!current.provider && !!trimmedModel && !alreadyInPool;

  return (
    <div className="space-y-2.5 mt-4 pt-3 border-t border-border">
      <button
        type="button"
        onClick={add}
        disabled={busy || !canAdd}
        className="w-full px-3 py-1.5 rounded border border-accent text-accent text-[12px] font-semibold hover:bg-accent-dim disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {alreadyInPool ? t("debugLlmInPool") : t("debugLlmAddToPool")}
      </button>

      <div>
        <div className="text-[10.5px] font-semibold tracking-[0.06em] uppercase text-text-3 mb-1">
          {t("debugLlmPool")} ({entries.length})
        </div>
        {entries.length === 0 ? (
          <div className="text-[11px] text-text-3 italic px-1 py-1">
            {t("debugLlmPoolEmpty")}
          </div>
        ) : (
          <ul className="space-y-0.5">
            {entries.map((e) => (
              <li
                key={`${e.provider}::${e.model}`}
                className="flex items-center gap-1.5 text-[11.5px] py-0.5 px-1 hover:bg-surface-2 rounded group"
              >
                <button
                  type="button"
                  onClick={() => onPickPool?.(e)}
                  title={t("debugLlmPoolPick")}
                  className="text-text-3 shrink-0 w-[60px] truncate text-left hover:text-text"
                >
                  {e.provider}
                </button>
                <button
                  type="button"
                  onClick={() => onPickPool?.(e)}
                  className="font-mono text-text flex-1 min-w-0 truncate text-left hover:underline"
                >
                  {e.model}
                </button>
                {pool && (
                  <div className="flex items-center gap-0.5 shrink-0">
                    {ROLE_DEFS.map((d) => {
                      const r = d.view(pool);
                      if (!r || r.provider !== e.provider || r.model !== e.model)
                        return null;
                      return (
                        <span
                          key={d.role}
                          className="text-[10px] text-accent px-0.5"
                          title={t(d.labelKey)}
                        >
                          {d.badge}
                        </span>
                      );
                    })}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => remove(e)}
                  disabled={busy}
                  title={t("debugLlmPoolRemove")}
                  className="opacity-50 hover:opacity-100 text-text-3 hover:text-[#f87171] px-1 disabled:opacity-30"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {entries.length > 0 && pool && (
        <>
          {ROLE_DEFS.map((d) => {
            const selected = d.view(pool);
            return (
              <div key={d.role} className="space-y-1">
                <RoleSelect
                  label={t(d.labelKey)}
                  entries={entries}
                  value={selected}
                  disabled={busy}
                  onChange={(provider, model) => setRole(d.role, provider, model)}
                />
                {(d.role === "dialogue" || d.role === "narration") && (
                  <VoiceRolePanel role={d.role} entry={selected} />
                )}
              </div>
            );
          })}
        </>
      )}

      {error && (
        <div className="text-[10.5px] text-[#f87171] break-words">{error}</div>
      )}
    </div>
  );
}

function VoiceRolePanel({
  role,
  entry,
}: {
  role: "dialogue" | "narration";
  entry: PoolEntry | null;
}) {
  const { t } = useI18n();
  const [voices, setVoices] = useState<MediaVoiceListResponse | null>(null);
  const [settings, setSettings] = useState<MediaSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const entryKey = entry ? `${entry.provider}::${entry.model}` : "";

  useEffect(() => {
    if (!entry) {
      setVoices(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void api
      .listMediaVoices(entry, true)
      .then((result) => {
        if (!cancelled) setVoices(result);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entryKey]);

  useEffect(() => {
    if (role !== "narration") return;
    let cancelled = false;
    void api
      .getMediaSettings()
      .then((result) => {
        if (!cancelled) setSettings(result);
      })
      .catch(() => {
        if (!cancelled) setSettings({ narration_voice: null });
      });
    return () => {
      cancelled = true;
    };
  }, [role]);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
      audioRef.current = null;
    };
  }, []);

  if (!entry) return null;

  const list = voices?.voices ?? [];
  const selectedVoice =
    settings?.narration_voice?.provider === entry.provider &&
    settings.narration_voice.model === entry.model
      ? settings.narration_voice.voice
      : "";

  async function saveNarrationVoice(voice: string) {
    if (!entry) return;
    const next: MediaSettings = {
      narration_voice: voice
        ? { provider: entry.provider, model: entry.model, voice }
        : null,
    };
    setSaving(true);
    setError(null);
    setSettings(next);
    try {
      setSettings(await api.updateMediaSettings(next));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function previewVoice(voice: string) {
    if (!entry) return;
    audioRef.current?.pause();
    setPreviewing(voice || "__default__");
    setPreviewError(null);
    try {
      const result = await api.synthesizeMediaSpeech({
        provider: entry.provider,
        model: entry.model,
        text:
          role === "narration"
            ? t("debugMediaPreviewNarrationText")
            : t("debugMediaPreviewDialogueText"),
        voice,
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
      setPreviewError(e instanceof Error ? e.message : String(e));
      setPreviewing(null);
    }
  }

  return (
    <div className="rounded border border-border/70 bg-surface-2/50 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2 text-[10.5px]">
        <span className="font-semibold text-text-3">
          {role === "narration"
            ? t("debugMediaNarrationVoice")
            : t("debugMediaDialogueVoices")}
        </span>
        <span className="text-text-3">
          {loading
            ? t("debugMediaVoicesLoading")
            : voices
              ? `${list.length} · ${t(sourceLabelKey(voices.source))}`
              : ""}
        </span>
      </div>

      {role === "narration" && list.length > 0 && (
        <div className="mt-1 flex items-center gap-1">
          <select
            value={selectedVoice}
            disabled={saving}
            onChange={(e) => void saveNarrationVoice(e.target.value)}
            className="min-w-0 flex-1 px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent disabled:opacity-50"
          >
            <option value="">{t("debugMediaNarrationDefault")}</option>
            {list.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voiceSelectLabel(voice, t)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void previewVoice(selectedVoice)}
            disabled={!!previewing}
            title={t("debugMediaPreview")}
            className="h-[30px] w-[34px] shrink-0 rounded border border-border bg-bg text-[12px] text-text hover:border-accent disabled:opacity-50"
          >
            {previewing ? "…" : "▶"}
          </button>
        </div>
      )}

      {role === "dialogue" && list.length > 0 && (
        <>
          <div className="mt-1 text-[10.5px] text-text-3">
            {t("debugMediaDialogueAuto")}
          </div>
          <div className="mt-1 max-h-36 overflow-y-auto flex flex-wrap gap-1">
            {list.map((voice) => (
              <span
                key={voice.id}
                title={voiceSelectLabel(voice, t)}
                className="max-w-full min-w-[126px] inline-flex items-center gap-1 rounded border border-border bg-bg px-1.5 py-1 text-[10.5px] text-text"
              >
                <button
                  type="button"
                  onClick={() => void previewVoice(voice.id)}
                  disabled={!!previewing}
                  title={t("debugMediaPreview")}
                  className="grid h-4 w-4 shrink-0 place-items-center rounded text-[9px] text-accent hover:bg-accent-dim disabled:opacity-40"
                >
                  {previewing === voice.id ? "…" : "▶"}
                </button>
                <span className="min-w-0 flex flex-col leading-tight">
                  <span className="truncate font-medium">
                    {voiceMainLabel(voice)}
                  </span>
                  {voiceMetaLabel(voice, t) && (
                    <span className="truncate text-[9.5px] text-text-3">
                      {voiceMetaLabel(voice, t)}
                    </span>
                  )}
                </span>
              </span>
            ))}
          </div>
        </>
      )}

      {!loading && list.length === 0 && (
        <div className="mt-1 text-[10.5px] text-text-3">
          {t("debugMediaVoicesEmpty")}
        </div>
      )}
      {saving && (
        <div className="mt-1 text-[10.5px] text-text-3">
          {t("debugMediaVoiceSaving")}
        </div>
      )}
      {(error || voices?.error) && (
        <div className="mt-1 text-[10.5px] text-text-3 break-words">
          {error || voices?.error}
        </div>
      )}
      {previewError && (
        <div className="mt-1 text-[10.5px] text-[#f87171] break-words">
          {previewError}
        </div>
      )}
    </div>
  );
}

function sourceLabelKey(source: string): MessageKey {
  if (source === "live") return "debugMediaVoicesLive";
  if (source === "fallback") return "debugMediaVoicesFallback";
  return "debugMediaVoicesCatalog";
}

function voiceMainLabel(voice: MediaVoice): string {
  if (voice.name && voice.name !== voice.id) return `${voice.name} · ${voice.id}`;
  return voice.id;
}

function voiceSelectLabel(
  voice: MediaVoice,
  t: (key: MessageKey, vars?: Record<string, string | number>) => string,
): string {
  const meta = voiceMetaLabel(voice, t);
  return meta ? `${voiceMainLabel(voice)} · ${meta}` : voiceMainLabel(voice);
}

function voiceMetaLabel(
  voice: MediaVoice,
  t: (key: MessageKey, vars?: Record<string, string | number>) => string,
): string {
  const parts: string[] = [];
  const gender = voice.gender.trim().toLowerCase();
  if (gender === "female") parts.push(t("debugMediaGenderFemale"));
  else if (gender === "male") parts.push(t("debugMediaGenderMale"));
  else if (voice.gender.trim()) parts.push(voice.gender.trim());
  if (voice.description.trim()) parts.push(voice.description.trim());
  if (voice.languages.length) parts.push(voice.languages.join("/"));
  return parts.join(" · ");
}

function RoleSelect({
  label,
  entries,
  value,
  disabled,
  onChange,
}: {
  label: string;
  entries: PoolEntry[];
  value: PoolEntry | null;
  disabled: boolean;
  onChange: (provider: string, model: string) => void;
}) {
  return (
    <div>
      <div className="text-[10.5px] font-semibold tracking-[0.06em] uppercase text-text-3 mb-1">
        {label}
      </div>
      <select
        value={value ? `${value.provider}::${value.model}` : ""}
        onChange={(e) => {
          const [provider, model] = e.target.value.split("::");
          if (provider && model) onChange(provider, model);
        }}
        disabled={disabled}
        className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent disabled:opacity-50"
      >
        {entries.map((e) => (
          <option
            key={`${e.provider}::${e.model}`}
            value={`${e.provider}::${e.model}`}
          >
            {e.provider} · {e.model}
          </option>
        ))}
      </select>
    </div>
  );
}
