/**
 * Renders a TRPG chat-message body with markdown + KaTeX + dialogue spans +
 * semantic blocks. Memoized on `text` so re-renders during streaming only
 * re-parse when content actually changes.
 *
 * The output is dropped into a `<div>` via `dangerouslySetInnerHTML`. All
 * input passes through marked's HTML escaper before reaching here, except
 * for the explicitly-allowed TRPG block tags we generate ourselves.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { renderTrpgMarkdown } from "../../utils/trpgMarkdown";
import type { TrpgSpeakerProfile } from "../../utils/trpgDialogue";

interface Props {
  text: string;
  /** Force TRPG-style dialogue rendering even when no marker is present. */
  forceTrpg?: boolean;
  speakerProfiles?: Record<string, TrpgSpeakerProfile>;
  className?: string;
  /** When true, append a blinking caret to the last text-bearing element so
   *  the player can see the stream is alive. The caret is a real DOM node
   *  injected after render — it survives every re-parse triggered by chunks. */
  streaming?: boolean;
}

interface SpeakerPreview {
  src: string;
  name: string;
  x: number;
  y: number;
  pinned: boolean;
}

const MAX_DICE_DISCLOSURE_STATES = 500;
const diceDisclosureState = new Map<string, boolean>();
let diceDisclosureClickHandlerBound = false;

