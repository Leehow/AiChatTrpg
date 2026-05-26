import { useI18n } from "../../../i18n";
import type { ParsedRuleset } from "../../../lib/ruleset/types";
import { PanelSection } from "./PanelSection";

interface Props {
  parsed: ParsedRuleset;
  onEdit: () => void;
}

export function RulesPanel({ parsed, onEdit }: Props) {
  const { t } = useI18n();
  const coreLen = (parsed.core.rules_markdown || "").trim().length;
  const companionLen = (parsed.core.companion?.content || "").trim().length;
  // The agent path produces template_json (a JSON skeleton); the legacy
  // PDF-upload path produces template_content (a flat markdown string).
  // Either signal counts as "sheet present".
  const sheet = parsed.character_sheet;
  const hasSheet =
    !!(sheet?.template_content) ||
    (sheet?.template_json && Object.keys(sheet.template_json).length > 0) ||
    !!(sheet?.guide_content && sheet.guide_content.trim());
  const rows: Array<{ key: string; name: string; val: string }> = [
    {
      key: "world_mode",
      name: t("ruleRowWorldMode"),
      val: parsed.meta.world_mode || "—",
    },
    {
      key: "core_rules",
      name: t("ruleRowCoreRules"),
      val: coreLen > 0 ? t("ruleValChars", { n: coreLen }) : t("ruleValEmpty"),
    },
    {
      key: "companion",
      name: t("ruleRowCompanion"),
      val:
        companionLen > 0
          ? t("ruleValChars", { n: companionLen })
          : t("ruleValEmpty"),
    },
    {
      key: "scenarios",
      name: t("ruleRowScenarios"),
      val: String(parsed.scenarios.length),
    },
    {
      key: "parameters",
      name: t("ruleRowParameters"),
      val: String(parsed.parameters.length),
    },
    {
      key: "character_sheet",
      name: t("ruleRowCharSheet"),
      val: hasSheet ? t("ruleValYes") : t("ruleValNo"),
    },
    {
      key: "dice_engine",
      name: t("ruleRowDiceEngine"),
      val: parsed.dice_ir ? t("ruleValCompiled") : t("ruleValPending"),
    },
  ];

  return (
    <PanelSection
      title={t("panelRules")}
      icon="⬡"
      onAction={onEdit}
      actionLabel={t("panelRulesAction")}
    >
      <div className="flex flex-col gap-1.5">
        {rows.map((r) => (
          <div
            key={r.key}
            className="flex items-center gap-2 px-2.5 py-1.5 bg-surface-2 rounded-lg text-[12px]"
          >
            <span className="flex-1 font-medium">{r.name}</span>
            <span className="text-accent font-semibold">{r.val}</span>
          </div>
        ))}
      </div>
    </PanelSection>
  );
}
