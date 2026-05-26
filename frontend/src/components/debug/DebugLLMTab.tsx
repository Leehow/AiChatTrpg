import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  LLMProviderInfo,
  LLMTestResponse,
  PoolEntry,
} from "../../api/types";
import { useI18n } from "../../i18n";
import { DebugLLMPool } from "./DebugLLMPool";

// One built-in prompt — the panel is a connectivity smoke-test, not a
// playground. Real prompt iteration happens in chat sessions.
const TEST_PROMPT = "Reply with one short sentence: hello.";

// LLM tester tab: pick a provider, optionally fetch its model list, hit
// "Send test". Shows TTFT and chars/sec so you can eyeball whether a
// new endpoint is healthy. Defaults to the local codex-relay debug
// provider so the panel works out of the box.
export function DebugLLMTab() {
  const { t } = useI18n();
  const [providers, setProviders] = useState<LLMProviderInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<LLMTestResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [models, setModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await api.listLLMProviders();
        if (cancelled) return;
        setProviders(list);
        if (list.length > 0) {
          // Prefer "debug" as default selection — that's the in-tree
          // codex-relay setup that works without external keys.
          const preferred =
            list.find((p) => p.provider === "debug")?.provider ??
            list[0].provider;
          setSelected((cur) => cur || preferred);
        }
      } catch (e) {
        if (!cancelled)
          setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const current = useMemo(
    () => providers.find((p) => p.provider === selected) ?? null,
    [providers, selected]
  );

  // Provider switch: rehydrate from the canonical default first; fall
  // back to the saved admin override only when there is no default
  // (e.g. the generic openai_compat slot). The test panel is meant to
  // probe the provider's *own* endpoint — saved admin overrides belong
  // to chat sessions, not connectivity smoke tests.
  useEffect(() => {
    if (!current) return;
    setApiKey("");
    setBaseUrl(current.default_base_url || current.saved_base_url);
    setModel(current.default_model || current.saved_model);
    setModels([]);
    setModelsError(null);
    setResult(null);
  }, [current]);

  async function fetchModels() {
    if (!current) return;
    setFetchingModels(true);
    setModelsError(null);
    try {
      const res = await api.listProviderModels({
        provider: current.provider,
        api_key: apiKey,
        base_url: baseUrl.trim(),
      });
      if (res.error) {
        setModels([]);
        setModelsError(res.error);
      } else {
        setModels(res.models);
        setModelsError(null);
      }
    } catch (e) {
      setModels([]);
      setModelsError(e instanceof Error ? e.message : String(e));
    } finally {
      setFetchingModels(false);
    }
  }

  async function send() {
    if (!current) return;
    setRunning(true);
    setResult(null);
    try {
      const res = await api.testLLM({
        provider: current.provider,
        model: model.trim(),
        api_key: apiKey,
        base_url: baseUrl.trim(),
        prompt: TEST_PROMPT,
      });
      setResult(res);
    } catch (e) {
      setResult({
        text: "",
        provider: current.provider,
        model,
        total_ms: 0,
        first_token_ms: null,
        chars: 0,
        chars_per_second: 0,
        finish_reason: null,
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setRunning(false);
    }
  }

  if (loadError) {
    return (
      <div className="text-[12px] text-[#f87171] py-3 px-2 bg-[rgba(248,113,113,0.1)] rounded border border-[rgba(248,113,113,0.3)]">
        {loadError}
      </div>
    );
  }

  if (providers.length === 0) {
    return (
      <div className="text-[12px] text-text-3 py-6 text-center">
        {t("debugLlmLoading")}
      </div>
    );
  }

  const showBaseUrl = current?.kind === "openai_compat";
  const requiresKey = current?.kind !== "mock";

  return (
    <div className="space-y-3 text-[12px]">
      <Field label={t("debugLlmProvider")}>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent"
        >
          {providers.map((p) => (
            <option key={p.provider} value={p.provider}>
              {p.label}
              {p.saved_api_key ? "  •" : ""}
            </option>
          ))}
        </select>
      </Field>

      <Field label={t("debugLlmApiKey")}>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            current?.saved_api_key
              ? t("debugLlmApiKeyKeep")
              : requiresKey
              ? t("debugLlmApiKeyPlaceholder")
              : t("debugLlmApiKeyMockHint")
          }
          className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent font-mono"
        />
      </Field>

      {showBaseUrl && (
        <Field label={t("debugLlmBaseUrl")}>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://..."
            className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent font-mono"
          />
        </Field>
      )}

      <Field label={t("debugLlmModel")}>
        <div className="flex gap-1.5">
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder={current?.default_model || "model id"}
            className="flex-1 min-w-0 px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent font-mono"
          />
          <button
            type="button"
            onClick={fetchModels}
            disabled={fetchingModels || !current}
            title={t("debugLlmFetchModels")}
            className="shrink-0 px-2 py-1.5 rounded border border-border text-[11px] text-text-2 hover:bg-surface-2 hover:text-text disabled:opacity-40 transition-colors"
          >
            {fetchingModels ? "…" : t("debugLlmFetchModels")}
          </button>
        </div>
        {modelsError && (
          <div className="mt-1 text-[10.5px] text-[#f87171] break-words">
            {modelsError}
          </div>
        )}
        {models.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {models.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setModel(m)}
                className={[
                  "px-1.5 py-0.5 rounded text-[10.5px] font-mono border transition-colors",
                  m === model
                    ? "bg-accent-dim text-[var(--accent-text)] border-accent"
                    : "bg-surface-2 text-text-2 border-border hover:text-text",
                ].join(" ")}
              >
                {m}
              </button>
            ))}
          </div>
        )}
      </Field>

      <div className="text-[10.5px] text-text-3 italic px-1">
        {t("debugLlmBuiltinPrompt")}: <span className="font-mono not-italic">{TEST_PROMPT}</span>
      </div>

      <button
        type="button"
        onClick={send}
        disabled={running || !current}
        className="w-full px-3 py-1.5 rounded bg-accent text-[var(--accent-text)] text-[12px] font-semibold hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
      >
        {running ? t("debugLlmSending") : t("debugLlmSend")}
      </button>

      {result && <ResultView result={result} />}

      <DebugLLMPool
        current={{
          provider: current?.provider ?? "",
          model,
          api_key: apiKey,
          base_url: baseUrl,
        }}
        onPickPool={(entry: PoolEntry) => {
          // Switch the form to that pool entry; the provider-change
          // effect resets the rest of the fields, then we override
          // the model so it matches the picked combo exactly.
          setSelected(entry.provider);
          // useEffect on `current` will re-run and reset model to the
          // provider default — schedule the override after that with a
          // microtask so we win the race.
          queueMicrotask(() => setModel(entry.model));
        }}
      />
    </div>
  );
}

