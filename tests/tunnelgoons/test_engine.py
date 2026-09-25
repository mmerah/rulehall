import pytest
from support.table import TUNNELGOONS, game, narrowed
from support.tunnelgoons import ENGINE

from rulehall.core.validation import Refusal
from rulehall.engines.engine import AnyEngine
from rulehall.engines.packs import SRD_PACK
from rulehall.engines.tunnelgoons.world import TunnelGoonsGame

PICKS = {
    "brute": "1",
    "skulker": "1",
    "erudite": "1",
    "item-1": "Rope",
    "item-2": "Torch",
    "item-3": "Melee Weapon (dagger)",
}


def _tunnelgoons_game() -> tuple[AnyEngine, TunnelGoonsGame]:
    engine, state = game(TUNNELGOONS)
    state = narrowed(state, TunnelGoonsGame)
    return engine, state


def test_the_shipped_game_begins_on_the_maps_start_with_the_starting_items() -> None:
    _, state = _tunnelgoons_game()
    assert state.pack_id == "srd"
    world = state.world
    assert world.visits[0] == world.current.id
    assert {item.name for item in world.carried(world.player.id)} == {
        "Pry Bar (melee weapon)",
        "Rope",
        "Torch",
    }


def test_create_character_on_the_legal_path() -> None:
    character = ENGINE.create_character("Kael", "A wiry scavenger", SRD_PACK, PICKS)
    assert character.sheet.kit == ("Rope", "Torch", "Melee Weapon (dagger)")
    assert character.sheet.sheet.abilities == {"brute": 1, "skulker": 1, "erudite": 1}


def test_a_sum_not_equal_to_three_is_refused() -> None:
    """Each pick is legal on its own, so only the sheet's own rule can say no, and it must read."""
    with pytest.raises(Refusal, match="share exactly 3 points"):
        _ = ENGINE.create_character(
            "Kael", "A wiry scavenger", SRD_PACK, dict(PICKS, brute="3", skulker="3")
        )
