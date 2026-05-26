import { useEffect, useRef } from "react";

// Singleton wrapper around @3d-dice/dice-box, written from its README API.
// Keeps one DiceBox instance + DOM container across the whole app so we don't
// re-init BabylonJS on every modal open.

const CONTAINER_ID = "chatrpg-dice-box";
const ASSET_PATH = "/assets/dice-box/";
const DEFAULT_AUTO_CLOSE_MS = 2500;

interface DiceBoxLib {
  init: () => Promise<void>;
  roll: (notation: string) => Promise<DiceRollEntry[]>;
  clear: () => void;
}

interface DiceRollEntry {
  value?: number;
  sides?: number;
  groupId?: number;
}

let instance: DiceBoxLib | null = null;
let initPromise: Promise<DiceBoxLib> | null = null;
let stylesInjected = false;

function injectStyles() {
  if (stylesInjected || typeof document === "undefined") return;
  stylesInjected = true;
  const style = document.createElement("style");
  style.textContent = `
    #${CONTAINER_ID} {
      position: fixed;
      inset: 0;
      z-index: -1;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s ease;
    }
    #${CONTAINER_ID}.is-active {
      z-index: 10000;
      opacity: 1;
      pointer-events: auto;
      cursor: pointer;
    }
    #${CONTAINER_ID} canvas {
      width: 100% !important;
      height: 100% !important;
      display: block;
    }
  `;
  document.head.appendChild(style);
}

function ensureContainer(): HTMLDivElement {
  injectStyles();
  let el = document.getElementById(CONTAINER_ID) as HTMLDivElement | null;
  if (el) return el;
  el = document.createElement("div");
  el.id = CONTAINER_ID;
  document.body.appendChild(el);
  return el;
}

async function getInstance(): Promise<DiceBoxLib> {
  if (instance) return instance;
  if (initPromise) return initPromise;
  ensureContainer();
  initPromise = (async () => {
    const { default: DiceBox } = await import("@3d-dice/dice-box");
    const box = new DiceBox(`#${CONTAINER_ID}`, {
      assetPath: ASSET_PATH,
      theme: "default",
      scale: 6,
      gravity: 1.5,
      throwForce: 5,
      spinForce: 4,
      startingHeight: 8,
      offscreen: false,
    });
    await box.init();
    instance = box;
    return box;
  })();
  return initPromise;
}

export interface DiceRollResult {
  total: number;
  rolls: number[];
}

interface DiceBox3DProps {
  visible: boolean;
  notation: string;
  onResult?: (r: DiceRollResult) => void;
  onClose?: () => void;
  /** How long the result stays on screen before auto-close fires. */
  autoCloseDelay?: number;
}

export function DiceBox3D({
  visible,
  notation,
  onResult,
  onClose,
  autoCloseDelay = DEFAULT_AUTO_CLOSE_MS,
}: DiceBox3DProps) {
  // Each visible→true cycle gets a fresh roll id. Async callbacks compare
  // against this so a stale roll from the previous open can't fire after the
  // user has dismissed and re-opened.
  const rollIdRef = useRef(0);
  const closeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current);
    };
  }, []);

  // Click-to-dismiss while the overlay is up.
  useEffect(() => {
    if (!visible) return;
    const el = ensureContainer();
    const handler = () => onClose?.();
    el.addEventListener("click", handler);
    return () => el.removeEventListener("click", handler);
  }, [visible, onClose]);

  useEffect(() => {
    const el = ensureContainer();
    if (!visible) {
      rollIdRef.current += 1;
      el.classList.remove("is-active");
      if (closeTimerRef.current) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
      if (instance) {
        try {
          instance.clear();
        } catch {
          // The library throws here if init hasn't completed; safe to ignore.
        }
      }
      return;
    }

    const myId = ++rollIdRef.current;
    el.classList.add("is-active");

    void (async () => {
      try {
        const box = await getInstance();
        if (rollIdRef.current !== myId) return;
        box.clear();
        const results = await box.roll(notation);
        if (rollIdRef.current !== myId) return;
        const rolls = (results ?? []).map((r) => Number(r?.value ?? 0));
        const total = rolls.reduce((a, b) => a + b, 0);
        onResult?.({ total, rolls });
        closeTimerRef.current = window.setTimeout(() => {
          if (rollIdRef.current === myId) onClose?.();
        }, autoCloseDelay);
      } catch (err) {
        console.error("[chatrpg] dice-box roll failed:", err);
        closeTimerRef.current = window.setTimeout(() => {
          if (rollIdRef.current === myId) onClose?.();
        }, 600);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, notation]);

  return null;
}

export default DiceBox3D;
