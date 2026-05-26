/**
 * Character UI compilation tab. Parallels `DiceEngineTab` — three states
 * (empty / compiling / failed) collapse to a single compile-or-retry call
 * to the backend, and a success view shows the widget tree.
 *
 * The artifact lives in `parsed.character_ui`. Manual compile is what
 * fills in older rulesets that pre-date this feature.
 */

import { useMemo, useState } from "react";
import { compileCharacterUIAPI } from "../../lib/ruleset/api";
import type {
  CharacterUISchema,
  Primitive,
} from "../character_ui/widgets";
import { SCHEMA_VERSION } from "../character_ui/widgets";

interface Props {
  artifact: Record<string, unknown> | null;
  rulesetId?: string;
  /** Notified after a successful manual recompile so the parent can refresh
   *  the cached parsed ruleset. */
  onCompiled?: (artifact: Record<string, unknown>) => void;
}

interface ArtifactView {
  status?: "compiling" | "failed";
  error?: string;
  model?: string;
  output_language?: string;
  schema_version?: string;
  saved_at?: string;
  package?: CharacterUISchema;
}

type Language = "zh" | "en";

function normaliseLanguage(raw: string | undefined | null): Language {
  const s = String(raw || "").trim().toLowerCase();
  if (s.startsWith("zh") || s === "chinese" || s.includes("中文")) return "zh";
  return "en";
}

function toView(artifact: Record<string, unknown> | null): ArtifactView {
  if (!artifact || typeof artifact !== "object") return {};
  return artifact as ArtifactView;
}

function countNodes(node: Primitive | undefined): number {
  if (!node || typeof node !== "object") return 0;
  let n = 1;
  if ("children" in node && Array.isArray(node.children)) {
    for (const c of node.children) n += countNodes(c as Primitive);
  }
  if ("item_template" in node && node.item_template) {
    n += countNodes(node.item_template as Primitive);
  }
  return n;
}

