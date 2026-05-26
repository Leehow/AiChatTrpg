import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { AdminProvider } from "../api/types";
import { useI18n } from "../i18n";

interface Draft {
  api_key: string;
  api_key_dirty: boolean;
  base_url: string;
  models: string[];
  new_model: string;
  saving: boolean;
  saved: boolean;
  error: string | null;
}

function emptyDraft(p: AdminProvider): Draft {
  return {
    api_key: "",
    api_key_dirty: false,
    base_url: p.base_url,
    models: [...p.models],
    new_model: "",
    saving: false,
    saved: false,
    error: null,
  };
}

export function Admin() {
  const { t } = useI18n();
  const [providers, setProviders] = useState<AdminProvider[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await api.listAdminProviders();
      setProviders(list);
      setDrafts((prev) => {
        const next: Record<string, Draft> = {};
        for (const p of list) {
          next[p.provider] = prev[p.provider] ?? emptyDraft(p);
        }
        return next;
      });
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function patch(provider: string, mut: (d: Draft) => Draft) {
    setDrafts((prev) => ({ ...prev, [provider]: mut(prev[provider]) }));
  }

  async function save(p: AdminProvider) {
    const d = drafts[p.provider];
    if (!d) return;
    patch(p.provider, (x) => ({ ...x, saving: true, error: null, saved: false }));
    try {
      const updated = await api.updateAdminProvider(p.provider, {
        api_key: d.api_key_dirty ? d.api_key : null,
        base_url: d.base_url,
        models: d.models,
      });
      setProviders((prev) =>
        prev.map((it) => (it.provider === p.provider ? updated : it))
      );
      patch(p.provider, (x) => ({
        ...x,
        api_key: "",
        api_key_dirty: false,
        saving: false,
        saved: true,
      }));
    } catch (e) {
      patch(p.provider, (x) => ({
        ...x,
        saving: false,
        error: e instanceof Error ? e.message : String(e),
      }));
    }
  }

  return (
    <div className="flex-1 overflow-y-auto bg-zinc-950 text-zinc-100">
      <header className="sticky top-0 z-10 bg-zinc-950/95 backdrop-blur border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{t("adminTitle")}</h1>
          <p className="text-xs text-zinc-500 mt-0.5">{t("adminSubtitle")}</p>
        </div>
        <a href="/" className="text-sm text-zinc-400 hover:text-zinc-200">
          {t("adminBackToChat")}
        </a>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-6 space-y-4">
        {loading && (
          <div className="text-zinc-400 text-sm">{t("adminLoading")}</div>
        )}
        {loadError && (
          <div className="bg-red-500/10 border border-red-500/30 rounded px-3 py-2 text-red-300 text-sm">
            {loadError}
          </div>
        )}
        {!loading && providers.length === 0 && !loadError && (
          <div className="text-zinc-500 text-sm">{t("adminNoProviders")}</div>
        )}
        {providers.map((p) => (
          <ProviderCard
            key={p.provider}
            provider={p}
            draft={drafts[p.provider]}
            onPatch={(mut) => patch(p.provider, mut)}
            onSave={() => save(p)}
          />
        ))}
      </div>
    </div>
  );
}

interface CardProps {
  provider: AdminProvider;
  draft: Draft | undefined;
  onPatch: (mut: (d: Draft) => Draft) => void;
  onSave: () => void;
}

function ProviderCard({ provider, draft, onPatch, onSave }: CardProps) {
  const { t } = useI18n();
  const d = draft;
  const keyStatus = useMemo(() => {
    if (!provider.api_key_set) return t("adminKeyMissing");
    if (provider.env_has_key) return t("adminKeyFromEnv");
    return t("adminKeyFromAdmin");
  }, [provider, t]);

  if (!d) return null;

  function addModel() {
    const name = d!.new_model.trim();
    if (!name) return;
    if (d!.models.includes(name)) {
      onPatch((x) => ({ ...x, new_model: "" }));
      return;
    }
    onPatch((x) => ({ ...x, models: [...x.models, name], new_model: "" }));
  }

  function removeModel(name: string) {
    onPatch((x) => ({ ...x, models: x.models.filter((m) => m !== name) }));
  }

  return (
    <section className="border border-zinc-800 rounded-lg bg-zinc-900/50">
      <header className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium capitalize">{provider.provider}</span>
          <span
            className={`text-[11px] px-1.5 py-0.5 rounded ${
              provider.api_key_set
                ? "bg-emerald-500/15 text-emerald-300"
                : "bg-amber-500/15 text-amber-300"
            }`}
          >
            {keyStatus}
          </span>
        </div>
        {provider.default_model && (
          <span className="text-xs text-zinc-500">
            {t("adminEnvDefault")}: <code>{provider.default_model}</code>
          </span>
        )}
      </header>

      <div className="px-4 py-4 space-y-4">
        <Field label={t("adminApiKey")}>
          <input
            type="password"
            value={d.api_key}
            onChange={(e) =>
              onPatch((x) => ({
                ...x,
                api_key: e.target.value,
                api_key_dirty: true,
                saved: false,
              }))
            }
            placeholder={
              provider.api_key_set ? t("adminApiKeyKeep") : t("adminApiKeyPlaceholder")
            }
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded focus:border-purple-500 outline-none text-sm"
          />
        </Field>

        <Field label={t("adminBaseUrl")}>
          <input
            value={d.base_url}
            onChange={(e) =>
              onPatch((x) => ({ ...x, base_url: e.target.value, saved: false }))
            }
            placeholder={t("adminBaseUrlPlaceholder")}
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded focus:border-purple-500 outline-none text-sm font-mono"
          />
        </Field>

        <Field label={t("adminModels")}>
          <div className="flex flex-wrap gap-1.5 mb-2 min-h-[1.5rem]">
            {d.models.length === 0 && (
              <span className="text-xs text-zinc-500 italic">
                {t("adminNoModels")}
              </span>
            )}
            {d.models.map((m) => (
              <span
                key={m}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-purple-500/15 text-purple-200 border border-purple-500/30"
              >
                <span>{m}</span>
                <button
                  type="button"
                  onClick={() => removeModel(m)}
                  className="text-purple-400 hover:text-red-400"
                  aria-label={t("adminRemoveModel")}
                  title={t("adminRemoveModel")}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={d.new_model}
              onChange={(e) =>
                onPatch((x) => ({ ...x, new_model: e.target.value, saved: false }))
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addModel();
                }
              }}
              placeholder={t("adminAddModelPlaceholder")}
              className="flex-1 px-3 py-2 bg-zinc-900 border border-zinc-700 rounded focus:border-purple-500 outline-none text-sm font-mono"
            />
            <button
              type="button"
              onClick={addModel}
              disabled={!d.new_model.trim()}
              className="px-3 py-2 text-sm rounded bg-zinc-800 hover:bg-zinc-700 disabled:bg-zinc-900 disabled:text-zinc-600"
            >
              {t("adminAddModel")}
            </button>
          </div>
        </Field>

        {d.error && (
          <div className="text-sm text-red-400">{d.error}</div>
        )}

        <div className="flex items-center justify-end gap-3">
          {d.saved && (
            <span className="text-xs text-emerald-400">{t("adminSaved")}</span>
          )}
          <button
            type="button"
            onClick={onSave}
            disabled={d.saving}
            className="px-4 py-2 text-sm rounded bg-purple-600 hover:bg-purple-500 disabled:bg-zinc-700 font-medium"
          >
            {d.saving ? t("adminSaving") : t("adminSave")}
          </button>
        </div>
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-zinc-400 mb-1">{label}</span>
      {children}
    </label>
  );
}
