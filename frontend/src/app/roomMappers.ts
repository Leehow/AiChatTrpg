import type { RoomEntry } from "../components/game/RoomsPanel";
import type { DraftSummaryDTO } from "../api/ruleset-drafts";
import type {
  SessionDetailDTO,
  SessionSummaryDTO,
} from "../api/sessions";

export function timeAgoLabel(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const diff = Date.now() - then;
  const min = Math.round(diff / 60_000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h`;
  const day = Math.round(hr / 24);
  return `${day}d`;
}

export function draftToRoom(
  d: DraftSummaryDTO,
  activeId: string | null
): RoomEntry {
  const badge = d.target_ruleset_id
    ? "[edit]"
    : d.base_ruleset_id
    ? "[fork]"
    : "[new]";
  return {
    id: d.id,
    name: d.title || "Untitled draft",
    rule: badge,
    time: timeAgoLabel(d.updated_at),
    active: d.id === activeId,
    kind: "rule_draft",
  };
}

export function summaryToRoom(
  s: SessionSummaryDTO,
  activeId: string | null
): RoomEntry {
  const isDraft = !s.setup_state.completed;
  const fallback = isDraft ? "Untitled draft" : "Untitled";
  const name = s.title || fallback;
  // Hide the rule label when the title already carries the same `[xxx]`
  // prefix — otherwise we'd render `[coc]` twice (label + start of name).
  const startsWithAbbr = /^\[[A-Za-z0-9]{1,8}\]/.test(name);
  const ruleLabel = startsWithAbbr
    ? ""
    : s.ruleset_short_name
    ? `[${s.ruleset_short_name}]`
    : s.ruleset_title || "—";
  return {
    id: s.id,
    name,
    rule: ruleLabel,
    time: timeAgoLabel(s.last_active_at),
    active: s.id === activeId,
    draft: isDraft,
  };
}

export function summaryFromDetail(d: SessionDetailDTO): SessionSummaryDTO {
  return {
    id: d.id,
    title: d.title,
    ruleset_id: d.ruleset_id,
    ruleset_title: d.ruleset_title,
    ruleset_short_name: d.ruleset_short_name,
    archived: d.archived,
    title_auto: d.title_auto,
    setup_state: d.setup_state,
    last_active_at: d.last_active_at,
    created_at: d.created_at,
    updated_at: d.updated_at,
  };
}
