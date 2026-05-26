"""Streaming ``[CHECK ...]`` marker replacement for TRPG GM output.

The GM emits a single-line marker like::

    [CHECK skill="Stealth" value=75 roll=20 difficulty=hard reason="深夜潜行"]

We buffer the stream byte-by-byte, and when a full marker lands we hand
its attributes to ``check_resolver`` and emit a rendered
``[dice]...[/dice]`` block in its place. The player never sees the raw
marker — by the time a chunk reaches the SSE client it's already either
plain narration or a finished ``[dice]`` block.

Design choices:
- **Conservative buffering**: only starts buffering when it sees the
  exact 7-char sequence ``"[CHECK "`` or ``"[CHECK]"``. Anything else
  passes straight through, so streaming latency is unaffected for
  normal prose.
- **Length cap**: if a buffered marker grows past ``MAX_MARKER_CHARS``
  without a closing ``]``, the wrapper flushes the buffer verbatim and
  resumes. This protects against pathological malformed markers.
- **Engine dispatch**: ``session.check_spec`` (or ``ruleset.check_spec``)
  picks the engine. Missing spec → ``custom_llm`` fallback → marker is
  preserved so the audit pass can flag the missing spec.
- **Sanitization**: also strips ``[CHECK]`` accidental close tags if
  present, and normalizes ``[CHECK_SKILL]`` style typos via a single
  regex before buffering.
"""

from __future__ import annotations

import logging
import re
from typing import Any, AsyncGenerator, Dict, Iterator, Optional, Tuple

from .check_actor_adapter import (
    ActorLookupContext,
    apply_actor_value_lookup,
    has_actor_lookup_request,
)
from .check_resolver import CheckArgs
from .check_runtime import (
    CheckExecution,
    execute_check_runtime,
    prepare_check_context,
    render_pending_check,
)

logger = logging.getLogger("chatlab.trpg")

MARKER_OPEN = "[CHECK"
MAX_MARKER_CHARS = 800   # marker payloads should be tiny; cap as a safety net

# Any proper prefix of ``[CHECK`` that could be the start of a marker
# split across a streaming-chunk boundary. ``[CHECK`` itself (6 chars) is
# also included because we can only decide whether it's really a marker
# once we see the char after it (space / ']' / whitespace). If the chunk
# ends with any of these, we stash it and wait for the next chunk rather
# than leaking a half-marker to the client.
_POTENTIAL_MARKER_PREFIXES = frozenset({
    "[", "[C", "[CH", "[CHE", "[CHEC", "[CHECK",
})

_MANDATORY_CHECK_TOKENS = (
    "sanity",
    "sancheck",
    "sanroll",
    "sanitycheck",
    "sanityroll",
    "sanloss",
    "horror",
    "fear",
    "terror",
    "fright",
    "stresscheck",
    "理智",
    "理智检定",
    "理智损失",
    "san值",
    "恐惧",
    "惊吓",
    "惊恐",
)

_OPTIONAL_COMMIT_KEYS = (
    "optional",
    "player_choice",
    "commit_required",
    "requires_player_commit",
    "can_decline",
)


def _find_unquoted_close(text: str, start: int) -> int:
    """Find the closing `]` of a CHECK marker body.

    Skips `]` chars inside `"..."` / `'...'` quoted attribute values, and
    treats unquoted nested `[ ... ]` as balanced units. This lets the
    parser handle `[CHECK ... roll="[EXTRA_ROLL: 6d4 = 2,3,1,4,2,1]" ...]`
    by ignoring the inner `]` that lives inside the quoted attribute.

    Returns the index of the outer `]`, or -1 if not found in the slice
    (caller keeps buffering until the next chunk arrives).
    """
    quote: Optional[str] = None
    depth = 0
    j = start
    while j < len(text):
        ch = text[j]
        if quote:
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            if depth == 0:
                return j
            depth -= 1
        j += 1
    return -1


# ---------------------------------------------------------------------------
# Attribute parsing
# ---------------------------------------------------------------------------


# key=value where value is either "quoted string", number, or bareword.
# Keys accept ascii letters + underscore. Values may contain CJK, digits,
# commas, decimal points, plus/minus, and spaces (when quoted).
_ATTR_RE = re.compile(
    r'(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
    r'(?:"(?P<qval>[^"]*)"|'
    r"'(?P<sval>[^']*)'|"
    r'(?P<bval>[^\s\]"]+))'
)


