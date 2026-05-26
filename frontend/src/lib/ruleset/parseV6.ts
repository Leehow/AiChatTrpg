import {
  ParsedRuleset,
  V6ParseError,
  V6RawArtifact,
  V6RulePackage,
  V6ParameterFamily,
} from "./types";

// Read a File via FileReader and return its text. Async because v6 JSON
// can be 2MB+ and we don't want to block the UI thread on .text() unwraps.
export async function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new V6ParseError("File reader returned non-string result"));
        return;
      }
      resolve(result);
    };
    reader.onerror = () =>
      reject(new V6ParseError(reader.error?.message || "Failed to read file"));
    reader.readAsText(file);
  });
}

export async function parseV6FromFile(file: File): Promise<ParsedRuleset> {
  const text = await readFileAsText(file);
  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch (err) {
    throw new V6ParseError(
      `Invalid JSON: ${err instanceof Error ? err.message : String(err)}`
    );
  }
  return parseV6(json);
}

export function parseV6(input: unknown): ParsedRuleset {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new V6ParseError("Top-level value must be a JSON object");
  }
  const raw = input as V6RawArtifact;

  // Version gate — accept v6 plus a tolerant "looks like v6" path so partially
  // hand-edited files still load. The shape check is the real signal.
  const version = (raw as { version?: unknown }).version;
  const looksLikeV6 =
    typeof raw.core_rules === "string" &&
    Array.isArray(raw.rule_packages) &&
    Array.isArray(raw.parameter_families);
  if (version !== 6 && !looksLikeV6) {
    throw new V6ParseError(
      `Unsupported ruleset version: ${String(version)} (expected 6)`,
      "version"
    );
  }
  if (typeof raw.core_rules !== "string" || !raw.core_rules.trim()) {
    throw new V6ParseError("Missing core_rules content", "core_rules");
  }

  const scenarios: V6RulePackage[] = Array.isArray(raw.rule_packages)
    ? raw.rule_packages
        .filter((p): p is V6RulePackage =>
          Boolean(p && typeof p === "object" && (p as V6RulePackage).package_id)
        )
        .map((p) => ({
          package_id: String(p.package_id),
          filename: p.filename,
          content: typeof p.content === "string" ? p.content : "",
          raw: typeof p.raw === "string" ? p.raw : undefined,
          excerpt_stats: p.excerpt_stats,
          error: p.error,
        }))
    : [];

  const parameters: V6ParameterFamily[] = Array.isArray(raw.parameter_families)
    ? raw.parameter_families
        .filter((f): f is V6ParameterFamily =>
          Boolean(
            f && typeof f === "object" && (f as V6ParameterFamily).family_id
          )
        )
        .map((f) => ({
          family_id: String(f.family_id),
          filename: f.filename,
          json: f.json,
          content: f.content,
          raw: f.raw,
          should_remain_markdown: f.should_remain_markdown,
          error: f.error,
        }))
    : [];

  // Three known dice_ir locations, in priority order:
  //   - top-level (preferred — chatrpg fixtures, new chatlab serialize_v6)
  //   - parse_artifacts.v6.dice_ir (post-stage-8 chatlab DB shape)
  //   - parse_artifacts.dice_ir_compiler (legacy chatlab top-level key)
  const dice_ir =
    raw.dice_ir ??
    raw.parse_artifacts?.v6?.dice_ir ??
    raw.parse_artifacts?.dice_ir_compiler ??
    null;

  return {
    meta: {
      book_id: String(raw.book_id || ""),
      book_title: String(raw.book_title || file_basename(raw)),
      world_mode: String(raw.world_mode || "fiction"),
      output_language: raw.output_language,
      parsed_at: raw.parsed_at,
      model: raw.model,
      stats: raw.stats,
    },
    core: {
      rules_markdown: raw.core_rules,
      companion: raw.companion?.content
        ? {
            filename: raw.companion.filename || "companion.md",
            content: raw.companion.content,
          }
        : undefined,
    },
    scenarios,
    parameters,
    character_sheet: raw.character_sheet,
    dice_ir,
    check_spec: null,
    // Backend column; absent on local-only parse, filled in by `dtoToParsed`
    // when the artifact comes back from the server.
    character_ui: null,
    raw,
  };
}

function file_basename(raw: V6RawArtifact): string {
  const f = raw.files?.[0]?.filename;
  if (f) return f.replace(/\.[^.]+$/, "");
  return "Untitled Ruleset";
}

// Persist a ParsedRuleset to localStorage. We store only the raw artifact —
// the parsed view is reconstructed on read so newer parsers can re-derive
// sections from older saved data.
const STORAGE_KEY = "chatrpg.rulesets";
const STORAGE_VERSION = 1;

interface StoredRulesets {
  version: number;
  items: Array<{ id: string; saved_at: string; raw: V6RawArtifact }>;
}

function loadStorage(): StoredRulesets {
  if (typeof window === "undefined") return { version: STORAGE_VERSION, items: [] };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { version: STORAGE_VERSION, items: [] };
    const parsed = JSON.parse(raw) as StoredRulesets;
    if (parsed.version !== STORAGE_VERSION || !Array.isArray(parsed.items)) {
      return { version: STORAGE_VERSION, items: [] };
    }
    return parsed;
  } catch {
    return { version: STORAGE_VERSION, items: [] };
  }
}

function saveStorage(data: StoredRulesets): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch (err) {
    // Quota exceeded on a 2MB ruleset is plausible — surface it.
    console.warn("[chatrpg] failed to persist ruleset:", err);
  }
}

export function listSavedRulesets(): Array<{
  id: string;
  saved_at: string;
  meta: ParsedRuleset["meta"];
}> {
  return loadStorage().items.map((item) => ({
    id: item.id,
    saved_at: item.saved_at,
    meta: parseV6(item.raw).meta,
  }));
}

export function saveRuleset(parsed: ParsedRuleset): string {
  const id = parsed.meta.book_id || crypto.randomUUID();
  const data = loadStorage();
  const idx = data.items.findIndex((it) => it.id === id);
  const entry = { id, saved_at: new Date().toISOString(), raw: parsed.raw };
  if (idx >= 0) data.items[idx] = entry;
  else data.items.push(entry);
  saveStorage(data);
  return id;
}

export function loadSavedRuleset(id: string): ParsedRuleset | null {
  const item = loadStorage().items.find((it) => it.id === id);
  return item ? parseV6(item.raw) : null;
}

export function deleteSavedRuleset(id: string): void {
  const data = loadStorage();
  data.items = data.items.filter((it) => it.id !== id);
  saveStorage(data);
}
