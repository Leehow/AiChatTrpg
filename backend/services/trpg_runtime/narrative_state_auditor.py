"""Audit narration against structured state changes.

This is not a replacement for an LLM auditor. It is a deterministic first-pass
safety net that catches common mismatches such as narration saying an NPC drew
a weapon while no corresponding state change was emitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .turn_output_contract import StateChange, StateChangeType


@dataclass(frozen=True)
class AuditWarning:
    warning_type: str
    message: str
    severity: str = "warning"  # info | warning | error
    matched_text: str | None = None
    expected_change_type: StateChangeType | None = None


class NarrativeStateAuditor:
    _PATTERNS: tuple[tuple[re.Pattern[str], StateChangeType, str], ...] = (
        (re.compile(r"(受伤|受了伤|流血|中弹|被砍|hp|hit points|wounded|injured|takes? \d+ damage)", re.I), StateChangeType.CHARACTER_DAMAGE, "narration implies character damage"),
        (re.compile(r"(拔出|掏出|拿出|举起).{0,8}(刀|剑|枪|匕首|weapon|knife|sword|gun|pistol)", re.I), StateChangeType.STATUS_EFFECT, "narration implies equipped/readied weapon or status"),
        (re.compile(r"(拿走|捡起|交给|递给|藏进|放进|偷走|takes?|picks up|hands? .* to|hides?)", re.I), StateChangeType.ITEM_TRANSFER, "narration implies item ownership/location changed"),
        (re.compile(r"(离开|进入|走进|走出|抵达|前往|moves? to|arrives?|enters?|leaves?)", re.I), StateChangeType.ENTITY_LOCATION, "narration implies entity location changed"),
        (re.compile(r"(发现线索|找到线索|发现了|找到.{0,12}(账本|钥匙|血迹|clue|discovers?|finds?))", re.I), StateChangeType.CLUE_DISCOVERED, "narration implies a clue was discovered"),
        (re.compile(r"(信任|怀疑|敌意|警惕|愤怒|trust|suspicious|hostile|wary|angry)", re.I), StateChangeType.NPC_ATTITUDE, "narration implies NPC attitude changed"),
        (re.compile(r"(时间过去|过了\d+|天亮|黄昏|深夜|time passes|hours? later|next morning)", re.I), StateChangeType.TIME_ADVANCE, "narration implies time advanced"),
    )

    _PLAYER_AGENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(你决定|你选择|你转身逃跑|你忍不住说|你立刻攻击|you decide|you choose|you run away|you attack)", re.I),
    )

    def audit(self, narration: str, state_changes: tuple[StateChange, ...]) -> tuple[AuditWarning, ...]:
        warnings: list[AuditWarning] = []
        change_types = {change.type for change in state_changes}
        for pattern, expected_type, message in self._PATTERNS:
            match = pattern.search(narration)
            if match and expected_type not in change_types:
                warnings.append(
                    AuditWarning(
                        warning_type="narrative_state_mismatch",
                        message=f"{message}, but no {expected_type.value} state change was provided",
                        severity="warning",
                        matched_text=match.group(0),
                        expected_change_type=expected_type,
                    )
                )
        for pattern in self._PLAYER_AGENCY_PATTERNS:
            match = pattern.search(narration)
            if match:
                warnings.append(
                    AuditWarning(
                        warning_type="possible_player_agency_violation",
                        message="narration may be deciding a major player action instead of asking the player",
                        severity="warning",
                        matched_text=match.group(0),
                    )
                )
        return tuple(warnings)
