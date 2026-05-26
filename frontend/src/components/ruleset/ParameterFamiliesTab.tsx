import { Fragment, useState } from "react";
import { useI18n } from "../../i18n";
import type { V6ParameterFamily } from "../../lib/ruleset/types";

interface Props {
  families: V6ParameterFamily[];
}

export function ParameterFamiliesTab({ families }: Props) {
  const { t } = useI18n();
  const [activeId, setActiveId] = useState<string | null>(
    families[0]?.family_id ?? null
  );

  if (families.length === 0) {
    return (
      <div className="max-w-[1100px] mx-auto px-6 py-12 text-center text-text-3 text-sm">
        {t("parametersEmpty")}
      </div>
    );
  }

  const active = families.find((f) => f.family_id === activeId) || families[0];

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6">
      <div className="flex gap-1.5 mb-5 flex-wrap">
        {families.map((fam) => {
          const count = fam.json?.entries?.length ?? 0;
          return (
            <button
              key={fam.family_id}
              onClick={() => setActiveId(fam.family_id)}
              className={[
                "px-3.5 py-1.5 rounded-lg text-[12px] font-medium transition-colors",
                "border whitespace-nowrap",
                activeId === fam.family_id
                  ? "bg-accent-dim text-[var(--accent-text)] border-accent"
                  : "bg-surface text-text-2 border-border hover:border-border-2",
              ].join(" ")}
            >
              {fam.json?.title || fam.family_id}
              <span className="ml-1.5 text-[10px] opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      <FamilyEntries family={active} />
    </div>
  );
}

function FamilyEntries({ family }: { family: V6ParameterFamily }) {
  const { t } = useI18n();
  const entries = family.json?.entries || [];

  if (family.error) {
    return (
      <div className="bg-accent-dim border border-border rounded-xl p-4 text-[var(--accent-text)] text-sm">
        {family.error}
      </div>
    );
  }
  if (family.should_remain_markdown) {
    return (
      <pre className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-text-2 font-sans bg-surface border border-border rounded-xl p-4">
        {family.content || family.raw || ""}
      </pre>
    );
  }
  if (entries.length === 0) {
    return (
      <div className="text-center text-text-3 text-sm py-8">
        {t("parametersFamilyEmpty")}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {entries.map((entry, i) => (
        <EntryCard key={i} entry={entry} />
      ))}
    </div>
  );
}

function EntryCard({ entry }: { entry: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const headline = pickHeadline(entry);
  const summary = pickSummary(entry);
  const fields = Object.entries(entry).filter(
    ([k]) => k !== headline.key && k !== summary.key
  );

  return (
    <div className="bg-surface border border-border rounded-xl p-4">
      <div className="text-[14px] font-semibold mb-1 truncate">
        {headline.value || "—"}
      </div>
      {summary.value && (
        <div className="text-[12px] text-text-2 leading-relaxed mb-2 line-clamp-3">
          {summary.value}
        </div>
      )}
      {fields.length > 0 && (
        <button
          onClick={() => setExpanded((x) => !x)}
          className="text-[11px] text-accent hover:underline"
        >
          {expanded ? "− details" : "+ details"}
        </button>
      )}
      {expanded && (
        <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-[11.5px]">
          {fields.map(([k, v]) => (
            <Fragment key={k}>
              <dt className="text-text-3 font-medium uppercase tracking-wide">
                {k}
              </dt>
              <dd className="text-text-2 break-words">{stringifyValue(v)}</dd>
            </Fragment>
          ))}
        </dl>
      )}
    </div>
  );
}

const HEADLINE_KEYS = ["name", "title", "id", "label"];
const SUMMARY_KEYS = ["description", "summary", "desc", "notes", "effect"];

function pickHeadline(entry: Record<string, unknown>) {
  for (const key of HEADLINE_KEYS) {
    if (typeof entry[key] === "string" && entry[key]) {
      return { key, value: entry[key] as string };
    }
  }
  // Fallback: first string value.
  for (const [k, v] of Object.entries(entry)) {
    if (typeof v === "string" && v) return { key: k, value: v };
  }
  return { key: "", value: "" };
}

function pickSummary(entry: Record<string, unknown>) {
  for (const key of SUMMARY_KEYS) {
    if (typeof entry[key] === "string" && entry[key]) {
      return { key, value: entry[key] as string };
    }
  }
  return { key: "", value: "" };
}

function stringifyValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}
