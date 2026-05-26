/**
 * Per-(ruleset, node) fold state for character-card sections.
 *
 * Persistence flows like MusicPlayer's `music_settings`: read once from
 * the cached `StoredUser.preferences`, hold the live map in module
 * state with subscribers, debounce a partial-merge POST to
 * `/api/auth/preferences` so the same account picks up the choice on
 * other devices.
 *
 * Pref shape:  preferences.character_ui_fold[systemId][nodeId] = "open" | "closed"
 */
import { useEffect, useState } from "react";
import { updatePreferencesAPI } from "../../api/auth";
import { getStoredUser } from "../../api/http";

const PREFS_KEY = "character_ui_fold";
type FoldState = "open" | "closed";
type FoldMap = Record<string, Record<string, FoldState>>;

function readInitial(): FoldMap {
  const user = getStoredUser();
  const raw = user?.preferences?.[PREFS_KEY];
  if (!raw || typeof raw !== "object") return {};
  const out: FoldMap = {};
  for (const [sys, inner] of Object.entries(raw as Record<string, unknown>)) {
    if (!inner || typeof inner !== "object") continue;
    const bucket: Record<string, FoldState> = {};
    for (const [k, v] of Object.entries(inner as Record<string, unknown>)) {
      if (v === "open" || v === "closed") bucket[k] = v;
    }
    out[sys] = bucket;
  }
  return out;
}

let foldMap: FoldMap = readInitial();
const subscribers = new Set<() => void>();

function notify() {
  for (const s of subscribers) s();
}

let pushTimer: number | null = null;
function schedulePush() {
  if (pushTimer != null) window.clearTimeout(pushTimer);
  pushTimer = window.setTimeout(() => {
    pushTimer = null;
    void updatePreferencesAPI({ [PREFS_KEY]: foldMap }).catch((err) => {
      console.warn("[chatrpg] persist character_ui_fold failed:", err);
    });
  }, 500);
}

function getState(systemId: string, nodeId: string): FoldState | undefined {
  return foldMap[systemId]?.[nodeId];
}

function setState(systemId: string, nodeId: string, value: FoldState) {
  const prev = foldMap[systemId]?.[nodeId];
  if (prev === value) return;
  const nextSys = { ...(foldMap[systemId] || {}), [nodeId]: value };
  foldMap = { ...foldMap, [systemId]: nextSys };
  notify();
  schedulePush();
}

/**
 * `defaultOpen` is consulted only when the user has no stored preference
 * for this (system, node) pair. Once they click, their choice sticks.
 */
export function useFoldPref(
  systemId: string,
  nodeId: string,
  defaultOpen: boolean,
): { open: boolean; toggle: () => void } {
  const [, force] = useState(0);
  useEffect(() => {
    const sub = () => force((n) => n + 1);
    subscribers.add(sub);
    return () => {
      subscribers.delete(sub);
    };
  }, []);
  const stored = getState(systemId, nodeId);
  const open = stored === undefined ? defaultOpen : stored === "open";
  const toggle = () => setState(systemId, nodeId, open ? "closed" : "open");
  return { open, toggle };
}
