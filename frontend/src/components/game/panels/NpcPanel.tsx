/**
 * Roster of NPCs the GM has established for this session — sourced from
 * `session.memory_state.npcs[]`. Renders as a compact avatar grid so the
 * player can match names to faces during play. The panel intentionally avoids
 * exposing mechanical HP. It only shows a coarse player-facing condition, and
 * the detail modal reveals public description + PC-known information.
 */

import { useState } from "react";
import type { MediaVoice } from "../../../api/types";
import type { BondNpcEnrichResponse, VoiceIntroResponse } from "../../../api/sessions";
import { useI18n } from "../../../i18n";
import { NpcDetailModal } from "./NpcDetailModal";
import { PanelSection } from "./PanelSection";
import {
  NpcPresencePill,
  useNpcLabels,
  type NpcEntry,
} from "./npcShared";

export type { NpcEntry, NpcStatus } from "./npcShared";

interface Props {
  npcs: NpcEntry[];
  /** Available voices from the configured dialogue TTS model. Empty
   *  array hides the voice section in the detail modal. */
  voiceOptions?: MediaVoice[];
  voiceProvider?: string;
  voiceModel?: string;
  /** Persists a voice change for the given NPC. The caller refetches
   *  the session detail so the modal sees the updated value next open. */
  onChangeNpcVoice?: (npcKey: string, voice: string) => Promise<void>;
  /** Forwarded to the detail modal so the NPC voice intro button can
   *  call the session-scoped API without the modal knowing sessionId. */
  onPlayNpcVoiceIntro?: (
    npcKey: string,
    opts?: { force?: boolean },
  ) => Promise<VoiceIntroResponse>;
  /** Triggers an NPC voice rematch. Skipped (locked) NPCs are preserved
   *  by the server; we surface the rematched/skipped counts as a small
   *  status badge after each click. */
  onRematchNpcVoices?: (opts?: { force?: boolean }) => Promise<{
    rematched: number;
    skipped_locked: number;
  }>;
  /** Runs bond-NPC enrichment for the whole session. The shell only
   *  provides this when at least one bond NPC is still missing rich
   *  profile fields, so the panel renders the action solely based on
   *  whether the prop is set. */
  onEnrichBondNpcs?: () => Promise<BondNpcEnrichResponse>;
}

export function NpcPanel({
  npcs,
  voiceOptions,
  voiceProvider,
  voiceModel,
  onChangeNpcVoice,
  onPlayNpcVoiceIntro,
  onRematchNpcVoices,
  onEnrichBondNpcs,
}: Props) {
  const { t } = useI18n();
  const labels = useNpcLabels();
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [rematchBusy, setRematchBusy] = useState(false);
  const [rematchResult, setRematchResult] = useState<{
    rematched: number;
    skipped: number;
  } | null>(null);
  const [rematchError, setRematchError] = useState<string | null>(null);
  const [bondBusy, setBondBusy] = useState(false);
  const [bondResult, setBondResult] = useState<{
    enriched: number;
    eligible: number;
    skipped: number;
    errorCount: number;
  } | null>(null);
  const [bondError, setBondError] = useState<string | null>(null);
  // Resolve the current entry from `npcs` on every render — after the
  // user picks a new voice, the parent refetches the session and pushes
  // a fresh `npcs` array, so this lookup makes the modal mirror the
  // updated value without forcing a reopen.
  const previewNpc = previewKey
    ? npcs.find((n) => n.key === previewKey) ?? null
    : null;
  const handleRematch = async () => {
    if (!onRematchNpcVoices || rematchBusy) return;
    setRematchBusy(true);
    setRematchError(null);
    try {
      const res = await onRematchNpcVoices();
      setRematchResult({
        rematched: res.rematched,
        skipped: res.skipped_locked,
      });
    } catch (err) {
      setRematchError(err instanceof Error ? err.message : t("voiceRematchFailed"));
    } finally {
      setRematchBusy(false);
    }
  };
  const handleBondEnrich = async () => {
    if (!onEnrichBondNpcs || bondBusy) return;
    setBondBusy(true);
    setBondError(null);
    try {
      const res = await onEnrichBondNpcs();
      setBondResult({
        enriched: res.enriched,
        eligible: res.eligible,
        skipped: res.skipped,
        errorCount: res.errors.length,
      });
      if (res.errors.length > 0) {
        setBondError(res.errors[0]);
      }
    } catch (err) {
      setBondError(err instanceof Error ? err.message : t("bondEnrichFailed"));
    } finally {
      setBondBusy(false);
    }
  };
  const rematchAction = onRematchNpcVoices ? (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        void handleRematch();
      }}
      disabled={rematchBusy}
      className="rounded-md border border-border bg-surface-2 px-2 py-[3px] text-[10px] text-text-2 hover:border-accent hover:text-accent-text disabled:opacity-40 transition-colors"
    >
      {rematchBusy ? t("voiceRematchRunning") : t("voiceRematchNpc")}
    </button>
  ) : undefined;
  const bondAction = onEnrichBondNpcs ? (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        void handleBondEnrich();
      }}
      disabled={bondBusy}
      title={t("bondEnrichTitle")}
      className="rounded-md border border-border bg-surface-2 px-2 py-[3px] text-[10px] text-text-2 hover:border-accent hover:text-accent-text disabled:opacity-40 transition-colors"
    >
      {bondBusy ? t("bondEnrichRunning") : t("bondEnrichAction")}
    </button>
  ) : undefined;
  const headerActions = (rematchAction || bondAction) ? (
    <div className="flex items-center gap-1">
      {bondAction}
      {rematchAction}
    </div>
  ) : undefined;
  return (
    <>
      <PanelSection title={labels.title} icon="👥" actions={headerActions}>
        {npcs.length === 0 ? (
          <div className="text-[11px] text-text-3 italic py-1">
            {labels.empty}
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-x-1.5 gap-y-2">
            {npcs.map((npc) => (
              <NpcTile
                key={npc.key}
                npc={npc}
                onPreview={() => setPreviewKey(npc.key)}
              />
            ))}
          </div>
        )}
        {(rematchResult || rematchError) && (
          <div className="mt-2 text-[10.5px] text-text-3">
            {rematchError ? (
              <span className="text-red-500/80">{rematchError}</span>
            ) : (
              <span className="italic">
                {t("voiceRematchResult", {
                  rematched: String(rematchResult?.rematched ?? 0),
                  locked: String(rematchResult?.skipped ?? 0),
                })}
              </span>
            )}
          </div>
        )}
        {(bondResult || bondError) && (
          <div className="mt-1 text-[10.5px] text-text-3">
            {bondError ? (
              <span className="text-red-500/80">{bondError}</span>
            ) : bondResult && bondResult.eligible === 0 ? (
              <span className="italic">{t("bondEnrichNoneEligible")}</span>
            ) : bondResult ? (
              <span className="italic">
                {t("bondEnrichResult", {
                  enriched: String(bondResult.enriched),
                  skipped: String(bondResult.skipped),
                })}
              </span>
            ) : null}
          </div>
        )}
      </PanelSection>
      {previewNpc && (
        <NpcDetailModal
          npc={previewNpc}
          onClose={() => setPreviewKey(null)}
          voiceOptions={voiceOptions}
          voiceProvider={voiceProvider}
          voiceModel={voiceModel}
          onChangeVoice={onChangeNpcVoice}
          onPlayVoiceIntro={onPlayNpcVoiceIntro}
        />
      )}
    </>
  );
}