export function CharacterUITab({ artifact, rulesetId, onCompiled }: Props) {
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = useMemo(() => toView(artifact), [artifact]);
  const tree = view.package?.tree;
  const isOutdated =
    !!view.schema_version
    && view.schema_version !== SCHEMA_VERSION
    && view.status !== "compiling"
    && view.status !== "failed";

  // Default the language picker to whatever the existing artifact was
  // compiled in, so a "Recompile" without changing the picker preserves
  // the user's previous choice.
  const [language, setLanguage] = useState<Language>(() =>
    normaliseLanguage(view.output_language),
  );

  const triggerCompile = async (lang?: Language) => {
    if (!rulesetId) return;
    setCompiling(true);
    setError(null);
    try {
      const result = await compileCharacterUIAPI(rulesetId, {
        save: true,
        output_language: lang || language,
      });
      if (result?.package && onCompiled) {
        onCompiled(result.package as Record<string, unknown>);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCompiling(false);
    }
  };

  const isInflight =
    view.status === "compiling" || (compiling && view.status !== "failed");
  const isFailed = view.status === "failed";
  const isEmpty = (!view.package || !tree) && !isInflight && !isFailed;

  if (isEmpty || isInflight || isFailed || isOutdated) {
    return (
      <div className="max-w-[680px] mx-auto px-6 py-12">
        <div className="bg-surface border border-dashed border-border-2 rounded-2xl p-8 text-center">
          <div className="text-3xl mb-3 opacity-60">
            {isInflight
              ? "⏳"
              : isFailed
                ? "⚠️"
                : isOutdated
                  ? "♻️"
                  : "🧬"}
          </div>
          <div className="text-base font-semibold mb-1.5">
            {isInflight
              ? "Compiling character UI…"
              : isFailed
                ? "Character UI compilation failed"
                : isOutdated
                  ? "Schema is from an older compiler version"
                  : "No character UI compiled yet"}
          </div>
          <div className="text-sm text-text-2 leading-relaxed mb-4">
            {isInflight
              ? "An LLM is composing the primitive tree from this ruleset's character template. This page refreshes when it's done."
              : isFailed
                ? "The compiler couldn't produce a valid schema. You can retry — the default model from your model pool will be used."
                : isOutdated
                  ? "This schema was compiled with an older version of the layout primitive set. Recompile to use the new compositional primitives."
                  : "Compile a layout from this ruleset's character template so the in-game sidebar can render the player card."}
          </div>
          {isFailed && view.error && (
            <div className="mt-3 mb-4 text-xs text-[var(--accent-text)] bg-accent-dim border border-border rounded-lg p-3 text-left max-w-md mx-auto font-mono">
              {view.error}
            </div>
          )}
          {rulesetId && !isInflight && (
            <div className="flex flex-col items-center gap-3">
              <LanguagePicker
                value={language}
                onChange={setLanguage}
                disabled={compiling}
              />
              <button
                onClick={() => triggerCompile()}
                disabled={compiling}
                className="px-5 py-2.5 rounded-xl bg-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                {compiling
                  ? "Compiling…"
                  : isFailed
                    ? "Retry compile"
                    : isOutdated
                      ? "Recompile"
                      : "Compile character UI"}
              </button>
            </div>
          )}
          {error && (
            <div className="mt-3 text-xs text-[var(--accent-text)] bg-accent-dim border border-border rounded-lg p-3 text-left max-w-md mx-auto">
              {error}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Success: artifact has a package with a primitive tree.
  const nodeCount = countNodes(tree);
  return (
    <div className="max-w-[1100px] mx-auto px-6 py-6">
      <div className="bg-surface border border-border rounded-xl p-4 mb-5 flex items-center gap-4 text-[12.5px] flex-wrap">
        <div>
          <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
            System
          </div>
          <div className="font-medium">
            {view.package?.system || "generic"}
          </div>
        </div>
        {view.model && (
          <div>
            <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
              Model
            </div>
            <div className="font-medium">{view.model}</div>
          </div>
        )}
        <div>
          <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
            Primitives
          </div>
          <div className="font-medium">{nodeCount}</div>
        </div>
        <div>
          <div className="text-text-3 text-[10.5px] uppercase tracking-wider mb-0.5">
            Language
          </div>
          <div className="font-medium uppercase">
            {view.output_language || "—"}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {rulesetId && (
            <>
              <LanguagePicker
                value={language}
                onChange={setLanguage}
                disabled={compiling}
                size="sm"
              />
              <button
                onClick={() => triggerCompile()}
                disabled={compiling}
                className="px-3 py-1.5 rounded-lg bg-surface-2 border border-border text-xs font-medium hover:bg-surface disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                {compiling ? "Recompiling…" : "Recompile"}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="bg-surface border border-border rounded-xl p-4">
        <div className="text-[10.5px] text-text-3 uppercase tracking-wider mb-2 font-semibold">
          Compiled tree
        </div>
        <pre className="whitespace-pre-wrap text-[11.5px] leading-relaxed text-text-2 font-mono bg-surface-2 border border-border rounded-lg p-3 max-h-[60vh] overflow-auto">
          {JSON.stringify(tree, null, 2)}
        </pre>
      </div>

      {error && (
        <div className="mt-4 text-xs text-[var(--accent-text)] bg-accent-dim border border-border rounded-lg p-3">
          {error}
        </div>
      )}
    </div>
  );
}

function LanguagePicker({
  value,
  onChange,
  disabled,
  size = "md",
}: {
  value: Language;
  onChange: (v: Language) => void;
  disabled?: boolean;
  size?: "sm" | "md";
}) {
  const cell = size === "sm"
    ? "px-2 py-0.5 text-[11px]"
    : "px-3 py-1 text-[12px]";
  const choice = (lang: Language, label: string) => (
    <button
      key={lang}
      type="button"
      onClick={() => onChange(lang)}
      disabled={disabled}
      className={[
        cell,
        "font-medium transition",
        value === lang
          ? "bg-accent text-white"
          : "bg-transparent text-text-2 hover:bg-surface-2 disabled:opacity-50",
      ].join(" ")}
    >
      {label}
    </button>
  );
  return (
    <div className="inline-flex border border-border rounded-md overflow-hidden divide-x divide-border bg-surface-2">
      {choice("zh", "中文")}
      {choice("en", "EN")}
    </div>
  );
}
