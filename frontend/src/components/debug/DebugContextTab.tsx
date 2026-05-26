import { useEffect, useState } from "react";
import { useI18n } from "../../i18n";
import {
  fetchContextSnapshot,
  listMessagesAPI,
  type ContextSnapshotBP2DTO,
  type ContextSnapshotBP3DTO,
  type ContextSnapshotDTO,
} from "../../api/sessions";
import type { MessageSnapshot } from "../../lib/debugUiBus";
import { ExpandableRow, Pre, Row, Section } from "./primitives";

interface Props {
  sessionId: string | null;
  /** When set, the tab renders the semi-stable/BP2/BP3 state captured at the time of that
   *  GM message instead of the live ruleset-wide snapshot. BP1 is always
   *  read live — it's stable ruleset-level data. */
  messageSnapshot?: MessageSnapshot;
  /** Bumped on every "view context" click so repeat clicks on the same
   *  message refresh the chat-cutoff fetch. */
  messageSnapshotSerial?: number;
}

// Mirror of the BP1/BP2/BP3 context the game pipeline injects into each LLM
// call. Default is "live" (current snapshot). When the chat's
// "view context" button passes a per-message bp_snapshot, module state plus
// BP2/BP3 are rendered from that snapshot and BP3.chat is reconstructed by filtering
// the messages table to entries before the GM message's created_at.
export function DebugContextTab({
  sessionId,
  messageSnapshot,
  messageSnapshotSerial = 0,
}: Props) {
  const { t } = useI18n();
  const [liveData, setLiveData] = useState<ContextSnapshotDTO | null>(null);
  const [scopedChat, setScopedChat] = useState<
    Array<Record<string, unknown>> | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sessionId) {
      setLiveData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchContextSnapshot(sessionId)
      .then((d) => {
        if (!cancelled) setLiveData(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Reconstruct BP3.chat at the time of the clicked message by pulling all
  // guide-phase rows before its created_at. Re-runs when serial bumps so a
  // user can click around between messages.
  useEffect(() => {
    if (!sessionId || !messageSnapshot?.bp_snapshot) {
      setScopedChat(null);
      return;
    }
    let cancelled = false;
    const scopedPhase = snapshotPhase(messageSnapshot);
    listMessagesAPI(sessionId, { limit: 1000 })
      .then((resp) => {
        if (cancelled) return;
        const cutoff = messageSnapshot.message_created_at;
        const filtered = resp.items
          .filter((m) => {
            const phase = readString(
              (m.metadata as Record<string, unknown> | null)?.phase,
            );
            if (scopedPhase === "ic") return true;
            return !phase || phase === "guide";
          })
          .filter((m) => m.created_at < cutoff)
          .map((m) => ({
            id: m.id,
            role: m.role === "gm" ? "assistant" : m.role,
            content: m.content,
            created_at: m.created_at,
            metadata: m.metadata,
          }));
        setScopedChat(filtered);
      })
      .catch(() => {
        if (!cancelled) setScopedChat([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, messageSnapshot, messageSnapshotSerial]);

  if (!sessionId) {
    return (
      <div className="text-[12px] text-text-3 leading-relaxed py-6 text-center">
        {t("debugCtxNoSession")}
      </div>
    );
  }
  if (loading && !liveData) {
    return (
      <div className="text-[12px] text-text-3 py-6 text-center">
        {t("debugCtxLoading")}
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-[12px] text-[#f87171] py-6 text-center">
        {t("debugCtxLoadFailed")}: {error}
      </div>
    );
  }
  if (!liveData) return null;

  // BP2 / BP3: from snapshot when scoped, else live.
  const hasBpSnapshot = !!messageSnapshot?.bp_snapshot;
  const bp2: ContextSnapshotBP2DTO = messageSnapshot
    && hasBpSnapshot
    ? _bp2FromSnapshot(messageSnapshot)
    : liveData.bp2;
  const bp3: ContextSnapshotBP3DTO = messageSnapshot
    && hasBpSnapshot
    ? _bp3FromSnapshot(messageSnapshot, scopedChat ?? [])
    : liveData.bp3;

  return (
    <div className="space-y-2">
      <TurnMetadataSection metadata={messageSnapshot?.message_metadata} />
      <Bp1Section data={liveData.bp1} />
      <ModuleStateSection data={bp2.module_state ?? {}} />
      <Bp2Section data={bp2} />
      <Bp3Section data={bp3} />
    </div>
  );
}

function _bp2FromSnapshot(s: MessageSnapshot): ContextSnapshotBP2DTO {
  const mem = s.bp_snapshot?.memory_state ?? {};
  const arr = (k: string) => {
    const v = (mem as Record<string, unknown>)[k];
    return Array.isArray(v) ? (v as Array<Record<string, unknown>>) : [];
  };
  return {
    module_state: s.bp_snapshot?.module_state ?? {},
    scenes: arr("scenes"),
    npcs: arr("npcs"),
    plot_threads: arr("plot_threads"),
    world_facts: arr("world_facts"),
    narrative_summary: s.bp_snapshot?.narrative_summary || "",
  };
}

function _bp3FromSnapshot(
  s: MessageSnapshot,
  chat: Array<Record<string, unknown>>,
): ContextSnapshotBP3DTO {
  const snap = s.bp_snapshot;
  if (!snap) {
    return {
      chat,
      pc: null,
      draft_card: null,
      ready: false,
      dice_history: [],
    };
  }
  return {
    chat,
    pc: snap.pc,
    draft_card: snap.draft_card,
    ready: snap.ready,
    dice_history: snap.dice_history,
  };
}

function snapshotPhase(s: MessageSnapshot): string {
  const snapPhase = readString(s.bp_snapshot?.source_phase);
  if (snapPhase) return snapPhase;
  return readString(s.message_metadata?.phase);
}

function TurnMetadataSection({
  metadata,
}: {
  metadata?: Record<string, unknown>;
}) {
  const { t } = useI18n();
  if (!metadata || Object.keys(metadata).length === 0) return null;
  const runtime = readRecord(metadata.npc_runtime_read);
  const hits = readRecord(runtime.action_board_hits);
  const matches = readRecords(hits.matches);
  const resolutions = readRecords(hits.resolutions);
  const hasHits = matches.length > 0 || resolutions.length > 0;

  return (
    <Section title={t("debugCtxTurnMetadata")}>
      {hasHits ? (
        <ExpandableRow
          label={t("debugCtxNpcActionBoardHits")}
          value={`${String(hits.llm_background_match_count ?? 0)} LLM / ${String(hits.match_count ?? matches.length)} total`}
          mono
        >
          <div className="px-1.5 py-1 space-y-1">
            {matches.map((match, idx) => (
              <ExpandableRow
                key={`match-${idx}-${String(match.card_id ?? "")}`}
                label={String(match.card_id ?? `#${idx + 1}`)}
                value={[
                  match.npc_id,
                  match.planner,
                  readStringArray(match.matched_triggers).join(","),
                ].filter(Boolean).join(" · ")}
                mono
              >
                <Pre json={match} />
              </ExpandableRow>
            ))}
            {resolutions.map((resolution, idx) => (
              <ExpandableRow
                key={`resolution-${idx}-${String(resolution.card_id ?? "")}`}
                label={String(resolution.decision ?? `#${idx + 1}`)}
                value={[
                  resolution.card_id,
                  resolution.npc_id,
                  resolution.reason,
                ].filter(Boolean).join(" · ")}
                mono
              >
                <Pre json={resolution} />
              </ExpandableRow>
            ))}
          </div>
        </ExpandableRow>
      ) : (
        <Row label={t("debugCtxNpcActionBoardHits")} value={t("debugCtxNpcActionBoardNoHits")} />
      )}
      <ExpandableRow
        label={t("debugCtxMetadataFull")}
        value={Object.keys(metadata).length + " keys"}
      >
        <Pre json={metadata} clip={1_000_000} />
      </ExpandableRow>
    </Section>
  );
}

function Bp1Section({ data }: { data: ContextSnapshotDTO["bp1"] }) {
  const { t } = useI18n();
  return (
    <Section title={t("debugCtxBp1")}>
      <Row label={t("debugCtxRulesetTitle")} value={data.ruleset_title || "—"} />
      <Row label={t("debugCtxWorldMode")} value={data.ruleset_world_mode || "—"} />
      <ExpandableRow
        label={t("debugCtxCoreRules")}
        value={charsLabel(data.core_rules.length)}
      >
        <Pre text={data.core_rules} clip={1_000_000} />
      </ExpandableRow>
      <ExpandableRow
        label={t("debugCtxSheetTemplate")}
        value={charsLabel(data.sheet_template.length)}
      >
        <Pre text={data.sheet_template} clip={1_000_000} />
      </ExpandableRow>
      <ExpandableRow
        label={t("debugCtxSheetGuide")}
        value={charsLabel(data.sheet_guide.length)}
      >
        <Pre text={data.sheet_guide} clip={1_000_000} />
      </ExpandableRow>
      {data.scene_guide ? (
        <ExpandableRow
          label={t("debugCtxSceneGuide")}
          value={charsLabel(data.scene_guide.length)}
        >
          <Pre text={data.scene_guide} clip={1_000_000} />
        </ExpandableRow>
      ) : (
        <Row label={t("debugCtxSceneGuide")} value="—" />
      )}
      {data.module_title ? (
        <ExpandableRow
          label={t("debugCtxModule")}
          value={`${data.module_title} · ${charsLabel(data.module_text.length)}`}
        >
          <Pre text={data.module_text} clip={1_000_000} />
        </ExpandableRow>
      ) : (
        <Row label={t("debugCtxModule")} value="—" />
      )}
    </Section>
  );
}

function Bp2Section({ data }: { data: ContextSnapshotDTO["bp2"] }) {
  const { t } = useI18n();
  const empty =
    data.scenes.length === 0 &&
    data.npcs.length === 0 &&
    data.plot_threads.length === 0 &&
    data.world_facts.length === 0 &&
    !data.narrative_summary;
  return (
    <Section title={t("debugCtxBp2")}>
      {empty && (
        <Row label="—" value={t("debugCtxEmpty")} />
      )}
      <ItemList label={t("debugCtxScenes")} items={data.scenes} />
      <ItemList label={t("debugCtxNpcs")} items={data.npcs} />
      <ItemList label={t("debugCtxPlots")} items={data.plot_threads} />
      <ItemList label={t("debugCtxFacts")} items={data.world_facts} />
      {data.narrative_summary ? (
        <ExpandableRow
          label={t("debugCtxNarrativeSummary")}
          value={charsLabel(data.narrative_summary.length)}
        >
          <Pre text={data.narrative_summary} clip={1_000_000} />
        </ExpandableRow>
      ) : (
        <Row label={t("debugCtxNarrativeSummary")} value="—" />
      )}
    </Section>
  );
}

function ModuleStateSection({
  data,
}: {
  data: Record<string, unknown>;
}) {
  const { t } = useI18n();
  return (
    <Section title={t("debugCtxModuleState")}>
      <ExpandableRow
        label="JSON"
        value={Object.keys(data).length + " keys"}
      >
        <Pre json={data} clip={1_000_000} />
      </ExpandableRow>
    </Section>
  );
}

function Bp3Section({ data }: { data: ContextSnapshotDTO["bp3"] }) {
  const { t } = useI18n();
  return (
    <Section title={t("debugCtxBp3")}>
      <ChatList label={t("debugCtxChat")} items={data.chat} />
      {data.pc ? (
        <ExpandableRow
          label={t("debugCtxPc")}
          value={summarizeCard(data.pc)}
        >
          <Pre json={data.pc} clip={1_000_000} />
        </ExpandableRow>
      ) : (
        <Row label={t("debugCtxPc")} value="—" />
      )}
      {data.draft_card ? (
        <ExpandableRow
          label={t("debugCtxDraftCard")}
          value={summarizeCard(data.draft_card)}
        >
          <Pre json={data.draft_card} clip={1_000_000} />
        </ExpandableRow>
      ) : (
        <Row label={t("debugCtxDraftCard")} value="—" />
      )}
      <Row label={t("debugCtxReady")} value={data.ready ? "true" : "false"} mono />
      <ItemList label={t("debugCtxDice")} items={data.dice_history} />
    </Section>
  );
}

function ItemList({
  label,
  items,
}: {
  label: string;
  items: Array<Record<string, unknown>>;
}) {
  const { t } = useI18n();
  if (!items.length) {
    return <Row label={label} value="—" />;
  }
  return (
    <ExpandableRow label={label} value={`${items.length} ${t("debugCtxEmpty") === "(空)" ? "条" : "items"}`}>
      <div className="px-1.5 py-1 space-y-1">
        {items.map((item, idx) => (
          <ExpandableRow
            key={idx}
            label={`#${idx + 1}`}
            value={summarizeItem(item)}
          >
            <Pre json={item} clip={1_000_000} />
          </ExpandableRow>
        ))}
      </div>
    </ExpandableRow>
  );
}

function ChatList({
  label,
  items,
}: {
  label: string;
  items: Array<Record<string, unknown>>;
}) {
  const { t } = useI18n();
  if (!items.length) {
    return <Row label={label} value="—" />;
  }
  return (
    <ExpandableRow label={label} value={`${items.length} ${t("debugCtxEmpty") === "(空)" ? "条" : "items"}`}>
      <div className="px-1.5 py-1 space-y-1">
        {items.map((item, idx) => {
          const role = String(item.role ?? "?");
          const content = String(item.content ?? "");
          const preview = content.replace(/\s+/g, " ").trim().slice(0, 60);
          return (
            <ExpandableRow
              key={idx}
              label={`${idx + 1}·${role}`}
              value={preview || "(empty)"}
            >
              <Pre json={item} clip={1_000_000} />
            </ExpandableRow>
          );
        })}
      </div>
    </ExpandableRow>
  );
}

function charsLabel(n: number): string {
  return `${n.toLocaleString()} chars`;
}

function readRecord(v: unknown): Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function readString(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

function readRecords(v: unknown): Array<Record<string, unknown>> {
  return Array.isArray(v)
    ? v.filter((item): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item))
    : [];
}

function readStringArray(v: unknown): string[] {
  return Array.isArray(v)
    ? v.map((item) => String(item).trim()).filter(Boolean)
    : [];
}

function summarizeItem(item: Record<string, unknown>): string {
  const fields = ["name", "title", "key", "label", "id"];
  for (const f of fields) {
    const v = item[f];
    if (typeof v === "string" && v.trim()) return v;
  }
  // Fallback: short JSON preview
  try {
    const s = JSON.stringify(item);
    return s.length > 60 ? s.slice(0, 60) + "…" : s;
  } catch {
    return "(item)";
  }
}

function summarizeCard(card: Record<string, unknown>): string {
  const candidates = ["name", "姓名", "character_name", "title"];
  for (const k of candidates) {
    const v = card[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return Object.keys(card).length + " fields";
}
