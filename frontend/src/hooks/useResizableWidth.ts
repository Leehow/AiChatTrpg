import { useCallback, useEffect, useRef, useState } from "react";

interface Options {
  storageKey: string;
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  /** Which edge the drag handle lives on. "right" → dragging right grows
   *  the panel (left rails). "left" → dragging left grows the panel
   *  (right rails). */
  edge: "left" | "right";
}

interface Result {
  width: number;
  isDragging: boolean;
  onResizeStart: (e: React.MouseEvent) => void;
}

function readStored(key: string, fallback: number, min: number, max: number) {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(key);
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

export function useResizableWidth({
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth,
  edge,
}: Options): Result {
  const [width, setWidth] = useState(() =>
    readStored(storageKey, defaultWidth, minWidth, maxWidth)
  );
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(storageKey, String(width));
  }, [storageKey, width]);

  useEffect(() => {
    if (!isDragging) return;
    const handleMove = (e: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const delta = e.clientX - drag.startX;
      const next =
        edge === "right" ? drag.startWidth + delta : drag.startWidth - delta;
      setWidth(Math.min(maxWidth, Math.max(minWidth, next)));
    };
    const handleUp = () => {
      setIsDragging(false);
      dragRef.current = null;
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
  }, [isDragging, edge, minWidth, maxWidth]);

  const onResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startWidth: width };
      setIsDragging(true);
    },
    [width]
  );

  return { width, isDragging, onResizeStart };
}