function NpcTile({
  npc,
  onPreview,
}: {
  npc: NpcEntry;
  onPreview: () => void;
}) {
  const initial = (npc.name || npc.key || "?").trim().slice(0, 1);
  const url = (npc.portrait_url || "").trim();
  const status = npc.status || "unknown";
  const dead = status === "dead";
  const wounded = status === "injured";
  const present = npc.isPresent === true;
  const labels = useNpcLabels();
  const tooltip = [
    npc.role ? `${npc.name} — ${npc.role}` : npc.name,
    labels.status[status],
    labels.presence[present ? "present" : "absent"],
  ].filter(Boolean).join("\n");
  return (
    <button
      type="button"
      className="flex flex-col items-center min-w-0 text-left group focus:outline-none"
      title={tooltip}
      onClick={onPreview}
    >
      <div className={[
        "w-12 h-12 rounded-full overflow-hidden bg-surface-2 border shrink-0 relative transition",
        "group-hover:ring-2 group-focus-visible:ring-2",
        dead
          ? "border-red-300 ring-red-300/35 group-hover:ring-red-300/45 group-focus-visible:ring-red-300/45"
          : wounded
            ? "border-amber-300 ring-amber-300/35 group-hover:ring-amber-300/45 group-focus-visible:ring-amber-300/45"
            : "border-border ring-primary/35 group-hover:ring-primary/35 group-focus-visible:ring-primary/35",
      ].join(" ")}
      >
        {url ? (
          <img
            src={url}
            alt={npc.name}
            className={`w-full h-full object-cover object-top ${dead ? "grayscale opacity-60" : ""}`}
            loading="lazy"
          />
        ) : (
          <div className={`w-full h-full flex items-center justify-center text-[12px] font-semibold text-text-3 ${dead ? "opacity-60" : ""}`}>
            {initial}
          </div>
        )}
        {dead && (
          <span
            className="absolute right-0 bottom-0 w-4 h-4 rounded-full border-2 border-surface bg-surface-2 text-red-600 flex items-center justify-center"
            aria-hidden="true"
          >
            <SkullIcon />
          </span>
        )}
      </div>
      <div
        className="text-[10px] text-text-2 mt-1 leading-tight w-full text-center truncate"
      >
        {npc.name}
      </div>
      <NpcPresencePill present={present} />
    </button>
  );
}

function SkullIcon() {
  // Single-path skull glyph sized to fit a 16px badge. `currentColor` lets
  // the parent ``span`` recolor it (red for dead) without per-icon props.
  return (
    <svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden="true">
      <path d="M8 1.5C5 1.5 2.6 3.6 2.6 6.4c0 1.5.7 2.8 1.7 3.6v1.4c0 .5.4.9.9.9h.5v1.2c0 .3.2.5.5.5s.5-.2.5-.5v-1.2h.7v1.2c0 .3.2.5.5.5s.5-.2.5-.5v-1.2h.7v1.2c0 .3.2.5.5.5s.5-.2.5-.5v-1.2h.5c.5 0 .9-.4.9-.9V10c1-.8 1.7-2.1 1.7-3.6 0-2.8-2.4-4.9-5.4-4.9zM5.6 7.6c-.7 0-1.2-.6-1.2-1.3s.6-1.3 1.2-1.3 1.2.6 1.2 1.3-.5 1.3-1.2 1.3zm4.8 0c-.7 0-1.2-.6-1.2-1.3s.6-1.3 1.2-1.3 1.2.6 1.2 1.3-.5 1.3-1.2 1.3z" />
    </svg>
  );
}
