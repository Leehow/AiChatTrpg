"""The 12 canonical scenario paradigms + custom fallback.

Sourced from the V6 rule parser's discovery prompt (`prompts/discovery.py`)
to keep the editor and parser aligned on what a "rule package" can be.
"""

from __future__ import annotations

from .base import ScenarioParadigm


CREATION = ScenarioParadigm(
    id="creation",
    description="character creation: stat generation, starting kit, session-zero choices",
    prompt_focus=(
        "Specify how players generate a new character: attributes, "
        "starting skills, gear/equipment kit, hooks, and any session-zero "
        "agreements."
    ),
    suggested_sections=(
        "Attributes", "Skills / Profession", "Starting Gear",
        "Background hooks", "Bonds & ties",
    ),
)

PROGRESSION = ScenarioParadigm(
    id="progression",
    description="XP / leveling / advancement / improvement rolls",
    prompt_focus=(
        "Specify how characters grow over time: XP awards, milestone "
        "criteria, skill improvement, level-up benefits, retraining."
    ),
    suggested_sections=(
        "XP / Milestones", "Skill improvement", "Class/role advancement",
        "Retraining", "Caps",
    ),
)

COMBAT = ScenarioParadigm(
    id="combat",
    description="initiative, attack/defend, damage, conditions",
    prompt_focus=(
        "Specify the combat round: initiative order, action economy, "
        "attack rolls, defense, damage application, conditions and "
        "status effects, death/incapacitation."
    ),
    suggested_sections=(
        "Initiative", "Action economy", "Attack & defense",
        "Damage & wounds", "Conditions", "Death & dying",
    ),
)

RECOVERY = ScenarioParadigm(
    id="recovery",
    description="healing, rest, body and mental damage recovery",
    prompt_focus=(
        "Specify how characters recover: short rest, long rest, "
        "magical/scientific healing, mental damage recovery, scarring."
    ),
    suggested_sections=(
        "Short / long rest", "Healing checks", "Mental recovery",
        "Permanent injuries / scars",
    ),
)

EXPLORATION = ScenarioParadigm(
    id="exploration",
    description="movement, hazards, dungeon-delving, perception checks",
    prompt_focus=(
        "Specify how the party explores: travel time, encumbrance, "
        "perception/search rolls, traps and hazards, light, navigation."
    ),
    suggested_sections=(
        "Movement & travel", "Perception & search", "Hazards & traps",
        "Light & navigation", "Encumbrance",
    ),
)

SOCIAL = ScenarioParadigm(
    id="social",
    description="persuasion / deception / negotiation / influence checks",
    prompt_focus=(
        "Specify how social conflicts resolve: persuasion, deception, "
        "intimidation; reputation / influence tracks; long-form social "
        "encounters and follow-ups."
    ),
    suggested_sections=(
        "Social rolls", "Reputation & influence",
        "Long-form social encounters", "Compelling actions",
    ),
)

ABILITIES = ScenarioParadigm(
    id="abilities",
    description="class powers / spells / feats / signature moves",
    prompt_focus=(
        "Specify how characters use special abilities: spell slots / "
        "magic point pools, cooldowns, casting time, action cost, "
        "limit-break style signature moves."
    ),
    suggested_sections=(
        "Resource pools", "Casting & activation",
        "Limit / signature moves", "Counterplay",
    ),
)

DOWNTIME_ECONOMY = ScenarioParadigm(
    id="downtime_economy",
    description="downtime activities, crafting, carousing, in-world economy",
    prompt_focus=(
        "Specify what happens between adventures: lifestyle costs, "
        "crafting, training, research, contacts, side businesses."
    ),
    suggested_sections=(
        "Lifestyle costs", "Crafting & training",
        "Research & contacts", "Side ventures",
    ),
)

CHASE_VEHICLES = ScenarioParadigm(
    id="chase_vehicles",
    description="chase mechanics, vehicle combat, pursuit speed",
    prompt_focus=(
        "Specify how chases and vehicle combat resolve: speed/maneuver "
        "ratings, terrain hazards, ramming, dismounts, escaping."
    ),
    suggested_sections=(
        "Chase rounds", "Vehicle stats", "Hazards & terrain",
        "Ramming & boarding", "Escape rules",
    ),
)

HACKING = ScenarioParadigm(
    id="hacking",
    description="cyberpunk / sci-fi hacking, programs, ICE",
    prompt_focus=(
        "Specify hacking / netrunning: connection, program slots, "
        "ICE encounters, dataforts, brain damage from black ICE."
    ),
    suggested_sections=(
        "Net architecture", "Programs & ICE",
        "Hacking actions", "Counter-intrusion",
    ),
)

SANITY = ScenarioParadigm(
    id="sanity",
    description="mental health / horror / corruption mechanics",
    prompt_focus=(
        "Specify mental damage: SAN / corruption / stress tracks, "
        "triggers, temporary/indefinite/permanent insanity, recovery."
    ),
    suggested_sections=(
        "SAN / Stress track", "Triggers & checks",
        "Temporary / indefinite / permanent insanity", "Recovery",
    ),
)

MISSION = ScenarioParadigm(
    id="mission",
    description="mission structure / objectives / job framework",
    prompt_focus=(
        "Specify mission framing: how a job is briefed, objectives, "
        "complications, payouts, faction reaction, end-of-mission "
        "downtime."
    ),
    suggested_sections=(
        "Mission briefing", "Objectives & complications",
        "Payouts", "Faction reaction",
    ),
)

CUSTOM = ScenarioParadigm(
    id="custom",
    description="user-defined paradigm; weakest validator",
    prompt_focus=(
        "The user is creating a paradigm not in the canonical list. "
        "Design a focused rule package per their brief. Use clear "
        "Markdown structure."
    ),
)


SCENARIO_PARADIGMS: tuple[ScenarioParadigm, ...] = (
    CREATION, PROGRESSION, COMBAT, RECOVERY, EXPLORATION, SOCIAL,
    ABILITIES, DOWNTIME_ECONOMY, CHASE_VEHICLES, HACKING, SANITY,
    MISSION, CUSTOM,
)

SCENARIO_PARADIGM_IDS: tuple[str, ...] = tuple(p.id for p in SCENARIO_PARADIGMS)


_LOOKUP: dict[str, ScenarioParadigm] = {p.id: p for p in SCENARIO_PARADIGMS}


def lookup_scenario(paradigm: str) -> ScenarioParadigm:
    """Return the named paradigm; falls back to `custom` when unknown."""
    return _LOOKUP.get(paradigm, CUSTOM)
