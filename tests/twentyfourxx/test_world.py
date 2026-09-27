import pytest
from support.table import change
from support.twentyfourxx import ENGINE, KESTREL, hired, small_world

from rulehall.core.validation import Refusal
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.twentyfourxx.rules import raised
from rulehall.engines.twentyfourxx.world import (
    STARTING_CREDITS,
    Gear,
    TwentyFourXXGame,
    TwentyFourXXWorld,
)


def test_item_broken_at_and_below_breaks() -> None:
    item = Gear(name="Vest", breaks=2)
    assert not item.broken
    item.broken_times = 1
    assert not item.broken
    item.broken_times = 2
    assert item.broken


def test_raised_steps_up_the_ladder() -> None:
    assert raised(None) == 8
    assert raised(8) == 10
    assert raised(10) == 12


def test_the_new_lead_takes_the_players_id_and_the_dead_lead_is_filed_by_name(
    draft: TwentyFourXXGame,
) -> None:
    world = hired(draft, KESTREL, skills={"Shooting": 8}).world
    world.player.alive = False
    facts = world.take_lead(KESTREL)

    assert (world.player.id, world.player.name) == (PLAYER_ID, "Kestrel")
    assert KESTREL not in world.cast
    assert KESTREL not in world.party
    assert not world.cast["rook"].alive
    assert "rook" in world.scene.here
    assert "Kestrel[kestrel]" not in world.cast_lines()
    assert any(fact.card == "Kestrel leads now" for fact in facts)
    TwentyFourXXWorld.model_validate_json(world.model_dump_json())


def test_credits_given_reach_the_member_and_a_dead_leads_gear_reaches_the_hold(
    draft: TwentyFourXXGame,
) -> None:
    draft = hired(draft, KESTREL, skills={}).draft()
    world = draft.world
    _ = change(ENGINE, draft, "spend", amount=2, why="his share", to_id=KESTREL)
    assert world.player.require_sheet().credits == STARTING_CREDITS - 2
    assert world.cast[KESTREL].require_sheet().credits == STARTING_CREDITS + 2

    world.player.alive = False
    _ = world.take_lead(KESTREL)
    assert [item.name for item in world.hold.values()] == ["Lockpick set"]
    assert world.cast["rook"].require_sheet().items == {}


def test_credits_paid_outside_the_crew_leave_the_payer_and_reach_no_sheet(
    draft: TwentyFourXXGame,
) -> None:
    draft = draft.draft()
    world = draft.world
    _ = change(ENGINE, draft, "spend", amount=1, why="up-front pay", to_id=KESTREL)
    facts = change(ENGINE, draft, "spend", amount=1, why="a bribe", to_id="dock-broker")

    assert world.player.require_sheet().credits == STARTING_CREDITS - 2
    assert world.cast[KESTREL].sheet is None
    assert "a bribe, to dock-broker" in facts[-1].trace


def test_require_gear_finds_a_ship_function_and_refuses_a_stranger() -> None:
    world = small_world().world
    item = world.require_gear(world.player, "hull-armor")
    assert item.name == "Hull armor"
    with pytest.raises(Refusal, match="not among"):
        world.require_gear(world.player, "nonexistent")


def test_hinder_twice_writes_only_one_fact(world: TwentyFourXXWorld) -> None:
    player = world.player
    facts = player.hinder("Winded")
    assert [fact.card for fact in facts] == ["Hindered: Winded"]
    assert player.require_sheet().hindrances == ["Winded"]
    assert player.hinder("Winded") == []
