import asyncio
from random import Random

import pytest
from support.lite5e import ScriptedDice
from support.lite5e_battle import (
    SteadyDice,
    companion,
    fight,
    foe,
    lay,
    member,
    play,
    scripted_plans,
)

from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.state import (
    Effect,
    Fight,
    FoeCombatant,
    MemberCombatant,
)
from rulehall.engines.lite5e.battle.turns import (
    battle_end,
    block_foes,
    current_combatant,
    end_turn,
    play_next,
    roll_initiative,
    surrender,
    toggle_auto,
)
from rulehall.engines.lite5e.battle.views import battle_view
from rulehall.engines.lite5e.sheet import Lite5ePerson


def _hero() -> Lite5ePerson:
    return member("player", weapon_ids=("longsword",))


def _block_fight(rng: Random) -> Fight:
    bo = member("bo", "rogue", weapon_ids=("shortsword",))
    f = fight(
        [(_hero(), "front"), (bo, "front")], [foe("wolf-1", "wolf"), foe("wolf-2", "wolf")], rng
    )
    f.battle.order = ["player", "wolf-1", "bo", "wolf-2"]
    return f


def _member(f: Fight, actor_id: str) -> MemberCombatant:
    found = f.battle.require_combatant(actor_id)
    assert isinstance(found, MemberCombatant)
    return found


def _foe(f: Fight, combatant_id: str) -> FoeCombatant:
    found = f.battle.require_combatant(combatant_id)
    assert isinstance(found, FoeCombatant)
    return found


def _down(f: Fight, actor_id: str) -> None:
    f.require_member(actor_id).require_vitals().hp.current = 0


def test_identical_foes_share_one_roll_and_the_higher_dexterity_wins_a_tie() -> None:
    f = fight(
        [(_hero(), "front")], [foe("wolf-1", "wolf"), foe("wolf-2", "wolf")], ScriptedDice(10, 12)
    )
    _ = roll_initiative(f, ())
    assert f.battle.order == ["wolf-1", "wolf-2", "player"]
    assert f.battle.phase == "foes"


def test_end_hands_the_turn_to_the_foes() -> None:
    f = _block_fight(Random(1))
    _ = end_turn(f)
    assert f.battle.phase == "foes"
    assert current_combatant(f).combatant_id == "wolf-1"
    with pytest.raises(Refusal):
        _ = end_turn(f)


def test_the_block_runs_to_the_next_player_turn_or_a_combatant_that_comes_again() -> None:
    f = _block_fight(Random(1))
    _ = end_turn(f)
    assert [foe.combatant_id for foe in block_foes(f)] == ["wolf-1"]
    _member(f, "bo").auto = True
    assert [foe.combatant_id for foe in block_foes(f)] == ["wolf-1", "wolf-2"]
    _down(f, "player")
    assert [foe.combatant_id for foe in block_foes(f)] == ["wolf-1", "wolf-2"]


def _companion_turn() -> Fight:
    guard = companion("guard", "guard")
    f = fight([(_hero(), "front"), (guard, "front")], [foe("wolf-1", "wolf")], Random(1))
    f.battle.order = ["guard", "wolf-1", "player"]
    return f


def test_a_companion_s_plans_read_as_action_and_target_names() -> None:
    view = battle_view(_companion_turn(), live=True, thinking=False, aiming="", picks=())
    plans = [(choice.name, choice.brief) for choice in view.choices if choice.kind == "plan"]
    assert plans and all("-" not in name for name, _ in plans)
    assert ("Spear", "Wolf-1") in plans


def test_auto_turned_on_in_a_companion_s_own_turn_plays_that_turn() -> None:
    f = _companion_turn()
    _ = toggle_auto(f, "guard")
    assert current_combatant(f).combatant_id == "wolf-1"
    assert f.battle.phase == "foes"


def test_a_lone_hero_at_0_hp_is_a_defeat_and_a_companion_fights_on() -> None:
    bo = member("bo", "rogue")
    f = fight([(_hero(), "front"), (bo, "front")], [foe("wolf", "wolf")], Random(1))
    _down(f, "player")
    assert battle_end(f) is None
    lay(f, "bo", "unconscious")
    end = battle_end(f)
    assert end is not None and end.outcome == "defeat"


def test_the_hero_s_death_ends_the_battle_first() -> None:
    f = fight([(_hero(), "front")], [foe("wolf", "wolf")], Random(1))
    _down(f, "player")
    _foe(f, "wolf").hp.current = 0
    f.require_member("player").require_sheet().vitals.death_failures = 3
    end = battle_end(f)
    assert end is not None and end.outcome == "hero_dead"


