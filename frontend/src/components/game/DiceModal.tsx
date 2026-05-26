import { useState } from "react";
import { useI18n } from "../../i18n";
import { DiceIcon, type DiceType } from "../dice/DiceIcons";

interface Props {
  onClose: () => void;
  /** Called with the chosen dice type once the user confirms; modal is closed by the caller. */
  onPick: (diceType: DiceType) => void;
}

const DICE_TYPES: DiceType[] = ["d4", "d6", "d8", "d10", "d12", "d20", "d100", "d2"];

export function DiceModal({ onClose, onPick }: Props) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<DiceType>("d20");

  return (
    <div
      className="fixed inset-0 bg-black/45 z-[300] flex items-center justify-center p-5 anim-fade-in"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-surface border border-border rounded-3xl p-7 w-[360px] max-h-[90vh] overflow-y-auto shadow-[0_24px_64px_var(--shadow-md)]">
        <div className="text-base font-semibold mb-1">{t("diceModalTitle")}</div>
        <div className="text-[13px] text-text-2 mb-5">{t("diceModalSub")}</div>
        <div className="grid grid-cols-4 gap-2 mb-5">
          {DICE_TYPES.map((d) => (
            <button
              key={d}
              onClick={() => setSelected(d)}
              className={[
                "aspect-square rounded-xl border flex flex-col items-center justify-center gap-1 transition-colors",
                selected === d
                  ? "bg-accent text-white border-accent"
                  : "bg-surface-2 text-text-2 border-border hover:bg-accent hover:text-white hover:border-accent",
              ].join(" ")}
            >
              <DiceIcon diceType={d} size={28} />
              <span className="text-[11px] font-semibold">{d}</span>
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 px-3 py-2.5 rounded-xl text-sm font-medium bg-surface-2 text-text-2 border border-border hover:opacity-85 transition"
          >
            {t("diceModalCancel")}
          </button>
          <button
            onClick={() => onPick(selected)}
            className="flex-1 px-3 py-2.5 rounded-xl text-sm font-medium bg-accent text-white hover:opacity-85 transition"
          >
            {t("diceModalRoll")}
          </button>
        </div>
      </div>
    </div>
  );
}
