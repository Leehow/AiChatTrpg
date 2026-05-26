// Left preview pane in the rule editor — shows draft meta, the RulesPanel
// summary, and clickable lists of every section the V6 schema carries:
// core rules, companion (背景/风格), rule packages, parameter families,
// and the character sheet (template + creation guide). Clicking any row
// opens a modal that renders the underlying markdown, pretty-printed
// JSON, or a hybrid view depending on the section kind.

import { useEffect, useState } from "react";
import { useI18n } from "../../i18n";
import { RulesPanel } from "../game/panels/RulesPanel";
import { MarkdownDoc } from "../ruleset/MarkdownDoc";
import type { ParsedRuleset, V6ParameterFamily } from "../../lib/ruleset/types";

type Selection =
  | { kind: "core" }
  | { kind: "companion" }
  | { kind: "scenario"; id: string }
  | { kind: "parameter"; id: string }
  | { kind: "sheet_template" }
  | { kind: "sheet_guide" }
  | null;

interface Props {
  parsed: ParsedRuleset;
  draftTitle: string;
  badge: "blank" | "fork" | "in-place";
  onOpenFullPreview?: () => void;
  // When true, render in normal document flow without an internal scroll
  // region so an outer container can own the scroll. Defaults to false to
  // preserve standalone behavior.
  embedded?: boolean;
}

export function EditorLeftPreview({
  parsed,
  draftTitle,
  badge,
  onOpenFullPreview,
  embedded = false,
}: Props) {
  const { t } = useI18n();
  const [selection, setSelection] = useState<Selection>(null);

  const badgeLabel =
    badge === "fork"
      ? t("draftBadgeFork")
      : badge === "in-place"
      ? t("draftBadgeInPlace")
      : t("draftBadgeBlank");

  const coreLen = (parsed.core.rules_markdown || "").trim().length;
  const companionLen = (parsed.core.companion?.content || "").trim().length;
  const sheet = parsed.character_sheet;
  const templateKeys = sheet?.template_json
    ? Object.keys(sheet.template_json).length
    : 0;
  const guideLen = (sheet?.guide_content || "").trim().length;
  const sheetItems: Array<{
    id: string;
    label: string;
    onClick: () => void;
  }> = [];
  if (templateKeys > 0 || guideLen > 0) {
    sheetItems.push({
      id: "__template__",
      label:
        templateKeys > 0
          ? t("draftSheetTemplateKeys", { n: templateKeys })
          : t("draftSheetTemplateMissing"),
      onClick: () => setSelection({ kind: "sheet_template" }),
    });
    sheetItems.push({
      id: "__guide__",
      label:
        guideLen > 0
          ? t("ruleValChars", { n: guideLen })
          : t("draftSheetGuideMissing"),
      onClick: () => setSelection({ kind: "sheet_guide" }),
    });
  }

  const rootClass = embedded
    ? "flex flex-col bg-surface"
    : "flex flex-col h-full overflow-hidden bg-surface";
  const bodyClass = embedded
    ? "p-3 flex flex-col gap-3"
    : "flex-1 overflow-y-auto p-3 flex flex-col gap-3";

  return (
    <div className={rootClass}>
      <div className="px-3 pt-3 pb-2 border-b border-border shrink-0">
        <div className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-3">
          {t("draftPreviewTitle")}
        </div>
        <div className="mt-1.5 text-[14px] font-semibold truncate">
          {draftTitle || t("draftUntitled")}
        </div>
        <span className="mt-1 inline-block text-[10px] uppercase tracking-[0.05em] px-1.5 py-0.5 rounded bg-accent-dim text-[var(--accent-text)]">
          {badgeLabel}
        </span>
      </div>

      <div className={bodyClass}>
        <RulesPanel
          parsed={parsed}
          onEdit={onOpenFullPreview ?? (() => undefined)}
        />

        <SectionList
          title={t("ruleRowCoreRules")}
          items={[
            {
              id: "__core__",
              label:
                coreLen > 0
                  ? t("ruleValChars", { n: coreLen })
                  : t("ruleValEmpty"),
              onClick: () => setSelection({ kind: "core" }),
            },
          ]}
          emptyLabel=""
        />

        <SectionList
          title={t("ruleRowCompanion")}
          items={[
            {
              id: "__companion__",
              label:
                companionLen > 0
                  ? t("ruleValChars", { n: companionLen })
                  : t("ruleValEmpty"),
              onClick: () => setSelection({ kind: "companion" }),
            },
          ]}
          emptyLabel=""
        />

        <SectionList
          title={t("draftScenariosList")}
          items={parsed.scenarios.map((s) => ({
            id: s.package_id,
            label: s.package_id,
            onClick: () =>
              setSelection({ kind: "scenario", id: s.package_id }),
          }))}
          emptyLabel={t("draftScenariosEmpty")}
        />

        <SectionList
          title={t("draftParametersList")}
          items={parsed.parameters.map((p) => ({
            id: p.family_id,
            label: p.family_id,
            onClick: () =>
              setSelection({ kind: "parameter", id: p.family_id }),
          }))}
          emptyLabel={t("draftParametersEmpty")}
        />

        <SectionList
          title={t("draftSheetSection")}
          items={sheetItems}
          emptyLabel={t("draftSheetEmpty")}
          itemPrefix={(id) =>
            id === "__template__"
              ? t("draftSheetTemplate")
              : id === "__guide__"
              ? t("draftSheetGuide")
              : null
          }
        />
      </div>

      {selection && (
        <SectionDialog
          parsed={parsed}
          selection={selection}
          onClose={() => setSelection(null)}
        />
      )}
    </div>
  );
}