function hashString(value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function rememberDiceOpenState(key: string, open: boolean) {
  if (!diceDisclosureState.has(key) && diceDisclosureState.size >= MAX_DICE_DISCLOSURE_STATES) {
    const oldest = diceDisclosureState.keys().next().value;
    if (oldest) diceDisclosureState.delete(oldest);
  }
  diceDisclosureState.set(key, open);
}

function elementFromEventTarget(target: EventTarget | null): Element | null {
  return target instanceof Element
    ? target
    : target instanceof Node
      ? target.parentElement
      : null;
}

function fallbackDiceKeyFor(detail: HTMLDetailsElement): string {
  return `global:${hashString((detail.textContent || "").slice(0, 4000))}`;
}

function rememberDiceDetailOpenState(detail: HTMLDetailsElement, open: boolean) {
  rememberDiceOpenState(fallbackDiceKeyFor(detail), open);
  if (detail.dataset.diceKey) {
    rememberDiceOpenState(detail.dataset.diceKey, open);
  }
}

function handleDiceDisclosureClick(event: globalThis.MouseEvent) {
  const targetElement = elementFromEventTarget(event.target);
  const summary = targetElement?.closest("summary.dice-summary");
  if (!summary) return;

  const detail = summary.closest("details.dice-block") as HTMLDetailsElement | null;
  if (!detail) return;

  event.preventDefault();
  event.stopPropagation();
  const nextOpen = !detail.open;
  detail.open = nextOpen;
  rememberDiceDetailOpenState(detail, nextOpen);
}

function ensureDiceDisclosureClickHandler() {
  if (typeof document === "undefined" || diceDisclosureClickHandlerBound) return;
  document.addEventListener("click", handleDiceDisclosureClick, true);
  diceDisclosureClickHandlerBound = true;
}

function diceKeyFor(
  messageText: string,
  detail: HTMLDetailsElement,
  root: HTMLElement,
): string {
  const existing = detail.dataset.diceKey;
  if (existing) return existing;
  const allDiceBlocks = Array.from(root.querySelectorAll<HTMLDetailsElement>("details.dice-block"));
  const index = Math.max(0, allDiceBlocks.indexOf(detail));
  const bodyHash = hashString((detail.textContent || "").slice(0, 4000));
  const key = `${hashString(messageText)}:${index}:${bodyHash}`;
  detail.dataset.diceKey = key;
  return key;
}

const SPEAKER_PREVIEW_WIDTH = 136;
const SPEAKER_PREVIEW_HEIGHT = 156;

function getSpeakerAvatarTarget(target: EventTarget | null): HTMLImageElement | null {
  const element = elementFromEventTarget(target);
  const avatar = element?.closest("img.trpg-speaker-avatar");
  return avatar instanceof HTMLImageElement ? avatar : null;
}

function buildSpeakerPreview(
  avatar: HTMLImageElement,
  point: { clientX: number; clientY: number },
  pinned: boolean,
): SpeakerPreview | null {
  const src = avatar.currentSrc || avatar.src || avatar.getAttribute("src") || "";
  if (!src) return null;
  const dialogue = avatar.closest(".trpg-dialogue") as HTMLElement | null;
  const name =
    avatar.getAttribute("alt")
    || dialogue?.dataset.speaker
    || dialogue?.dataset.npcKey
    || "";
  return {
    src,
    name: name.trim() || "NPC",
    x: point.clientX,
    y: point.clientY,
    pinned,
  };
}

function speakerPreviewPosition(preview: SpeakerPreview) {
  if (typeof window === "undefined") {
    return { left: preview.x + 14, top: preview.y + 14 };
  }

  const gutter = 12;
  const offset = 14;
  let left = preview.x + offset;
  let top = preview.y + offset;

  if (left + SPEAKER_PREVIEW_WIDTH > window.innerWidth - gutter) {
    left = preview.x - SPEAKER_PREVIEW_WIDTH - offset;
  }
  if (top + SPEAKER_PREVIEW_HEIGHT > window.innerHeight - gutter) {
    top = window.innerHeight - SPEAKER_PREVIEW_HEIGHT - gutter;
  }

  return {
    left: Math.max(gutter, left),
    top: Math.max(gutter, top),
  };
}

function isTouchLikeClick(event: MouseEvent<HTMLDivElement>): boolean {
  const native = event.nativeEvent as globalThis.MouseEvent & { pointerType?: string };
  if (native.pointerType === "touch" || native.pointerType === "pen") return true;
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(hover: none), (pointer: coarse)").matches;
}

export function TrpgMessage({
  text,
  forceTrpg = true,
  speakerProfiles,
  className,
  streaming = false,
}: Props) {
  ensureDiceDisclosureClickHandler();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [speakerPreview, setSpeakerPreview] = useState<SpeakerPreview | null>(null);
  const html = useMemo(
    () => renderTrpgMarkdown(text || "", { forceTrpg, speakerProfiles }),
    [text, forceTrpg, speakerProfiles],
  );

  useLayoutEffect(() => {
    if (!streaming) return;
    const root = rootRef.current;
    if (!root) return;
    // Walk to the deepest last child that can host inline content. Stops at
    // <details>, <table>, etc. — those would render the caret in the wrong
    // visual spot. For typical narrative prose the host is the last <p>, <li>,
    // or <span>; otherwise we fall back to root.
    const blockBoundaries = new Set([
      "DETAILS", "TABLE", "THEAD", "TBODY", "TR", "UL", "OL", "PRE", "BLOCKQUOTE", "HR",
    ]);
    let host: Element = root;
    while (true) {
      const last = host.lastElementChild;
      if (!last || blockBoundaries.has(last.tagName)) break;
      host = last;
    }
    const caret = document.createElement("span");
    caret.className = "streaming-cursor";
    caret.setAttribute("aria-hidden", "true");
    host.appendChild(caret);
    return () => {
      caret.remove();
    };
  }, [streaming, html]);

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const cleanups: Array<() => void> = [];
    const diceBlocks = Array.from(root.querySelectorAll<HTMLDetailsElement>("details.dice-block"));
    diceBlocks.forEach((detail) => {
      const key = diceKeyFor(text || "", detail, root);
      const fallbackKey = fallbackDiceKeyFor(detail);
      const savedOpen = diceDisclosureState.get(key) ?? diceDisclosureState.get(fallbackKey);
      if (savedOpen !== undefined && detail.open !== savedOpen) {
        detail.open = savedOpen;
      }
      const onToggle = () => {
        rememberDiceOpenState(key, detail.open);
        rememberDiceOpenState(fallbackKey, detail.open);
      };
      detail.addEventListener("toggle", onToggle);
      cleanups.push(() => detail.removeEventListener("toggle", onToggle));
    });
    return () => cleanups.forEach((cleanup) => cleanup());
  });

  useEffect(() => {
    if (!speakerPreview?.pinned) return undefined;
    const closePinnedPreview = (event: PointerEvent) => {
      if (getSpeakerAvatarTarget(event.target)) return;
      setSpeakerPreview(null);
    };
    document.addEventListener("pointerdown", closePinnedPreview, true);
    return () => document.removeEventListener("pointerdown", closePinnedPreview, true);
  }, [speakerPreview?.pinned]);

  useEffect(() => {
    if (!speakerPreview || speakerPreview.pinned) return undefined;
    const closeHoverPreview = (event: PointerEvent) => {
      if (getSpeakerAvatarTarget(event.target)) return;
      setSpeakerPreview(null);
    };
    document.addEventListener("pointermove", closeHoverPreview, true);
    return () => document.removeEventListener("pointermove", closeHoverPreview, true);
  }, [speakerPreview]);

  function handleBodyMouseOver(event: MouseEvent<HTMLDivElement>) {
    const root = rootRef.current;
    const avatar = getSpeakerAvatarTarget(event.target);
    if (!root || !avatar || !root.contains(avatar)) return;
    const nextPreview = buildSpeakerPreview(avatar, event, false);
    if (nextPreview) setSpeakerPreview(nextPreview);
  }

  function handleBodyMouseMove(event: MouseEvent<HTMLDivElement>) {
    const root = rootRef.current;
    const avatar = getSpeakerAvatarTarget(event.target);
    if (!root || !avatar || !root.contains(avatar)) {
      setSpeakerPreview((current) => (current?.pinned ? current : null));
      return;
    }
    setSpeakerPreview((current) => {
      if (!current || current.pinned) return current;
      return { ...current, x: event.clientX, y: event.clientY };
    });
  }

  function handleBodyMouseOut(event: MouseEvent<HTMLDivElement>) {
    const root = rootRef.current;
    const avatar = getSpeakerAvatarTarget(event.target);
    if (!root || !avatar || !root.contains(avatar)) return;
    const relatedTarget = event.relatedTarget;
    if (relatedTarget instanceof Node && avatar.contains(relatedTarget)) return;
    setSpeakerPreview((current) => (current?.pinned ? current : null));
  }

  function handleBodyClick(event: MouseEvent<HTMLDivElement>) {
    const root = rootRef.current;
    const target = event.target;
    const avatar = getSpeakerAvatarTarget(target);
    if (!root || !avatar || !root.contains(avatar)) return;
    if (!isTouchLikeClick(event)) return;
    const nextPreview = buildSpeakerPreview(avatar, event, true);
    if (!nextPreview) return;
    event.preventDefault();
    event.stopPropagation();
    setSpeakerPreview((current) => (
      current?.pinned && current.src === nextPreview.src && current.name === nextPreview.name
        ? null
        : nextPreview
    ));
  }

  const previewPosition = speakerPreview ? speakerPreviewPosition(speakerPreview) : null;

  return (
    <>
      <div
        ref={rootRef}
        className={["trpg-prose", className].filter(Boolean).join(" ")}
        onClick={handleBodyClick}
        onMouseOver={handleBodyMouseOver}
        onMouseMove={handleBodyMouseMove}
        onMouseOut={handleBodyMouseOut}
        dangerouslySetInnerHTML={{ __html: html }}
      />
      {speakerPreview && previewPosition && (
        <div
          className="fixed z-[80] w-[136px] pointer-events-none rounded-md border border-black/10 bg-surface/95 p-2 shadow-xl backdrop-blur"
          style={previewPosition}
          role="tooltip"
        >
          <img
            src={speakerPreview.src}
            alt={speakerPreview.name}
            className="mx-auto h-24 w-24 rounded-full object-cover object-top bg-surface-2"
          />
          <div className="mt-2 max-h-10 overflow-hidden text-center text-xs font-medium leading-snug text-text-1">
            {speakerPreview.name}
          </div>
        </div>
      )}
    </>
  );
}
