import { useI18n } from "../../../../i18n";
import { ExpandableRow, Pre, Row, Section } from "../../primitives";
import { EmptyHint } from "../EmptyHint";
import {
  formatDiceSummary,
  formatTier,
  readHouseRules,
  summarizeDiceRequest,
} from "../formatters";
import { displayValue, readObject, readStringArray } from "../utils";

interface Props {
  diceEntries: Record<string, unknown>[];
}

export function DiceSection({ diceEntries }: Props) {
  const { t } = useI18n();
  return (
    <Section title={`${t("debugMemorySecDice")} (${diceEntries.length})`}>
      {diceEntries.length === 0 ? (
        <EmptyHint />
      ) : (
        diceEntries.slice(0, 12).map((d, i) => {
          const dd = d as Record<string, unknown>;
          const trace = readObject(dd.trace);
          const resultDetail = readObject(dd.result_detail);
          const rollTrace = readObject(dd.roll_trace ?? trace.roll_trace);
          const request = readObject(dd.request);
          const warnings = readStringArray(dd.warnings ?? trace.warnings);
          const houseRules = readHouseRules(trace);
          return (
            <ExpandableRow
              key={`dice-${i}`}
              label={String(dd.expression ?? trace.roll_expression ?? "?")}
              value={formatDiceSummary(dd, trace)}
              mono
            >
              <div className="px-1.5 py-1 space-y-1">
                <Row
                  label={t("debugDiceTraceProcedure")}
                  value={displayValue(dd.procedure_id ?? trace.procedure_id)}
                  mono
                />
                <Row
                  label={t("debugDiceTraceEngine")}
                  value={displayValue(dd.engine ?? trace.engine)}
                  mono
                />
                <Row
                  label={t("debugDiceTraceSeed")}
                  value={displayValue(dd.seed ?? trace.roll_seed)}
                  mono
                />
                <Row
                  label={t("debugDiceTraceTier")}
                  value={formatTier(resultDetail, trace)}
                  mono
                />
                <Row
                  label={t("debugDiceTraceHouseRules")}
                  value={houseRules.length ? houseRules.join(", ") : "—"}
                  mono
                />
                <Row
                  label={t("debugDiceTraceWarnings")}
                  value={warnings.length ? warnings.join(" · ") : "—"}
                />
                {Object.keys(rollTrace).length > 0 && (
                  <ExpandableRow
                    label={t("debugDiceTraceRollTrace")}
                    value={`${Object.keys(rollTrace).length} keys`}
                    mono
                  >
                    <Pre json={rollTrace} clip={1_000_000} />
                  </ExpandableRow>
                )}
                {Object.keys(request).length > 0 && (
                  <ExpandableRow
                    label={t("debugDiceTraceRequest")}
                    value={summarizeDiceRequest(request)}
                    mono
                  >
                    <Pre json={request} clip={1_000_000} />
                  </ExpandableRow>
                )}
                <ExpandableRow
                  label={t("debugDiceTraceResult")}
                  value={formatTier(resultDetail, trace)}
                  mono
                >
                  <Pre json={resultDetail} clip={1_000_000} />
                </ExpandableRow>
              </div>
              <Pre json={d} />
            </ExpandableRow>
          );
        })
      )}
    </Section>
  );
}