function SectionList({
  title,
  items,
  emptyLabel,
  itemPrefix,
}: {
  title: string;
  items: Array<{
    id: string;
    label: string;
    onClick?: () => void;
  }>;
  emptyLabel: string;
  itemPrefix?: (id: string) => string | null;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface-2 p-3">
      <div className="text-[11px] font-semibold tracking-[0.08em] uppercase text-text-3 mb-2">
        {title} ({items.length})
      </div>
      {items.length === 0 ? (
        <div className="text-[12px] text-text-3 py-1">{emptyLabel}</div>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((it) => {
            const prefix = itemPrefix ? itemPrefix(it.id) : null;
            return (
              <li key={it.id}>
                <button
                  type="button"
                  onClick={it.onClick}
                  disabled={!it.onClick}
                  className={[
                    "w-full text-left text-[12px] truncate font-mono",
                    "px-2 py-1 rounded bg-surface flex items-center gap-2",
                    it.onClick
                      ? "hover:bg-accent-dim hover:text-[var(--accent-text)] cursor-pointer transition-colors"
                      : "cursor-default",
                  ].join(" ")}
                  title={it.label}
                >
                  {prefix && (
                    <span className="text-text-3 shrink-0">{prefix}</span>
                  )}
                  <span className="truncate">{it.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function SectionDialog({
  parsed,
  selection,
  onClose,
}: {
  parsed: ParsedRuleset;
  selection: Exclude<Selection, null>;
  onClose: () => void;
}) {
  const { t } = useI18n();

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  let title = "";
  let body: React.ReactNode = null;

  if (selection.kind === "core") {
    title = t("ruleRowCoreRules");
    const text = parsed.core.rules_markdown || "";
    body = text.trim()
      ? <MarkdownDoc text={text} />
      : <EmptyBody label={t("ruleValEmpty")} />;
  } else if (selection.kind === "companion") {
    title = parsed.core.companion?.filename || t("ruleRowCompanion");
    const text = parsed.core.companion?.content || "";
    body = text.trim()
      ? <MarkdownDoc text={text} />
      : <EmptyBody label={t("ruleValEmpty")} />;
  } else if (selection.kind === "scenario") {
    const pkg = parsed.scenarios.find((s) => s.package_id === selection.id);
    title = pkg?.package_id || selection.id;
    const text = pkg?.content || "";
    body = text.trim()
      ? <MarkdownDoc text={text} />
      : <EmptyBody label={t("ruleValEmpty")} />;
  } else if (selection.kind === "parameter") {
    const fam = parsed.parameters.find((p) => p.family_id === selection.id);
    title = fam?.family_id || selection.id;
    body = <ParameterFamilyBody family={fam} emptyLabel={t("ruleValEmpty")} />;
  } else if (selection.kind === "sheet_template") {
    title = `${t("draftSheetSection")} · ${t("draftSheetTemplate")}`;
    const tj = parsed.character_sheet?.template_json;
    body = tj && Object.keys(tj).length > 0
      ? (
        <pre className="text-[11px] leading-relaxed font-mono whitespace-pre-wrap break-words bg-surface-2 rounded p-3 border border-border">
          {JSON.stringify(tj, null, 2)}
        </pre>
      )
      : <EmptyBody label={t("draftSheetTemplateMissing")} />;
  } else {
    // sheet_guide
    title = `${t("draftSheetSection")} · ${t("draftSheetGuide")}`;
    const text = parsed.character_sheet?.guide_content || "";
    body = text.trim()
      ? <MarkdownDoc text={text} />
      : <EmptyBody label={t("draftSheetGuideMissing")} />;
  }

  return (
    <div
      className="fixed inset-0 z-[80] bg-black/45 backdrop-blur-sm flex items-center justify-center px-4 py-6"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="relative w-[min(92vw,720px)] max-h-[88vh] flex flex-col rounded-lg border border-border bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="font-semibold text-text truncate font-mono text-[13px]">
            {title}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="w-8 h-8 rounded-md text-text-2 hover:bg-surface-2 hover:text-text flex items-center justify-center text-lg leading-none"
          >
            ×
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-4 flex-1">{body}</div>
      </div>
    </div>
  );
}

function ParameterFamilyBody({
  family,
  emptyLabel,
}: {
  family: V6ParameterFamily | undefined;
  emptyLabel: string;
}) {
  if (!family) return <EmptyBody label={emptyLabel} />;
  if (family.should_remain_markdown && family.content?.trim()) {
    return <MarkdownDoc text={family.content} />;
  }
  const entries = family.json?.entries ?? [];
  if (entries.length === 0 && !(family.content || "").trim()) {
    return <EmptyBody label={emptyLabel} />;
  }
  return (
    <div className="flex flex-col gap-3">
      {(family.content || "").trim() && (
        <details className="rounded border border-border bg-surface-2 p-3">
          <summary className="cursor-pointer text-[12px] text-text-2 font-semibold">
            content (markdown)
          </summary>
          <div className="mt-2">
            <MarkdownDoc text={family.content || ""} />
          </div>
        </details>
      )}
      <div className="text-[11px] text-text-3 font-medium">
        entries ({entries.length})
      </div>
      <pre className="text-[11px] leading-relaxed font-mono whitespace-pre-wrap break-words bg-surface-2 rounded p-3 border border-border">
        {JSON.stringify(entries, null, 2)}
      </pre>
    </div>
  );
}

function EmptyBody({ label }: { label: string }) {
  return (
    <div className="text-[13px] text-text-3 italic py-6 text-center">
      {label}
    </div>
  );
}
