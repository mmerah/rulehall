from collections.abc import Callable
from random import Random
from typing import cast

import pytest
from support.lite5e import ScriptedDice
from support.lite5e_battle import SteadyDice, fight, foe, lay, member

from rulehall.engines.lite5e.battle.attack import (
    advantage_of,
    armor_class,
    buffed,
    resisted,
    roll_attack,
)
from rulehall.engines.lite5e.battle.damage import (
    DamageRoll,
    Dealt,
    resolve,
    roll_save,
    take_damage,
)
from rulehall.engines.lite5e.battle.specs import (
    ActionSpec,
    SaveSpec,
    stat_block_action,
    weapon_action,
)
from rulehall.engines.lite5e.battle.state import (
    Combatant,
    Effect,
    Fight,
    ended_facts,
)
from rulehall.engines.lite5e.data import (
    Ability,
    Advantage,
    Bonus,
    BonusTarget,
    Condition,
    DamageType,
    EffectRule,
    Resistance,
    srd,
)
from rulehall.engines.lite5e.rules import ABILITIES, DODGE
from rulehall.engines.lite5e.sheet import Lite5ePerson

RULES = srd().battle_effects.effects
REDUCTION_HOLDERS: dict[str, Callable[[], Lite5ePerson]] = {
    "uncanny-dodge": lambda: member("ann", "rogue", level=5),
    "deflect-attacks": lambda: member("ann", "monk", level=3),
    "stones-endurance": lambda: member(
        "ann", species_id="goliath", subspecies_id="giant-ancestry-stones-endurance"
    ),
}


def _rows(has: Callable[[EffectRule], object]) -> list[str]:
    return [effect_id for effect_id, rule in RULES.items() if has(rule)]


def _modifiers[ModifierT](effect_id: str, kind: type[ModifierT]) -> list[ModifierT]:
    rule = RULES.get(effect_id)
    return [] if rule is None else [found for found in rule.modifiers if isinstance(found, kind)]


def _bonuses(effect_id: str, to: BonusTarget) -> list[int]:
    return [found.fixed_amount() for found in _modifiers(effect_id, Bonus) if found.to == to]


def _fight(rng: Random, effect_id: str | None = None) -> Fight:
    ann = member("ann", weapon_ids=("longsword",))
    f = fight([(ann, "front")], [foe("skeleton", "skeleton")], rng)
    if effect_id is not None:
        f.battle.effects.append(
            Effect(holder_id="ann", source_id="ann", effect_id=effect_id, damage_type="fire")
        )
    return f


def _ann(f: Fight) -> Combatant:
    return f.battle.require_combatant("ann")


def _longsword(f: Fight) -> ActionSpec:
    return weapon_action(f.require_member("ann").require_sheet(), "longsword", off_hand=False)


def _reasons(f: Fight, *, attacked: bool) -> tuple[str, ...]:
    skeleton = f.battle.require_combatant("skeleton")
    if attacked:
        claws = stat_block_action(srd().require_stat_block("skeleton").actions[0])
        return advantage_of(f, skeleton, _ann(f), claws)[1]
    return advantage_of(f, _ann(f), skeleton, _longsword(f))[1]


@pytest.mark.parametrize(
    "effect_id",
    [
        effect_id
        for effect_id in RULES
        if _bonuses(effect_id, "armor-class") or _bonuses(effect_id, "minimum-armor-class")
    ],
)
def test_an_effect_shifts_and_floors_the_armor_class(effect_id: str) -> None:
    plain = _fight(Random(1))
    base = armor_class(plain, _ann(plain))
    held = _fight(Random(1), effect_id)
    shifted = base + sum(_bonuses(effect_id, "armor-class"))
    expected = max([shifted, *_bonuses(effect_id, "minimum-armor-class")])
    assert armor_class(held, _ann(held)) == expected


