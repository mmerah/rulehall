import pytest
from support.lite5e import (
    BANDITS,
    HALL,
    ScriptedDice,
    hero,
    person,
    sheet_proposal,
    world,
)

from rulehall.core.validation import Refusal

NO_DICE = ScriptedDice()
SHORT_REST_USES = frozenset(
    {
        "second-wind",
        "channel-divinity",
        "action-surge",
        "adrenaline-rush",
        "rage",
        "wild-shape",
        "focus",
    }
)


def test_a_long_rest_needs_a_first_visit_and_short_rests_are_two_at_most() -> None:
    built = world()
    with pytest.raises(Refusal, match="first visit"):
        _ = built.rest("long", NO_DICE)
    _ = built.rest("short", NO_DICE)
    _ = built.rest("short", NO_DICE)
    with pytest.raises(Refusal, match="short rests at most"):
        _ = built.rest("short", NO_DICE)
    _ = built.move(HALL, ())
    _ = built.rest("long", NO_DICE)
    assert built.short_rests_since_long_rest == 0
    with pytest.raises(Refusal, match="first visit"):
        _ = built.rest("long", NO_DICE)


def test_a_hostile_person_one_way_away_blocks_a_rest_and_a_captive_does_not() -> None:
    built = world(person(BANDITS, HALL, "bandit", hostile=True))
    with pytest.raises(Refusal, match="hostile"):
        _ = built.rest("short", NO_DICE)
    built.npcs[BANDITS].captive = True
    _ = built.rest("short", NO_DICE)


def test_a_routed_group_regroups_under_its_name_at_a_long_rest() -> None:
    built = world(person(BANDITS, HALL, "bandit", hostile=True))
    bandits = built.npcs[BANDITS]
    name = bandits.name
    bandits.name = f"{name}, routed"
    bandits.routed = True
    _ = built.move(HALL, ())
    _ = built.rest("long", NO_DICE)
    assert (bandits.name, bandits.routed) == (name, False)


def test_a_long_rest_brings_hp_hit_dice_and_inspiration_back_and_one_exhaustion_off() -> None:
    sheet = hero(sheet_proposal("fighter"), level=2).require_sheet()
    _ = sheet.take_harm(5, "fire")
    sheet.temp_hp = 2
    sheet.hit_dice_spent = 2
    sheet.exhaustion = 2
    sheet.long_rest()
    assert sheet.vitals.hp.current == sheet.vitals.hp.maximum
    assert (sheet.temp_hp, sheet.hit_dice_spent, sheet.exhaustion) == (0, 0, 1)
    assert sheet.inspiration


def test_a_hostile_person_who_joins_the_party_blocks_no_rest() -> None:
    built = world(person(BANDITS, HALL, "bandit", hostile=True))
    _ = built.join(built.npcs[BANDITS])
    _ = built.rest("short", NO_DICE)
