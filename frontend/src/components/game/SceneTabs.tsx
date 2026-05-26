import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import type { ChatMessage } from "./Message";

// Scene timeline strip rendered above the chat. Buckets the message list by
// scene so the player can jump back to character creation or any past scene
// like flipping through chapter tabs. Visible chips are kept short
// (prev / current / next) — the rest live behind a dropdown so the strip
// stays readable even after dozens of scene transitions.

export interface SceneVisit {
  // First IC-or-guide message id of this contiguous visit. We anchor scroll
  // here when the player opens a multi-visit tab so the most recent return
  // beat is the entry point, with the older visits readable by scrolling up.
  startMessageId: string;
  startCreatedAt: string;
  // ISO timestamp of the message right BEFORE this visit started (i.e. when
  // the player was last in some other scene). Empty for the first visit.
  prevLeftAt: string;
}

export interface SceneBucket {
  key: string;             // stable identity ("__guide__" | scene_key | unnamed#N)
  label: string;           // human-readable; falls back to scene_key
  messageIds: Set<string>; // membership lookup for filtering
  isGuide: boolean;        // character-creation bucket
  visits: SceneVisit[];    // contiguous visit segments, in chronological order
}

const GUIDE_KEY = "__guide__";
const SET_SCENE_RE = /\[SET_SCENE([^\]]*)\]([\s\S]*?)\[\/SET_SCENE\]/g;
const SCENE_ATTR_RE = /\b(?:scene|to)\s*=\s*"?([\w\-:.]+)"?/i;

interface MarkerHit {
  key: string;
  name: string;
  at: string; // ISO timestamp of the GM message that emitted the marker
}

// Pull every [SET_SCENE scene=key]Display Name[/SET_SCENE] out of the GM
// timeline so we can backfill scenes for messages that predate the backend
// scene_key tagging. Only GM messages can change scene, so we ignore others.
function extractSceneMarkers(messages: ChatMessage[]): MarkerHit[] {
  const hits: MarkerHit[] = [];
  for (const m of messages) {
    if (m.role !== "gm" || !m.text || !m.createdAt) continue;
    SET_SCENE_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = SET_SCENE_RE.exec(m.text)) !== null) {
      const attrs = match[1] || "";
      const body = (match[2] || "").trim();
      const keyMatch = attrs.match(SCENE_ATTR_RE);
      const key = keyMatch?.[1]?.trim() || "";
      if (!key) continue;
      hits.push({ key, name: body || key, at: m.createdAt });
    }
  }
  hits.sort((a, b) => a.at.localeCompare(b.at));
  return hits;
}

export function buildBuckets(
  messages: ChatMessage[],
  labels: { guide: string; unnamed: string },
): SceneBucket[] {
  const guide: SceneBucket = {
    key: GUIDE_KEY, label: labels.guide,
    messageIds: new Set(), isGuide: true, visits: [],
  };
  const byKey = new Map<string, SceneBucket>();
  const nameByKey = new Map<string, string>();

  const markers = extractSceneMarkers(messages);
  for (const hit of markers) {
    if (hit.name) nameByKey.set(hit.key, hit.name);
  }

  function ensureBucket(key: string, fallbackName: string): SceneBucket {
    let b = byKey.get(key);
    if (!b) {
      b = {
        key,
        label: nameByKey.get(key) || fallbackName || labels.unnamed,
        messageIds: new Set(),
        isGuide: false,
        visits: [],
      };
      byKey.set(key, b);
    } else if (!b.label || b.label === labels.unnamed) {
      const better = nameByKey.get(key) || fallbackName;
      if (better) b.label = better;
    }
    return b;
  }

  let activeKey = "";
  let activeName = "";
  let markerIdx = 0;
  // Track the bucket the previous message landed in so we can detect a return:
  // when the current message lands in a bucket different from `lastBucketKey`
  // AND that bucket already has earlier messages, that's a re-visit.
  let lastBucketKey = "";
  let lastCreatedAt = "";
  for (const m of messages) {
    while (
      markerIdx < markers.length
      && (!m.createdAt || markers[markerIdx].at <= m.createdAt)
    ) {
      activeKey = markers[markerIdx].key;
      activeName = markers[markerIdx].name;
      markerIdx++;
    }

    let landedKey = "";
    let landedBucket: SceneBucket;
    if (m.phase === "guide") {
      landedKey = GUIDE_KEY;
      landedBucket = guide;
    } else {
      const key = m.sceneKey || activeKey || "";
      if (!key) {
        landedKey = GUIDE_KEY;
        landedBucket = guide;
      } else {
        const fallbackName = m.sceneName || activeName || key;
        landedBucket = ensureBucket(key, fallbackName);
        landedKey = key;
      }
    }

    // First message ever in this bucket → visit #1. Or, returning to a bucket
    // we left earlier → start a new visit.
    const isFirstEntryEver = landedBucket.messageIds.size === 0;
    const isReturn = !isFirstEntryEver
      && lastBucketKey !== ""
      && lastBucketKey !== landedKey;
    if (isFirstEntryEver || isReturn) {
      landedBucket.visits.push({
        startMessageId: m.id,
        startCreatedAt: m.createdAt || "",
        prevLeftAt: isReturn ? lastCreatedAt : "",
      });
    }
    landedBucket.messageIds.add(m.id);
    lastBucketKey = landedKey;
    if (m.createdAt) lastCreatedAt = m.createdAt;
  }

  const all: SceneBucket[] = [];
  if (guide.messageIds.size > 0) all.push(guide);
  for (const b of byKey.values()) all.push(b);
  return all;
}

