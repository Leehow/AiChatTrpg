// Top toolbar in the editor screen — Promote / Recompile / Delete /
// Export. Promote-to-target is only enabled when the draft has a
// target_ruleset_id (in-place edit mode).

import { useState } from "react";
import { useI18n } from "../../i18n";

interface Props {
  draftTitle: string;
  hasTarget: boolean;
  needsDiceCompile: boolean;
  needsCharacterUiCompile: boolean;
  previewCollapsed: boolean;
  onTogglePreview: () => void;
  onPromoteNew: () => void;
  onPromoteTarget: () => void;
  onRecompileDice: () => void;
  onRecompileCharacterUi: () => void;
  onDelete: () => void;
  onExport: () => void;
  onLeave: () => void;
  busy?: boolean;
}

export function EditorToolbar({
  draftTitle,
  hasTarget,
  needsDiceCompile,
  needsCharacterUiCompile,
  previewCollapsed,
  onTogglePreview,
  onPromoteNew,
  onPromoteTarget,
  onRecompileDice,
  onRecompileCharacterUi,
  onDelete,
  onExport,
  onLeave,
  busy = false,
}: Props) {
  const { t } = useI18n();
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div className="h-13 flex items-center gap-2 px-3 border-b border-border bg-surface shrink-0">
      <button
        onClick={onLeave}
        title={t("draftToolbarLeave")}
        className="w-8 h-8 rounded-lg flex items-center justify-center text-text-2 hover:bg-surface-2 transition-colors"
      >
        ←
      </button>
      <button
        type="button"
        onClick={onTogglePreview}
        title={t("draftToolbarTogglePreview")}
        aria-pressed={!previewCollapsed}
        className="w-8 h-8 rounded-lg flex items-center justify-center text-text-2 hover:bg-surface-2 transition-colors"
      >
        {previewCollapsed ? "›" : "‹"}
      </button>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold truncate">
          {draftTitle || t("draftUntitled")}
        </div>
      </div>
      <ToolbarButton
        onClick={onRecompileDice}
        disabled={busy}
        highlight={needsDiceCompile}
        label={t("draftToolbarRecompileDice")}
      />
      <ToolbarButton
        onClick={onRecompileCharacterUi}
        disabled={busy}
        highlight={needsCharacterUiCompile}
        label={t("draftToolbarRecompileCharUi")}
      />
      <div className="w-px h-6 bg-border mx-0.5" />
      {hasTarget && (
        <ToolbarButton
          onClick={onPromoteTarget}
          disabled={busy}
          variant="accent"
          label={t("draftToolbarPromoteTarget")}
        />
      )}
      <ToolbarButton
        onClick={onPromoteNew}
        disabled={busy}
        variant="accent"
        label={t("draftToolbarPromoteNew")}
      />
      <ToolbarButton
        onClick={onExport}
        disabled={busy}
        label={t("draftToolbarExport")}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          if (confirmDelete) {
            setConfirmDelete(false);
            onDelete();
          } else {
            setConfirmDelete(true);
            window.setTimeout(() => setConfirmDelete(false), 3000);
          }
        }}
        className={[
          "h-8 px-2.5 rounded-lg text-[12px] font-medium transition-colors",
          confirmDelete
            ? "bg-red-500 text-white hover:bg-red-600"
            : "text-text-3 hover:bg-red-500/10 hover:text-red-500",
        ].join(" ")}
      >
        {confirmDelete ? t("draftToolbarDeleteConfirm") : t("draftToolbarDelete")}
      </button>
    </div>
  );
}

function ToolbarButton({
  onClick,
  disabled,
  label,
  highlight,
  variant,
}: {
  onClick: () => void;
  disabled?: boolean;
  label: string;
  highlight?: boolean;
  variant?: "accent";
}) {
  const base =
    "h-8 px-2.5 rounded-lg text-[12px] font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const variantCls =
    variant === "accent"
      ? "bg-accent text-white hover:bg-accent/90"
      : highlight
      ? "bg-accent-dim text-[var(--accent-text)] hover:bg-accent/30"
      : "text-text-2 hover:bg-surface-2";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${variantCls}`}
    >
      {label}
    </button>
  );
}