function ResultView({ result }: { result: LLMTestResponse }) {
  const { t } = useI18n();
  const ok = !result.error;
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <div className="px-2 py-1.5 bg-surface-2 flex items-center gap-2 text-[10.5px] uppercase tracking-[0.06em]">
        <span
          className={[
            "px-1 py-0 rounded text-[9.5px] font-semibold",
            ok
              ? "bg-[rgba(52,211,153,0.18)] text-[#34d399]"
              : "bg-[rgba(248,113,113,0.18)] text-[#f87171]",
          ].join(" ")}
        >
          {ok ? "ok" : "fail"}
        </span>
        <span className="text-text-3 flex-1 truncate">
          {result.provider} · {result.model || "—"}
        </span>
      </div>
      {ok && (
        <div className="grid grid-cols-3 gap-px bg-border">
          <Stat
            label={t("debugLlmTtft")}
            value={
              result.first_token_ms != null
                ? `${result.first_token_ms}ms`
                : "—"
            }
          />
          <Stat
            label={t("debugLlmTotal")}
            value={`${result.total_ms}ms`}
          />
          <Stat
            label={t("debugLlmSpeed")}
            value={
              result.chars_per_second > 0
                ? `${result.chars_per_second.toFixed(1)} c/s`
                : "—"
            }
          />
        </div>
      )}
      <div className="px-2.5 py-2 max-h-[260px] overflow-auto bg-surface">
        {result.error ? (
          <pre className="text-[11px] text-[#f87171] whitespace-pre-wrap break-words font-mono">
            {result.error}
          </pre>
        ) : (
          <pre className="text-[11.5px] text-text whitespace-pre-wrap break-words leading-relaxed">
            {result.text || (
              <span className="italic text-text-3">
                {t("debugLlmEmptyResponse")}
              </span>
            )}
          </pre>
        )}
        {result.finish_reason && (
          <div className="mt-1 text-[10px] text-text-3 font-mono">
            finish: {result.finish_reason}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-2 py-1 bg-surface flex flex-col gap-0.5">
      <span className="text-[9.5px] uppercase tracking-[0.06em] text-text-3">
        {label}
      </span>
      <span className="text-[11px] font-mono text-text truncate">{value}</span>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[10.5px] font-semibold tracking-[0.06em] uppercase text-text-3 mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}
