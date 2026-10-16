import re
from random import Random

import pytest
from support.lite5e import GATE, HALL, ScriptedDice, hero, person, sheet_proposal, world
from support.lite5e_battle import companion, member

from rulehall.core.facts import Fact
from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.args import StartBattle
from rulehall.engines.lite5e.battle.aftermath import HERO_FALLS, settle_battle, start_battle
from rulehall.engines.lite5e.battle.state import Battle, FoeCombatant, MemberCombatant
from rulehall.engines.lite5e.battle.turns import BattleEnd, Outcome
from rulehall.engines.lite5e.sheet import Lite5ePerson
from rulehall.engines.lite5e.world import Lite5eWorld
from rulehall.engines.sheet import PLAYER_ID

SECRET = re.compile(r"\b(DC|AC|CR|XP|HP)\b\D{0,3}\d|\d+ (XP|HP)\b|passive", re.IGNORECASE)


def _hero() -> Lite5ePerson:
    built = hero(sheet_proposal("fighter"))
    sheet = built.require_sheet()
    sheet.add_gear("longsword", 1)
    sheet.equipped_ids.append("longsword")
    return built


def _world(
    *npcs: Lite5ePerson, party: tuple[Lite5ePerson, ...] = (), dice: Random | None = None
) -> Lite5eWorld:
    built = world(*npcs, *party, player=_hero(), dice=dice)
    built.party_ids.extend(member.id for member in party)
    return built


def _start(
    built: Lite5eWorld, *foe_ids: str, rng: Random | None = None, opening: str = "face_to_face"
) -> list[Fact]:
    args = StartBattle.model_validate({"foe_ids": foe_ids, "opening": opening})
    return start_battle(built, args, rng or Random(1))


def _battle(built: Lite5eWorld) -> Battle:
    assert built.battle is not None
    return built.battle


def _foe(built: Lite5eWorld, combatant_id: str) -> FoeCombatant:
    found = _battle(built).require_combatant(combatant_id)
    assert isinstance(found, FoeCombatant)
    return found


def _member(built: Lite5eWorld, actor_id: str) -> MemberCombatant:
    found = _battle(built).require_combatant(actor_id)
    assert isinstance(found, MemberCombatant)
    return found


def _settle(
    built: Lite5eWorld, outcome: Outcome, rng: Random | None = None, *, yielded: bool = False
) -> tuple[list[Fact], str | None, list[str]]:
    resolution, notes = settle_battle(
        built, BattleEnd(outcome=outcome, yielded=yielded), rng or Random(1)
    )
    return list(resolution.facts), resolution.narrator_cue, notes


def _told(facts: list[Fact]) -> list[str]:
    return [fact.trace for fact in facts if fact.told]


def test_start_battle_refuses_a_foe_not_here_or_not_hidden() -> None:
    built = _world(
        person("guard", GATE, "guard"),
        person("far", HALL, "guard"),
        person("lurker", GATE, "goblin-warrior", known=False),
        dice=ScriptedDice(20),
    )
    for foe_id, opening in (
        ("far", "face_to_face"),
        ("guard", "foe_ambush"),
        ("lurker", "face_to_face"),
        (PLAYER_ID, "face_to_face"),
    ):
        with pytest.raises(Refusal):
            _ = _start(built, foe_id, opening=opening)
    assert built.battle is None


def test_a_former_class_companion_never_becomes_a_foe() -> None:
    former = person("ally", GATE)
    former.sheet = member("ally").require_sheet()
    built = _world(former)
    with pytest.raises(Refusal, match="former class companion"):
        _ = _start(built, "ally")
    assert built.battle is None


def test_the_battle_opens_with_numbered_foes_and_each_member_in_its_row() -> None:
    dog = companion("dog", "mastiff")
    dog.formation_row = "back"
    tag = person("tag", GATE)
    built = _world(
        person("goblins", GATE, "goblin-warrior", count=3),
        person("goblins-2", HALL),
        party=(dog, tag),
    )
    _ = _start(built, "goblins")
    battle = _battle(built)
    assert [foe.combatant_id for foe in battle.foes()] == ["goblins-1", "goblins-3", "goblins-4"]
    assert battle.foes()[0].name == "Goblins 1"
    assert [(m.combatant_id, m.row) for m in battle.member_combatants()] == [
        (PLAYER_ID, "front"),
        ("dog", "back"),
    ]
    assert built.long_rest_earned
    with pytest.raises(Refusal):
        _ = _start(built, "goblins")


