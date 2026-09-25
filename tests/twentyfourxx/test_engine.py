from support.table import TWENTYFOURXX, game, narrowed
from support.twentyfourxx import ENGINE, SCENE_BASE, small_world

from rulehall.engines.engine import AnyEngine
from rulehall.engines.packs import SRD_PACK
from rulehall.engines.twentyfourxx.world import TwentyFourXXGame, TwentyFourXXNext

COMM = "comm"
CLIMBING_GEAR = "climbing-gear"
NIGHT_VISION_GOGGLES = "night-vision-goggles"


def _twentyfourxx_game() -> tuple[AnyEngine, TwentyFourXXGame]:
    engine, state = game(TWENTYFOURXX)
    state = narrowed(state, TwentyFourXXGame)
    return engine, state


def test_the_shipped_game_begins_with_the_srd_pack_and_the_operators_gear() -> None:
    _, state = _twentyfourxx_game()
    assert state.pack_id == SRD_PACK
    world = state.world
    assert list(world.player.require_sheet().items) == [COMM, CLIMBING_GEAR, NIGHT_VISION_GOGGLES]
    assert world.scene.place_id == "docking-ring"


def test_master_sections_shows_hidden_entities() -> None:
    world = small_world()
    sections = dict(ENGINE.master_sections(world))
    assert "Sable" in sections["HIDDEN HERE (the player has not found these)"]


def test_installing_the_next_scene_sets_whether_the_ship_is_here() -> None:
    draft = small_world()
    draft.world.ship_here = True

    scene = TwentyFourXXNext.model_validate(
        dict(SCENE_BASE) | {"recap": "Left the bay.", "ship_here": False}
    )

    _ = ENGINE.install(draft, scene)

    assert draft.world.ship_here is False
