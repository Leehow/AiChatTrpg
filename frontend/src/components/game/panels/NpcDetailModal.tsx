/**
 * Detail card opened from the NPC sidebar grid. Public description +
 * PC-known facts come from the GM-curated `memory_state.npcs[]` row;
 * the optional "音色" section appears only when a dialogue TTS model
 * is configured for the session.
 */
import { useEffect, useMemo } from "react";
import type { MediaVoice } from "../../../api/types";
import type { VoiceIntroResponse } from "../../../api/sessions";
import { useI18n } from "../../../i18n";
import { useVoiceIntroController } from "./CharacterPanel";
import { VoiceSelector } from "./VoiceSelector";
import {
  NpcPresencePill,
  useNpcLabels,
  type NpcEntry,
} from "./npcShared";

interface Props {
  npc: NpcEntry;
  onClose: () => void;
  voiceOptions?: MediaVoice[];
  voiceProvider?: string;
  voiceModel?: string;
  onChangeVoice?: (npcKey: string, voice: string) => Promise<void>;
  /** Synthesises (or replays cached) a short in-character voice intro
   *  for this NPC. */
  onPlayVoiceIntro?: (
    npcKey: string,
    opts?: { force?: boolean },
  ) => Promise<VoiceIntroResponse>;
}

export function NpcDetailModal({
  npc,
  onClose,
  voiceOptions,
  voiceProvider,
  voiceModel,
  onChangeVoice,
  onPlayVoiceIntro,
}: Props) {
  const { t } = useI18n();
  const labels = useNpcLabels();
  const initial = (npc.name || npc.key || "?").trim().slice(0, 1);
  const url = (npc.portrait_url || "").trim();
  const voicesAvailable =
    (voiceOptions?.length ?? 0) > 0
    && !!voiceProvider
    && !!voiceModel
    && !!onChangeVoice;
  // Bind the controller to the current npc.key so a panel reuse with a
  // different NPC always calls the new key.
  const npcKey = npc.key;
  const introCall = useMemo(
    () =>
      onPlayVoiceIntro
        ? (opts?: { force?: boolean }) => onPlayVoiceIntro(npcKey, opts)
        : undefined,
    [onPlayVoiceIntro, npcKey],
  );
  const voiceIntro = useVoiceIntroController(introCall);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[80] bg-black/45 backdrop-blur-sm flex items-center justify-center px-4 py-6"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative w-[min(92vw,440px)] max-h-[88vh] overflow-hidden rounded-lg border border-border bg-surface shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="absolute top-2 right-2 w-8 h-8 rounded-md text-text-2 hover:bg-surface-2 hover:text-text flex items-center justify-center"
          aria-label={labels.close}
          onClick={onClose}
        >
          ×
        </button>
        <div className="flex items-center gap-3 px-4 py-4 border-b border-border pr-12">
          <div className="w-16 h-16 rounded-full overflow-hidden bg-surface-2 border border-border shrink-0">
            {url ? (
              <img
                src={url}
                alt={npc.name}
                className={`w-full h-full object-cover object-top ${npc.status === "dead" ? "grayscale opacity-60" : ""}`}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-lg font-semibold text-text-3">
                {initial}
              </div>
            )}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 min-w-0">
              <div className="font-semibold text-text truncate">{npc.name}</div>
              <NpcPresencePill present={npc.isPresent === true} />
            </div>
            {npc.role && (
              <div className="mt-1 text-xs text-text-3 truncate">{npc.role}</div>
            )}
            <div className="mt-1 text-[11px] text-text-3">
              {npc.nameRevealed ? labels.identityKnown : labels.identityUnknown}
            </div>
          </div>
        </div>
        <div className="max-h-[62vh] overflow-y-auto px-4 py-4 space-y-4">
          <section>
            <div className="text-[11px] uppercase tracking-[0.08em] font-semibold text-text-3 mb-1.5">
              {labels.description}
            </div>
            <p className="text-sm leading-relaxed text-text-2 whitespace-pre-wrap">
              {npc.description?.trim() || labels.noDescription}
            </p>
          </section>
          <section>
            <div className="text-[11px] uppercase tracking-[0.08em] font-semibold text-text-3 mb-1.5">
              {labels.knownInfo}
            </div>
            {npc.knownFacts?.length ? (
              <ul className="space-y-1.5">
                {npc.knownFacts.map((fact, idx) => (
                  <li
                    key={`${npc.key}-fact-${idx}`}
                    className="text-sm leading-relaxed text-text-2 flex gap-2"
                  >
                    <span className="mt-[0.55em] h-1 w-1 rounded-full bg-text-3 shrink-0" />
                    <span>{fact}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-text-3 italic">{labels.noKnownInfo}</div>
            )}
          </section>
          {voicesAvailable && (
            <section>
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <div className="text-[11px] uppercase tracking-[0.08em] font-semibold text-text-3">
                    {t("voiceSelectorLabel")}
                  </div>
                  {npc.tts_voice_locked && (
                    <span
                      className="rounded-sm border border-amber-500/30 bg-amber-500/10 px-1.5 py-[1px] text-[9.5px] uppercase tracking-[0.08em] text-amber-700"
                      title={t("voiceLockedHintTitle")}
                    >
                      {t("voiceLockedHint")}
                    </span>
                  )}
                </div>
                {onPlayVoiceIntro && (
                  <button
                    type="button"
                    disabled={voiceIntro.busy}
                    onClick={() => void voiceIntro.play()}
                    className="rounded-md border border-border bg-surface-2 px-2 py-[3px] text-[10px] text-text-2 hover:border-accent hover:text-accent-text disabled:opacity-40 transition-colors"
                  >
                    {voiceIntro.busy
                      ? t("voiceIntroLoading")
                      : voiceIntro.lastCached
                        ? `${t("voiceIntroPlay")} · ${t("voiceIntroCached")}`
                        : t("voiceIntroPlay")}
                  </button>
                )}
              </div>
              <VoiceSelector
                voices={voiceOptions!}
                current={npc.voice || ""}
                provider={voiceProvider!}
                model={voiceModel!}
                onChange={(voice) => onChangeVoice!(npc.key, voice)}
              />
              {(voiceIntro.lastText || voiceIntro.error) && (
                <div className="mt-1.5 text-[10.5px] leading-snug text-text-3">
                  {voiceIntro.error ? (
                    <span className="text-red-500/80">{voiceIntro.error}</span>
                  ) : (
                    <span className="italic">{voiceIntro.lastText}</span>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
