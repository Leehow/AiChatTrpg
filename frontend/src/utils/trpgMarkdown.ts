/**
 * TRPG markdown pipeline. Pure-text → safe HTML for `dangerouslySetInnerHTML`.
 *
 * Pipeline:
 *   1. Style dialogue (`「quote」[speak]name[/speak]` → styled span)
 *   2. Convert TRPG semantic markers to HTML
 *      ([dice], [ooc], [debug], [thought], [sign], [note], [screen], [memory])
 *   3. Convert `[BUTTON_CREATE_ROLE]label[/BUTTON_CREATE_ROLE]` to action button
 *   4. Strip internal control markers (UPDATE_MEMORY, SET_SCENE, ...)
 *   5. Render KaTeX with placeholders (so marked won't mangle the math HTML)
 *   6. Pre-convert CJK-adjacent bold (CommonMark flanking rules drop these)
 *   7. marked.parse with GFM tables + line breaks
 *   8. Restore KaTeX placeholders, wrap tables, fix link targets
 */

import { marked } from "marked";
import katex from "katex";
import "katex/dist/katex.min.css";

import { stripTrpgInternalMarkers, hasTrpgInternalMarker } from "./trpgMarkers";
import {
  findSpeakerProfile,
  getTrpgSpeakerType,
  styleTrpgDialogue,
  type TrpgSpeakerProfile,
} from "./trpgDialogue";

marked.setOptions({ breaks: true, gfm: true });

// ---------- HTML utility ----------

