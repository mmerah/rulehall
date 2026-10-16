from collections.abc import Sequence
from typing import Literal

from rulehall.core.facts import Fact
from rulehall.engines.lite5e.battle.state import (
    Combatant,
    Fight,
    FoeCombatant,
    MoraleMark,
    ended_facts,
    told,
)
from rulehall.engines.lite5e.data import Ability, CreatureType, StatBlock
from rulehall.engines.lite5e.rules import CHALLENGE_RATINGS
from rulehall.engines.lite5e.sheet import combined_edge

type MoraleCause = Literal["harm", "demand", "rout"]

MORALE_ABILITY: Ability = "wisdom"
MORALE_DC = 10
NEVER_CHECK_TYPES: frozenset[CreatureType] = frozenset(
    {"construct", "plant", "undead", "swarm of tiny undead"}
)
FLEEING_TYPES: frozenset[CreatureType] = frozenset({"beast", "swarm of tiny beasts"})


def is_morale_exempt(fight: Fight, group_id: str) -> bool:
    foes = fight.battle.require_group_foes(group_id)
    block = foes[0].stat_block()
    other_ranks = [
        _rank(other.stat_block()) for other in fight.battle.foes() if other.person_id != group_id
    ]
    outranks_all = bool(other_ranks) and all(_rank(block) > rank for rank in other_ranks)
    return len(foes) == 1 or block.creature_type in NEVER_CHECK_TYPES or outranks_all


def demand_refusal(fight: Fight, target: Combatant) -> str:
    if not isinstance(target, FoeCombatant):
        return "a demand names a foe"
    group_id, name = target.person_id, target.group_name
    if is_morale_exempt(fight, group_id):
        return f"{name} never gives up"
    if "demand" in fight.battle.morale_marks.get(group_id, []):
        return f"{name} already heard a demand in this battle"
    if not _morale_triggers(fight.battle.require_group_foes(group_id)):
        return f"{name} has no foe down and still holds half its HP"
    return ""


def check_morale(fight: Fight, group_id: str, cause: MoraleCause) -> list[Fact]:
    battle = fight.battle
    foes = battle.require_group_foes(group_id)
    if cause != "rout" and is_morale_exempt(fight, group_id):
        return []
    if cause == "harm":
        marks = battle.morale_marks.setdefault(group_id, [])
        due: list[MoraleMark] = [mark for mark in _morale_triggers(foes) if mark not in marks]
        if not due:
            return []
        marks.extend(due)
    block = foes[0].stat_block()
    led = any(
        fight.is_standing(foe) and _rank(foe.stat_block()) > _rank(block) for foe in battle.foes()
    )
    edge = combined_edge(
        "disadvantage" if cause == "rout" else "none", "advantage" if led else "none"
    )
    test = foes[0].roll_save(MORALE_ABILITY, MORALE_DC, edge, fight.rng)
    group_name = foes[0].group_name
    facts = [
        Fact(
            trace=f"morale of {group_name}: {MORALE_ABILITY} save {test.total} vs DC "
            f"{MORALE_DC}" + (", led" if led else ""),
            dice=test.dice,
        )
    ]
    if test.success:
        return [*facts, told(f"{group_name} hold firm")]
    fled = cause != "rout" and block.creature_type in FLEEING_TYPES
    for foe in foes:
        if fight.is_standing(foe) and not battle.is_incapacitated(foe.combatant_id):
            foe.withdrawal = "fled" if fled else "surrendered"
            facts.append(told(f"{foe.name} {'flees' if fled else 'surrenders'}"))
            facts.extend(ended_facts(fight, battle.stop_turns(foe.combatant_id)))
    return facts


def _morale_triggers(foes: Sequence[FoeCombatant]) -> list[MoraleMark]:
    triggers: list[MoraleMark] = []
    if any(foe.hp.current == 0 for foe in foes):
        triggers.append("first-drop")
    if 2 * sum(foe.hp.current for foe in foes) < sum(foe.hp.maximum for foe in foes):
        triggers.append("half-hp")
    return triggers


def _rank(block: StatBlock) -> int:
    return CHALLENGE_RATINGS.index(block.challenge_rating)
