import { useI18n } from "../../i18n";

interface StepHeaderProps {
  step: number;
}

export function StepHeader({ step }: StepHeaderProps) {
  const { t } = useI18n();
  const steps = [t("setupStepRule"), t("setupStepModule"), t("setupStepChar")];
  return (
    <div className="flex items-center gap-0 mx-auto">
      {steps.map((label, i) => {
        const state = step === i ? "active" : step > i ? "done" : "pending";
        return (
          <div key={i} className="flex items-center">
            {i > 0 && <div className="w-4 h-px bg-border shrink-0" />}
            <div
              className={[
                "flex items-center gap-1.5 text-xs font-medium px-2",
                state === "active"
                  ? "text-text"
                  : state === "done"
                  ? "text-accent"
                  : "text-text-3",
              ].join(" ")}
            >
              <div
                className={[
                  "w-[18px] h-[18px] rounded-full border-[1.5px] flex items-center justify-center",
                  "text-[10px] font-semibold shrink-0",
                  state === "active"
                    ? "border-accent bg-accent-dim text-accent"
                    : state === "done"
                    ? "border-accent bg-accent text-white"
                    : "border-border-2 bg-surface-2",
                ].join(" ")}
              >
                {state === "done" ? "✓" : i + 1}
              </div>
              <span className="hidden sm:inline">{label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
