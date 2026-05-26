import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type {
  ModuleAppendixEntry,
  ModuleGlobalRef,
  ModuleParseResponse,
  ModulePlayableUnit,
  ModuleSection,
  ModuleSemanticStep,
} from "../../api/types";
import { useI18n } from "../../i18n";
import { loadModule, onModuleChanged, setModule } from "../../lib/module/store";

export function DebugModuleTab() {
  const { t } = useI18n();
  const [mod, setMod] = useState<ModuleParseResponse | null>(loadModule);
  const [semanticBusy, setSemanticBusy] = useState(false);
  const [semanticError, setSemanticError] = useState<string | null>(null);

  useEffect(() => onModuleChanged(() => setMod(loadModule())), []);

  useEffect(() => {
    if (!mod?.id) return;
    let cancelled = false;
    void (async () => {
      try {
        const updated = await api.getModule(mod.id);
        if (cancelled) return;
        setModule(updated);
        setMod(updated);
      } catch {}
    })();
    return () => {
      cancelled = true;
    };
  }, [mod?.id]);

  useEffect(() => {
    if (!mod?.id || mod.semantic_status !== "running") return;
    let cancelled = false;
    const tick = async () => {
      try {
        const updated = await api.getModule(mod.id);
        if (cancelled) return;
        setModule(updated);
        setMod(updated);
      } catch {}
    };
    const timer = window.setInterval(() => void tick(), 2500);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [mod?.id, mod?.semantic_status]);

  if (!mod) {
    return (
      <div className="text-[12px] text-text-3 py-6 text-center">
        {t("debugModuleEmpty")}
      </div>
    );
  }

  const previewLimit = 4000;
  const preview = mod.markdown.slice(0, previewLimit);
  const truncated = mod.markdown.length > previewLimit;
  const structure = mod.semantic_structure || {};
  const sections = asList<ModuleSection>(structure.sections);
  const playable = asList<ModulePlayableUnit>(structure.playable_units);
  const refs = asList<ModuleGlobalRef>(structure.global_refs);
  const appendixEntries = asList<ModuleAppendixEntry>(mod.appendix_index?.entries);
  const steps = asList<ModuleSemanticStep>(mod.semantic_steps);

  async function runSemanticParse() {
    if (!mod?.id || semanticBusy) return;
    setSemanticBusy(true);
    setSemanticError(null);
    try {
      const updated = await api.parseModuleSemantics(mod.id);
      setModule(updated);
      setMod(updated);
      if (updated.semantic_status === "running") {
        setSemanticBusy(false);
      }
    } catch (e) {
      setSemanticError(e instanceof Error ? e.message : String(e));
    } finally {
      setSemanticBusy(false);
    }
  }

  return (
    <div className="space-y-3 text-[12px]">
      <Section title={t("debugModuleMeta")}>
        <Row label="filename" value={mod.filename} mono />
        <Row label="format" value={mod.source_format} mono />
        <Row label="backend" value={mod.backend} mono />
        <Row label="pages" value={String(mod.page_count)} mono />
        <Row label="chars" value={String(mod.markdown.length)} mono />
        <Row label="images dropped" value={String(mod.images_dropped)} mono />
        <Row
          label="duration"
          value={`${mod.duration_seconds.toFixed(1)}s`}
          mono
        />
        <Row label="toc source" value={mod.toc_source} mono />
        <Row label="semantic" value={mod.semantic_status || "pending"} mono />
        {mod.semantic_error && (
          <Row label="semantic error" value={mod.semantic_error} mono />
        )}
        {semanticError && <Row label="parse error" value={semanticError} />}
        <button
          type="button"
          onClick={() => void runSemanticParse()}
          disabled={semanticBusy}
          className="mt-2 px-2 py-1 rounded bg-surface-2 text-[11px] text-text-2 hover:text-text disabled:opacity-50 transition-colors"
        >
          {semanticBusy ? t("debugModuleParsing") : t("debugModuleRunSemantic")}
        </button>
      </Section>

      <Section
        title={`${t("debugModuleToc")} (${mod.toc.length})`}
        defaultOpen={mod.toc.length > 0}
      >
        {mod.toc.length === 0 ? (
          <div className="text-[11px] text-text-3 italic px-2 py-1">
            {t("debugModuleTocEmpty")}
          </div>
        ) : (
          <ul className="space-y-0.5">
            {mod.toc.map((entry, i) => (
              <li
                key={`${entry.anchor}-${i}`}
                style={{ paddingLeft: `${(entry.level - 1) * 12}px` }}
                className="text-[11.5px] text-text leading-relaxed truncate"
                title={entry.title}
              >
                <span className="text-text-3 mr-1.5 font-mono text-[10px]">
                  H{entry.level}
                </span>
                {entry.title}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("debugModuleSemantic")} defaultOpen>
        <Row label="title" value={String(structure.title || "")} />
        <Row label="type" value={String(structure.type || "")} mono />
        <Row label="connection" value={String(structure.connection || "")} mono />
        <Row label="anchor" value={String(structure.anchor_type || "")} mono />
        <Row label="progression" value={String(structure.progression || "")} mono />
      </Section>

      <Section
        title={`${t("debugModuleSteps")} (${steps.length})`}
        defaultOpen={steps.length > 0}
      >
        {steps.length === 0 ? (
          <Empty />
        ) : (
          <div className="space-y-2">
            {steps.map((item, i) => (
              <div key={`${item.stage || "step"}-${i}`} className="text-[11px]">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[10px] uppercase text-text-3">
                    {item.stage || `step ${i + 1}`}
                  </span>
                  <span className="text-text-2">{item.status || ""}</span>
                </div>
                {item.summary && (
                  <div className="text-text leading-relaxed mt-0.5">
                    {item.summary}
                  </div>
                )}
                {item.output && Object.keys(item.output).length > 0 && (
                  <JsonBlock value={item.output} />
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section
        title={`${t("debugModuleStructure")} (${sections.length})`}
        defaultOpen={sections.length > 0}
      >
        <ItemList items={sections} empty={<Empty />} />
      </Section>

      <Section
        title={`${t("debugModulePlayable")} (${playable.length})`}
        defaultOpen={playable.length > 0}
      >
        <ItemList items={playable} empty={<Empty />} />
      </Section>

      <Section
        title={`${t("debugModuleGlobalRefs")} (${refs.length})`}
        defaultOpen={refs.length > 0}
      >
        <ItemList items={refs} empty={<Empty />} />
      </Section>

      <Section title={t("debugModuleBriefing")} defaultOpen={!!mod.briefing_md}>
        {mod.briefing_md ? (
          <pre className="text-[11px] text-text whitespace-pre-wrap break-words leading-relaxed font-mono max-h-[420px] overflow-auto bg-surface rounded p-2 border border-border">
            {mod.briefing_md}
          </pre>
        ) : (
          <Empty />
        )}
      </Section>

      <Section
        title={`${t("debugModuleAppendix")} (${appendixEntries.length})`}
        defaultOpen={appendixEntries.length > 0}
      >
        {appendixEntries.length === 0 ? (
          <Empty />
        ) : (
          <div className="space-y-2">
            {appendixEntries.slice(0, 120).map((entry, i) => (
              <div key={`${entry.name || "entry"}-${i}`} className="text-[11px]">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold text-text truncate">
                    {entry.name || "(untitled)"}
                  </span>
                  <span className="font-mono text-[10px] text-text-3">
                    {entry.type || entry.category || "entry"}
                  </span>
                </div>
                {entry.brief && (
                  <div className="text-text-2 leading-relaxed">{entry.brief}</div>
                )}
                {entry.stats_summary && (
                  <div className="font-mono text-[10px] text-text-3">
                    {entry.stats_summary}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title={t("debugModuleMarkdown")} defaultOpen={false}>
        <pre className="text-[11px] text-text whitespace-pre-wrap break-words leading-relaxed font-mono max-h-[420px] overflow-auto bg-surface rounded p-2 border border-border">
          {preview}
          {truncated && (
            <span className="block mt-2 text-text-3 italic">
              {t("debugModuleTruncated").replace(
                "{n}",
                String(mod.markdown.length - previewLimit)
              )}
            </span>
          )}
        </pre>
      </Section>

      <button
        type="button"
        onClick={() => setModule(null)}
        className="text-[11px] text-text-3 hover:text-[#f87171] underline transition-colors"
      >
        {t("debugModuleRemove")}
      </button>
    </div>
  );
}

function ItemList<T extends ModuleSection | ModulePlayableUnit | ModuleGlobalRef>({
  items,
  empty,
}: {
  items: T[];
  empty: React.ReactNode;
}) {
  const { t } = useI18n();
  if (items.length === 0) return <>{empty}</>;
  return (
    <div className="space-y-2">
      {items.slice(0, 120).map((item, i) => (
        <div key={`${item.title || "item"}-${i}`} className="text-[11px]">
          <div className="flex items-baseline gap-2">
            <span className="font-semibold text-text truncate">
              {item.title || "(untitled)"}
            </span>
            <span className="font-mono text-[10px] text-text-3">
              {itemTag(item)}
            </span>
          </div>
          {item.summary && (
            <div className="text-text-2 leading-relaxed">{item.summary}</div>
          )}
          {(lineStart(item) || lineEnd(item)) && (
            <div className="font-mono text-[10px] text-text-3">
              {t("debugModuleLines")
                .replace("{start}", String(lineStart(item) || 0))
                .replace("{end}", String(lineEnd(item) || 0))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Empty() {
  const { t } = useI18n();
  return (
    <div className="text-[11px] text-text-3 italic px-2 py-1">
      {t("debugModuleEmptyList")}
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  const { t } = useI18n();
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-[10px] text-text-3 font-mono uppercase">
        {t("debugModuleOutput")}
      </summary>
      <pre className="mt-1 text-[10.5px] text-text-2 whitespace-pre-wrap break-words leading-relaxed font-mono max-h-[260px] overflow-auto bg-surface rounded p-2 border border-border">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function asList<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function itemTag(item: ModuleSection | ModulePlayableUnit | ModuleGlobalRef): string {
  if ("type" in item && item.type) return item.type;
  if ("kind" in item && item.kind) return item.kind;
  return "";
}

const lineStart = (item: ModuleSection | ModulePlayableUnit | ModuleGlobalRef) =>
  item.line_start ?? item.start_line;
const lineEnd = (item: ModuleSection | ModulePlayableUnit | ModuleGlobalRef) =>
  item.line_end ?? item.end_line;
function Section({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full px-2 py-1.5 bg-surface-2 flex items-center gap-2 text-[10.5px] uppercase tracking-[0.06em] text-text-3 font-semibold hover:text-text transition-colors"
      >
        <span className="font-mono text-[9px]">{open ? "▼" : "▶"}</span>
        <span>{title}</span>
      </button>
      {open && <div className="px-2.5 py-2 bg-surface">{children}</div>}
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2 text-[11px] py-0.5">
      <span className="text-text-3 w-[120px] shrink-0 font-mono text-[10px] uppercase tracking-[0.04em]">
        {label}
      </span>
      <span
        className={[
          "text-text flex-1 truncate",
          mono ? "font-mono text-[11px]" : "",
        ].join(" ")}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}
