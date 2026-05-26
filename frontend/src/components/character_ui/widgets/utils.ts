/**
 * Path resolution + value coercion shared by the recursive primitive
 * renderer. Path semantics match the backend prompt: dot-notation
 * resolved against the current scope (the root scope is the card; the
 * `list` primitive pushes each iterated entry as the new scope).
 */

export type Card = Record<string, unknown>;
export type Scope = unknown;

export function resolvePath(scope: Scope, path: string | null | undefined): unknown {
  if (!path || scope == null) return undefined;
  // The special segment __key__ is replaced by the renderer when iterating
  // an object source — it never reaches here. If it does, treat as missing.
  if (path === "__key__") return undefined;
  const segments = path.split(".");
  let cur: unknown = scope;
  for (const seg of segments) {
    if (cur == null) return undefined;
    if (typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[seg];
  }
  return cur;
}

export function asString(value: unknown, fallback = ""): string {
  if (value == null) return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

export function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

export function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  return [];
}

export function asObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

/** Render any value as a display string. Used by `text` primitives so a
 *  path that points at an unexpected object shape still produces output
 *  rather than crashing the panel. */
export function displayValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((v) => displayValue(v))
      .filter((s) => s !== "")
      .join(", ");
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if ("value" in obj) return displayValue(obj.value);
    if ("name" in obj) return displayValue(obj.name);
    return "";
  }
  return "";
}

const COLOR_MAP: Record<string, string> = {
  red: "#ef4444",
  blue: "#3b82f6",
  green: "#22c55e",
  amber: "#f59e0b",
  purple: "#a855f7",
  teal: "#14b8a6",
};

export function resolveBarColor(color?: string): string {
  if (color && COLOR_MAP[color]) return COLOR_MAP[color];
  return "var(--accent)";
}

/** Iterate a list source: array → entries with `__key__` = numeric index;
 *  object → entries where each item is the value with `__key__` injected. */
export function iterateSource(
  source: unknown,
): Array<{ key: string; item: unknown }> {
  if (Array.isArray(source)) {
    return source.map((item, i) => ({ key: String(i), item }));
  }
  if (source && typeof source === "object") {
    return Object.entries(source as Record<string, unknown>).map(
      ([key, item]) => ({ key, item }),
    );
  }
  return [];
}

/** Resolve a relative path against an iterated item, supporting `__key__`. */
export function resolveItemPath(
  item: unknown,
  itemKey: string,
  path: string | null | undefined,
): unknown {
  if (!path) return undefined;
  if (path === "__key__") return itemKey;
  return resolvePath(item, path);
}
