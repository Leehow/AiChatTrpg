"""Per-update application + parsing helpers for NPC turn sync.

These helpers run *after* the LLM returns its ``npc_updates`` list. They
parse the JSON, audit each update against forbidden NPC memories, apply
text / interest / name-claim deltas through ``NpcAgent``, and stamp the
legacy text-projection marker on Runtime V2 NPCs.

The facade ``services.trpg_npc.turn_sync`` orchestrates calls to these
helpers; this module owns the per-update mutation logic so the facade
stays focused on workflow and prompt wiring.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from agents.trpg.llm_json import extract_json_object
from services.trpg_memory.memory_models import MemoryItem
from services.trpg_npc.leak_checker import LeakChecker


logger = logging.getLogger("chatrpg.trpg_npc.turn_sync")


_CLAIM_HISTORY_LIMIT = 6


def _parse_updates(raw: str) -> list[Any]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        obj = extract_json_object(text)
    except Exception:
        try:
            obj = _json.loads(text)
        except (TypeError, ValueError):
            logger.warning(
                "[chatrpg.trpg_npc.turn_sync] could not parse JSON: %.200s", text,
            )
            return []
    if not isinstance(obj, dict):
        return []
    updates = obj.get("npc_updates")
    return updates if isinstance(updates, list) else []


def _audit_update_memory_leaks(
    update: dict[str, Any],
    forbidden_memories: Any,
) -> tuple[Any, ...]:
    memories = tuple(
        memory for memory in (forbidden_memories or ())
        if isinstance(memory, MemoryItem)
    )
    if not memories:
        return ()
    generated_text = "\n".join(
        str(update.get(key) or "")
        for key in (
            "emotional_state",
            "motivation",
            "new_action_event",
        )
    )
    return LeakChecker().check(
        generated_text=generated_text,
        forbidden_memories=memories,
    )


def _apply_name_claim(agent: Any, key: str, claim: dict[str, Any]) -> bool:
    """Record a hidden NPC's spoken alias / cover name. Returns True when
    the NPC dict was mutated.

    If the claim happens to equal the true name, this is treated as a
    natural reveal (delegates to ``agent.reveal_name``) — better than
    letting a misclassification freeze the leak.

    Otherwise stores ``claimed_name`` + ``name_claim_truth`` + a rolling
    ``name_claim_history`` (capped at 6 entries) and lifts
    ``player_known_name`` to the alias so the GM next turn references
    the alias instead of the description.
    """
    npc = agent.get(key)
    if not npc:
        return False
    claimed = str(claim.get("claimed_name") or "").strip()
    if not claimed:
        return False
    true_name = str(npc.get("name") or "").strip()
    if true_name and claimed == true_name:
        return agent.reveal_name(key)

    truth = str(claim.get("truth_status") or "unknown").strip().lower()
    if truth not in ("false", "unknown", "true"):
        truth = "unknown"
    reason = str(claim.get("reason") or "").strip()
    history = list(npc.get("name_claim_history") or [])
    history.append(
        {"claimed_name": claimed, "truth_status": truth, "reason": reason[:240]}
    )
    updates: dict[str, Any] = {
        "claimed_name": claimed,
        "name_claim_truth": truth,
        "name_claim_history": history[-_CLAIM_HISTORY_LIMIT:],
    }
    if reason:
        updates["name_claim_reason"] = reason[:240]
    if npc.get("name_revealed") is not True:
        updates["player_known_name"] = claimed
    return bool(agent.update(key, **updates))


def _apply_interest_delta(
    agent: Any,
    key: str,
    delta: int,
) -> None:
    npc = agent.get(key)
    if not npc:
        return
    kn = npc.get("player_knowledge")
    if not isinstance(kn, dict):
        return
    current = kn.get("interest")
    try:
        cur_int = int(current)
    except (TypeError, ValueError):
        cur_int = 3
    new_value = max(0, min(10, cur_int + int(delta)))
    if new_value == cur_int:
        return
    kn["interest"] = new_value
    # Re-derive the frozen behaviour band from the new score.
    from services.trpg_npc.psychology import player_interest_profile
    kn["interest_profile"] = player_interest_profile(new_value)
    drive = kn.get("interest_drive")
    if isinstance(drive, dict):
        floor = int(drive.get("floor") or 0)
        drive["floor"] = min(floor, new_value)
    agent.mark_dirty()


def _has_runtime_v2(npc: dict[str, Any]) -> bool:
    return isinstance(npc.get("runtime_state_v2"), dict)


def _runtime_state_version(npc: dict[str, Any]) -> int:
    state = npc.get("runtime_state_v2")
    if not isinstance(state, dict):
        return 0
    try:
        return int(state.get("state_version") or 0)
    except (TypeError, ValueError):
        return 0


def _is_stale_v2_update(
    npc: dict[str, Any],
    key: str,
    expected_versions: dict[str, int],
) -> bool:
    if key not in expected_versions:
        return False
    return _runtime_state_version(npc) != int(expected_versions.get(key) or 0)


def _mark_v2_projection(
    agent: Any,
    key: str,
    *,
    based_on_turn_id: int | None,
    state_version: int,
) -> None:
    npc = agent.get(key)
    if not npc:
        return
    from services.trpg_npc.utils import now_iso

    npc["turn_sync_v2"] = {
        "mode": "legacy_text_projection",
        "based_on_turn_id": based_on_turn_id,
        "state_version": state_version,
        "updated_at": now_iso(),
    }
    agent.mark_dirty()
