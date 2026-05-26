import { useState } from "react";
import { useI18n } from "../../i18n";
import type { V6CharacterSheet } from "../../lib/ruleset/types";

interface Props {
  sheet?: V6CharacterSheet;
}

type View = "template" | "guide";

export function CharacterSheetTab({ sheet }: Props) {
  const { t } = useI18n();
  const [view, setView] = useState<View>("template");

  if (!sheet || (!sheet.template_content && !sheet.guide_content)) {
    return (
      <div className="max-w-[860px] mx-auto px-6 py-12 text-center text-text-3 text-sm">
        {t("characterSheetEmpty")}
      </div>
    );
  }

  return (
    <div className="max-w-[860px] mx-auto px-6 py-6">
      <div className="flex gap-1.5 mb-5">
        <button
          onClick={() => setView("template")}
          className={[
            "px-3.5 py-1.5 rounded-lg text-[12px] font-medium border transition-colors",
            view === "template"
              ? "bg-accent-dim text-[var(--accent-text)] border-accent"
              : "bg-surface text-text-2 border-border hover:border-border-2",
          ].join(" ")}
        >
          {t("characterSheetTemplate")}
        </button>
        <button
          onClick={() => setView("guide")}
          className={[
            "px-3.5 py-1.5 rounded-lg text-[12px] font-medium border transition-colors",
            view === "guide"
              ? "bg-accent-dim text-[var(--accent-text)] border-accent"
              : "bg-surface text-text-2 border-border hover:border-border-2",
          ].join(" ")}
        >
          {t("characterSheetGuide")}
        </button>
      </div>

      <pre className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-text-2 font-sans bg-surface border border-border rounded-xl p-4">
        {(view === "template"
          ? sheet.template_content
          : sheet.guide_content) || ""}
      </pre>
    </div>
  );
}