_NUMERIC_KEYS = {"value", "bonus", "penalty", "target"}
_BASE_KEYS = {
    "skill", "value", "roll", "difficulty", "bonus", "penalty",
    "pool", "target", "reason",
}


def _coerce(key: str, raw: str) -> Any:
    """Numeric keys become ints; everything else stays a string."""
    if key in _NUMERIC_KEYS:
        try:
            return int(raw)
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                return raw
    return raw


def _coerce_extra(raw: str) -> Any:
    """Best-effort coercion for generic IR extension args."""
    text = str(raw or "").strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _truthy_extra(raw: Any) -> bool:
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _compact_check_text(raw: Any) -> str:
    return re.sub(r"[\s_\-./:：·|]+", "", str(raw or "").strip().lower())


def _looks_mandatory_check(args: CheckArgs, procedure_id: str, engine: str) -> bool:
    if any(_truthy_extra((args.extras or {}).get(key)) for key in _OPTIONAL_COMMIT_KEYS):
        return False
    parts = [
        args.skill,
        args.reason,
        procedure_id,
        engine,
        (args.extras or {}).get("check"),
        (args.extras or {}).get("check_key"),
        (args.extras or {}).get("procedure_id"),
    ]
    exact_labels = [
        _compact_check_text(args.skill),
        _compact_check_text((args.extras or {}).get("check")),
        _compact_check_text((args.extras or {}).get("check_key")),
    ]
    if any(label in {"san", "san值"} for label in exact_labels):
        return True
    haystack = _compact_check_text(" ".join(str(part or "") for part in parts))
    return any(token in haystack for token in _MANDATORY_CHECK_TOKENS)


def parse_check_marker(payload: str) -> Tuple[CheckArgs, Dict[str, str]]:
    """Parse the inner text of a ``[CHECK ...]`` marker.

    ``payload`` is the text BETWEEN ``[CHECK`` and the closing ``]``
    (i.e. what the regex captures as attribute pairs). Returns the
    built ``CheckArgs`` plus a raw attr map for diagnostics.
    """
    attrs: Dict[str, str] = {}
    for m in _ATTR_RE.finditer(payload or ""):
        key = m.group("key").lower()
        val = (
            m.group("qval")
            or m.group("sval")
            or m.group("bval")
            or ""
        )
        attrs[key] = val

    args = CheckArgs(
        skill=attrs.get("skill", ""),
        value=_coerce("value", attrs["value"]) if "value" in attrs else None,
        roll=attrs.get("roll"),
        difficulty=attrs.get("difficulty", "regular") or "regular",
        bonus=_coerce("bonus", attrs.get("bonus", "0")),
        penalty=_coerce("penalty", attrs.get("penalty", "0")),
        pool=attrs.get("pool", ""),
        target=_coerce("target", attrs["target"]) if "target" in attrs else None,
        reason=attrs.get("reason", ""),
        extras={
            key: _coerce_extra(val)
            for key, val in attrs.items()
            if key not in _BASE_KEYS
        },
    )
    return args, attrs


# ---------------------------------------------------------------------------
# Stream wrapper
# ---------------------------------------------------------------------------


