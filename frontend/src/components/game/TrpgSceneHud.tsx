import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n";
import { TrpgForceTimeModal } from "./TrpgForceTimeModal";
import { TrpgSceneHudAdvanceControls } from "./TrpgSceneHudAdvanceControls";
import type { TrpgHudCurrentTime, TrpgSceneHudSnapshot } from "./trpgHudTypes";

interface ModuleStateLike {
  day_count?: number | null;
  in_game_time?: string | null;
  in_game_date?: string | null;
  in_game_period?: string | null;
  scene?: string | null;
  scene_name?: string | null;
}

interface Props {
  sessionId: string;
  module: ModuleStateLike;
  snapshot?: TrpgSceneHudSnapshot | null;
  onChanged?: () => void;
}

// Floating draggable HUD showing in-game day/clock/period and scene name.
// Visual style mirrors chatlab's TrpgSceneHud.vue: a single rounded-rect
// translucent pill with two stacked rows (time + scene) and a gear in the
// top-right. Position is persisted in localStorage so the player's chosen
// spot survives reloads.
const HUD_POS_KEY = "chatrpg.scene_hud_pos";
const HUD_DEFAULT_WIDTH = 220;
const HUD_DEFAULT_HEIGHT = 52;
const HUD_PAD = 6;

interface HudPos { x: number; y: number }

function readStoredPos(): HudPos | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(HUD_POS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed?.x === "number" && typeof parsed?.y === "number") {
      return { x: parsed.x, y: parsed.y };
    }
  } catch {
    // ignore corrupt entry
  }
  return null;
}

function clampPos(
  x: number, y: number, width: number, height: number,
): HudPos {
  if (typeof window === "undefined") return { x, y };
  const maxX = Math.max(HUD_PAD, window.innerWidth - width - HUD_PAD);
  const maxY = Math.max(HUD_PAD, window.innerHeight - height - HUD_PAD);
  return {
    x: Math.max(HUD_PAD, Math.min(maxX, x)),
    y: Math.max(HUD_PAD, Math.min(maxY, y)),
  };
}

