import { useI18n } from "../../../../i18n";
import type { PublicMemoryViewDTO } from "../../../../api/sessions";
import { ExpandableRow, Pre, Row, Section } from "../../primitives";
import { EmptyHint } from "../EmptyHint";
import { isPublicViewEmpty, truncate } from "../utils";

interface Props {
  publicView: PublicMemoryViewDTO | null;
}

export function PublicViewSection({ publicView }: Props) {
  const { t } = useI18n();
  return (
    <Section title={t("debugMemorySecPublicView")}>
      {!publicView || isPublicViewEmpty(publicView) ? (
        <EmptyHint />
      ) : (
        <div className="space-y-1">
          <Row
            label={t("debugPublicViewRelationships")}
            value={String(publicView.relationships.length)}
            mono
          />
          {publicView.relationships.slice(0, 8).map((rel, i) => (
            <ExpandableRow
              key={`public-rel-${rel.npc_id}-${i}`}
              label={rel.npc_id || `npc_${i}`}
              value={truncate(rel.summary, 90)}
            >
              <Pre json={rel} />
            </ExpandableRow>
          ))}
          <Row
            label={t("debugPublicViewClues")}
            value={String(publicView.clues.length)}
            mono
          />
          {publicView.clues.slice(0, 8).map((clue, i) => (
            <ExpandableRow
              key={`public-clue-${clue.clue_id || i}`}
              label={clue.title || `clue_${i}`}
              value={truncate(clue.summary || clue.status, 90)}
            >
              <Pre json={clue} />
            </ExpandableRow>
          ))}
          <ExpandableRow
            label={t("debugPublicViewThreads")}
            value={String(publicView.open_threads.length)}
            mono
          >
            <Pre json={publicView.open_threads} />
          </ExpandableRow>
          <ExpandableRow
            label={t("debugPublicViewFacts")}
            value={String(publicView.remembered_facts.length)}
            mono
          >
            <Pre json={publicView.remembered_facts} />
          </ExpandableRow>
        </div>
      )}
    </Section>
  );
}