@pytest.mark.parametrize(
    "effect_id", [effect_id for effect_id in RULES if _modifiers(effect_id, Advantage)]
)
def test_an_effect_gives_its_attack_edge_with_its_reason(effect_id: str) -> None:
    held = _fight(Random(1), effect_id)
    for edge in _modifiers(effect_id, Advantage):
        if edge.on in ("attack", "attacked"):
            shown = f"{edge.kind}: {edge.reason}"
            assert shown in _reasons(held, attacked=edge.on == "attacked")
            if effect_id == DODGE:
                lay(held, "ann", "incapacitated")
                assert shown not in _reasons(held, attacked=True)


@pytest.mark.parametrize(
    "effect_id",
    [
        effect_id
        for effect_id in RULES
        if any(found.on == "save" for found in _modifiers(effect_id, Advantage))
        or _bonuses(effect_id, "save")
    ],
)
def test_an_effect_gives_its_save_edges_and_bonuses(effect_id: str) -> None:
    checks: list[tuple[Ability, Condition | None, int]] = []
    for found in _modifiers(effect_id, Advantage):
        for key in found.keys if found.on == "save" else ():
            if key in ABILITIES:
                checks.append((key, None, 10))
            else:
                checks.append(("constitution", cast(Condition, key), 10))
    for found in _modifiers(effect_id, Bonus):
        checks.extend((key, None, found.fixed_amount()) for key in found.keys if key in ABILITIES)
    for ability, against, shift in checks:
        save = SaveSpec(ability=ability, dc=10)
        plain, held = (
            roll_save(f, _ann(f), save, against=against, spell=False)
            for f in (_fight(ScriptedDice(5, 15)), _fight(ScriptedDice(5, 15), effect_id))
        )
        assert held.total - plain.total == shift


@pytest.mark.parametrize("effect_id", [e for e in RULES if _modifiers(e, Resistance)])
def test_an_effect_resists_its_damage_types(effect_id: str) -> None:
    held = _fight(Random(1), effect_id)
    types: list[DamageType] = [
        damage_type
        for found in _modifiers(effect_id, Resistance)
        for damage_type in found.damage_types or ("fire",)
    ]
    for damage_type in types:
        assert resisted(held, _ann(held), 10, damage_type) == 5
    assert resisted(held, _ann(held), 10, "psychic") == 10


@pytest.mark.parametrize("effect_id", _rows(lambda r: r.roll_die))
def test_an_effect_rolls_its_die_onto_attack_rolls(effect_id: str) -> None:
    die = RULES[effect_id].roll_die
    assert die is not None
    plain, held = (
        roll_attack(f, _ann(f), f.battle.require_combatant("skeleton"), _longsword(f), "none")
        for f in (_fight(SteadyDice(3)), _fight(SteadyDice(3), effect_id))
    )
    assert held.total - plain.total == (3 if die > 0 else -3)


@pytest.mark.parametrize("effect_id", [e for e in RULES if _bonuses(e, "weapon")])
def test_an_effect_raises_weapon_attacks(effect_id: str) -> None:
    held = _fight(Random(1), effect_id)
    longsword = _longsword(held)
    raised = buffed(held, _ann(held), longsword)
    bonus = sum(_bonuses(effect_id, "weapon"))
    assert longsword.to_hit is not None
    assert raised.to_hit == longsword.to_hit + bonus
    assert raised.damage[0].bonus == longsword.damage[0].bonus + bonus


@pytest.mark.parametrize("effect_id", _rows(lambda r: r.state))
def test_an_effect_ends_with_its_state(effect_id: str) -> None:
    held = _fight(Random(1), effect_id)
    told = [fact.trace for fact in ended_facts(held, held.battle.effects)]
    assert told == [f"Ann: no longer {RULES[effect_id].state}"]


def _hit(f: Fight, amount: int) -> None:
    damage = DamageRoll(dealt=(Dealt(amount=amount, damage_type="piercing"),), dice=())
    skeleton = f.battle.require_combatant("skeleton")
    _ = take_damage(f, skeleton, _ann(f), damage, critical=False, hit=True)


