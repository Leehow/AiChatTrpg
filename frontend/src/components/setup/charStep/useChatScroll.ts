import { useCallback, useEffect, useRef, useState } from "react";

export function useChatScroll({ active }: { active: boolean }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [showJumpDown, setShowJumpDown] = useState(false);

  useEffect(() => {
    if (!active) return;
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      const atBottom = distance <= 32;
      atBottomRef.current = atBottom;
      setShowJumpDown(!atBottom);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [active]);

  const jumpToLatest = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    atBottomRef.current = true;
    setShowJumpDown(false);
  }, []);

  return { scrollRef, atBottomRef, showJumpDown, jumpToLatest };
}
