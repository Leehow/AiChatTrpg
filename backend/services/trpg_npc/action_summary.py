"""LLM-compressed NPC action history.

Each NPC carries one ``action_summary`` field — a single descriptive
sentence (or short paragraph for very active NPCs) covering everything
the player has watched them do that still matters. Instead of an
unbounded ``actions[]`` list with embedding-based retrieval (chatlab's
approach), we ask an LLM to *rewrite* the summary every time a new
event lands, keeping critical details and dropping stale ones.

Why not actions list:

- A list grows monotonically; a summary stays bounded.
- The GM prompt only needs "what's true about this NPC's recent
  behaviour", not a chronological log.
- No embedding service, no vector store, no similarity ranking.
- Stale details fall away naturally (the LLM is told to drop them);
  important continuity stays in the summary because we feed the
  previous summary as the starting point.

The summary is passive — it describes what the NPC has done and what's
relevant about their current behavioural posture. It does NOT predict
future actions (that's presim's job, not yet ported).
"""

from __future__ import annotations

import logging
from typing import Any

from agents.trpg.llm_json import call_llm_json_task


logger = logging.getLogger("chatrpg.trpg_npc.action_summary")


SUMMARY_MAX_CHARS = 280


_SUMMARY_PROMPT = """You maintain a one-sentence (occasionally 2-sentence) running summary
of an NPC's behaviour in a TRPG session. Your job each turn: read the
current summary plus the new event, and rewrite the summary so it
captures what is currently TRUE and IMPORTANT about how this NPC has
been behaving toward the PC and the scene.

## Inputs
- NPC profile (name, role, personality)
- Current summary (may be empty on first call)
- New event (one short paragraph describing what just happened)

## Rules
- Output ONE updated summary. Plain text only. No markdown, no quotes,
  no labels.
- Keep the language matching the source (Chinese events → Chinese
  summary, English → English).
- Limit: roughly {max_chars} characters. If you must drop something,
  drop the OLDEST and LEAST CONSEQUENTIAL detail first.
- Keep details that are still influencing how the NPC will behave next:
  threats made, weapons drawn, secrets revealed, allegiances stated,
  injuries taken, lies told, debts owed.
- Drop detail that's no longer mechanically or narratively load-bearing:
  small talk, weather descriptions, completed routine actions.
- Don't add your own narration. Don't speculate about what the NPC
  will do next. Past + present only.
- Don't include the NPC's name as a prefix; the summary is implicitly
  about them.

Output the new summary text only."""


async def update_action_summary(
    npc: dict[str, Any],
    new_event: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    max_chars: int = SUMMARY_MAX_CHARS,
) -> bool:
    """Rewrite ``npc["action_summary"]`` to incorporate ``new_event``.

    Returns True when the summary was updated. The NPC dict is
    mutated in place; the caller is responsible for ``flag_modified``
    + commit (which the agent's ``save()`` handles automatically).

    The LLM call is best-effort. On failure the existing summary is
    left untouched and we just log — losing one event is far better
    than losing the whole summary.
    """
    if not isinstance(npc, dict):
        return False
    event = (new_event or "").strip()
    if not event:
        return False
    if not (model and base_url and api_key):
        # No LLM available — fall back to plain append, capped at max_chars.
        return _fallback_append(npc, event, max_chars=max_chars)

    name = str(npc.get("name") or npc.get("key") or "this NPC")
    role = str(npc.get("role") or "")
    personality = str(npc.get("personality") or "")
    current = str(npc.get("action_summary") or "")

    user_message = (
        f"NPC: {name}\n"
        f"Role: {role or '(unspecified)'}\n"
        f"Personality: {personality or '(unspecified)'}\n\n"
        f"Current summary: {current or '(none — this is the first event)'}\n\n"
        f"New event:\n{event}"
    )
    try:
        raw = await call_llm_json_task(
            stage="npc_action_summary",
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prefix=_SUMMARY_PROMPT.format(max_chars=max_chars),
            user_message=user_message,
            stream=False,
        )
    except Exception:
        logger.warning(
            "[chatrpg.trpg_npc.action_summary] LLM call failed for %s, falling back to append",
            name, exc_info=True,
        )
        return _fallback_append(npc, event, max_chars=max_chars)

    text = (raw or "").strip()
    if not text:
        return _fallback_append(npc, event, max_chars=max_chars)
    # Hard cap — the prompt asks for ~max_chars, but defend against the
    # model occasionally going long.
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    if text == current:
        return False
    npc["action_summary"] = text
    return True


def _fallback_append(npc: dict[str, Any], event: str, *, max_chars: int) -> bool:
    """Best-effort summary update without LLM.

    Used when no LLM config is supplied or the LLM call failed. Just
    concatenates the new event and trims from the FRONT (oldest first)
    to keep within the cap. Quality is poor (no real summarisation) but
    at least the field stays bounded and contains the most recent
    behaviour.
    """
    current = str(npc.get("action_summary") or "")
    candidate = f"{current} | {event}".strip(" |") if current else event
    if len(candidate) > max_chars:
        # Drop characters from the front until we fit, then trim to a
        # word boundary if possible.
        candidate = candidate[-max_chars:]
        sep = candidate.find(" | ")
        if sep > 0:
            candidate = candidate[sep + 3:]
    if candidate == current:
        return False
    npc["action_summary"] = candidate
    return True