export function TrpgSceneHud({ sessionId, module, snapshot, onChanged }: Props) {
  const { t } = useI18n();
  const [showModal, setShowModal] = useState(false);
  const hudRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<HudPos | null>(() => readStoredPos());
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{
    startX: number; startY: number; px: number; py: number; pointerId: number;
  } | null>(null);

  const liveDay = Number(module.day_count ?? 0) || 0;
  const liveClock = String(module.in_game_time ?? "").trim();
  const liveCurrentTime: TrpgHudCurrentTime = {
    day: liveDay || null,
    clock: liveClock || null,
    date: String(module.in_game_date ?? "").trim() || null,
    period: liveClock ? null : (String(module.in_game_period ?? "").trim() || null),
  };
  const isHistorical = snapshot !== undefined && snapshot !== null;
  const currentTime = isHistorical ? (snapshot.currentTime ?? liveCurrentTime) : liveCurrentTime;
  const day = Number(currentTime?.day ?? 0) || 0;
  const clock = String(currentTime?.clock ?? "").trim();
  const rawScene = isHistorical
    ? (
        String(snapshot.sceneName ?? "").trim() ||
        String(snapshot.sceneKey ?? "").trim()
      )
    : (
        String(module.scene_name ?? "").trim() ||
        String(module.scene ?? "").trim()
      );
  const sceneDisplay = rawScene && rawScene !== "—" ? rawScene : "";

  const period = useMemo(
    () => periodToLabel(
      String(currentTime?.period ?? "").trim(),
      clock,
      t as (k: string) => string,
    ),
    [clock, currentTime?.period, t],
  );

  const timeText = [
    day ? `D${day}` : "",
    clock,
    period,
  ].filter(Boolean).join(" · ");

  // Initial position: default to top-right of viewport on first paint.
  useLayoutEffect(() => {
    if (pos !== null) return;
    if (typeof window === "undefined") return;
    const w = hudRef.current?.offsetWidth || HUD_DEFAULT_WIDTH;
    const h = hudRef.current?.offsetHeight || HUD_DEFAULT_HEIGHT;
    const next = clampPos(
      window.innerWidth - w - 16,
      12,
      w,
      h,
    );
    setPos(next);
  }, [pos]);

  // Re-clamp on viewport resize so a saved position from a wider window
  // doesn't strand the HUD off-screen.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onResize = () => {
      setPos((cur) => {
        if (!cur) return cur;
        const w = hudRef.current?.offsetWidth || HUD_DEFAULT_WIDTH;
        const h = hudRef.current?.offsetHeight || HUD_DEFAULT_HEIGHT;
        return clampPos(cur.x, cur.y, w, h);
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Persist position whenever it lands on a real value (skip the null seed).
  useEffect(() => {
    if (!pos || typeof window === "undefined") return;
    try {
      window.localStorage.setItem(HUD_POS_KEY, JSON.stringify(pos));
    } catch {
      // localStorage may be unavailable (private mode) — drag still works.
    }
  }, [pos]);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (!e.isPrimary || e.button !== 0) return;
    const target = e.target as HTMLElement | null;
    if (target?.closest('[data-no-drag="true"]')) return;
    if (!pos) return;
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      px: pos.x,
      py: pos.y,
      pointerId: e.pointerId,
    };
    setDragging(true);
    e.preventDefault();
  }, [pos]);

  useEffect(() => {
    if (!dragging) return;
    const handleMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || e.pointerId !== drag.pointerId) return;
      const w = hudRef.current?.offsetWidth || HUD_DEFAULT_WIDTH;
      const h = hudRef.current?.offsetHeight || HUD_DEFAULT_HEIGHT;
      const nx = drag.px + (e.clientX - drag.startX);
      const ny = drag.py + (e.clientY - drag.startY);
      setPos(clampPos(nx, ny, w, h));
    };
    const handleUp = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (drag && e.pointerId !== drag.pointerId) return;
      setDragging(false);
      dragRef.current = null;
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };
  }, [dragging]);

  if (typeof document === "undefined") return null;

  const hud = (
    <>
      <div
        ref={hudRef}
        onPointerDown={onPointerDown}
        className={[
          "chatrpg-scene-hud",
          isHistorical ? "chatrpg-scene-hud--historical" : "",
          "fixed z-40 select-none touch-none",
          "flex flex-col items-start gap-[2px]",
          "pl-2.5 pr-9 py-[5px]",
          "rounded-lg",
          "shadow-[0_1px_3px_var(--shadow)]",
          "transition-shadow duration-150",
          dragging
            ? "cursor-grabbing shadow-[0_4px_14px_var(--shadow-md)]"
            : "cursor-grab hover:shadow-[0_2px_8px_var(--shadow-md)]",
        ].join(" ")}
        style={{
          left: pos ? `${pos.x}px` : "-9999px",
          top: pos ? `${pos.y}px` : "-9999px",
          fontSize: "11px",
          lineHeight: 1.3,
          maxWidth: "min(260px, calc(100vw - 8px))",
          visibility: pos ? "visible" : "hidden",
        }}
        title={t("hudGearTitle")}
        aria-label="trpg scene hud"
      >
        <button
          type="button"
          data-no-drag="true"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); setShowModal(true); }}
          className={[
            "chatrpg-scene-hud-btn",
            "absolute top-[5px] right-1.5",
            "inline-flex items-center justify-center",
            "w-[22px] h-[22px] rounded-full",
            "transition-colors",
          ].join(" ")}
          title={t("hudGearTitle")}
          aria-label={t("hudGearTitle")}
        >
          <GearIcon />
        </button>

        {timeText ? (
          <div className="flex items-center gap-1 max-w-full">
            <ClockIcon />
            <span className="font-mono tracking-tight">{timeText}</span>
          </div>
        ) : (
          <div className="flex items-center gap-1 max-w-full italic opacity-80">
            <ClockIcon />
            <span>{t("hudNoTime")}</span>
          </div>
        )}

        {sceneDisplay && (
          <div className="flex items-center gap-1 max-w-full">
            <PinIcon />
            <span
              className="overflow-hidden text-ellipsis whitespace-nowrap"
              style={{ maxWidth: "min(200px, calc(100vw - 56px))" }}
            >
              {sceneDisplay}
            </span>
          </div>
        )}

        <TrpgSceneHudAdvanceControls
          sessionId={sessionId}
          isHistorical={isHistorical}
          onChanged={onChanged}
        />
      </div>

      {showModal && (
        <TrpgForceTimeModal
          sessionId={sessionId}
          initialDay={liveDay || 1}
          initialClock={liveClock || "09:00"}
          initialDate={String(module.in_game_date || "")}
          onClose={() => setShowModal(false)}
          onSaved={() => {
            setShowModal(false);
            onChanged?.();
          }}
        />
      )}
    </>
  );

  return createPortal(hud, document.body);
}


function periodToLabel(
  period: string,
  clock: string,
  t: (k: string) => string,
): string {
  const clean = period.toLowerCase();
  if (clean === "morning") return t("hudPeriodMorning");
  if (clean === "afternoon") return t("hudPeriodAfternoon");
  if (clean === "evening") return t("hudPeriodEvening");
  if (clean === "night") return t("hudPeriodNight");
  if (!clock) return "";
  const hour = Number.parseInt(clock.split(":")[0] || "", 10);
  if (!Number.isFinite(hour)) return "";
  if (hour >= 6 && hour < 12) return t("hudPeriodMorning");
  if (hour >= 12 && hour < 18) return t("hudPeriodAfternoon");
  if (hour >= 18 && hour < 22) return t("hudPeriodEvening");
  return t("hudPeriodNight");
}


function ClockIcon() {
  return (
    <svg
      viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round"
      className="w-3 h-3 opacity-60 flex-shrink-0"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="7.25" />
      <path d="M10 6.25v4l2.5 1.5" />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg
      viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round"
      className="w-3 h-3 opacity-60 flex-shrink-0"
      aria-hidden="true"
    >
      <path d="M10 17.5s5.5-4.6 5.5-9a5.5 5.5 0 1 0-11 0c0 4.4 5.5 9 5.5 9z" />
      <circle cx="10" cy="8.5" r="2" />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg
      viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round"
      className="w-3.5 h-3.5"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
    </svg>
  );
}
