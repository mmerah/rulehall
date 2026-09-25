import pytest
from pydantic import ValidationError
from support.twentyfourxx import KESTREL, hired, small_world

from rulehall.core.validation import Refusal
from rulehall.engines.twentyfourxx.rules import raised
from rulehall.engines.twentyfourxx.world import Gear, TwentyFourXXGame, TwentyFourXXWorld


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


def test_take_lead_swaps_player_and_cast_entry_and_keeps_ids(draft: TwentyFourXXGame) -> None:
    world = hired(draft, KESTREL, skills={"Shooting": 8}).world
    dead_id = world.player.id
    world.player.alive = False
    facts = world.take_lead(KESTREL)

    assert world.player.id == KESTREL
    assert world.player.sheet is not None
    assert KESTREL not in world.cast
    assert KESTREL not in world.party
    assert world.cast[dead_id].id == dead_id
    assert not world.cast[dead_id].alive
    assert dead_id in world.scene.here
    assert any(fact.card == "Kestrel leads now" for fact in facts)
    assert world.player.card_line("Hit") == "Hit"
    assert world.cast[dead_id].mention == world.cast[dead_id].tag
    TwentyFourXXWorld.model_validate_json(world.model_dump_json())


def test_a_world_where_a_cast_member_leads_is_refused() -> None:
    world = small_world().world
    world.cast[KESTREL].leads = True
    with pytest.raises(ValidationError, match="only the player, leads"):
        TwentyFourXXWorld.model_validate_json(world.model_dump_json())


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