function escapeHtml(text: string): string {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(text: string): string {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

const TRPG_ATTR_RE =
  /([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s\]"]+))/g;

function parseTrpgAttrs(attrsText: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const match of attrsText.matchAll(TRPG_ATTR_RE)) {
    const [, key, qval, sval, bval] = match;
    out[key.toLowerCase()] = qval ?? sval ?? bval ?? "";
  }
  return out;
}

// CommonMark emphasis flanking rules drop `**bold**` adjacent to CJK
// characters or fullwidth punctuation. Pre-converting to <strong> sidesteps
// the flanking check entirely. Skips fenced code and inline code spans.
function preprocessCJKBold(text: string): string {
  if (!text || text.indexOf("**") === -1) return text;
  const fenceRe = /(^|\n)(```|~~~)[\s\S]*?\n\2[ \t]*(?=\n|$)/g;
  const segments: { code: boolean; text: string }[] = [];
  let lastIdx = 0;
  let m: RegExpExecArray | null;
  while ((m = fenceRe.exec(text)) !== null) {
    if (m.index > lastIdx) {
      segments.push({ code: false, text: text.slice(lastIdx, m.index) });
    }
    segments.push({ code: true, text: m[0] });
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < text.length) {
    segments.push({ code: false, text: text.slice(lastIdx) });
  }

  const transformProse = (s: string): string => {
    const codeSpans: string[] = [];
    s = s.replace(/`[^`\n]*`/g, (full) => {
      const i = codeSpans.length;
      codeSpans.push(full);
      return `__TRPG_CODE_SPAN_${i}__`;
    });
    s = s.replace(
      /\*\*([^\s*][^*\n]*?[^\s*]|[^\s*])\*\*/g,
      "<strong>$1</strong>",
    );
    s = s.replace(/__TRPG_CODE_SPAN_(\d+)__/g, (_, i) => codeSpans[Number(i)] || "");
    return s;
  };

  return segments
    .map((seg) => (seg.code ? seg.text : transformProse(seg.text)))
    .join("");
}

// ---------- KaTeX ----------

function renderKatex(latex: string, displayMode: boolean): string {
  const trimmed = latex.trim();
  try {
    return katex.renderToString(trimmed, {
      displayMode,
      throwOnError: false,
      output: "htmlAndMathml",
    });
  } catch {
    return `<span class="katex-error">${escapeHtml(trimmed)}</span>`;
  }
}

function processMath(text: string, placeholders: string[]): string {
  // Display math: $$...$$
  let out = text.replace(/\$\$([\s\S]+?)\$\$/g, (_m, math) => {
    const idx = placeholders.length;
    placeholders.push(renderKatex(math, true));
    return `<katex-ph data-i="${idx}"></katex-ph>`;
  });
  // Display math: \[...\]
  out = out.replace(/\\\[([\s\S]+?)\\\]/g, (_m, math) => {
    const idx = placeholders.length;
    placeholders.push(renderKatex(math, true));
    return `<katex-ph data-i="${idx}"></katex-ph>`;
  });
  // Inline math: $...$ (single-line, not $$)
  out = out.replace(/\$([^\$\n]+?)\$/g, (_m, math) => {
    const idx = placeholders.length;
    placeholders.push(renderKatex(math, false));
    return `<katex-ph data-i="${idx}"></katex-ph>`;
  });
  // Inline math: \(...\)
  out = out.replace(/\\\(([\s\S]+?)\\\)/g, (_m, math) => {
    const idx = placeholders.length;
    placeholders.push(renderKatex(math, false));
    return `<katex-ph data-i="${idx}"></katex-ph>`;
  });
  return out;
}

function restoreKatex(html: string, placeholders: string[]): string {
  return html.replace(/<katex-ph data-i="(\d+)"><\/katex-ph>/g, (_m, idx) => {
    return placeholders[parseInt(idx, 10)] || "";
  });
}

/**
 * Tint `<strong>NAME</strong>` runs in narration with the speaker's color so
 * that "内特·帕特森" written in narration matches the color of that NPC's
 * dialogue. Bolds inside `.trpg-dialogue` are unaffected — the existing
 * `.trpg-dialogue strong { color: inherit }` rule still wins by specificity.
 */
function decorateNameMentions(
  html: string,
  profiles: Record<string, TrpgSpeakerProfile> | undefined,
): string {
  if (!profiles) return html;
  return html.replace(/<strong>([^<]+)<\/strong>/g, (full, inner) => {
    const profile = findSpeakerProfile(inner, profiles);
    if (!profile) return full;
    const type = profile.type || getTrpgSpeakerType(profile.displayName || inner);
    const colorIdx = typeof profile.colorIdx === "number" ? profile.colorIdx : 0;
    const colorAttr =
      type === "npc" || type === "bystander" ? ` data-color-idx="${colorIdx}"` : "";
    return `<strong class="trpg-name" data-speaker-type="${type}"${colorAttr}>${inner}</strong>`;
  });
}

// ---------- Semantic block conversions ----------

function normalizeBlockContent(content: string, compact: boolean): string {
  let cleaned = String(content || "").replace(/\r\n?/g, "\n");
  if (compact) {
    cleaned = cleaned
      .replace(/\n[ \t]*\n+/g, "\n");
    return cleaned
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .join("<br>");
  }
  return cleaned.replace(/\n{3,}/g, "\n\n").trim();
}

const SEMANTIC_BLOCKS: Array<[string, string, string]> = [
  ["thought", "thought-block", "Inner"],
  ["sign", "sign-block", "Sign"],
  ["note", "note-block", "Note"],
  ["screen", "screen-block", "Screen"],
  ["memory", "memory-block", "Memory"],
];

const GEMINI_TTS_AUDIO_TAG_RE =
  /\[(?:short pause|long pause|whispers?|shouting|yawn|cough|sighs?|gasp|giggles?|laughs?|amazed|crying|curious|excited|mischievously|panicked|sarcastic|serious|tired|trembling|admiration|agitation|anger|annoyance|anticipation|anxiety|appreciation|approval|astonishment|awe|boredom|caution|compassion|confidence|confusion|contempt|curiosity|determination|disappointment|disapproval|disgust|doubt|eagerness|embarrassment|empathy|encouraging|enjoyment|enthusiasm|excitement|fear|frustration|gratitude|happy|hope|horror|interest|joy|love|negative|nervousness|neutral|optimism|pain|positive|sadness|sarcasm|satisfaction|surprise|sympathy)\]/gi;
const MINIMAX_TTS_AUDIO_TAG_RE =
  /\((?:laughs|sighs|gasps|coughs|clear-throat|groans|breath|pant|inhale|exhale|sniffs|snorts|humming|hissing|emm|lip-smacking|sneezes|burps|crying|chuckle)\)/gi;

function convertTrpgBlocks(
  text: string,
  options: { speakerProfiles?: Record<string, TrpgSpeakerProfile> } = {},
): string {
  let result = text;

  // Strip [CREATE_CHARACTER] (handled separately as a UI signal)
  result = result.replace(/\[CREATE_CHARACTER\]/g, "");

  // Convert [BUTTON_CREATE_ROLE]label[/BUTTON_CREATE_ROLE] → action button
  result = result.replace(
    /\[BUTTON_CREATE_ROLE\]([\s\S]*?)\[\/BUTTON_CREATE_ROLE\]/gi,
    (_m, label) =>
      `<button class="btn-create-role" data-action="create-role">${String(label).trim()}</button>`,
  );

  // Strip blocks the player should never see
  result = result.replace(/\[TAKE_TIME\][\s\S]*?\[\/TAKE_TIME\]/gi, "");
  result = result.replace(/\[ATMOSPHERE\][\s\S]*?\[\/ATMOSPHERE\]/gi, "");

  // Strip leftover [speak] tags (styleTrpgDialogue already consumed attached ones)
  result = result.replace(
    /\[speak(?::[\w-]*)?(?::[\w.-]+)?\][\s\S]*?\[\/speak\]/gi,
    "",
  );
  result = result
    .replace(MINIMAX_TTS_AUDIO_TAG_RE, "")
    .replace(GEMINI_TTS_AUDIO_TAG_RE, "");

  // Strip TRPG state/control markers
  result = stripTrpgInternalMarkers(result, { stripUnclosedLine: true });

  // [dice] → collapsible <details>. We keep contests open by default since
  // they auto-roll without a "投出" button and a one-line summary makes it
  // look like nothing happened. CoC checks (one-line skill rolls) stay
  // collapsed to avoid cluttering the chat with rule arithmetic the player
  // can drill into on demand.
  result = result.replace(/\[dice\]([\s\S]*?)\[\/dice\]/gi, (_m, content) => {
    const lines = String(content).trim().split("\n");
    const summary = (lines[0] || "").replace(/^[\s#*-]+/, "").trim() || "Roll";
    const rest = lines.slice(1).join("\n").trim();
    const isContest = /对抗检定|Opposed|CONTEST/i.test(summary);
    const openAttr = isContest ? " open" : "";
    return `<details class="dice-block"${openAttr}><summary class="dice-summary">🎲 ${escapeHtml(summary)}</summary>\n\n${rest}\n\n</details>`;
  });

  // [ROLL expr=...]content[/ROLL] → chatrpg's GM-prompted-roll block.
  // The inner text is the player-facing instruction, so render expanded.
  result = result.replace(
    /\[ROLL([^\]]*)\]([\s\S]*?)\[\/ROLL\]/gi,
    (_m, attrs, content) => {
      const inner = String(content).trim();
      const exprMatch = String(attrs).match(/expr=([^\s\]]+)/i);
      const summary = exprMatch
        ? `🎲 Roll ${escapeHtml(exprMatch[1])}`
        : "🎲 Roll";
      return `<details class="dice-block" open><summary class="dice-summary">${summary}</summary>\n\n${inner}\n\n</details>`;
    },
  );

  // [ooc] → GM aside
  result = result.replace(/\[ooc\]([\s\S]*?)\[\/ooc\]/gi, (_m, content) => {
    const inner = String(content).trim();
    return `<div class="ooc-block"><div class="ooc-label">GM</div><div class="ooc-content">\n\n${inner}\n\n</div></div>`;
  });

  // [npc_card name="..." role="..." key="..."]appearance[/npc_card]
  // First-appearance heavy card. The GM is responsible for choosing
  // whether `name` is the description label or the real name; the
  // backend's mask_hidden_true_name does NOT touch literal marker text.
  // `key`, when present, is consumed by the React layer to look up
  // portrait_url from speakerProfiles.
  result = result.replace(
    /\[npc_card([^\]]*)\]([\s\S]*?)\[\/npc_card\]/gi,
    (_m, attrsText, body) => {
      const attrs = parseTrpgAttrs(String(attrsText || ""));
      const name = String(attrs.name || "").trim();
      const role = String(attrs.role || "").trim();
      const key = String(attrs.key || attrs.npc_key || "").trim();
      const appearance = String(body || "").trim();
      if (!name && !appearance) return "";
      const profile = key
        ? findSpeakerProfile(key, options.speakerProfiles)
        : findSpeakerProfile(name, options.speakerProfiles);
      const safeName = escapeHtml(name);
      const safeRole = escapeHtml(role);
      const safeKey = escapeHtml(key);
      const safeAppearance = escapeHtml(appearance).replace(/\n/g, "<br>");
      const keyAttr = safeKey ? ` data-npc-key="${safeKey}"` : "";
      const portrait = profile?.avatarUrl
        ? `<img class="npc-card-portrait" src="${escapeAttr(profile.avatarUrl)}" alt="${safeName}" onerror="this.style.display='none'" />`
        : "";
      return (
        `<div class="npc-card-block"${keyAttr}>` +
        `<div class="npc-card-header">` +
        portrait +
        `<div class="npc-card-meta">` +
        `<span class="npc-card-badge">👤 NPC</span>` +
        (safeName ? `<span class="npc-card-name">${safeName}</span>` : "") +
        (safeRole ? `<span class="npc-card-role">${safeRole}</span>` : "") +
        `</div>` +
        `</div>` +
        (safeAppearance
          ? `<div class="npc-card-body">${safeAppearance}</div>`
          : "") +
        `</div>`
      );
    },
  );

  // [name_reveal npc_key="..." name="..."][optional reason][/name_reveal]
  // Lightweight chip — narrative moment when a hidden NPC's true name
  // becomes player-known. Backend marker handler also fires
  // `agent.reveal_name(npc_key)` so the chip is in lockstep with state.
  // Self-closing (no body) is the common case.
  const renderRevealChip = (attrsText: string, body: string): string => {
    const attrs = parseTrpgAttrs(attrsText);
    const name = String(attrs.name || "").trim();
    const npcKey = String(attrs.npc_key || attrs.key || "").trim();
    if (!name && !npcKey) return "";
    const profile = npcKey
      ? findSpeakerProfile(npcKey, options.speakerProfiles)
      : findSpeakerProfile(name, options.speakerProfiles);
    const safeName = escapeHtml(name || npcKey);
    const safeKey = escapeHtml(npcKey);
    const safeReason = escapeHtml(String(body || "").trim());
    const keyAttr = safeKey ? ` data-npc-key="${safeKey}"` : "";
    const reasonAttr = safeReason ? ` title="${safeReason}"` : "";
    // Tint the chip with the same per-speaker `--speaker-color` used by
    // dialogue runs and `**name**` mentions, so reveal sits visually
    // alongside that NPC's other appearances on the page.
    const type = profile?.type || "npc";
    const colorIdx =
      typeof profile?.colorIdx === "number" ? profile.colorIdx : 0;
    const colorAttr =
      type === "npc" || type === "bystander" ? ` data-color-idx="${colorIdx}"` : "";
    return (
      `<span class="name-reveal-chip" data-speaker-type="${type}"${colorAttr}${keyAttr}${reasonAttr}>` +
      `🪪 <span class="name-reveal-name">${safeName}</span>` +
      `</span>`
    );
  };
  result = result.replace(
    /\[name_reveal([^\]]*)\]([\s\S]*?)\[\/name_reveal\]/gi,
    (_m, attrsText, body) => renderRevealChip(String(attrsText || ""), String(body || "")),
  );
  // Also accept open form (no closing tag) since the backend tolerates it.
  result = result.replace(
    /\[name_reveal([^\]]*)\](?!\s*\[\/name_reveal\])/gi,
    (_m, attrsText) => renderRevealChip(String(attrsText || ""), ""),
  );

  // [debug] → directive card
  result = result.replace(/\[debug\]([\s\S]*?)\[\/debug\]/gi, (_m, content) => {
    const inner = String(content).trim();
    return `<div class="debug-block"><div class="debug-label">🔧 DEBUG</div><div class="debug-content">${escapeHtml(inner)}</div></div>`;
  });

  // Semantic narrative blocks
  for (const [tag, cls, label] of SEMANTIC_BLOCKS) {
    if (!result.includes(`[${tag}]`)) continue;
    const re = new RegExp(`\\[${tag}\\]([\\s\\S]*?)\\[\\/${tag}\\]`, "gi");
    result = result.replace(re, (_m, c) => {
      const compact = tag === "sign" || tag === "note" || tag === "screen";
      const cleaned = normalizeBlockContent(c, compact);
      return `<div class="${cls}"><div class="semantic-label">${label}</div><div class="semantic-content">${cleaned}</div></div>`;
    });
  }

  return result.trim();
}

