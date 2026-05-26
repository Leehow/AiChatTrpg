import { useState } from "react";
import { useI18n } from "../../i18n";
import type { ParsedRuleset } from "../../lib/ruleset/types";
import { CoreRulesTab } from "./CoreRulesTab";
import { ScenarioRulesTab } from "./ScenarioRulesTab";
import { ParameterFamiliesTab } from "./ParameterFamiliesTab";
import { DiceEngineTab } from "./DiceEngineTab";
import { CharacterSheetTab } from "./CharacterSheetTab";
import { CharacterUITab } from "./CharacterUITab";
import type { RulesetDetailDTO } from "../../lib/ruleset/api";

type TabId =
  | "core"
  | "scenarios"
  | "parameters"
  | "character"
  | "character_ui"
  | "dice";

interface RulesetViewProps {
  parsed: ParsedRuleset;
  rulesetId?: string;
  onClose: () => void;
  onDiceIRChanged?: (artifact: ParsedRuleset["dice_ir"]) => void;
  onRulesetChanged?: (detail: RulesetDetailDTO) => void;
  onCharacterUIChanged?: (artifact: ParsedRuleset["character_ui"]) => void;
}

export function RulesetView({
  parsed,
  rulesetId,
  onClose,
  onDiceIRChanged,
  onRulesetChanged,
  onCharacterUIChanged,
}: RulesetViewProps) {
  const { t } = useI18n();
  const [tab, setTab] = useState<TabId>("core");

  const tabs: Array<{ id: TabId; label: string; count?: number }> = [
    { id: "core", label: t("rulesetTabCore") },
    {
      id: "scenarios",
      label: t("rulesetTabScenarios"),
      count: parsed.scenarios.length,
    },
    {
      id: "parameters",
      label: t("rulesetTabParameters"),
      count: parsed.parameters.length,
    },
    {
      id: "character",
      label: t("rulesetTabCharacter"),
      count: parsed.character_sheet?.template_content ? 1 : 0,
    },
    { id: "character_ui", label: "Character UI" },
    { id: "dice", label: t("rulesetTabDice") },
  ];

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-bg anim-fade-in">
      <div className="h-13 flex items-center px-4 border-b border-border bg-surface gap-3 shrink-0">
        <button
          onClick={onClose}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-text-2 hover:bg-surface-2 transition-colors"
          title={t("rulesetBack")}
        >
          ←
        </button>
        <div>
          <div className="text-sm font-semibold leading-tight">
            {parsed.meta.book_title}
          </div>
          <div className="text-[11px] text-text-3 leading-tight">
            {parsed.meta.world_mode}
            {parsed.meta.parsed_at &&
              ` · ${new Date(parsed.meta.parsed_at).toLocaleDateString()}`}
          </div>
        </div>
      </div>

      <div className="flex border-b border-border bg-surface px-2 shrink-0 overflow-x-auto">
        {tabs.map((entry) => (
          <button
            key={entry.id}
            onClick={() => setTab(entry.id)}
            className={[
              "px-4 py-3 text-[13px] font-medium relative whitespace-nowrap transition-colors",
              tab === entry.id
                ? "text-accent"
                : "text-text-2 hover:text-text",
            ].join(" ")}
          >
            {entry.label}
            {entry.count != null && (
              <span className="ml-1.5 text-[11px] text-text-3">
                {entry.count}
              </span>
            )}
            {tab === entry.id && (
              <span className="absolute bottom-0 left-3 right-3 h-0.5 bg-accent rounded-t" />
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "core" && <CoreRulesTab core={parsed.core} />}
        {tab === "scenarios" && (
          <ScenarioRulesTab scenarios={parsed.scenarios} />
        )}
        {tab === "parameters" && (
          <ParameterFamiliesTab families={parsed.parameters} />
        )}
        {tab === "character" && (
          <CharacterSheetTab sheet={parsed.character_sheet} />
        )}
        {tab === "character_ui" && (
          <CharacterUITab
            artifact={parsed.character_ui}
            rulesetId={rulesetId}
            onCompiled={onCharacterUIChanged}
          />
        )}
        {tab === "dice" && (
          <DiceEngineTab
            artifact={parsed.dice_ir}
            checkSpec={parsed.check_spec}
            rulesetId={rulesetId}
            onCompiled={onDiceIRChanged}
            onApplied={onRulesetChanged}
          />
        )}
      </div>
    </div>
  );
}
