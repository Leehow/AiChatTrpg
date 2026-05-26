import { useState } from "react";
import { useI18n } from "../../i18n";
import type { ParsedRuleset } from "../../lib/ruleset/types";
import { MarkdownDoc } from "./MarkdownDoc";

interface Props {
  core: ParsedRuleset["core"];
}

type ViewSelection = "rules" | "companion";

export function CoreRulesTab({ core }: Props) {
  const { t } = useI18n();
  const [view, setView] = useState<ViewSelection>("rules");

  const hasCompanion = Boolean(core.companion?.content);

  return (
    <div className="max-w-[860px] mx-auto px-6 py-6">
      {hasCompanion && (
        <div className="flex gap-1.5 mb-5">
          <Selector
            active={view === "rules"}
            onClick={() => setView("rules")}
            label={t("coreRulesMain")}
          />
          <Selector
            active={view === "companion"}
            onClick={() => setView("companion")}
            label={core.companion?.filename || t("coreRulesCompanion")}
          />
        </div>
      )}

      <MarkdownDoc
        text={
          view === "companion" && core.companion
            ? core.companion.content
            : core.rules_markdown
        }
      />
    </div>
  );
}

function Selector({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "px-3.5 py-1.5 rounded-lg text-[12px] font-medium transition-colors",
        active
          ? "bg-accent-dim text-[var(--accent-text)] border border-accent"
          : "bg-surface text-text-2 border border-border hover:border-border-2",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

