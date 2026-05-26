"""Pure string / regex / sanitization helpers for TRPG TTS.

These helpers have no DB, LLM, or asyncio dependencies. They are imported by
`services.trpg_tts` and its sibling helpers to keep `trpg_tts.py` itself
small and focused on the streaming flow.
"""

from __future__ import annotations

import re
from html import unescape

_QUOTE_WITH_SPEAK_RE = re.compile(
    r"「([^」]*)」"
    r"(?:\s*\[speak(?::([\w-]*))?(?::([\w.-]+))?\]([\s\S]+?)\[/speak\])?",
    re.IGNORECASE,
)
_SPEAK_TAG_RE = re.compile(
    r"\[speak(?::[\w-]*)?(?::[\w.-]+)?\][\s\S]*?\[/speak\]",
    re.IGNORECASE,
)
_SEMANTIC_BLOCK_RE = re.compile(
    r"\[(thought|sign|note|screen|memory|ooc|oss)\]([\s\S]*?)\[/\1\]",
    re.IGNORECASE,
)
_INLINE_CONTROL_RE = re.compile(
    r"\[(?:CHECK|CONTEST|ROLL|EXTRA_ROLL|SEARCH_RULES)\b(?:\"[^\"]*\"|'[^']*'|[^\]])*\]",
    re.IGNORECASE,
)
_CONTROL_BLOCK_TAGS = (
    "UPDATE_?NPC_?PARAMS|UPDATE_?PC_?PARAMS|UPDATE_?MEMORY|SET_?SCENE|"
    "CREATE_?MODULE|ADD_?NOTE|TAKE_?TIME|CREATE_?NPC|UPDATE_?PC|"
    "UPDATE_?NPC|ATMOSPHERE|SECTION_?END|SEARCH_?MODULE|SEARCH_?RULES|"
    "GET_?PC|GET_?NPCS|INTRODUCE_?RULES|CREATE_?CHARACTER|"
    "BUTTON_?CREATE_?ROLE|SET_?OBJECTIVE|UPDATE_?OBJECTIVE|OFFER_?EXITS"
)
_CONTROL_BLOCK_RE = re.compile(
    rf"\[(?:{_CONTROL_BLOCK_TAGS})\b[^\]]*\][\s\S]*?\[/(?:{_CONTROL_BLOCK_TAGS})\]",
    re.IGNORECASE,
)
_CONTROL_OPEN_LINE_RE = re.compile(
    rf"\[(?:{_CONTROL_BLOCK_TAGS})\b[^\]]*\][^\n]*\n?",
    re.IGNORECASE,
)
_CONTROL_CLOSE_RE = re.compile(rf"\[/(?:{_CONTROL_BLOCK_TAGS})\]", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；.!?;])\s+|\n+")
_DELIVERY_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _truncate_prompt_text(text: str, limit: int) -> str:
    text = _compact_text(text)
    if len(text) <= limit:
        return text
    if limit <= 16:
        return text[:limit]
    return f"{text[: max(1, limit - 4)].rstrip()} ..."


def _normalize_lookup(value) -> str:
    return re.sub(r"[\s·•・/／,，、;；:：\-_—|()（）【】\[\]]+", "", str(value or "").strip().lower())


def _lookup_matches(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a == b or (len(a) >= 2 and a in b) or (len(b) >= 2 and b in a)


def _strip_corner_quote_wrapper(text: str) -> str:
    out = (text or "").strip()
    while out.startswith("「") and out.endswith("」") and len(out) >= 2:
        out = out[1:-1].strip()
    return out


def _is_pc_speaker(speaker: str) -> bool:
    return _normalize_lookup(speaker) in {"pc", "playercharacter", "玩家角色"}


def _gender_hint(label: str) -> str:
    lower = (label or "").lower()
    if re.search(r"女|妇|娘|姐|妹|妈|母|婆|奶奶|姑|阿姨|太太|woman|lady|girl|female|miss|madam", lower):
        return "female"
    if re.search(r"男|先生|大叔|大爷|爷爷|父亲|爸|小伙|汉子|少年|老头|man|boy|male|sir|mister", lower):
        return "male"
    return ""


def _strip_json_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3].rstrip()
    if text.lower().startswith("json\n"):
        text = text[5:].strip()
    return text


