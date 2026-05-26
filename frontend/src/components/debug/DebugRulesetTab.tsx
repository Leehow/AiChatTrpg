import { useI18n } from "../../i18n";
import type { ParsedRuleset } from "../../lib/ruleset/types";
import { ExpandableRow, Pre, Row, Section } from "./primitives";

// Read-only inspector for whatever ruleset is in focus. Each section can
// be collapsed; long blobs (markdown, JSON) expand inline so the panel
// stays scannable but lets you drill into the raw data without leaving
// the screen.
export function DebugRulesetTab({ parsed }: { parsed: ParsedRuleset | null }) {
  const { t } = useI18n();
  if (!parsed) {
    return (
      <div className="text-[12px] text-text-3 leading-relaxed py-6 text-center">
        {t("debugPanelEmpty")}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Section title={t("debugSecMeta")}>
        <Row label="book_id" value={parsed.meta.book_id || "—"} mono />
        <Row label="book_title" value={parsed.meta.book_title} />
        <Row label="world_mode" value={parsed.meta.world_mode} />
        {parsed.meta.output_language && (
          <Row label="lang" value={parsed.meta.output_language} />
        )}
        {parsed.meta.model && (
          <Row label="model" value={parsed.meta.model} mono />
        )}
        {parsed.meta.parsed_at && (
          <Row
            label="parsed_at"
            value={new Date(parsed.meta.parsed_at).toLocaleString()}
          />
        )}
        <ExpandableRow label="raw" value="json">
          <Pre json={parsed.raw} clip={6000} />
        </ExpandableRow>
      </Section>

      <Section title={t("debugSecCore")}>
        <ExpandableRow
          label="rules"
          value={`${parsed.core.rules_markdown.length.toLocaleString()} chars`}
        >
          <Pre text={parsed.core.rules_markdown} clip={20000} />
        </ExpandableRow>
        {parsed.core.companion ? (
          <ExpandableRow
            label="companion"
            value={`${parsed.core.companion.content.length.toLocaleString()} chars`}
          >
            <Pre text={parsed.core.companion.content} clip={20000} />
          </ExpandableRow>
        ) : (
          <Row label="companion" value="—" />
        )}
      </Section>

      <Section title={`${t("debugSecScenarios")} (${parsed.scenarios.length})`}>
        {parsed.scenarios.length === 0 ? (
          <div className="text-[11px] text-text-3 italic">—</div>
        ) : (
          parsed.scenarios.map((pkg) => (
            <ExpandableRow
              key={pkg.package_id}
              label={pkg.package_id}
              value={`${(pkg.content?.length ?? 0).toLocaleString()}`}
              mono
            >
              <Pre text={pkg.content || ""} clip={20000} />
            </ExpandableRow>
          ))
        )}
      </Section>

      <Section title={`${t("debugSecParameters")} (${parsed.parameters.length})`}>
        {parsed.parameters.length === 0 ? (
          <div className="text-[11px] text-text-3 italic">—</div>
        ) : (
          parsed.parameters.map((fam) => (
            <ExpandableRow
              key={fam.family_id}
              label={fam.family_id}
              value={`${fam.json?.entries?.length ?? 0} entries`}
            >
              <Pre json={fam.json?.entries ?? []} clip={20000} />
            </ExpandableRow>
          ))
        )}
      </Section>

      <Section title={t("debugSecCharSheet")}>
        {parsed.character_sheet?.template_content ? (
          <ExpandableRow
            label="template"
            value={`${parsed.character_sheet.template_content.length.toLocaleString()} chars`}
          >
            <Pre text={parsed.character_sheet.template_content} clip={20000} />
          </ExpandableRow>
        ) : parsed.character_sheet?.template_json &&
          Object.keys(parsed.character_sheet.template_json).length > 0 ? (
          <ExpandableRow
            label="template"
            value={`${Object.keys(parsed.character_sheet.template_json).length} keys`}
          >
            <Pre
              json={parsed.character_sheet.template_json}
              clip={20000}
            />
          </ExpandableRow>
        ) : (
          <Row label="template" value="—" />
        )}
        {parsed.character_sheet?.guide_content ? (
          <ExpandableRow
            label="guide"
            value={`${parsed.character_sheet.guide_content.length.toLocaleString()} chars`}
          >
            <Pre text={parsed.character_sheet.guide_content} clip={20000} />
          </ExpandableRow>
        ) : (
          <Row label="guide" value="—" />
        )}
      </Section>

      <DiceIRSection parsed={parsed} />
      <HouseRulesSection parsed={parsed} />
    </div>
  );
}

function DiceIRSection({ parsed }: { parsed: ParsedRuleset }) {
  const { t } = useI18n();
  const ir = parsed.dice_ir;
  const compiled = ir?.package?.compiled;
  const specs = compiled?.check_specs ?? [];
  const applied = ir?.applied_check_spec;
  const runtimeSpec = parsed.check_spec ?? null;

  // Three-state status: in-flight stub / failed stub / compiled / none
  const statusValue = !ir
    ? "—"
    : ir.status === "compiling"
    ? t("debugDiceStatusCompiling")
    : ir.status === "failed"
    ? t("debugDiceStatusFailed")
    : "compiled";

  return (
    <Section title={t("debugSecDice")}>
      <Row label="status" value={statusValue} />
      {ir?.status === "compiling" && (
        <>
          {ir.model && <Row label="model" value={ir.model} mono />}
          {ir.started_at && (
            <Row label="started_at" value={ir.started_at} mono />
          )}
        </>
      )}
      {ir?.status === "failed" && (
        <>
          {ir.model && <Row label="model" value={ir.model} mono />}
          {ir.error && <Row label="error" value={ir.error} mono />}
          {ir.failed_at && (
            <Row label="failed_at" value={ir.failed_at} mono />
          )}
        </>
      )}
      {ir && !ir.status && (
        <>
          {ir.schema_version && (
            <Row label="schema" value={ir.schema_version} mono />
          )}
          {ir.model && <Row label="model" value={ir.model} mono />}
          {compiled?.default_procedure_id && (
            <Row
              label="default"
              value={compiled.default_procedure_id}
              mono
            />
          )}
          {applied?.procedure_id && (
            <Row label="runtime" value={applied.procedure_id} mono />
          )}
          {applied?.source && (
            <Row label="source" value={applied.source} mono />
          )}
          {applied?.applied_at && (
            <Row label="applied_at" value={applied.applied_at} mono />
          )}
          {runtimeSpec && Object.keys(runtimeSpec).length > 0 && (
            <ExpandableRow
              label={t("debugDiceRuntimeSpec")}
              value={runtimeSpecSummary(runtimeSpec)}
              mono
            >
              <Pre json={runtimeSpec} clip={12000} />
            </ExpandableRow>
          )}
          <Row label="check_specs" value={String(specs.length)} />
          {specs.length > 0 &&
            specs.map((spec) => (
              <ExpandableRow
                key={spec.procedure_id}
                label={spec.procedure_id}
                value={spec.validation?.ok ? "ok" : "fail"}
                badge={spec.validation?.ok ? "ok" : "fail"}
                mono
              >
                <Pre json={spec} clip={12000} />
              </ExpandableRow>
            ))}
          <ExpandableRow label="artifact" value="json">
            <Pre json={ir} clip={12000} />
          </ExpandableRow>
        </>
      )}
    </Section>
  );
}

function HouseRulesSection({ parsed }: { parsed: ParsedRuleset }) {
  const { t } = useI18n();
  const fromDiceIr = normalizeHouseRules(parsed.dice_ir?.house_rules).map((rule) => ({
    source: "dice_ir.house_rules",
    rule,
  }));
  const fromParsed = normalizeHouseRules(parsed.raw.house_rules).map((rule) => ({
    source: "parsed_v6.house_rules",
    rule,
  }));
  const rules = [...fromDiceIr, ...fromParsed];

  return (
    <Section title={`${t("debugSecHouseRules")} (${rules.length})`}>
      {rules.length === 0 ? (
        <div className="text-[11px] text-text-3 italic">
          {t("debugHouseRulesEmpty")}
        </div>
      ) : (
        rules.map(({ source, rule }, idx) => {
          const patches = Array.isArray(rule.patches) ? rule.patches : [];
          const label = String(rule.id ?? rule.name ?? `house_rule_${idx + 1}`);
          const target = [
            rule.procedure_id || rule.procedure,
            Array.isArray(rule.procedure_ids) && rule.procedure_ids.length
              ? `${rule.procedure_ids.length} procedures`
              : "",
            rule.extends ? `extends ${String(rule.extends)}` : "",
            rule.engine ? `engine ${String(rule.engine)}` : "",
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <ExpandableRow
              key={`${source}-${idx}-${label}`}
              label={label}
              value={`${source} · ${patches.length} patches${target ? ` · ${target}` : ""}`}
              mono
            >
              <Pre json={rule} clip={12000} />
            </ExpandableRow>
          );
        })
      )}
    </Section>
  );
}

function normalizeHouseRules(raw: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(raw)) {
    return raw.filter(isRecord);
  }
  if (isRecord(raw)) {
    const overlays = raw.overlays ?? raw.rules;
    if (Array.isArray(overlays)) return overlays.filter(isRecord);
    if (Array.isArray(raw.patches)) return [raw];
  }
  return [];
}

function runtimeSpecSummary(spec: Record<string, unknown>): string {
  const pieces = [
    spec.engine ? String(spec.engine) : "",
    spec._runtime_applied_procedure_id
      ? `applied ${String(spec._runtime_applied_procedure_id)}`
      : "",
    spec._runtime_default_procedure_id
      ? `default ${String(spec._runtime_default_procedure_id)}`
      : "",
  ].filter(Boolean);
  return pieces.join(" · ") || "json";
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
