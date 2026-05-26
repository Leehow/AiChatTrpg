import { useState } from "react";
import { useI18n } from "../../i18n";
import { forceInGameTimeAPI } from "../../api/sessions";

interface Props {
  sessionId: string;
  initialDay: number;
  initialClock: string;
  initialDate: string;
  onClose: () => void;
  onSaved: () => void;
}

export function TrpgForceTimeModal({
  sessionId, initialDay, initialClock, initialDate, onClose, onSaved,
}: Props) {
  const { t } = useI18n();
  const [day, setDay] = useState(String(initialDay));
  const [clock, setClock] = useState(initialClock);
  const [date, setDate] = useState(initialDate);
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    setError("");
    const dayNum = Number.parseInt(day.trim(), 10);
    if (!Number.isFinite(dayNum) || dayNum < 1) {
      setError(t("hudErrDayInvalid"));
      return;
    }
    if (!/^\d{1,2}:\d{2}$/.test(clock.trim())) {
      setError(t("hudErrClockInvalid"));
      return;
    }
    if (!acknowledged) {
      setError(t("hudErrNeedAck"));
      return;
    }
    setSaving(true);
    try {
      await forceInGameTimeAPI(sessionId, {
        day: dayNum,
        clock: clock.trim(),
        date: date.trim() || undefined,
      });
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("hudErrSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      role="dialog"
      onClick={onClose}
    >
      <div
        className="bg-bg border border-border rounded-xl shadow-[0_12px_36px_var(--shadow-lg)] p-5 w-[min(92vw,420px)] flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className="text-[20px]">⏱</div>
          <div className="flex-1">
            <div className="text-[15px] font-semibold text-text">
              {t("hudModalTitle")}
            </div>
            <div className="text-[12px] text-text-3 mt-0.5">
              {t("hudModalSub")}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-3 hover:text-text px-1"
            aria-label="close"
          >
            ×
          </button>
        </div>

        <div className="flex flex-col gap-2.5">
          <Field label="Day">
            <input
              type="number"
              min={1}
              value={day}
              onChange={(e) => setDay(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-border text-[13px] text-text"
            />
          </Field>
          <Field label={t("hudFieldClock")}>
            <input
              type="text"
              placeholder="09:00"
              value={clock}
              onChange={(e) => setClock(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-border text-[13px] text-text font-mono"
            />
          </Field>
          <Field label={t("hudFieldDate")} hint={t("hudFieldDateHint")}>
            <input
              type="text"
              value={date}
              placeholder="1975-08-15"
              onChange={(e) => setDate(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-border text-[13px] text-text"
            />
          </Field>
        </div>

        <label className="flex items-start gap-2 text-[12px] text-text-2 cursor-pointer">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-0.5"
          />
          <span>{t("hudAck")}</span>
        </label>

        {error && (
          <div className="text-[12px] text-[#f87171]">{error}</div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-md text-[13px] text-text-2 hover:bg-surface-2 transition-colors"
          >
            {t("hudCancel")}
          </button>
          <button
            type="button"
            disabled={saving || !acknowledged}
            onClick={submit}
            className="px-3 py-1.5 rounded-md text-[13px] bg-accent-dim text-[var(--accent-text)] hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            {saving ? t("hudSaving") : t("hudConfirm")}
          </button>
        </div>
      </div>
    </div>
  );
}


function Field({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-[11.5px] text-text-3 uppercase tracking-[0.06em]">
        {label}
      </div>
      {children}
      {hint && <div className="text-[10.5px] text-text-3">{hint}</div>}
    </div>
  );
}
