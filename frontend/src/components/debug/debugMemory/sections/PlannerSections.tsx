import { useI18n } from "../../../../i18n";
import { ExpandableRow, Pre, Row, Section } from "../../primitives";
import { EmptyHint } from "../EmptyHint";
import {
  type BackgroundPlannerCard,
  formatPlannerKnowledge,
  formatPlannerLeaks,
  formatPlannerStatus,
  formatStringList,
} from "../formatters";
import { displayValue, truncate } from "../utils";

interface NpcPlannerSectionProps {
  plannerLatest: Record<string, unknown>;
  plannerRuns: Record<string, unknown>[];
  plannerAllRunsCount: number;
}

export function NpcPlannerSection({
  plannerLatest,
  plannerRuns,
  plannerAllRunsCount,
}: NpcPlannerSectionProps) {
  const { t } = useI18n();
  return (
    <Section title={`${t("debugMemorySecNPCPlanner")} (${plannerAllRunsCount})`}>
      {Object.keys(plannerLatest).length === 0 && plannerRuns.length === 0 ? (
        <EmptyHint />
      ) : (
        <>
          {Object.keys(plannerLatest).length > 0 && (
            <div className="space-y-1">
              <Row
                label={t("debugMemoryPlannerStatus")}
                value={formatPlannerStatus(plannerLatest)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerTurn")}
                value={displayValue(plannerLatest.based_on_turn_id)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerModel")}
                value={truncate(displayValue(plannerLatest.model), 70)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerSelected")}
                value={formatStringList(plannerLatest.selected_npc_ids)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerPlanned")}
                value={formatStringList(plannerLatest.planned_card_ids)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerPersisted")}
                value={displayValue(plannerLatest.persisted_action_cards)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerKnowledge")}
                value={formatPlannerKnowledge(plannerLatest)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerLeaks")}
                value={formatPlannerLeaks(plannerLatest)}
                mono
              />
              <Row
                label={t("debugMemoryPlannerUpdated")}
                value={displayValue(plannerLatest.updated_at)}
                mono
              />
            </div>
          )}
          {plannerRuns.length > 0 && (
            <div className="pt-1">
              <Row
                label={t("debugMemoryPlannerRuns")}
                value={plannerRuns
                  .map((run) => {
                    const turn = displayValue(run.based_on_turn_id);
                    const status = displayValue(run.status);
                    const planned = displayValue(run.planned);
                    const skipped = String(run.skipped ?? "").trim();
                    return skipped
                      ? `t${turn}:${status}/${skipped}`
                      : `t${turn}:${status}/${planned}`;
                  })
                  .join(" · ")}
                mono
              />
            </div>
          )}
        </>
      )}
    </Section>
  );
}

interface NpcActionCardsSectionProps {
  plannerCards: BackgroundPlannerCard[];
}

export function NpcActionCardsSection({ plannerCards }: NpcActionCardsSectionProps) {
  const { t } = useI18n();
  return (
    <Section title={`${t("debugMemorySecNPCActionCards")} (${plannerCards.length})`}>
      {plannerCards.length === 0 ? (
        <EmptyHint />
      ) : (
        plannerCards.slice(0, 12).map((card) => (
          <ExpandableRow
            key={`${card.sceneId}-${card.cardId}`}
            label={card.npcId || card.cardId}
            value={truncate(
              [
                card.actionType,
                card.intent,
                `t${card.basedOnTurnId}-${card.validUntilTurn}`,
                card.triggers.join(","),
              ]
                .filter(Boolean)
                .join(" · "),
              100,
            )}
            mono
          >
            <Row
              label={t("debugMemoryPlannerCardMeta")}
              value={`${card.sceneId} · p=${card.priority.toFixed(2)}`}
              mono
            />
            <Pre json={card.raw} />
          </ExpandableRow>
        ))
      )}
    </Section>
  );
}
