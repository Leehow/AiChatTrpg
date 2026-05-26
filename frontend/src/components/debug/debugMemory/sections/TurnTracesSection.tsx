import { useI18n } from "../../../../i18n";
import type { TurnTraceDTO } from "../../../../api/sessions";
import { ExpandableRow, Pre, Row, Section } from "../../primitives";
import { EmptyHint } from "../EmptyHint";
import {
  formatTraceCache,
  formatTraceChecks,
  formatTraceContextBlocks,
  formatTraceContextProjection,
  formatTraceKnowledge,
  formatTraceStructured,
  formatTurnTraceSummary,
} from "../formatters";
import { readObject } from "../utils";

interface Props {
  turnTraces: TurnTraceDTO[];
}

export function TurnTracesSection({ turnTraces }: Props) {
  const { t } = useI18n();
  return (
    <Section title={`${t("debugMemorySecTurnTraces")} (${turnTraces.length})`}>
      {turnTraces.length === 0 ? (
        <EmptyHint />
      ) : (
        turnTraces.slice(0, 12).map((trace) => (
          <ExpandableRow
            key={trace.id}
            label={trace.turn_id || trace.id}
            value={formatTurnTraceSummary(trace)}
            mono
          >
            <div className="px-1.5 py-1 space-y-1">
              <Row
                label={t("debugTurnTraceMemory")}
                value={`${trace.memory_proposal_count} → ${trace.committed_memory_ids.length} / ${trace.rejected_memory_count}`}
                mono
              />
              <Row
                label={t("debugTurnTraceChecks")}
                value={formatTraceChecks(trace)}
                mono
              />
              <Row
                label={t("debugTurnTraceStructured")}
                value={formatTraceStructured(trace)}
                mono
              />
              <Row
                label={t("debugTurnTraceCache")}
                value={formatTraceCache(trace)}
                mono
              />
              <Row
                label={t("debugTurnTraceContextBlocks")}
                value={formatTraceContextBlocks(trace)}
                mono
              />
              <Row
                label={t("debugTurnTraceKnowledge")}
                value={formatTraceKnowledge(trace)}
                mono
              />
              <ExpandableRow
                label={t("debugTurnTraceContextProjection")}
                value={formatTraceContextProjection(trace)}
                mono
              >
                <Pre json={readObject(trace.parsed_contract_summary.context_cache_projection)} clip={1_000_000} />
              </ExpandableRow>
              <ExpandableRow
                label={t("debugTurnTraceSummary")}
                value={`${Object.keys(trace.parsed_contract_summary).length} keys`}
                mono
              >
                <Pre json={trace.parsed_contract_summary} clip={1_000_000} />
              </ExpandableRow>
            </div>
            <Pre json={trace} clip={1_000_000} />
          </ExpandableRow>
        ))
      )}
    </Section>
  );
}