def test_surrendered_foes_become_captives_and_a_second_surrender_adds_to_them() -> None:
    held = person("bandits-captives", GATE, "bandit", captive=True)
    built = _world(person("bandits", GATE, "bandit", count=3), held)
    _ = _start(built, "bandits")
    for foe in _battle(built).foes()[:2]:
        foe.withdrawal = "surrendered"
    _ = _settle(built, "defeat")
    assert built.npcs["bandits-captives"].count == 3
    assert built.npcs["bandits"].count == 1


def test_a_defeat_stands_the_fallen_at_1_hp_and_leaves_the_foes_not_hostile() -> None:
    tag = person("tag", GATE)
    built = _world(person("goblins", GATE, "goblin-warrior", count=3, hostile=True), party=(tag,))
    _ = _start(built, "goblins")
    assert "tag" not in {m.combatant_id for m in _battle(built).member_combatants()}
    _foe(built, "goblins-1").hp.current = 0
    _foe(built, "goblins-2").hp.current = 1
    built.player.require_sheet().vitals.hp.current = 0
    facts, cue, notes = _settle(built, "defeat")
    assert built.player.require_sheet().vitals.hp.current == 1
    assert not built.npcs["goblins"].hostile
    assert built.npcs["goblins"].count == 2
    assert "Tag" in notes[0]
    assert cue is not None and "Tag" in cue
    assert not any(SECRET.search(trace) for trace in _told(facts))
    _ = built.rest("long", Random(1))
    _ = _start(built, "goblins")
    assert [foe.hp.current for foe in _battle(built).foes()] == [10, 10]


def test_xp_is_split_among_the_members_alive_at_the_end() -> None:
    party = (member("bo", "rogue"), member("cleo", "cleric"))
    built = _world(person("goblins", GATE, "goblin-warrior", count=2), party=party)
    cleo = built.npcs["cleo"]
    _ = _start(built, "goblins")
    for foe in _battle(built).foes():
        foe.hp.current = 0
    _member(built, "bo").withdrawal = "left"
    cleo.require_sheet().vitals.hp.current = 0
    cleo.require_sheet().vitals.death_failures = 3
    facts, _, _ = _settle(built, "victory")
    assert built.player.require_sheet().xp == 50
    assert not cleo.alive
    assert "cleo" not in built.party_ids
    xp = next(fact for fact in facts if fact.card.endswith("XP each"))
    assert xp.card == "+50 XP each" and not SECRET.search(xp.trace)


def test_the_hero_s_death_ends_the_game() -> None:
    built = _world(person("wolf", GATE, "wolf"))
    _ = _start(built, "wolf")
    sheet = built.player.require_sheet()
    sheet.vitals.hp.current = 0
    sheet.vitals.death_failures = 3
    _, cue, _ = _settle(built, "hero_dead")
    assert not built.player.alive
    assert cue == HERO_FALLS


def test_a_group_whose_last_members_surrendered_is_gone_not_dead_and_drops_its_gear_once() -> None:
    built = _world(person("bandits", GATE, "bandit", count=2))
    _ = _start(built, "bandits")
    dropped, surrendered = _battle(built).foes()
    dropped.hp.current = 0
    surrendered.withdrawal = "surrendered"
    facts, _, _ = _settle(built, "victory")
    assert "bandits" not in built.npcs
    assert not any("dead" in fact.card for fact in facts)
    items = len(built.items)
    _ = _start(built, "bandits-captives")
    _battle(built).foes()[0].hp.current = 0
    _ = _settle(built, "victory")
    assert len(built.items) == items


def test_a_regrouped_routed_group_is_routed_again_when_it_flees() -> None:
    built = _world(person("wolves", GATE, "wolf"))
    for _ in range(2):
        _ = _start(built, next(npc_id for npc_id in built.npcs if npc_id.startswith("wolves")))
        _battle(built).foes()[0].withdrawal = "fled"
        _ = _settle(built, "victory")
        routed = built.npcs["wolves-routed"]
        assert routed.routed and routed.name == "Wolves, routed"
        routed.regroup()
        routed.place_id = built.current.id
