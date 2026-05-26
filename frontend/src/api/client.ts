// Tiny API client. Reset to scaffolding — only health + admin endpoints exist
// while the TRPG runtime is being redesigned from scratch.

import { apiFetch, getStoredToken } from "./http";
import type {
  AdminProvider,
  AdminProviderUpdate,
  Health,
  ListModelsRequest,
  ListModelsResponse,
  LLMProviderInfo,
  LLMTestRequest,
  LLMTestResponse,
  MediaSettings,
  MediaTtsRequest,
  MediaTtsResponse,
  MediaVoiceListResponse,
  PoolAddRequest,
  PoolEntry,
  PoolView,
  ModuleParseResponse,
  ModuleSummary,
  OCRHealthResponse,
  OCRProviderInfo,
  OCRProviderUpdate,
  OCRTestResponse,
} from "./types";

export const api = {
  health: () => apiFetch<Health>(`/api/health`),

  listAdminProviders: () => apiFetch<AdminProvider[]>(`/api/admin/providers`),
  updateAdminProvider: (provider: string, body: AdminProviderUpdate) =>
    apiFetch<AdminProvider>(`/api/admin/providers/${provider}`, {
      method: "PUT",
      json: body,
    }),
  listAdminModels: () =>
    apiFetch<Record<string, string[]>>(`/api/admin/models`),

  listLLMProviders: () => apiFetch<LLMProviderInfo[]>(`/api/llm/providers`),
  testLLM: (body: LLMTestRequest) =>
    apiFetch<LLMTestResponse>(`/api/llm/test`, {
      method: "POST",
      json: body,
    }),
  listProviderModels: (body: ListModelsRequest) =>
    apiFetch<ListModelsResponse>(`/api/llm/models`, {
      method: "POST",
      json: body,
    }),

  getModelPool: () => apiFetch<PoolView>(`/api/llm/pool`),
  addToPool: (body: PoolAddRequest) =>
    apiFetch<PoolView>(`/api/llm/pool/add`, { method: "POST", json: body }),
  removeFromPool: (body: PoolEntry) =>
    apiFetch<PoolView>(`/api/llm/pool/remove`, { method: "POST", json: body }),
  setPoolDefault: (body: PoolEntry) =>
    apiFetch<PoolView>(`/api/llm/pool/default`, { method: "POST", json: body }),
  setPoolFast: (body: PoolEntry) =>
    apiFetch<PoolView>(`/api/llm/pool/fast`, { method: "POST", json: body }),
  setPoolDialogue: (body: PoolEntry) =>
    apiFetch<PoolView>(`/api/llm/pool/dialogue`, { method: "POST", json: body }),
  setPoolAvatar: (body: PoolEntry) =>
    apiFetch<PoolView>(`/api/llm/pool/avatar`, { method: "POST", json: body }),
  setPoolIllustration: (body: PoolEntry) =>
    apiFetch<PoolView>(`/api/llm/pool/illustration`, { method: "POST", json: body }),
  setPoolNarration: (body: PoolEntry) =>
    apiFetch<PoolView>(`/api/llm/pool/narration`, { method: "POST", json: body }),

  listMediaVoices: (entry: PoolEntry, live = true) => {
    const params = new URLSearchParams({
      provider: entry.provider,
      model: entry.model,
      live: String(live),
    });
    return apiFetch<MediaVoiceListResponse>(`/api/media/voices?${params}`);
  },
  getMediaSettings: () => apiFetch<MediaSettings>(`/api/media/settings`),
  updateMediaSettings: (body: MediaSettings) =>
    apiFetch<MediaSettings>(`/api/media/settings`, { method: "PUT", json: body }),
  synthesizeMediaSpeech: (body: MediaTtsRequest) =>
    apiFetch<MediaTtsResponse>(`/api/media/tts`, { method: "POST", json: body }),

  listOCRProviders: () => apiFetch<OCRProviderInfo[]>(`/api/ocr/providers`),
  updateOCRProvider: (provider: string, body: OCRProviderUpdate) =>
    apiFetch<OCRProviderInfo>(`/api/ocr/providers/${provider}`, {
      method: "PUT",
      json: body,
    }),
  ocrProviderHealth: (provider: string) =>
    apiFetch<OCRHealthResponse>(`/api/ocr/providers/${provider}/health`),
  parseModule: async (file: File): Promise<ModuleParseResponse> => {
    const form = new FormData();
    form.append("file", file);
    const headers: Record<string, string> = {};
    const token = getStoredToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`/api/modules/parse`, {
      method: "POST",
      headers,
      body: form,
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body && typeof body === "object" && "detail" in body) {
          detail = String((body as { detail: unknown }).detail);
        }
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    return (await res.json()) as ModuleParseResponse;
  },
  parseModuleStream: async (
    file: File,
    handlers: {
      onLog?: (line: string) => void;
      onProgress?: (page: number, total: number, line: string) => void;
      onStage?: (stage: string, info: Record<string, unknown>) => void;
      onTocChunk?: (delta: string, totalChars: number) => void;
    },
    signal?: AbortSignal
  ): Promise<ModuleParseResponse> => {
    // Use fetch-event-source so we can POST a multipart body alongside
    // an Authorization header — neither possible with browser EventSource.
    const { fetchEventSource } = await import("@microsoft/fetch-event-source");
    const form = new FormData();
    form.append("file", file);
    const headers: Record<string, string> = {};
    const token = getStoredToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    return new Promise<ModuleParseResponse>((resolve, reject) => {
      let resolved = false;
      void fetchEventSource(`/api/modules/parse-stream`, {
        method: "POST",
        headers,
        body: form,
        signal,
        openWhenHidden: true,
        async onopen(res) {
          if (!res.ok) {
            let detail = `${res.status} ${res.statusText}`;
            try {
              const body = await res.json();
              if (body && typeof body === "object" && "detail" in body) {
                detail = String((body as { detail: unknown }).detail);
              }
            } catch {
              // ignore
            }
            reject(new Error(detail));
            throw new Error(detail);
          }
        },
        onmessage(msg) {
          if (!msg.data) return;
          let event: {
            type:
              | "log"
              | "progress"
              | "stage"
              | "toc_chunk"
              | "done"
              | "error";
            line?: string;
            page?: number;
            total?: number;
            stage?: string;
            delta?: string;
            total_chars?: number;
            result?: ModuleParseResponse;
            message?: string;
            [k: string]: unknown;
          };
          try {
            event = JSON.parse(msg.data);
          } catch {
            return;
          }
          if (event.type === "log") {
            handlers.onLog?.(event.line || "");
          } else if (event.type === "progress") {
            handlers.onProgress?.(
              event.page || 0,
              event.total || 0,
              event.line || ""
            );
          } else if (event.type === "stage") {
            handlers.onStage?.(event.stage || "", event);
          } else if (event.type === "toc_chunk") {
            handlers.onTocChunk?.(event.delta || "", event.total_chars || 0);
          } else if (event.type === "done" && event.result) {
            resolved = true;
            resolve(event.result);
          } else if (event.type === "error") {
            resolved = true;
            reject(new Error(event.message || "parse failed"));
          }
        },
        onerror(err) {
          if (!resolved) reject(err);
          throw err; // stop retries
        },
        onclose() {
          if (!resolved) reject(new Error("stream closed without result"));
        },
      });
    });
  },
  acceptedModuleExtensions: () =>
    apiFetch<string[]>(`/api/modules/accepted-extensions`),
  listModules: () => apiFetch<ModuleSummary[]>(`/api/modules`),
  getModule: (id: string) =>
    apiFetch<ModuleParseResponse>(`/api/modules/${id}`),
  parseModuleSemantics: (id: string) =>
    apiFetch<ModuleParseResponse>(`/api/modules/${id}/semantic/parse`, {
      method: "POST",
    }),
  deleteModule: (id: string) =>
    apiFetch<null>(`/api/modules/${id}`, { method: "DELETE" }),
  setModuleShared: (id: string, isShared: boolean) =>
    apiFetch<ModuleSummary>(`/api/modules/${id}/share`, {
      method: "POST",
      json: { is_shared: isShared },
    }),
  // Pass `moduleId` whenever the parsed module has been persisted — the
  // backend caches the LLM-cleaned title on that row so repeat calls
  // return instantly. Pass `filename`+`markdown` for one-shot extraction
  // when no row exists yet.
  extractModuleTitle: (
    body: { moduleId: string } | { filename: string; markdown: string }
  ) => {
    const json =
      "moduleId" in body
        ? { module_id: body.moduleId }
        : { filename: body.filename, markdown: body.markdown };
    return apiFetch<{ title: string; cached: boolean }>(
      `/api/modules/extract-title`,
      { method: "POST", json }
    );
  },

  testOCR: async (provider: string, file: File): Promise<OCRTestResponse> => {
    // Multipart upload — bypass apiFetch's JSON helper but reuse its
    // auth pattern by attaching the Bearer token manually.
    const form = new FormData();
    form.append("provider", provider);
    form.append("file", file);
    const headers: Record<string, string> = {};
    const token = getStoredToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`/api/ocr/test`, {
      method: "POST",
      headers,
      body: form,
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body && typeof body === "object" && "detail" in body) {
          detail = String((body as { detail: unknown }).detail);
        }
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    return (await res.json()) as OCRTestResponse;
  },
};
