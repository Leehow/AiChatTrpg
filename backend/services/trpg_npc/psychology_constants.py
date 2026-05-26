"""Constants and regex hints for :mod:`services.trpg_npc.psychology`.

Split out from ``psychology.py`` so the rubric table and the keyword regex
patterns can live in a focused module while the facade keeps the public API
and higher-level logic. Keep the patterns synced with chatlab whenever
chatlab evolves — both projects must score the same NPC text the same way.
"""

from __future__ import annotations

import re
from typing import Any


INTEREST_RUBRIC: tuple[dict[str, Any], ...] = (
    {
        "min": 0, "max": 0, "band": "0", "label": "none",
        "guidance": (
            "No desire to interact with the PC. Avoids personal questions "
            "and only reacts to direct, unavoidable contact."
        ),
    },
    {
        "min": 1, "max": 2, "band": "1-2", "label": "low/passive",
        "guidance": (
            "Not interested in the PC personally. Notices obvious visible "
            "facts but keeps interaction brief unless duty or survival "
            "requires it."
        ),
    },
    {
        "min": 3, "max": 4, "band": "3-4", "label": "mild/contextual",
        "guidance": (
            "May ask ordinary situational questions, such as business, "
            "safety, or relationship-maintenance questions, but avoids "
            "sustained probing."
        ),
    },
    {
        "min": 5, "max": 6, "band": "5-6", "label": "active/professional",
        "guidance": (
            "Actively engages when relevant. Can ask follow-up questions, "
            "test inconsistencies, or steer one exchange toward useful "
            "disclosure."
        ),
    },
    {
        "min": 7, "max": 8, "band": "7-8", "label": "strong/goal-driven",
        "guidance": (
            "Strongly wants something from the PC. Creates opportunities "
            "to interact, uses leading questions, bargains, pressure, or "
            "checks."
        ),
    },
    {
        "min": 9, "max": 10, "band": "9-10", "label": "obsessive/mission-critical",
        "guidance": (
            "The PC interaction objective is urgent or central. "
            "Repeatedly probes, may surveil, recruit, trap, or coordinate "
            "with allies, but still cannot invent facts outside "
            "known_facts/exposure_log."
        ),
    },
)


INNER_STATE_THOUGHT_CAP = 5


_PREEXISTING_RE = re.compile(
    r"("
    r"from_bond|bond_context|old\s+friend|childhood\s+friend|"
    r"friend\s+of\s+the\s+(pc|player|character)|"
    r"(pc|player|character)'?s\s+friend|"
    r"family\s+(member|contact|friend)|relative|spouse|partner|lover|"
    r"colleague|coworker|mentor|student|handler|supervisor|boss|employer|"
    r"knows?\s+the\s+(pc|player|character)|already\s+knows?|"
    r"认识玩家|认识主角|玩家的朋友|主角的朋友|旧友|老朋友|熟人|"
    r"亲人|家人|同事|导师|学生|上司|雇主|搭档|恋人|旧识"
    r")",
    re.IGNORECASE,
)
_PLOT_ACCESS_RE = re.compile(
    r"("
    r"briefed|dossier|assigned|surveil|monitor|track|hunt|"
    r"investigating\s+(the\s+)?(pc|player|character)|"
    r"looking\s+for|sent\s+to|handler|case\s+file|investigation\s+file|"
    r"简报|档案|受命|监视|盯梢|追踪|追捕|寻找|奉命|线人|"
    r"调查玩家|调查主角|调查角色|调查档案|案件档案"
    r")",
    re.IGNORECASE,
)
_HIGH_INTEREST_RE = re.compile(
    r"("
    r"detective|investigator|journalist|reporter|guard|officer|police|"
    r"doctor|clerk|manager|owner|handler|spy|informant|curious|suspicious|"
    r"侦探|调查员|记者|警官|警察|守卫|保安|医生|店主|老板|经理|线人|间谍|好奇|怀疑"
    r")",
    re.IGNORECASE,
)
_LOW_INTEREST_RE = re.compile(
    r"("
    r"shy|withdrawn|reclusive|misanthropic|hostile|distant|unfriendly|"
    r"羞涩|孤僻|内向|冷淡|敌意|不愿交谈|疏远"
    r")",
    re.IGNORECASE,
)
_SOCIAL_DRIVE_RE = re.compile(
    r"("
    r"sociable|social|friendly|chatty|talkative|outgoing|gregarious|"
    r"likes?\s+making\s+friends|wants?\s+friends?|lonely|bored|curious|"
    r"爱交朋友|喜欢交朋友|健谈|话多|热情|外向|友善|孤独|寂寞|无聊|好奇"
    r")",
    re.IGNORECASE,
)
_AFFINITY_DRIVE_RE = re.compile(
    r"("
    r"common\s+(hobby|interest|profession|background)|shared\s+(hobby|interest|profession|background)|"
    r"same\s+(profession|job|trade|hobby|school|hometown)|fellow\s+(traveler|doctor|soldier|artist|scholar|agent)|"
    r"共同爱好|共同兴趣|共同职业|共同经历|同行|同业|同好|老乡|同乡|同校|同门"
    r")",
    re.IGNORECASE,
)
_GOAL_RE = re.compile(
    r"("
    r"wants?|needs?|goal|objective|task|mission|target|hire|recruit|"
    r"想要|希望|目的|目标|任务|追求|雇佣|招募|寻找"
    r")",
    re.IGNORECASE,
)
