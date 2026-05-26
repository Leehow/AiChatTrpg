// Tiny pub-sub store for the most-recently-parsed module. Mirrors the
// auth pattern in api/http.ts — localStorage as durable state, a window
// event for cross-component sync. We only ever hold *one* module at a
// time; uploading another replaces it.
//
// Why not Zustand: chatrpg has no state library installed, and the
// surface area here is tiny. Adding a dependency would be overkill.

import type { ModuleParseResponse } from "../../api/types";

const STORAGE_KEY = "chatrpg.module.parsed";
const EVENT_NAME = "chatrpg-module-changed";

export function loadModule(): ModuleParseResponse | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as ModuleParseResponse;
    // The store used to hold pre-DB format entries with no `id` field.
    // Drop those silently — the user has been told to re-upload, and
    // dragging stale data forward would just confuse the debug tab.
    if (!parsed || typeof parsed !== "object" || !parsed.id) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function setModule(module: ModuleParseResponse | null): void {
  if (typeof window === "undefined") return;
  if (module === null) {
    window.localStorage.removeItem(STORAGE_KEY);
  } else {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(module));
  }
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function onModuleChanged(handler: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(EVENT_NAME, handler);
  // Cross-tab sync: the storage event fires in *other* tabs when this
  // one writes, complementing the in-tab dispatch above.
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(EVENT_NAME, handler);
    window.removeEventListener("storage", handler);
  };
}
