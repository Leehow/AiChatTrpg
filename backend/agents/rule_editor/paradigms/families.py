"""The 22 canonical parameter family paradigms + custom fallback.

Sourced from the V6 rule parser's discovery prompt. Each paradigm
declares its `family_specific_fields` so the editor agent fills in the
right shape per family.
"""

from __future__ import annotations

from .base import FamilyParadigm


def _f(
    id: str, description: str, entry_definition: str, *fields: str,
) -> FamilyParadigm:
    return FamilyParadigm(
        id=id,
        description=description,
        entry_definition=entry_definition,
        family_specific_fields=fields,
    )


SPELL = _f(
    "spell", "one spell or ritual",
    "a single spell entry",
    "mp_cost", "range", "target", "duration", "casting_time", "school",
    "effect", "components",
)

POWER = _f(
    "power", "one signature ability / supernatural power",
    "a usable special ability",
    "cost", "action_type", "prerequisite", "effect", "duration",
)

WEAPON = _f(
    "weapon", "one weapon",
    "a weapon a character can wield",
    "damage", "range", "hands", "weight", "cost", "properties",
    "damage_type",
)

ARMOR = _f(
    "armor", "one piece of armor",
    "a worn protective item",
    "armor_value", "encumbrance", "slot", "cost", "properties",
)

ITEM = _f(
    "item", "one piece of gear",
    "a piece of equipment, supply, or trinket",
    "cost", "weight", "slot", "properties", "uses",
)

CREATURE = _f(
    "creature", "one monster or NPC stat block",
    "a stat block for a creature or notable NPC",
    "attributes", "attacks", "skills", "hit_points", "armor",
    "special", "habitat",
)

NPC_TEMPLATE = _f(
    "npc_template", "one reusable NPC archetype",
    "a generic NPC profile players might meet repeatedly",
    "attributes_band", "common_skills", "equipment", "motivation",
    "voice",
)

ROLE = _f(
    "role", "one class / background / role",
    "a character class or role definition",
    "skill_points", "hit_die", "starting_kit", "signature_features",
    "advancement",
)

FEATURE = _f(
    "feature", "one feat / trait / talent",
    "a stand-alone character option",
    "prerequisite", "benefit", "action_type",
)

CONDITION = _f(
    "condition", "one status condition",
    "a status effect that can be inflicted on a character",
    "effect", "duration", "recovery", "stack",
)

DISEASE = _f(
    "disease", "one disease",
    "a contagion with stages and saves",
    "incubation", "stages", "saves", "cure",
)

POISON = _f(
    "poison", "one poison",
    "a delivered toxin",
    "delivery", "save", "stages", "antidote",
)

VEHICLE = _f(
    "vehicle", "one vehicle",
    "a mountable / drivable vehicle",
    "speed", "capacity", "durability", "cost", "special",
    "crew_required",
)

PROGRAM = _f(
    "program", "one hacking / netrunning program",
    "a software tool for hacking",
    "mp_cost", "target", "effect", "signature", "size",
)

CYBERWARE = _f(
    "cyberware", "one cybernetic upgrade",
    "an installable cybernetic implant",
    "cost", "install_difficulty", "humanity_cost", "effect", "slot",
)

DRUG = _f(
    "drug", "one drug",
    "a recreational or combat drug",
    "effect", "duration", "addiction", "side_effects", "cost",
)

BACKGROUND = _f(
    "background", "one backstory archetype",
    "a character background package",
    "skill_points", "suggested_skills", "hooks", "starting_gear",
)

OCCUPATION = _f(
    "occupation", "one occupation / career",
    "a profession a character can have",
    "skill_points", "suggested_skills", "credit_rating", "contacts",
)

TABLE_RANDOM = _f(
    "table_random", "one random table",
    "a roll table producing flavor results",
    "roll_expr", "rows",
)

TABLE_PRICE = _f(
    "table_price", "one price list",
    "a category of goods with prices",
    "category", "rows", "currency",
)

TABLE_GENERATION = _f(
    "table_generation", "one generator table",
    "a generator (NPC, location, name) producing structured results",
    "roll_expr", "rows", "chained_table",
)

CUSTOM = FamilyParadigm(
    id="custom",
    description="user-defined family; common shell only validator",
    entry_definition="a custom-shaped entry",
    family_specific_fields=(),
)


FAMILY_PARADIGMS: tuple[FamilyParadigm, ...] = (
    SPELL, POWER, WEAPON, ARMOR, ITEM, CREATURE, NPC_TEMPLATE, ROLE,
    FEATURE, CONDITION, DISEASE, POISON, VEHICLE, PROGRAM, CYBERWARE,
    DRUG, BACKGROUND, OCCUPATION, TABLE_RANDOM, TABLE_PRICE,
    TABLE_GENERATION, CUSTOM,
)

FAMILY_PARADIGM_IDS: tuple[str, ...] = tuple(p.id for p in FAMILY_PARADIGMS)


_LOOKUP: dict[str, FamilyParadigm] = {p.id: p for p in FAMILY_PARADIGMS}


def lookup_family(paradigm: str) -> FamilyParadigm:
    """Return the named paradigm; falls back to `custom` when unknown."""
    return _LOOKUP.get(paradigm, CUSTOM)
