import type { PublicMemoryViewDTO } from "../../../api/sessions";

export function readArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

export function readObject(v: unknown): Record<string, unknown> {
  return isRecord(v) ? v : {};
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

export function readStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.map((item) => String(item).trim()).filter(Boolean);
}

export function isPublicViewEmpty(view: PublicMemoryViewDTO): boolean {
  return (
    view.relationships.length === 0 &&
    view.clues.length === 0 &&
    view.open_threads.length === 0 &&
    view.remembered_facts.length === 0
  );
}

export function pickName(v: unknown): string {
  if (v && typeof v === "object") {
    const r = v as Record<string, unknown>;
    return String(r.name ?? r.title ?? r.label ?? "");
  }
  return "";
}

export function pickKey(v: unknown): string {
  if (v && typeof v === "object") {
    const r = v as Record<string, unknown>;
    return String(r.key ?? r.id ?? "");
  }
  return "";
}

export function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n) + "…";
}

export function displayValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

export function numberValue(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

export function formatElapsed(totalMinutes: number): string {
  if (totalMinutes <= 0) return "—";
  const days = Math.floor(totalMinutes / (24 * 60));
  const remAfterDays = totalMinutes - days * 24 * 60;
  const hours = Math.floor(remAfterDays / 60);
  const mins = remAfterDays - hours * 60;
  const parts: string[] = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  if (mins > 0) parts.push(`${mins}m`);
  return parts.join(" ") || "—";
}
