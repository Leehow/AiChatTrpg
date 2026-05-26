import { useEffect, useRef, useState } from "react";

// CSS 3D coin flip for d2 — @3d-dice/dice-box has no d2 model so we render
// our own. Result is a plain Math.random; the 3D-looking spin is purely
// presentation.

interface CoinFlipProps {
  visible: boolean;
  onResult?: (value: 1 | 2) => void;
  onClose?: () => void;
  autoCloseDelay?: number;
}

const FLIP_DURATION_MS = 1700;
const DEFAULT_AUTO_CLOSE_MS = 2200;

type Phase = "idle" | "flipping" | "settled";

export function CoinFlip({
  visible,
  onResult,
  onClose,
  autoCloseDelay = DEFAULT_AUTO_CLOSE_MS,
}: CoinFlipProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [rotateDeg, setRotateDeg] = useState(0);
  const [result, setResult] = useState<1 | 2 | null>(null);
  const animTimerRef = useRef<number | null>(null);
  const closeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!visible) {
      setPhase("idle");
      setResult(null);
      setRotateDeg(0);
      if (animTimerRef.current) window.clearTimeout(animTimerRef.current);
      if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current);
      return;
    }

    const value: 1 | 2 = Math.random() < 0.5 ? 1 : 2;
    const fullRotations = 4 + Math.floor(Math.random() * 3);
    const target = fullRotations * 360 + (value === 2 ? 180 : 0);

    setPhase("flipping");
    setResult(null);
    setRotateDeg(target);

    animTimerRef.current = window.setTimeout(() => {
      setPhase("settled");
      setResult(value);
      onResult?.(value);
      if (autoCloseDelay > 0) {
        closeTimerRef.current = window.setTimeout(() => {
          onClose?.();
        }, autoCloseDelay);
      }
    }, FLIP_DURATION_MS);

    return () => {
      if (animTimerRef.current) window.clearTimeout(animTimerRef.current);
      if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  if (!visible) return null;

  const dismiss = () => {
    if (animTimerRef.current) window.clearTimeout(animTimerRef.current);
    if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current);
    onClose?.();
  };

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center cursor-pointer"
      onClick={dismiss}
    >
      <div
        style={{ perspective: "900px" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="w-32 h-32 relative"
          style={{
            transformStyle: "preserve-3d",
            transform: `rotateX(${rotateDeg}deg)`,
            transition:
              phase === "flipping"
                ? `transform ${FLIP_DURATION_MS}ms cubic-bezier(0.22, 0.72, 0.31, 1)`
                : "none",
          }}
        >
          <div
            className="absolute inset-0 rounded-full flex items-center justify-center border-4 select-none"
            style={{
              backfaceVisibility: "hidden",
              background: "linear-gradient(135deg, #fbbf24, #d97706)",
              borderColor: "#7c2d12",
              color: "#451a03",
              boxShadow:
                "0 8px 32px rgba(217, 119, 6, 0.5), inset 0 3px 6px rgba(255,255,255,0.4)",
            }}
          >
            <div className="flex flex-col items-center leading-none">
              <span className="text-5xl font-bold">1</span>
              <span className="text-[10px] mt-1 tracking-widest opacity-70">HEADS</span>
            </div>
          </div>

          <div
            className="absolute inset-0 rounded-full flex items-center justify-center border-4 select-none"
            style={{
              backfaceVisibility: "hidden",
              transform: "rotateX(180deg)",
              background: "linear-gradient(135deg, #94a3b8, #475569)",
              borderColor: "#1e293b",
              color: "#f1f5f9",
              boxShadow:
                "0 8px 32px rgba(71, 85, 105, 0.5), inset 0 3px 6px rgba(255,255,255,0.3)",
            }}
          >
            <div className="flex flex-col items-center leading-none">
              <span className="text-5xl font-bold">2</span>
              <span className="text-[10px] mt-1 tracking-widest opacity-70">TAILS</span>
            </div>
          </div>
        </div>
      </div>

      {phase === "settled" && result !== null && (
        <div className="absolute bottom-[15vh] left-1/2 -translate-x-1/2 pointer-events-none">
          <div className="bg-black/70 backdrop-blur-md border border-white/20 rounded-xl px-6 py-3 text-center min-w-[160px]">
            <div className="text-white/60 text-xs mb-1 tracking-widest">1d2</div>
            <div className="text-white text-3xl font-bold tabular-nums">{result}</div>
            <div className="text-white/50 text-xs mt-1">
              {result === 1 ? "Heads" : "Tails"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CoinFlip;
