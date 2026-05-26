import { useState } from "react";
import { useI18n } from "../../i18n";
import { advanceInGameTimeAPI } from "../../api/sessions";

interface Props {
  sessionId: string;
  /** Hide the controls when the HUD is rendering a historical snapshot —
   *  advancing the live clock while reading a past scene would be confusing. */
  isHistorical: boolean;
  /** Triggered after a successful advance so the parent can refetch the
   *  session detail and re-derive `module_state`. */
  onChanged?: () => void;
}

// Compact +10m / +1h / +… row that sits inside the floating scene HUD. Owns
// its own request/error state so the HUD doesn't have to. Hidden entirely
// when `isHistorical` is true.
export function TrpgSceneHudAdvanceControls({
  sessionId, isHistorical, onChanged,
}: Props) {
  const { t } = useI18n();
  const [advancing, setAdvancing] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [customMin, setCustomMin] = useState("");
  const [error, setError] = useState("");

  if (isHistorical) return null;

  async function runAdvance(minutes: number) {
    if (!minutes || !Number.isFinite(minutes)) return;
    setError("");
    setAdvancing(true);
    try {
      await advanceInGameTimeAPI(sessionId, { minutes });
      onChanged?.();
      setCustomOpen(false);
      setCustomMin("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("hudAdvanceFailed"));
    } finally {
      setAdvancing(false);
    }
  }

  function applyCustom() {
    const n = Number.parseInt(customMin.trim(), 10);
    if (!Number.isFinite(n) || n <= 0) {
      setError(t("hudAdvanceInvalid"));
      return;
    }
    void runAdvance(n);
  }

  return (
    <>
      <div data-no-drag="true" onPointerDown={(e) => e.stopPropagation()}
        className="flex items-center gap-1 mt-[1px] text-[10.5px] flex-wrap">
        {customOpen ? (
          <>
            <input type="number" inputMode="numeric" min={1} value={customMin}
              onChange={(e) => setCustomMin(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); applyCustom(); }
                if (e.key === "Escape") { e.preventDefault(); setCustomOpen(false); }
              }}
              placeholder={t("hudAdvanceCustomPlaceholder")}
              className="w-[64px] px-1.5 py-[1px] rounded bg-surface-2 border border-border text-[10.5px] text-text"
              autoFocus />
            <HudActionBtn label={advancing ? t("hudSaving") : t("hudAdvanceApply")}
              disabled={advancing} onClick={applyCustom} />
            <HudActionBtn label={t("hudCancel")} disabled={advancing}
              onClick={() => { setCustomOpen(false); setCustomMin(""); setError(""); }} />
          </>
        ) : (
          <>
            <HudActionBtn label={t("hudAdvance10m")} disabled={advancing} onClick={() => runAdvance(10)} />
            <HudActionBtn label={t("hudAdvance1h")} disabled={advancing} onClick={() => runAdvance(60)} />
            <HudActionBtn label={t("hudAdvanceCustom")} disabled={advancing}
              onClick={() => { setError(""); setCustomOpen(true); }} />
          </>
        )}
      </div>

      {error && (
        <div data-no-drag="true" className="text-[10px] text-[#f87171] max-w-full whitespace-normal break-words">
          {error}
        </div>
      )}
    </>
  );
}


function HudActionBtn({
  label, disabled, onClick,
}: { label: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button type="button" data-no-drag="true" disabled={disabled}
      onPointerDown={(e) => e.stopPropagation()} onClick={onClick}
      className="chatrpg-scene-hud-btn px-1.5 py-[1px] rounded text-[10.5px] leading-none border border-border bg-surface-2 text-text-2 hover:text-text hover:bg-bg disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
      {label}
    </button>
  );
}