class CheckMarkerStream:
    """Text-mode buffer that replaces ``[CHECK ...]`` markers inline.

    Not tied to any specific event type — callers feed `.feed(chunk)`
    with raw content text and pull fully-resolved text via `.drain()`.
    The final `.flush()` pushes any partial buffer out verbatim.
    """

    def __init__(
        self,
        spec: Optional[Dict[str, Any]],
        actor_context: ActorLookupContext | Dict[str, Any] | None = None,
        execution_sink: list[CheckExecution] | None = None,
    ):
        self.spec = spec or {}
        self.actor_context = actor_context
        self.execution_sink = execution_sink
        self._buffer = ""       # holds a partial marker in progress
        self._output = ""       # ready-to-emit text
        self._buffering = False  # True while inside a marker
        # Holds up to 6 chars that might be the start of "[CHECK" split
        # across a chunk boundary. Prepended to the next feed() input so
        # the marker is recognized once the rest of the bytes arrive.
        self._pending_prefix = ""

    def feed(self, text: str) -> None:
        """Consume a text chunk, possibly crossing marker boundaries."""
        if not text and not self._pending_prefix:
            return
        if self._pending_prefix:
            text = self._pending_prefix + text
            self._pending_prefix = ""
        remaining = self._buffer + text if self._buffering else text
        self._buffer = ""

        # Scan character-by-character; cheap enough for small chunks.
        i = 0
        while i < len(remaining):
            if self._buffering:
                close_idx = _find_unquoted_close(remaining, i)
                if close_idx == -1:
                    self._buffer = remaining[i:]
                    if len(self._buffer) > MAX_MARKER_CHARS:
                        # Flush verbatim — something's wrong.
                        logger.warning(
                            "[TRPG] [CHECK] marker overflow (%d chars), flushing verbatim",
                            len(self._buffer),
                        )
                        self._output += self._buffer
                        self._buffer = ""
                        self._buffering = False
                    break
                marker_body = remaining[i:close_idx]
                rendered = self._resolve(marker_body)
                self._output += rendered
                i = close_idx + 1
                self._buffering = False
                continue

            open_idx = remaining.find(MARKER_OPEN, i)
            if open_idx == -1:
                self._output += remaining[i:]
                break

            # Conservative: require a space or `]` right after "[CHECK".
            # Protects things like "[CHECKLIST]" from being swallowed.
            peek_start = open_idx + len(MARKER_OPEN)
            if peek_start >= len(remaining):
                # Chunk ended exactly at "[CHECK" — can't tell yet.
                # Emit everything before the "[" and stash the rest.
                self._output += remaining[i:open_idx]
                self._pending_prefix = remaining[open_idx:]
                return
            after = remaining[peek_start:peek_start + 1]
            if after not in (" ", "]", "\t", "\n"):
                # Not our marker — pass the '[' through and keep scanning.
                self._output += remaining[i:open_idx + 1]
                i = open_idx + 1
                continue

            self._output += remaining[i:open_idx]
            i = open_idx + len(MARKER_OPEN)
            self._buffering = True
            self._buffer = ""
            # Loop continues; buffering branch picks up from here.

        # Defensive tail check: if the output ends with a proper prefix of
        # "[CHECK" (e.g. chunk ended at "[", "[C", "[CH", ...), move those
        # chars into _pending_prefix so we re-scan them with the next
        # chunk. Without this, a boundary between "[" and "CHECK..." (or
        # anywhere inside the 6-char prefix) would leak as raw text.
        if not self._buffering and self._output:
            for length in range(min(len(MARKER_OPEN), len(self._output)), 0, -1):
                tail = self._output[-length:]
                if tail in _POTENTIAL_MARKER_PREFIXES:
                    self._pending_prefix = tail
                    self._output = self._output[:-length]
                    break

    def _resolve(self, marker_body: str) -> str:
        """Given text between '[CHECK' and ']', return the rendered block.

        Auto vs pending split:
        - ``auto=true`` or a known mandatory mechanic (e.g. SAN / horror /
          fear checks): roll inline, replace with the rendered ``[dice]``
          block.
        - default (no ``auto`` attr or ``auto=false``): emit a
          ``[pending_check id=... ...]`` placeholder so the frontend can
          render a "投出" button. The player decides when to commit; if
          they pivot to a different action instead, the placeholder simply
          ages out — nothing is rolled until they click. Use
          ``optional=true`` to force this behavior for risky-but-declinable
          checks whose skill label otherwise looks mandatory."""
        # ``marker_body`` starts with either " attrs..." or "" (bare [CHECK]).
        args, _attrs = parse_check_marker(marker_body)
        args = apply_actor_value_lookup(args, self.actor_context)
        has_actor_lookup = has_actor_lookup_request(args)
        if (
            args.roll is None
            and args.value is None
            and args.target is None
            and not args.pool
            and not has_actor_lookup
        ):
            # Empty marker — preserve as-is, let audit flag it.
            logger.info("[TRPG] Empty [CHECK] marker encountered — passthrough")
            return "[CHECK" + marker_body + "]"
        procedure_id = str(args.extras.get("procedure_id") or "").strip()
        context = prepare_check_context(
            args,
            self.spec,
            procedure_id=procedure_id,
            system=args.extras.get("system"),
        )
        auto = args.extras.get("auto")
        mandatory = _looks_mandatory_check(
            args,
            context.procedure_id or procedure_id,
            context.engine,
        )
        if auto is True or args.roll is not None or (auto is not False and mandatory):
            # GM said auto, or supplied an actual roll already (e.g. earlier
            # debug injection / explicit dice from the player), or the check
            # is mechanically forced — resolve now.
            execution = execute_check_runtime(
                args,
                self.spec,
                procedure_id=procedure_id,
                system=args.extras.get("system"),
                auto_roll=True,
                source="inline_check",
            )
            if execution.result.warnings:
                for w in execution.result.warnings:
                    logger.info("[TRPG] CHECK resolve warning: %s", w)
            if self.execution_sink is not None:
                self.execution_sink.append(execution)
            return execution.rendered
        return render_pending_check(
            args,
            context.spec,
            procedure_id=context.procedure_id,
        )

    def drain(self) -> str:
        """Pull ready-to-emit text and reset the output accumulator."""
        out, self._output = self._output, ""
        return out

    def flush(self) -> str:
        """Final call: push any in-progress buffer out verbatim."""
        if self._pending_prefix:
            # Chunk ended on a "[CHECK" prefix and no more chunks arrived
            # — emit verbatim so nothing is silently dropped.
            self._output += self._pending_prefix
            self._pending_prefix = ""
        if self._buffering and self._buffer:
            # A marker was opened but never closed — emit verbatim.
            self._output += "[CHECK" + self._buffer
            self._buffer = ""
            self._buffering = False
        return self.drain()


