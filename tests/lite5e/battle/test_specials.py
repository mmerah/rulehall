from collections.abc import Awaitable, Callable
from typing import get_args

import pytest
from support.lite5e_battle import (
    SteadyDice,
    bonus_plan_texts,
    fight,
    foe,
    member,
    plan_texts,
    scripted_plans,
)

from rulehall.engines.lite5e.battle.attack import advantage_of
from rulehall.engines.lite5e.battle.damage import (
    DamageRoll,
    Dealt,
    change_row,
    end_of_turn_fire_aura,
    resolve,
    roll_save,
    start_of_turn_regeneration,
    take_damage,
)
from rulehall.engines.lite5e.battle.opponent import opponent_system
from rulehall.engines.lite5e.battle.specs import (
    SaveSpec,
    stat_block_action,
)
from rulehall.engines.lite5e.battle.state import (
    Effect,
    Fight,
    FoeCombatant,
)
from rulehall.engines.lite5e.battle.turns import end_turn, play_next
from rulehall.engines.lite5e.data import SpecialId, srd
from rulehall.engines.lite5e.rules import FormationRow


def _against(stat_block_id: str, row: FormationRow = "front", face: int = 15) -> Fight:
    hero = member("player", weapon_ids=("longsword",))
    hero.require_sheet().inspiration = False
    return fight(
        [(hero, "front"), (member("bo"), "front")],
        [foe("it", stat_block_id, row)],
        SteadyDice(face),
    )


def _it(f: Fight) -> FoeCombatant:
    found = f.battle.require_combatant("it")
    assert isinstance(found, FoeCombatant)
    return found


def _shortfall(f: Fight, actor_id: str) -> int:
    return f.require_member(actor_id).require_sheet().vitals.hp.shortfall


def _strike(f: Fight, action_id: str, target_id: str) -> None:
    it = _it(f)
    action = stat_block_action(it.stat_block().require_action(action_id))
    _ = resolve(f, it, action, [f.battle.require_combatant(target_id)])


async def _pack_tactics() -> None:
    f = _against("giant-rat")
    f.battle.combatants.append(foe("rat-2", "giant-rat"))
    bite = stat_block_action(_it(f).stat_block().require_action("bite"))
    _, reasons = advantage_of(f, _it(f), f.battle.require_combatant("player"), bite)
    assert "advantage: pack tactics" in reasons


async def _magic_resistance() -> None:
    f = _against("imp")
    save = SaveSpec(ability="wisdom", dc=30)
    spell = roll_save(f, _it(f), save, against=None, spell=True)
    plain = roll_save(f, _it(f), save, against=None, spell=False)
    assert len(spell.dice[0].faces) > len(plain.dice[0].faces)


async def _nimble_escape() -> None:
    f = _against("goblin-warrior")
    assert bonus_plan_texts(f, _it(f)) == ("nimble escape: back",)


async def _undead_fortitude() -> None:
    f = _against("zombie", face=20)
    damage = DamageRoll(dealt=(Dealt(amount=16, damage_type="slashing"),), dice=())
    _ = take_damage(
        f, f.battle.require_combatant("player"), _it(f), damage, critical=False, hit=True
    )
    assert _it(f).hp.current == 1


async def _bloodied_fury() -> None:
    f = _against("berserker")
    _it(f).hp.current = 10
    greataxe = stat_block_action(_it(f).stat_block().require_action("greataxe"))
    _, reasons = advantage_of(f, _it(f), f.battle.require_combatant("player"), greataxe)
    assert "advantage: bloodied fury" in reasons


async def _rampage() -> None:
    f = _against("gnoll-warrior")
    f.require_member("player").require_sheet().vitals.hp.current = 1
    _strike(f, "rend", "player")
    assert _shortfall(f, "bo") > 0


async def _swarm() -> None:
    f = _against("swarm-of-rats")
    assert "Traits: swarm" in opponent_system(f)


async def _charge() -> None:
    f = _against("allosaurus", "back")
    f.battle.order = ["player", "it", "bo"]
    charge = next(text for text in plan_texts(f, _it(f)) if "charge" in text)
    _ = end_turn(f)
    f.battle.pending_plans["it"] = charge
    _ = await play_next(f, scripted_plans)
    assert _shortfall(f, "player") > 0
    assert f.battle.has_condition("player", "prone")


async def _fire_aura() -> None:
    f = _against("fire-elemental")
    stunned = Effect(holder_id="it", source_id="player", effect_id="stun", condition="stunned")
    f.battle.effects.append(stunned)
    _ = end_of_turn_fire_aura(f, _it(f))
    assert _shortfall(f, "player") > 0 and _shortfall(f, "bo") > 0
    assert f.battle.has_condition("player", "burning")
    azer = _against("azer-sentinel")
    azer.battle.effects.append(stunned)
    assert end_of_turn_fire_aura(azer, _it(azer)) == []


async def _regeneration() -> None:
    f = _against("troll")
    _it(f).hp.current = 50
    _ = start_of_turn_regeneration(f, _it(f))
    assert _it(f).hp.current == 50 + 15
    fire = DamageRoll(dealt=(Dealt(amount=5, damage_type="fire"),), dice=())
    _ = take_damage(f, f.battle.require_combatant("player"), _it(f), fire, critical=False, hit=True)
    burned = _it(f).hp.current
    _ = start_of_turn_regeneration(f, _it(f))
    assert _it(f).hp.current == burned


async def _life_drain() -> None:
    f = _against("specter")
    maximum = f.require_member("player").require_sheet().vitals.hp.maximum
    _ = _strike(f, "life-drain", "player")
    assert f.require_member("player").require_sheet().vitals.hp.maximum < maximum


def _leaves_unharmed(stat_block_id: str) -> None:
    f = _against(stat_block_id)
    _ = change_row(f, _it(f), provoking=True, teleport=False)
    assert (_it(f).row, _it(f).hp.shortfall) == ("back", 0)


async def _agile() -> None:
    _leaves_unharmed("rat")


async def _flyby() -> None:
    _leaves_unharmed("owl")


SPECIAL_PLAYS: dict[SpecialId, Callable[[], Awaitable[None]]] = {
    "pack-tactics": _pack_tactics,
    "magic-resistance": _magic_resistance,
    "nimble-escape": _nimble_escape,
    "undead-fortitude": _undead_fortitude,
    "bloodied-fury": _bloodied_fury,
    "rampage": _rampage,
    "swarm": _swarm,
    "charge": _charge,
    "fire-aura": _fire_aura,
    "regeneration": _regeneration,
    "life-drain": _life_drain,
    "agile": _agile,
    "flyby": _flyby,
}


def test_the_table_plays_every_special() -> None:
    assert set(SPECIAL_PLAYS) == set(get_args(SpecialId.__value__))
    assert {
        special.special_id
        for block in srd().bestiary.stat_blocks.values()
        for special in block.specials
    } == set(SPECIAL_PLAYS)


@pytest.mark.parametrize("special_id", list(SPECIAL_PLAYS))
async def test_a_special_plays_its_rule(special_id: SpecialId) -> None:
    await SPECIAL_PLAYS[special_id]()
