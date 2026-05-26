// EditorDesignSidebar — left-side design surface for the rule editor.
// Hosts the agent tab switcher (rule-design / dice-design), the
// RuleDesignPanel status chips + compile button, and the existing
// EditorLeftPreview rules summary in a single column. The center column
// is freed up for chat content.

import type { DraftDetailDTO } from "../../api/ruleset-drafts";
import { useI18n } from "../../i18n";
import type { ParsedRuleset } from "../../lib/ruleset/types";
import { EditorLeftPreview } from "./EditorLeftPreview";
import { RuleDesignPanel } from "./RuleDesignPanel";

export type TabId = "main" | "dice";

interface Props {
  draft: DraftDetailDTO;
  parsed: ParsedRuleset;
  draftTitle: string;
  badge: "blank" | "fork" | "in-place";
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  compiling: boolean;
  onCompile: () => void;
}

export function EditorDesignSidebar({
  draft,
  parsed,
  draftTitle,
  badge,
  activeTab,
  onTabChange,
  compiling,
  onCompile,
}: Props) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-y-auto bg-surface">
      <div className="shrink-0 h-12 flex items-center gap-1.5 px-3 border-b border-border bg-surface">
        <TabButton
          active={activeTab === "main"}
          label={t("draftAgentTabMain")}
          onClick={() => onTabChange("main")}
        />
        <TabButton
          active={activeTab === "dice"}
          label={t("draftAgentTabDice")}
          onClick={() => onTabChange("dice")}
        />
        <div className="flex-1" />
        <span className="text-[10px] uppercase tracking-[0.05em] px-1.5 py-0.5 rounded bg-accent-dim text-[var(--accent-text)]">
          {t("draftAgentLiveTag")}
        </span>
      </div>
      <RuleDesignPanel
        draft={draft}
        compiling={compiling}
        onCompile={onCompile}
      />
      <EditorLeftPreview
        parsed={parsed}
        draftTitle={draftTitle}
        badge={badge}
        embedded
      />
    </div>
  );
}

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "h-8 px-3 rounded-lg text-[12px] font-medium transition-colors",
        active
          ? "bg-accent text-white"
          : "text-text-2 hover:bg-surface-2",
      ].join(" ")}
    >
      {label}
    </button>
  );
}