# ---------------------------------------------------------------------------
# Async generator wrapper — drop-in replacement for the streaming source
# ---------------------------------------------------------------------------


async def replace_checks_in_stream(
    source: AsyncGenerator[Dict[str, Any], None],
    spec: Optional[Dict[str, Any]],
    actor_context: ActorLookupContext | Dict[str, Any] | None = None,
    execution_sink: list[CheckExecution] | None = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Wrap an event stream, replacing ``[CHECK ...]`` in ``content`` chunks.

    Non-``content`` events pass through untouched. When the source ends we
    flush any trailing buffer so no marker leaks through.
    """
    buf = CheckMarkerStream(
        spec,
        actor_context=actor_context,
        execution_sink=execution_sink,
    )
    async for event in source:
        if event.get("type") != "content":
            # Flush pending content before forwarding a non-content event
            tail = buf.drain()
            if tail:
                yield {"type": "content", "content": tail}
            yield event
            continue
        buf.feed(event.get("content", ""))
        out = buf.drain()
        if out:
            yield {"type": "content", "content": out}
    tail = buf.flush()
    if tail:
        yield {"type": "content", "content": tail}


# ---------------------------------------------------------------------------
# Synchronous helper — useful for audit passes on already-captured text
# ---------------------------------------------------------------------------


def replace_checks_in_text(
    text: str,
    spec: Optional[Dict[str, Any]],
    actor_context: ActorLookupContext | Dict[str, Any] | None = None,
    execution_sink: list[CheckExecution] | None = None,
) -> str:
    """Apply CHECK resolution to already-complete text (post-hoc fixup)."""
    buf = CheckMarkerStream(
        spec,
        actor_context=actor_context,
        execution_sink=execution_sink,
    )
    buf.feed(text)
    return buf.flush() or buf.drain()


def iter_check_markers(text: str) -> Iterator[Tuple[int, int, str]]:
    """Yield ``(start, end, body)`` for each CHECK marker in ``text``.

    Useful for audit/debugging. ``body`` is the inner attrs (no brackets).
    """
    i = 0
    while True:
        idx = text.find(MARKER_OPEN, i)
        if idx == -1:
            return
        after = text[idx + len(MARKER_OPEN):idx + len(MARKER_OPEN) + 1]
        if after not in (" ", "]", "\t", "\n"):
            i = idx + 1
            continue
        close = text.find("]", idx + len(MARKER_OPEN))
        if close == -1:
            return
        yield idx, close + 1, text[idx + len(MARKER_OPEN):close]
        i = close + 1