def test_bless_turns_a_failed_death_save_into_a_success() -> None:
    bo = member("bo", "rogue")
    f = fight([(_hero(), "front"), (bo, "front")], [foe("wolf", "wolf")], ScriptedDice(2, 8))
    f.battle.order = ["bo", "player", "wolf"]
    _down(f, "player")
    f.battle.effects.append(Effect(holder_id="player", source_id="bo", effect_id="bless"))
    _ = end_turn(f)
    _ = asyncio.run(play_next(f, scripted_plans))
    assert f.require_member("player").require_vitals().death_successes == 1


def test_a_natural_20_on_a_death_save_lets_the_member_act_at_once() -> None:
    bo = member("bo", "rogue")
    f = fight([(_hero(), "front"), (bo, "front")], [foe("wolf", "wolf")], SteadyDice(20))
    f.battle.order = ["bo", "player", "wolf"]
    _down(f, "player")
    _ = end_turn(f)
    _ = asyncio.run(play_next(f, scripted_plans))
    assert f.require_member("player").require_vitals().hp.current == 1
    assert current_combatant(f).combatant_id == "player"


def test_a_natural_1_on_a_death_save_keeps_the_bardic_die() -> None:
    bard = member("bo", "bard")
    f = fight([(_hero(), "front"), (bard, "front")], [foe("wolf", "wolf")], ScriptedDice(4, 1))
    f.battle.order = ["bo", "player", "wolf"]
    _down(f, "player")
    f.require_member("player").require_sheet().inspiration = False
    f.battle.effects.extend(
        Effect(holder_id="player", source_id="bo", effect_id=effect_id)
        for effect_id in ("bless", "bardic-inspiration")
    )
    _ = end_turn(f)
    _ = asyncio.run(play_next(f, scripted_plans))
    assert f.require_member("player").require_vitals().death_failures == 2
    assert f.battle.find_effect("player", "bardic-inspiration") is not None


def test_invisibility_gives_advantage_on_initiative() -> None:
    f = fight([(_hero(), "front")], [foe("wolf", "wolf")], ScriptedDice(1, 20, 1))
    lay(f, "player", "invisible")
    _ = roll_initiative(f, ())
    assert f.battle.order == ["player", "wolf"]


def test_fear_makes_a_foe_flee_instead_of_acting() -> None:
    f = fight([(_hero(), "front")], [foe("wolf", "wolf")], SteadyDice(2))
    f.battle.effects.append(Effect(holder_id="wolf", source_id="player", effect_id="fear"))
    _ = end_turn(f)
    _ = asyncio.run(play_next(f, scripted_plans))
    assert _foe(f, "wolf").row == "back"
    assert f.require_member("player").require_vitals().hp.shortfall == 0


def test_a_multiattack_turns_to_a_standing_member_once_its_target_drops() -> None:
    hero = _hero()
    hero.require_vitals().hp.current = 1
    f = fight(
        [(hero, "front"), (member("bo"), "back")],
        [foe("captain", "bandit-captain")],
        SteadyDice(15),
    )
    f.battle.order = ["player", "captain", "bo"]
    _ = end_turn(f)
    _ = asyncio.run(play_next(f, scripted_plans))
    assert f.require_member("player").require_vitals().death_failures == 0
    assert f.require_member("bo").require_vitals().hp.shortfall > 0


def test_a_dash_from_the_back_row_leaves_the_battle_and_ends_it_as_an_escape() -> None:
    bo = member("bo", "rogue")
    f = fight([(_hero(), "back"), (bo, "front")], [foe("wolf", "wolf")], Random(1))
    f.battle.order = ["player", "wolf", "bo"]
    _ = play(f, "act dash")
    assert _member(f, "player").withdrawal == "left"
    assert battle_end(f) is None
    assert f.battle.phase == "foes"
    _down(f, "bo")
    end = battle_end(f)
    assert end is not None and end.outcome == "escape"


def test_surrender_is_a_defeat_by_yielding() -> None:
    f = fight([(_hero(), "front")], [foe("wolf", "wolf")], Random(1))
    end = surrender(f)
    assert (end.outcome, end.yielded) == ("defeat", True)


def test_extra_attack_gives_two_attacks_for_one_action() -> None:
    f = fight(
        [(member("player", level=5, weapon_ids=("longsword",)), "front")],
        [foe("ogre", "ogre")],
        Random(1),
    )
    _ = play(f, "act longsword", "ogre")
    assert f.battle.budget.attacks_left == 1
    _ = play(f, "act longsword", "ogre")
    with pytest.raises(Refusal, match="no pick"):
        _ = play(f, "act longsword", "ogre")