def _reduction_fight(reduction_id: str) -> Fight:
    ann = REDUCTION_HOLDERS[reduction_id]()
    f = fight([(ann, "front")], [foe("skeleton", "skeleton")], SteadyDice(4))
    sheet = ann.require_sheet()
    sheet.vitals.hp.current = sheet.vitals.hp.maximum = 40
    return f


@pytest.mark.parametrize("reduction_id", list(REDUCTION_HOLDERS))
def test_a_damage_reduction_cuts_the_first_hit_of_each_round(reduction_id: str) -> None:
    f = _reduction_fight(reduction_id)
    sheet = f.require_member("ann").require_sheet()
    cut = {
        "uncanny-dodge": 25 - 25 // 2,
        "deflect-attacks": 4 + sheet.modifier("dexterity") + sheet.level,
        "stones-endurance": 4 + sheet.modifier("constitution"),
    }[reduction_id]
    _hit(f, 25)
    assert sheet.vitals.hp.current == 40 - 25 + cut
    sheet.vitals.hp.current = 40
    _hit(f, 25)
    assert sheet.vitals.hp.current == 15


def test_stones_endurance_cuts_damage_from_no_hit() -> None:
    f = _reduction_fight("stones-endurance")
    sheet = f.require_member("ann").require_sheet()
    fire = DamageRoll(dealt=(Dealt(amount=25, damage_type="fire"),), dice=())
    _ = take_damage(f, f.battle.require_combatant("skeleton"), _ann(f), fire)
    assert sheet.vitals.hp.current == 40 - 25 + 4 + sheet.modifier("constitution")


def test_stones_endurance_waits_for_the_resisted_damage() -> None:
    f = _reduction_fight("stones-endurance")
    f.battle.effects.append(
        Effect(
            holder_id="ann",
            source_id="ann",
            effect_id="protection-from-energy",
            damage_type="fire",
        )
    )
    sheet = f.require_member("ann").require_sheet()
    uses = sheet.uses_left("stones-endurance")
    fire = DamageRoll(dealt=(Dealt(amount=25, damage_type="fire"),), dice=())
    _ = take_damage(f, f.battle.require_combatant("skeleton"), _ann(f), fire)
    assert (sheet.vitals.hp.current, sheet.uses_left("stones-endurance")) == (40 - 12, uses)


def test_shillelagh_keeps_the_weapon_s_magic_bonus() -> None:
    druid = member("ann", "druid", weapon_ids=("weapon-1-quarterstaff",))
    f = fight([(druid, "front")], [foe("skeleton", "skeleton")], Random(1))
    f.battle.effects.append(Effect(holder_id="ann", source_id="ann", effect_id="shillelagh"))
    sheet = druid.require_sheet()
    raised = buffed(f, _ann(f), weapon_action(sheet, "weapon-1-quarterstaff", off_hand=False))
    wisdom = sheet.modifier("wisdom")
    assert (raised.to_hit, raised.damage[0].bonus) == (
        wisdom + sheet.proficiency_bonus() + 1,
        wisdom + 1,
    )
    assert raised.damage[0].dice == "1d8"


@pytest.mark.parametrize("effect_id", _rows(lambda r: r.hit_damage))
def test_an_effect_adds_its_damage_to_a_hit(effect_id: str) -> None:
    f = _fight(SteadyDice(15))
    skeleton = f.battle.require_combatant("skeleton")
    holder_id = "ann" if effect_id == "divine-favor" else "skeleton"
    f.battle.effects.append(Effect(holder_id=holder_id, source_id="ann", effect_id=effect_id))
    facts = resolve(f, _ann(f), _longsword(f), [skeleton])
    name = srd().require_spell(effect_id).name
    assert any(event.label == name for fact in facts for event in fact.dice)
