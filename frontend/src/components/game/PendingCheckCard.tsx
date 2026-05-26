import { useI18n } from "../../i18n";
import type { PendingCheckSummary } from "./Message";

interface Props {
  pending: PendingCheckSummary;
  // Disabled when a previous click on the same message is still streaming —
  // GameShell tracks one in-flight resolve at a time so two button clicks
  // don't race two continuation turns.
  busy?: boolean;
  onResolve: (pending: PendingCheckSummary) => void;
}

const DIFFICULTY_LABEL: Record<string, string> = {
  regular: "Regular",
  hard: "Hard",
  extreme: "Extreme",
};

// Lightweight chip that sits under a GM message holding an unresolved
// `[pending_check ...]` placeholder. The "投出" button is the only call to
// action; the helper line tells the player they can also just write a
// different in-character action and the check will quietly age out — i.e.
// no commitment the moment the GM proposes a check.
export function PendingCheckCard({ pending, busy, onResolve }: Props) {
  const { t } = useI18n();
  const skill = (pending.skill || "").trim();
  const value = pending.value;
  const difficulty = (pending.difficulty || "regular").toLowerCase();
  const reason = (pending.reason || "").trim();
  const difficultyLabel =
    DIFFICULTY_LABEL[difficulty] ||
    difficulty.replace(/^./, (c) => c.toUpperCase());
  const headerParts: string[] = [];
  if (skill) headerParts.push(skill);
  if (typeof value === "number" && Number.isFinite(value)) {
    headerParts.push(String(value));
  }
  headerParts.push(difficultyLabel);

  return (
    <div
      className="mt-1.5 flex flex-col gap-1.5 rounded-md border border-border bg-accent-dim/40 px-3 py-2 text-[12px] leading-snug"
      data-pending-check-id={pending.id}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span aria-hidden="true">🎲</span>
          <span className="truncate font-medium text-text">
            {headerParts.join(" · ") || t("pendingCheckLabel")}
          </span>
        </div>
        <button
          type="button"
          onClick={() => onResolve(pending)}
          disabled={busy}
          aria-label={t("pendingCheckRoll")}
          className="shrink-0 rounded-md bg-accent px-3 py-1 text-[12px] font-semibold text-white hover:bg-accent/90 disabled:cursor-progress disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          {busy ? t("pendingCheckRolling") : t("pendingCheckRoll")}
        </button>
      </div>
      {reason && (
        <div className="text-text-2">{reason}</div>
      )}
      <div className="text-[11px] text-text-3">
        {t("pendingCheckHint")}
      </div>
    </div>
  );
}
