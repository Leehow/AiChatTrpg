import { useI18n } from "../../../i18n";
import { PanelSection } from "./PanelSection";

export interface MemoryItem {
  text: string;
  importance: "high" | "med" | "low";
}

const DOT_BG: Record<MemoryItem["importance"], string> = {
  high: "bg-accent",
  med: "bg-text-3",
  low: "bg-border-2",
};

export function MemoryPanel({ memories }: { memories: MemoryItem[] }) {
  const { t } = useI18n();
  return (
    <PanelSection title={t("panelMemory")} icon="◈" defaultOpen={false}>
      {memories.length === 0 ? (
        <div className="text-[12px] text-text-3 py-2">{t("memoryEmpty")}</div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {memories.map((m, i) => (
            <div
              key={i}
              className="flex gap-2 px-2.5 py-1.5 bg-surface-2 rounded-lg text-[12px] leading-snug text-text-2"
            >
              <div
                className={[
                  "w-1.5 h-1.5 rounded-full shrink-0 mt-1",
                  DOT_BG[m.importance],
                ].join(" ")}
              />
              <div>{m.text}</div>
            </div>
          ))}
        </div>
      )}
    </PanelSection>
  );
}
