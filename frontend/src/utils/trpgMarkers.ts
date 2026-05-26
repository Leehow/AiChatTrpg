/**
 * TRPG internal control markers — never shown to players.
 * Examples: [UPDATE_MEMORY]{...}, [SET_SCENE]{...}, [CREATE_NPC]{...}.
 *
 * The GM emits these as side-effect directives during streaming. Postprocess
 * executes them, then the renderer strips them so the player sees only prose.
 */

const TRPG_INTERNAL_MARKER_NAMES = [
  "UPDATE_MEMORY",
  "SET_SCENE",
  "CREATE_MODULE",
  "ADD_NOTE",
  "TAKE_TIME",
  "CREATE_NPC",
  "UPDATE_PC_PARAMS",
  "UPDATE_NPC_PARAMS",
  "UPDATE_PC",
  "ATMOSPHERE",
  "SECTION_END",
  "EXTRA_ROLL",
  "SEARCH_MODULE",
  "SEARCH_RULES",
  "GET_PC",
  "GET_NPCS",
  "INTRODUCE_RULES",
  "CREATE_CHARACTER",
  "BUTTON_CREATE_ROLE",
  "SET_OBJECTIVE",
  "CHECK",
  "CONTEST",
  // `pending_check` is the placeholder for the "投出" button card. It's
  // rendered out-of-band from `metadata.pending_checks`, so the literal
  // text must not leak into the prose.
  "pending_check",
  // chatrpg-only structural markers (ROLL is rendered as a dice block
  // upstream of stripping; the rest are silent control side-effects).
  "REVEAL_CLUE",
  "ADVANCE_SCENE",
] as const;

const TRPG_INTERNAL_MARKER_PATTERN = TRPG_INTERNAL_MARKER_NAMES.join("|");
const TRPG_INTERNAL_OPEN_TAG_SOURCE = String.raw`\[(?:${TRPG_INTERNAL_MARKER_PATTERN})(?:[^\]]*)?\]`;
const TRPG_INTERNAL_CLOSE_TAG_SOURCE = String.raw`\[/(?:${TRPG_INTERNAL_MARKER_PATTERN})\]`;

const trpgInternalOpenTagRe = new RegExp(TRPG_INTERNAL_OPEN_TAG_SOURCE, "i");
const trpgInternalClosedBlockRe = new RegExp(
  `${TRPG_INTERNAL_OPEN_TAG_SOURCE}[\\s\\S]*?${TRPG_INTERNAL_CLOSE_TAG_SOURCE}`,
  "gi",
);
const trpgInternalJsonPayloadRe = new RegExp(
  `${TRPG_INTERNAL_OPEN_TAG_SOURCE}[^\\{\\n]*\\{[^{}]*(?:\\{[^{}]*\\}[^{}]*)*\\}`,
  "gi",
);
const trpgInternalUnclosedLineRe = new RegExp(
  `${TRPG_INTERNAL_OPEN_TAG_SOURCE}[^\\n]*\\n?`,
  "gi",
);
const trpgInternalClosingTagRe = new RegExp(TRPG_INTERNAL_CLOSE_TAG_SOURCE, "gi");

export function hasTrpgInternalMarker(text: string): boolean {
  return trpgInternalOpenTagRe.test(text || "");
}

export function stripTrpgInternalMarkers(
  text: string,
  options: { stripUnclosedLine?: boolean } = {},
): string {
  if (!text) return text;

  let result = text
    .replace(trpgInternalClosedBlockRe, "")
    .replace(trpgInternalJsonPayloadRe, "");

  if (options.stripUnclosedLine) {
    result = result.replace(trpgInternalUnclosedLineRe, "");
  }

  return result.replace(trpgInternalClosingTagRe, "");
}
