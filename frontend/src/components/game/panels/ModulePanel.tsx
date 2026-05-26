import { useI18n } from "../../../i18n";
import { PanelSection } from "./PanelSection";

export interface ModuleState {
  tag: string;
  title: string;
  scene: string;
  desc: string;
  progress: boolean[];
}

export function ModulePanel({ mod }: { mod: ModuleState }) {
  const { t } = useI18n();
  // Sessions whose module_state was seeded by older code paths can be
  // missing the `progress` array. Defensive default avoids a hard crash
  // that takes the entire chat surface down.
  const progress = Array.isArray(mod.progress) ? mod.progress : [];
  const done = progress.filter(Boolean).length;
  return (
    <PanelSection title={t("panelModule")} icon="📖">
      <div className="inline-flex items-center gap-1 text-[11px] bg-accent-dim text-[var(--accent-text)] rounded-md px-2 py-0.5 mb-2 font-medium">
        ⬡ {mod.tag}
      </div>
      <div className="text-[13px] font-semibold mb-1">{mod.title}</div>
      <div className="text-[11px] text-accent mb-1.5 font-medium">{mod.scene}</div>
      <div className="text-[12px] text-text-2 leading-relaxed">{mod.desc}</div>
      <div className="mt-2.5 flex gap-1">
        {progress.map((d, i) => (
          <div
            key={i}
            className={[
              "flex-1 h-[3px] rounded-full transition-colors duration-300",
              d ? "bg-accent" : "bg-border",
            ].join(" ")}
          />
        ))}
      </div>
      <div className="text-[10px] text-text-3 mt-1">
        {t("moduleProgress", { done, total: progress.length })}
      </div>
    </PanelSection>
  );
}
