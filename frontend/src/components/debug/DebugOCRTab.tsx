import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  OCRHealthResponse,
  OCRProviderInfo,
  OCRProviderUpdate,
} from "../../api/types";
import { useI18n } from "../../i18n";

// Settings-only OCR tab. The real "test extraction" path is the module
// upload button on the setup page — there's no point duplicating it
// here. Formulas and tables are always extracted (they're useful for
// rule modules); images are dropped post-parse, see backend.

type SaveState = "idle" | "saving" | "saved" | "error";

export function DebugOCRTab() {
  const { t } = useI18n();
  const [providers, setProviders] = useState<OCRProviderInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  // Editable fields. Keys mirror OCRProviderUpdate so we can submit
  // a thin slice on save.
  const [cli, setCli] = useState("");
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [modelVersion, setModelVersion] = useState("vlm");

  const [health, setHealth] = useState<OCRHealthResponse | null>(null);
  const [healthRunning, setHealthRunning] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await api.listOCRProviders();
        if (cancelled) return;
        setProviders(list);
        const active = list.find((p) => p.active) ?? list[0];
        if (active) setSelected((cur) => cur || active.provider);
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
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

  useEffect(() => {
    if (!current) return;
    const cfg = current.config || {};
    setCli(String(cfg.cli ?? "mineru"));
    setBaseUrl(String(cfg.base_url ?? "https://mineru.net/api/v4"));
    setModelVersion(String(cfg.model_version ?? "vlm"));
    setApiKeyInput("");
    setHealth(null);
    setSaveState("idle");
  }, [current]);

  async function save() {
    if (!current) return;
    setSaveState("saving");
    setSaveError(null);
    const payload: OCRProviderUpdate = {};
    if (apiKeyInput.trim()) payload.api_key = apiKeyInput.trim();
    if (current.provider === "mineru_local") {
      payload.cli = cli.trim() || "mineru";
    } else if (current.provider === "mineru_cloud") {
      payload.base_url = baseUrl.trim() || "https://mineru.net/api/v4";
      payload.model_version = modelVersion;
    }
    try {
      const updated = await api.updateOCRProvider(current.provider, payload);
      setProviders((prev) =>
        prev.map((p) =>
          p.provider === updated.provider
            ? updated
            : { ...p, active: false }
        )
      );
      setApiKeyInput("");
      setSaveState("saved");
    } catch (e) {
      setSaveState("error");
      setSaveError(e instanceof Error ? e.message : String(e));
    }
  }

  async function runHealth() {
    if (!current) return;
    setHealthRunning(true);
    setHealth(null);
    try {
      const res = await api.ocrProviderHealth(current.provider);
      setHealth(res);
    } catch (e) {
      setHealth({
        provider: current.provider,
        ok: false,
        detail: { error: e instanceof Error ? e.message : String(e) },
      });
    } finally {
      setHealthRunning(false);
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
        {t("debugOcrLoading")}
      </div>
    );
  }

  const isPdfText = current?.provider === "pdftext_local";
  const isLocal = current?.provider === "mineru_local";
  const isCloud = current?.provider === "mineru_cloud";

  return (
    <div className="space-y-3 text-[12px]">
      <Field label={t("debugOcrProvider")}>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent"
        >
          {providers.map((p) => (
            <option key={p.provider} value={p.provider}>
              {p.label}
              {p.api_key_set ? "  •" : ""}
            </option>
          ))}
        </select>
      </Field>

      {isPdfText && (
        <p className="text-[11.5px] text-text-2 leading-relaxed px-1 py-2">
          {t("debugOcrPdftextHint")}
        </p>
      )}

      {isLocal && (
        <>
          <Field label={t("debugOcrCli")}>
            <input
              value={cli}
              onChange={(e) => setCli(e.target.value)}
              placeholder="mineru"
              className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent font-mono"
            />
          </Field>
          <p className="text-[10.5px] text-text-3 italic px-1 leading-relaxed">
            {t("debugOcrInstallHint")}
          </p>
        </>
      )}

      {isCloud && (
        <>
          <Field label={t("debugOcrApiKey")}>
            <input
              type="password"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder={
                current?.api_key_set
                  ? t("debugOcrApiKeyKeep")
                  : t("debugOcrApiKeyPlaceholder")
              }
              className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent font-mono"
            />
          </Field>
          <Field label={t("debugOcrBaseUrl")}>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://mineru.net/api/v4"
              className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent font-mono"
            />
          </Field>
          <Field label={t("debugOcrModelVersion")}>
            <select
              value={modelVersion}
              onChange={(e) => setModelVersion(e.target.value)}
              className="w-full px-2 py-1.5 bg-bg border border-border rounded text-[12px] text-text outline-none focus:border-accent"
            >
              <option value="vlm">vlm</option>
              <option value="pipeline">pipeline</option>
              <option value="MinerU-HTML">MinerU-HTML</option>
            </select>
          </Field>
        </>
      )}

      <p className="text-[10.5px] text-text-3 italic px-1 leading-relaxed">
        {t("debugOcrDefaults")}
      </p>

      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={save}
          disabled={saveState === "saving"}
          className="px-3 py-1.5 rounded bg-accent text-[var(--accent-text)] text-[12px] font-semibold hover:opacity-90 disabled:opacity-40 transition-opacity"
        >
          {saveState === "saving" ? t("debugOcrSaving") : t("debugOcrSave")}
        </button>
        <button
          type="button"
          onClick={runHealth}
          disabled={healthRunning}
          className="px-3 py-1.5 rounded border border-border text-[11px] text-text-2 hover:bg-surface-2 hover:text-text disabled:opacity-40 transition-colors"
        >
          {healthRunning ? t("debugOcrChecking") : t("debugOcrCheckHealth")}
        </button>
        {saveState === "saved" && (
          <span className="text-[11px] text-[#34d399]">{t("debugOcrSaved")}</span>
        )}
        {saveState === "error" && saveError && (
          <span className="text-[11px] text-[#f87171] truncate" title={saveError}>
            {saveError}
          </span>
        )}
      </div>

      {health && <HealthView res={health} />}
    </div>
  );
}

function HealthView({ res }: { res: OCRHealthResponse }) {
  const { t } = useI18n();
  const ok = res.ok;
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
          {ok ? t("debugOcrHealthy") : t("debugOcrUnhealthy")}
        </span>
        <span className="text-text-3 flex-1 truncate">{res.provider}</span>
      </div>
      <pre className="px-2.5 py-2 max-h-[160px] overflow-auto bg-surface text-[11px] text-text whitespace-pre-wrap break-words font-mono">
        {JSON.stringify(res.detail, null, 2)}
      </pre>
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
