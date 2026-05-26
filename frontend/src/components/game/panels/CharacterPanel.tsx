import { useRef, useState } from "react";
import type { MediaVoice } from "../../../api/types";
import type { VoiceIntroResponse } from "../../../api/sessions";
import { useI18n } from "../../../i18n";
import { PanelSection } from "./PanelSection";
import { VoiceSelector } from "./VoiceSelector";
import { CharacterCardRenderer } from "../../character_ui/CharacterCardRenderer";
import type { CharacterUISchema } from "../../character_ui/widgets";

// Same heuristic the ImageNode renderer uses — keep them in sync so the
// inline portrait and any LLM-emitted `image` primitive agree on what
// counts as a real image. Duplicated to avoid pulling the whole widgets
// barrel into this leaf component.
function looksLikeImageUrl(s: string): boolean {
  if (!s) return false;
  if (/^(https?:|data:image\/|blob:)/i.test(s)) return true;
  if (s.startsWith("/")) return true;
  return /\.(png|jpe?g|gif|webp|svg|avif)(\?|#|$)/i.test(s);
}

function pickPortraitUrl(card: Record<string, unknown> | null | undefined): string {
  if (!card || typeof card !== "object") return "";
  const identity = (card as { identity?: unknown }).identity;
  if (!identity || typeof identity !== "object") return "";
  const raw = (identity as { portrait_url?: unknown }).portrait_url;
  if (typeof raw !== "string") return "";
  return looksLikeImageUrl(raw) ? raw : "";
}

export interface CharacterStats {
  name: string;
  className: string;
  level: number;
  hp: { cur: number; max: number };
  mp?: { cur: number; max: number };
  sp?: { cur: number; max: number };
  attrs: Array<{ name: string; val: number; mod: string }>;
}

interface Props {
  character: CharacterStats;
  accent: string;
  /** Raw character JSON straight from the session — needed so the schema
   *  renderer can resolve dot-paths against it. */
  rawCard?: Record<string, unknown> | null;
  /** LLM-compiled UI schema. When present (with rawCard), the schema
   *  renderer takes over and the legacy fallback layout is skipped. */
  schema?: CharacterUISchema | null;
  /** When provided, a single "翻译" / "Translate" action button appears
   *  in the panel header. The target language is the global UI locale
   *  (top-right toggle) — that's the single source of truth for "what
   *  language the player is reading in", so the per-panel toggle was
   *  removed to avoid two competing controls. */
  onTranslate?: () => void;
  translating?: boolean;
  /** Voice picker — empty `voiceOptions` hides the section. The PC's
   *  current voice is read from the raw card (`tts_voice` /
   *  `active_tts_voice`) by GameShell and passed in here. */
  voiceOptions?: MediaVoice[];
  voiceProvider?: string;
  voiceModel?: string;
  currentVoice?: string;
  onChangeVoice?: (voice: string) => Promise<void>;
  /** Generate (or replay cached) a short in-character voice intro for
   *  the PC. The button next to the voice selector calls this and plays
   *  the returned audio_url locally. */
  onPlayVoiceIntro?: (opts?: { force?: boolean }) => Promise<VoiceIntroResponse>;
}

export function CharacterPanel({
  character,
  accent,
  rawCard,
  schema,
  onTranslate,
  translating,
  voiceOptions,
  voiceProvider,
  voiceModel,
  currentVoice,
  onChangeVoice,
  onPlayVoiceIntro,
}: Props) {
  const { t } = useI18n();
  const useSchema = !!(
    schema
    && schema.tree
    && schema.tree.type
    && rawCard
    && typeof rawCard === "object"
  );

  const voiceIntro = useVoiceIntroController(onPlayVoiceIntro);

  const translateProps = onTranslate
    ? {
        actionLabel: translating
          ? t("characterTranslating") || "翻译中…"
          : t("characterTranslate") || "翻译",
        onAction: translating ? undefined : onTranslate,
      }
    : {};

  const showVoice = (voiceOptions?.length ?? 0) > 0
    && !!voiceProvider
    && !!voiceModel
    && !!onChangeVoice;
  const voiceBlock = showVoice ? (
    <div className="mt-2.5 pt-2.5 border-t border-border/60">
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[11px] uppercase tracking-[0.08em] font-semibold text-text-3">
          {t("voiceSelectorLabel")}
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
        current={currentVoice || ""}
        provider={voiceProvider!}
        model={voiceModel!}
        onChange={onChangeVoice!}
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
    </div>
  ) : null;

  if (useSchema) {
    const portraitUrl = pickPortraitUrl(rawCard);
    return (
      <PanelSection title={t("panelCharacter")} icon="⚔" {...translateProps}>
        {/* Absolute-positioned portrait sits in the top-right corner of
         *  the panel body. It never enters the flow, so the LLM-compiled
         *  sheet keeps its full panel width — no row reservation, no
         *  column-like wrap. The first identity rows tuck under it; once
         *  content scrolls past the portrait height, the upper-right
         *  corner is just empty space, never a left-side text column. */}
        <div className="relative">
          {portraitUrl && (
            <img
              src={portraitUrl}
              alt={character.name || "character portrait"}
              className="absolute top-0 right-0 w-20 h-20 object-cover rounded-lg border border-border bg-surface-2 pointer-events-none"
              loading="lazy"
            />
          )}
          <CharacterCardRenderer schema={schema!} card={rawCard!} />
        </div>
        {voiceBlock}
      </PanelSection>
    );
  }

  return (
    <PanelSection title={t("panelCharacter")} icon="⚔" {...translateProps}>
      <div className="w-full h-[72px] bg-surface-2 rounded-lg flex items-center justify-center font-mono text-[10px] text-text-3 border border-dashed border-border-2 mb-2.5">
        character portrait
      </div>
      <div className="text-sm font-semibold mb-0.5">{character.name}</div>
      <div className="text-xs text-text-2 mb-2.5">
        {character.className} · {t("charLevelLabel", { level: character.level })}
      </div>
      <StatBar label="HP" cur={character.hp.cur} max={character.hp.max} color={accent} />
      {character.mp && (
        <StatBar label="MP" cur={character.mp.cur} max={character.mp.max} color="#6BA3BE" />
      )}
      {character.sp && (
        <StatBar label="SP" cur={character.sp.cur} max={character.sp.max} color="#72A87D" />
      )}
      <div className="grid grid-cols-3 gap-1 mt-2.5">
        {character.attrs.map((a) => (
          <div
            key={a.name}
            className="bg-surface-2 rounded-lg px-1 py-1.5 text-center"
          >
            <div className="text-[9px] text-text-3 font-semibold tracking-[0.06em]">
              {a.name}
            </div>
            <div className="text-sm font-semibold mt-0.5">{a.val}</div>
            <div className="text-[10px] text-accent mt-0.5">{a.mod}</div>
          </div>
        ))}
      </div>
      {voiceBlock}
    </PanelSection>
  );
}

// Shared local hook used by both this panel and `NpcDetailModal` via a
// twin implementation — see `voiceIntroController` re-export below. Owns
// a single <audio> element scoped to the panel instance so two open
// previews can't accidentally talk over each other.
export function useVoiceIntroController(
  call?: (opts?: { force?: boolean }) => Promise<VoiceIntroResponse>,
) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastText, setLastText] = useState<string>("");
  const [lastCached, setLastCached] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const play = async (opts?: { force?: boolean }) => {
    if (!call || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await call(opts);
      setLastText(res.text || "");
      setLastCached(res.cached === true);
      if (res.audio_url) {
        if (!audioRef.current) {
          audioRef.current = new Audio();
        }
        audioRef.current.src = res.audio_url;
        await audioRef.current.play().catch((err) => {
          console.warn("[chatrpg] voice intro playback failed:", err);
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("voiceIntroFailed"));
    } finally {
      setBusy(false);
    }
  };
  return { busy, lastText, lastCached, error, play };
}

function StatBar({
  label,
  cur,
  max,
  color,
}: {
  label: string;
  cur: number;
  max: number;
  color: string;
}) {
  const pct = Math.min(100, Math.round((cur / max) * 100));
  return (
    <div className="flex items-center gap-2 mb-1.5">
      <div className="text-[11px] font-medium text-text-3 w-[26px]">{label}</div>
      <div className="flex-1 h-1 bg-surface-2 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <div className="text-[11px] text-text-2 w-[38px] text-right">
        {cur}/{max}
      </div>
    </div>
  );
}
