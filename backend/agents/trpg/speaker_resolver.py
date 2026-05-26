"""Resolve TRPG [speak] tag labels to stable NPC keys.

GM narration emits `[speak]label[/speak]` where the label is a display string:
a real name, nickname, or a descriptive bystander label like "灰发工装男人".
Frontend portrait / future voice lookup is more stable when tags also carry
the NPC key:

    [speak]name[/speak]                 -> legacy, no annotation
    [speak:emotion]name[/speak]         -> emotion only
    [speak::npc_key]name[/speak]        -> key only
    [speak:emotion:npc_key]name[/speak] -> both

Unresolved labels are left unchanged so one-off bystanders still render with
generic silhouettes and stable per-label colors.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


_SPEAK_TAG_RE = re.compile(
    r"\[speak(?::(?P<emotion>[\w-]*))?(?::(?P<key>[\w.-]*))?\]"
    r"(?P<label>[^\[]+?)"
    r"\[/speak\]",
    re.IGNORECASE,
)

_CJK_RE = re.compile(r"[一-鿿]")
_TITLE_SUFFIX_RE = re.compile(
    r"(牧师|祭司|神父|医生|警长|警察|司机|店主|老板|侍者|守卫|卫兵|士兵|教授|老师|记者)$"
)
_DESCRIPTIVE_SUFFIX_RE = re.compile(
    r"(男人|女人|男子|女子|男孩|女孩|少年|少女|大叔|大妈|老人|老妇|老头|先生|女士|家伙|路人|旁观|人物)$"
)
_TITLE_EQUIVALENTS = {
    "牧师": ("牧师", "祭司", "神父", "priest", "pastor", "clergy", "minister"),
    "祭司": ("祭司", "牧师", "神父", "priest", "pastor", "clergy", "minister"),
    "神父": ("神父", "牧师", "祭司", "priest", "pastor", "clergy", "minister"),
    "医生": ("医生", "医师", "doctor", "physician"),
    "警长": ("警长", "警察", "sheriff", "police"),
    "警察": ("警察", "警长", "police", "sheriff"),
    "司机": ("司机", "driver"),
    "店主": ("店主", "老板", "owner", "shopkeeper"),
    "老板": ("老板", "店主", "owner", "boss"),
    "侍者": ("侍者", "waiter", "server"),
    "守卫": ("守卫", "卫兵", "guard"),
    "卫兵": ("卫兵", "守卫", "guard"),
    "士兵": ("士兵", "soldier"),
    "教授": ("教授", "professor"),
    "老师": ("老师", "teacher"),
    "记者": ("记者", "journalist", "reporter"),
}
_DESCRIPTIVE_CHAR_STOPWORDS = frozenset(
    "的了是在和有他她你我们着又人者个一二三里中上下前后"
)
_DESCRIPTIVE_FIELDS = (
    "description", "brief", "role", "appearance", "personality",
    "public_description", "summary", "portrait_prompt",
    "公开身份", "描述", "外观", "身份",
)
_NON_NPC_SPEAKERS = {"pc", "gm", "kp", "keeper", "narrator", "旁白", "系统"}
_GENERIC_VISIBLE_LABELS = {
    "未知",
    "未标注",
    "陌生人",
    "陌生男性",
    "陌生女性",
    "陌生男人",
    "陌生女人",
    "男人",
    "女人",
    "男子",
    "女子",
    "老人",
    "司机",
    "医生",
    "祭司",
    "老板",
    "店主",
}
_UNTRACKABLE_GENERIC_LABELS = {
    "未知",
    "未标注",
    "陌生人",
    "陌生男性",
    "陌生女性",
    "陌生男人",
    "陌生女人",
    "男人",
    "女人",
    "男子",
    "女子",
    "老人",
}
_VOICE_LABEL_RE = re.compile(
    r"(声音|广播|电台|无线电|对讲机|喇叭|扩音器|录音|留声机|话筒|麦克风|音响|电话|旁白)$"
)


@dataclass(frozen=True)
class SpeakerTagRef:
    label: str
    emotion: str = ""
    key: str = ""


def _normalize(text: str) -> str:
    return re.sub(r"[\s·•・/／,，、;；:：\-_—|]+", "", str(text or "").strip().lower())


def _normalize_loose(text: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(text or "").strip().lower())


def _collect_descriptive_text(npc: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in _DESCRIPTIVE_FIELDS:
        value = npc.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if str(item).strip())
    return " ".join(parts).lower()


def _name_aliases(npc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for field in (
        "name", "full_name", "display_name", "short_name", "nickname",
        "alias", "player_known_name", "claimed_name", "known_as",
        "public_name",
    ):
        value = npc.get(field)
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    aliases = npc.get("aliases")
    if isinstance(aliases, str) and aliases.strip():
        out.append(aliases.strip())
    elif isinstance(aliases, list):
        out.extend(str(a).strip() for a in aliases if str(a).strip())
    return out


def _match_by_name(label: str, npcs: list[dict[str, Any]]) -> str | None:
    label_norm = _normalize(label)
    if not label_norm:
        return None
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        key = npc.get("key")
        if not key:
            continue
        for alias in _name_aliases(npc):
            alias_norm = _normalize(alias)
            if not alias_norm:
                continue
            if label_norm == alias_norm or label_norm in alias_norm or alias_norm in label_norm:
                return str(key)
    return None


def _split_title_label(label: str) -> tuple[str, str] | None:
    clean = (label or "").strip()
    match = _TITLE_SUFFIX_RE.search(clean)
    if not match:
        return None
    title = match.group(1)
    stem = clean[:match.start()].strip()
    if len(_normalize_loose(stem)) < 2:
        return None
    return stem, title


def _title_matches_npc(title: str, npc: dict[str, Any]) -> bool:
    equivalents = _TITLE_EQUIVALENTS.get(title, (title,))
    text = " ".join(
        str(npc.get(field) or "")
        for field in (
            "player_known_name", "public_name", "display_name", "claimed_name",
            "known_as", "role", "occupation", "summary", "description",
            "public_description", "appearance", "portrait_prompt",
        )
    ).lower()
    return any(eq.lower() in text for eq in equivalents)


def _match_by_title_label(label: str, npcs: list[dict[str, Any]]) -> str | None:
    split = _split_title_label(label)
    if split is None:
        return None
    stem, title = split
    stem_norm = _normalize_loose(stem)
    best_key: str | None = None
    best_score = 0
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        key = npc.get("key")
        if not key or not _title_matches_npc(title, npc):
            continue
        for alias in _name_aliases(npc):
            alias_norm = _normalize_loose(alias)
            if not alias_norm:
                continue
            if stem_norm in alias_norm or alias_norm in stem_norm:
                score = min(len(stem_norm), len(alias_norm))
                if score > best_score:
                    best_score = score
                    best_key = str(key)
    return best_key


def _match_by_descriptive(label: str, npcs: list[dict[str, Any]]) -> str | None:
    raw = (label or "").strip()
    if not raw or not _CJK_RE.search(raw):
        return None
    # Descriptive matching is intentionally only for labels that look like
    # descriptions ("灰发工装男人"). Short proper names such as "拉斯" can
    # otherwise collide with arbitrary characters in hidden NPC prose, e.g.
    # "拉丁文" + "赛斯".
    if not _DESCRIPTIVE_SUFFIX_RE.search(raw):
        return None
    stem = _DESCRIPTIVE_SUFFIX_RE.sub("", raw).strip() or raw
    chars = {
        ch for ch in stem
        if _CJK_RE.match(ch) and ch not in _DESCRIPTIVE_CHAR_STOPWORDS
    }
    if len(chars) < 2:
        return None

    min_score = max(2, (len(chars) + 1) // 2)
    best_key: str | None = None
    best_score = 0
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        key = npc.get("key")
        if not key:
            continue
        text = _collect_descriptive_text(npc)
        if not text:
            continue
        score = sum(1 for ch in chars if ch.lower() in text)
        if score >= min_score and score > best_score:
            best_score = score
            best_key = str(key)
    return best_key


def resolve_speaker_label(label: str, npcs: list[dict[str, Any]]) -> str | None:
    """Return a matching NPC key, or None if no confident match."""
    if not label or not npcs:
        return None
    key = _match_by_name(label, npcs)
    if key:
        return key
    key = _match_by_title_label(label, npcs)
    if key:
        return key
    return _match_by_descriptive(label, npcs)


def iter_speaker_tags(content: str) -> list[SpeakerTagRef]:
    """Return visible speaker labels in order of appearance."""
    if not content:
        return []
    refs: list[SpeakerTagRef] = []
    for match in _SPEAK_TAG_RE.finditer(content):
        refs.append(SpeakerTagRef(
            label=(match.group("label") or "").strip(),
            emotion=(match.group("emotion") or "").strip(),
            key=(match.group("key") or "").strip(),
        ))
    return refs


def is_probable_named_speaker(label: str) -> bool:
    """Heuristic for auto-creating visible NPCs from spoken dialogue.

    We only create entries for stable-looking names, not generic descriptors
    or system speakers. One-off bystanders can still render as colored spans
    without entering the NPC runtime roster.
    """
    clean = str(label or "").strip()
    if not clean:
        return False
    if clean.lower() in _NON_NPC_SPEAKERS:
        return False
    if clean in _GENERIC_VISIBLE_LABELS:
        return False
    if _split_title_label(clean):
        return False
    if _DESCRIPTIVE_SUFFIX_RE.search(clean):
        return False
    if len(clean) > 32:
        return False
    return bool(_CJK_RE.search(clean) or re.search(r"[A-Za-z]", clean))


def is_trackable_visible_speaker(label: str) -> bool:
    """Return true when a spoken label should enter the PC-known NPC roster.

    This is broader than ``is_probable_named_speaker``: role/description
    labels like "医生" or "灰发工装男人" are not true names, but the PC has
    still perceived a concrete person. Extremely generic labels ("陌生人",
    "男人") and disembodied voice labels stay out to avoid roster spam.
    """
    clean = str(label or "").strip()
    if not clean:
        return False
    if clean.lower() in _NON_NPC_SPEAKERS:
        return False
    if clean in _UNTRACKABLE_GENERIC_LABELS:
        return False
    if _VOICE_LABEL_RE.search(clean):
        return False
    if len(clean) > 40:
        return False
    return bool(_CJK_RE.search(clean) or re.search(r"[A-Za-z]", clean))


def annotate_speak_tags(content: str, npcs: list[dict[str, Any]]) -> str:
    """Insert stable NPC keys into `[speak]` tags when labels resolve.

    Idempotent: tags already carrying a key are left unchanged.
    """
    if not content or not npcs:
        return content
    cache: dict[str, str | None] = {}

    def _replace(match: re.Match) -> str:
        existing_emotion = (match.group("emotion") or "").strip()
        existing_key = (match.group("key") or "").strip()
        label = (match.group("label") or "").strip()
        if existing_key:
            return match.group(0)
        if label not in cache:
            cache[label] = resolve_speaker_label(label, npcs)
        key = cache[label]
        if not key:
            return match.group(0)
        prefix = f"[speak:{existing_emotion}:{key}]"
        return f"{prefix}{match.group('label')}[/speak]"

    return _SPEAK_TAG_RE.sub(_replace, content)
