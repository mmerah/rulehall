from collections.abc import Sequence
from random import Random

from rulehall.core.facts import Fact
from rulehall.core.validation import Slug
from rulehall.engines.lite5e.battle.actions import SLOT, TARGET, Aim, take_action
from rulehall.engines.lite5e.battle.foes import bonus_plans_of, plans_of, scripted_plan
from rulehall.engines.lite5e.battle.state import (
    Battle,
    Combatant,
    Effect,
    Fight,
    FoeCombatant,
    MemberCombatant,
)
from rulehall.engines.lite5e.battle.views import require_aim
from rulehall.engines.lite5e.data import Condition, srd
from rulehall.engines.lite5e.rules import FormationRow, Light
from rulehall.engines.lite5e.sheet import Lite5ePerson
from rulehall.engines.sheet import Gauge
from support.lite5e import GATE, hero, person, sheet_proposal


class SteadyDice(Random):
    def __init__(self, face: int) -> None:
        super().__init__()
        self.face = face

    def randint(self, a: int, b: int) -> int:
        return max(a, min(self.face, b))


def member(
    actor_id: Slug,
    class_id: str = "fighter",
    species_id: str = "human",
    *,
    subspecies_id: str | None = None,
    level: int = 1,
    weapon_ids: Sequence[Slug] = (),
) -> Lite5ePerson:
    built = hero(sheet_proposal(class_id, species_id, subspecies_id=subspecies_id), level)
    built = built.model_copy(update={"id": actor_id, "name": actor_id.title()})
    sheet = built.require_sheet()
    if weapon_ids:
        held = srd().gear.weapons
        sheet.equipped_ids[:] = [key for key in sheet.equipped_ids if key not in held]
    for weapon_id in weapon_ids:
        sheet.add_gear(weapon_id, 1)
        sheet.equipped_ids.append(weapon_id)
    return built


def foe(combatant_id: Slug, stat_block_id: str, row: FormationRow = "front") -> FoeCombatant:
    block = srd().require_stat_block(stat_block_id)
    group_id = combatant_id.rsplit("-", 1)[0] if combatant_id[-1].isdigit() else combatant_id
    return FoeCombatant(
        combatant_id=combatant_id,
        person_id=group_id,
        name=combatant_id.title(),
        group_name=group_id.title(),
        stat_block_id=stat_block_id,
        row=row,
        hp=Gauge(current=block.hit_points, maximum=block.hit_points),
    )


def fight(
    members: Sequence[tuple[Lite5ePerson, FormationRow]],
    foes: Sequence[FoeCombatant],
    rng: Random,
    *,
    light: Light = "bright",
) -> Fight:
    sides: list[Combatant] = [
        MemberCombatant(combatant_id=person.id, row=row) for person, row in members
    ]
    sides.extend(foes)
    battle = Battle(
        order=[combatant.combatant_id for combatant in sides],
        combatants=sides,
        phase="member",
        light=light,
        cover=False,
    )
    return Fight(battle=battle, members={person.id: person for person, _ in members}, rng=rng)


def lay(fight: Fight, holder_id: Slug, condition: Condition, source_id: Slug = "gm") -> None:
    fight.battle.effects.append(
        Effect(holder_id=holder_id, source_id=source_id, effect_id="test", condition=condition)
    )


def companion(actor_id: Slug, stat_block_id: str) -> Lite5ePerson:
    built = person(actor_id, GATE, stat_block_id)
    built.fill_stat_block_hp()
    return built


def plan_texts(fight: Fight, combatant: Combatant) -> tuple[str, ...]:
    return tuple(plan.text for plan in plans_of(fight, combatant))


def bonus_plan_texts(fight: Fight, combatant: Combatant) -> tuple[str, ...]:
    return tuple(plan.text for plan in bonus_plans_of(fight, combatant))


async def scripted_plans(fight: Fight, foes: Sequence[FoeCombatant]) -> dict[Slug, str]:
    return {foe.combatant_id: scripted_plan(fight, foe).text for foe in foes}


def play(
    fight: Fight, command: str, *target_ids: Slug, slot_level: int | None = None
) -> list[Fact]:
    slot = () if slot_level is None else (f"{SLOT} {slot_level}",)
    picks = [*(f"{TARGET} {target_id}" for target_id in target_ids), *slot]
    return take_action(fight, require_aim(fight, command), picks)


def play_first_pick(fight: Fight, aim: Aim) -> list[Fact]:
    target_ids = aim.target_ids[:1] if aim.one_row else aim.target_ids[: aim.cap]
    slot = () if not aim.slot_levels else (f"{SLOT} {aim.slot_levels[0]}",)
    picks = [*(f"{TARGET} {target_id}" for target_id in target_ids), *slot]
    return take_action(fight, aim, picks)