def _sanitize_tts_text(text: str, *, keep_speak_tags: bool) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</p\s*>", "\n\n", cleaned, flags=re.IGNORECASE)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"```[\s\S]*?```", "\n", cleaned)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", lambda m: (m.group(1) or "").strip(), cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    if not keep_speak_tags:
        cleaned = _SPEAK_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*>\s?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+(?=\S)", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+(?=\S)", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*\n]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_\n]+)_", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)

    lines: list[str] = []
    for line in cleaned.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if set(stripped) <= {"-", "_", "*", "=", " "}:
            continue
        if "|" in stripped:
            cells = [cell.strip() for cell in stripped.strip("|").split("|") if cell.strip()]
            stripped = "，".join(cells) if cells else ""
        stripped = re.sub(r"\s+", " ", stripped).strip()
        if stripped:
            lines.append(stripped)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _sanitize_speaker_name(value: str) -> str:
    text = _sanitize_tts_text(value, keep_speak_tags=False)
    return re.sub(r"\s+", " ", text).strip()


def _render_semantic_blocks_for_tts(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(1).lower()
        content = _compact_text(match.group(2))
        if not content:
            return ""
        if tag == "thought":
            inner = content.replace("「", "").replace("」", "")
            return f"「{inner}」[speak]PC[/speak]"
        prefixes = {
            "sign": "牌子上写着：",
            "note": "字条上写着：",
            "screen": "屏幕上显示：",
            "memory": "记忆里浮现：",
            "ooc": "GM补充说明：",
            "oss": "远处传来：",
        }
        return f"{prefixes.get(tag, '')}{content}"

    rendered = _SEMANTIC_BLOCK_RE.sub(replace, text)
    for tag in ("sign", "note", "screen", "memory", "ooc", "oss"):
        rendered = re.sub(rf"\[{tag}\]", "", rendered, flags=re.IGNORECASE)
        rendered = re.sub(rf"\[/{tag}\]", "", rendered, flags=re.IGNORECASE)
    return rendered


def _strip_control_markers(text: str) -> str:
    text = _INLINE_CONTROL_RE.sub("", text)
    text = _CONTROL_BLOCK_RE.sub("", text)
    text = _CONTROL_OPEN_LINE_RE.sub("", text)
    text = _CONTROL_CLOSE_RE.sub("", text)
    text = re.sub(r"\[dice\][\s\S]*?\[/dice\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[debug\][\s\S]*?\[/debug\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[/?(?:ATMOSPHERE|CREATE_CHARACTER)\]", "", text, flags=re.IGNORECASE)
    return text


def _prepare_tts_source(text: str) -> str:
    # `sanitize_markers` is imported lazily to avoid a cycle: this module is
    # imported by `services.trpg_tts` which already imports marker sanitize.
    from services.trpg_marker_sanitize import sanitize_markers

    prepared = sanitize_markers(text or "")
    prepared = _render_semantic_blocks_for_tts(prepared)
    prepared = _strip_control_markers(prepared)
    prepared = _sanitize_tts_text(prepared, keep_speak_tags=True)
    return prepared.strip()


def _split_text(text: str, *, max_chars: int) -> list[str]:
    text = text.strip()
    if not text or len(text) <= max_chars:
        return [text] if text else []
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text) if p and p.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if current and len(current) + len(part) + 1 > max_chars:
            chunks.append(current.strip())
            current = part
        else:
            current = f"{current} {part}".strip() if current else part
    if current:
        chunks.append(current.strip())
    if chunks:
        return chunks
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