// ---------- Main entry ----------

export interface RenderTrpgOptions {
  /** Force TRPG-mode dialogue styling even when no marker is present. */
  forceTrpg?: boolean;
  speakerProfiles?: Record<string, TrpgSpeakerProfile>;
}

export function renderTrpgMarkdown(
  raw: string,
  options: RenderTrpgOptions = {},
): string {
  if (!raw) return "";

  // 1. Dialogue spans (must run before semantic-block stripping)
  let text = styleTrpgDialogue(raw, {
    forceTrpg: options.forceTrpg ?? false,
    speakerProfiles: options.speakerProfiles,
  });

  // 2-4. TRPG semantic blocks + control marker stripping
  text = convertTrpgBlocks(text, { speakerProfiles: options.speakerProfiles });

  // 5. KaTeX with placeholders
  const placeholders: string[] = [];
  text = processMath(text, placeholders);

  // 6. CJK bold fix
  text = preprocessCJKBold(text);

  // 7. marked
  let html = marked.parse(text, { async: false }) as string;

  // 8. Restore math, wrap tables, fix link targets, tint speaker-name bolds
  html = restoreKatex(html, placeholders);
  html = html.replace(/<table>/g, '<div class="table-wrapper"><table>');
  html = html.replace(/<\/table>/g, "</table></div>");
  html = html.replace(
    /<a\s+href="/g,
    '<a target="_blank" rel="noopener noreferrer" href="',
  );
  html = decorateNameMentions(html, options.speakerProfiles);

  return html;
}

export { hasTrpgInternalMarker };