interface Props {
  messages: ChatMessage[];
  activeKey: string | null; // null = follow latest
  onSelect: (key: string) => void;
}

const VISIBLE_NEIGHBORS = 1; // chips shown each side of "current"

export function SceneTabs({ messages, activeKey, onSelect }: Props) {
  const { t } = useI18n();
  const buckets = useMemo(
    () => buildBuckets(messages, {
      guide: t("sceneTabsCharacterCreation"),
      unnamed: t("sceneTabsUnnamed"),
    }),
    [messages, t],
  );

  if (buckets.length <= 1) return null; // nothing to switch between yet

  const latestKey = buckets[buckets.length - 1].key;
  const selectedKey = activeKey ?? latestKey;
  const selectedIdx = Math.max(
    0, buckets.findIndex((b) => b.key === selectedKey),
  );

  // Visible window: previous, current, next. Always include the latest so the
  // player can jump back to "now" with one click even when scrolled deep
  // into history.
  const visibleIndices = new Set<number>();
  for (
    let i = Math.max(0, selectedIdx - VISIBLE_NEIGHBORS);
    i <= Math.min(buckets.length - 1, selectedIdx + VISIBLE_NEIGHBORS);
    i++
  ) {
    visibleIndices.add(i);
  }
  visibleIndices.add(buckets.length - 1);
  visibleIndices.add(0);
  const overflow = buckets.length > visibleIndices.size;

  return (
    <div className="flex items-center gap-1 px-3 py-1.5 border-b border-border bg-bg/80 backdrop-blur-sm overflow-x-auto">
      {[...visibleIndices].sort((a, b) => a - b).map((idx) => (
        <SceneChip
          key={buckets[idx].key}
          bucket={buckets[idx]}
          isActive={idx === selectedIdx}
          isLatest={idx === buckets.length - 1}
          onClick={() => onSelect(buckets[idx].key)}
        />
      ))}
      {overflow && (
        <SceneOverflowMenu
          buckets={buckets}
          selectedIdx={selectedIdx}
          latestKey={latestKey}
          onSelect={onSelect}
          allLabel={t("sceneTabsAll")}
          currentLabel={t("sceneTabsCurrent")}
        />
      )}
    </div>
  );
}


function SceneChip({
  bucket, isActive, isLatest, onClick,
}: {
  bucket: SceneBucket;
  isActive: boolean;
  isLatest: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={bucket.label}
      className={[
        "shrink-0 max-w-[160px] truncate",
        "px-2.5 py-1 rounded-full text-[12px] transition-colors",
        "border",
        isActive
          ? "bg-accent-dim text-[var(--accent-text)] border-accent-dim font-medium"
          : "bg-surface text-text-2 border-border hover:bg-surface-2",
      ].join(" ")}
    >
      {isLatest && !isActive && (
        <span
          className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle"
          style={{ background: "var(--accent)" }}
          aria-hidden="true"
        />
      )}
      <span className="align-middle">{bucket.label}</span>
    </button>
  );
}


function SceneOverflowMenu({
  buckets, selectedIdx, latestKey, onSelect, allLabel, currentLabel,
}: {
  buckets: SceneBucket[];
  selectedIdx: number;
  latestKey: string;
  onSelect: (key: string) => void;
  allLabel: string;
  currentLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div ref={menuRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={allLabel}
        aria-label={allLabel}
        className={[
          "px-2 py-1 rounded-full border text-[12px] transition-colors",
          open
            ? "bg-surface-2 border-border-2 text-text"
            : "bg-surface border-border text-text-2 hover:bg-surface-2",
        ].join(" ")}
      >
        ⋯
      </button>
      {open && (
        <div
          className={[
            "absolute right-0 top-full mt-1 z-30",
            "min-w-[200px] max-w-[280px] max-h-[320px] overflow-y-auto",
            "rounded-lg border border-border bg-surface",
            "shadow-[0_8px_24px_var(--shadow-md)]",
            "py-1",
          ].join(" ")}
          role="menu"
        >
          {buckets.map((b, idx) => {
            const isActive = idx === selectedIdx;
            const isLatest = b.key === latestKey;
            return (
              <button
                key={b.key}
                type="button"
                role="menuitem"
                onClick={() => { onSelect(b.key); setOpen(false); }}
                title={b.label}
                className={[
                  "w-full text-left px-3 py-1.5 text-[12px] flex items-center gap-2",
                  "transition-colors",
                  isActive
                    ? "bg-accent-dim text-[var(--accent-text)]"
                    : "text-text-2 hover:bg-surface-2",
                ].join(" ")}
              >
                {isLatest ? (
                  <span
                    className="inline-block w-1.5 h-1.5 rounded-full"
                    style={{ background: "var(--accent)" }}
                    aria-hidden="true"
                  />
                ) : (
                  <span className="inline-block w-1.5 h-1.5" aria-hidden="true" />
                )}
                <span className="truncate flex-1">{b.label}</span>
                {isLatest && (
                  <span className="text-[10px] uppercase tracking-wide opacity-60">
                    {currentLabel}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
