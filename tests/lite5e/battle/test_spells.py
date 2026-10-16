from random import Random

import pytest
from support.lite5e import ScriptedDice
from support.lite5e_battle import fight, foe, lay, member, play, play_first_pick

from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.actions import member_aims
from rulehall.engines.lite5e.battle.attack import cast_through
from rulehall.engines.lite5e.battle.damage import (
    DamageRoll,
    Dealt,
    take_damage,
)
from rulehall.engines.lite5e.battle.specs import weapon_action
from rulehall.engines.lite5e.battle.spells import REVIVIFY_DIAMOND, cast_spell
from rulehall.engines.lite5e.battle.state import (
    Fight,
    MemberCombatant,
)
from rulehall.engines.lite5e.data import srd

CASTER_CLASS_IDS = ("wizard", "cleric", "druid", "sorcerer", "bard", "warlock", "paladin", "ranger")


def _bandits(rng: Random) -> Fight:
    ann = member("ann", weapon_ids=("longsword",))
    cleo = member("cleo", "cleric", level=3)
    wiz = member("wiz", "wizard", level=3)
    for person in (ann, cleo, wiz):
        person.require_sheet().inspiration = False
    wiz.require_sheet().picks.setdefault("prepared", []).extend(("magic-missile", "scorching-ray"))
    bandits = [
        foe("bandit-1", "bandit"),
        foe("bandit-2", "bandit"),
        foe("bandit-3", "bandit", "back"),
    ]
    return fight([(ann, "front"), (cleo, "back"), (wiz, "back")], bandits, rng)


def _member(f: Fight, actor_id: str) -> MemberCombatant:
    found = f.battle.require_combatant(actor_id)
    assert isinstance(found, MemberCombatant)
    return found


def _damage(amount: int) -> DamageRoll:
    return DamageRoll(dealt=(Dealt(amount=amount, damage_type="slashing"),), dice=())


@pytest.mark.parametrize(("amount", "dc"), [(4, 10), (30, 15), (70, 30)])
def test_the_concentration_dc_is_half_the_damage_from_10_to_30(amount: int, dc: int) -> None:
    f = _bandits(ScriptedDice(20))
    at = f.battle.require_combatant
    sheet = f.require_member("cleo").require_sheet()
    sheet.concentration_spell_id = "bless"
    sheet.temp_hp = 70
    _, facts = take_damage(f, at("bandit-1"), at("cleo"), _damage(amount))
    traces = [fact.trace for fact in facts]
    assert any("constitution save" in trace and trace.endswith(f"vs DC {dc}") for trace in traces)


def test_one_slot_per_turn() -> None:
    f = _bandits(Random(1))
    at = f.battle.require_combatant
    wiz = _member(f, "wiz")
    cast_spell(f, wiz, "magic-missile", [at("bandit-1")], 1, None)
    with pytest.raises(Refusal, match="one spell slot per turn"):
        cast_spell(f, wiz, "magic-missile", [at("bandit-1")], 1, None)


def test_every_battle_spell_casts() -> None:
    uncast: list[str] = []
    for spell_id, spell in srd().spells.spells.items():
        if spell.group != "battle":
            continue
        class_id = next(class_id for class_id in CASTER_CLASS_IDS if class_id in spell.class_ids)
        f = _spell_fight(spell_id, class_id)
        aims = [
            aim
            for aim in member_aims(f, _member(f, "player"))
            if aim.action_id == spell_id or (aim.variant_id or "").startswith(spell_id)
        ]
        if not aims:
            uncast.append(spell_id)
            continue
        _ = play_first_pick(f, aims[0])
    assert uncast == []


def _spell_fight(spell_id: str, class_id: str) -> Fight:
    caster = member("player", class_id, level=5, weapon_ids=("longsword",))
    sheet = caster.require_sheet()
    kind = "cantrip" if srd().require_spell(spell_id).level == 0 else "prepared"
    sheet.picks.setdefault(kind, []).append(spell_id)
    sheet.add_gear(REVIVIFY_DIAMOND, 1)
    hurt, downed, dead = member("ann"), member("bo"), member("cy")
    f = fight(
        [(caster, "front"), (hurt, "front"), (downed, "front"), (dead, "front")],
        [foe("ogre", "ogre"), foe("bandit", "bandit"), foe("zombie", "zombie", "back")],
        Random(1),
    )
    hurt.require_sheet().vitals.hp.current = 1
    downed.require_sheet().vitals.hp.current = 0
    dead.require_sheet().vitals.hp.current = 0
    dead.require_sheet().vitals.death_failures = 3
    lay(f, "ogre", "grappled", "player")
    lay(f, "ann", "poisoned")
    return f


def test_true_strike_on_a_pact_weapon_attacks_with_charisma() -> None:
    sheet = member("ann", "warlock", level=3).require_sheet()
    sheet.picks["invocation"] = ["pact-of-the-blade"]
    sheet.picks["pact-weapon"] = ["longsword"]
    sheet.picks.setdefault("cantrip", []).append("true-strike")
    pact = weapon_action(sheet, "longsword", off_hand=False, pact=True)
    guided = cast_through(sheet, pact, "true-strike")
    charisma = sheet.modifier("charisma")
    assert charisma != sheet.modifier("strength")
    assert (guided.to_hit, guided.damage[0].bonus) == (
        charisma + sheet.proficiency_bonus(),
        charisma,
    )


def test_an_area_spell_takes_each_target_once() -> None:
    wiz = member("player", "wizard", level=3)
    wiz.require_sheet().picks.setdefault("prepared", []).append("burning-hands")
    f = fight([(wiz, "front")], [foe("ogre", "ogre")], Random(5))
    with pytest.raises(Refusal, match="each target once"):
        _ = play(f, "act burning-hands", "ogre", "ogre", slot_level=1)
