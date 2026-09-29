import pytest
from pydantic import ValidationError
from support.table import TUNNELGOONS, game, narrowed
from support.tunnelgoons import ENGINE, small_world

from rulehall.core.validation import Refusal
from rulehall.engines.rooms.panels import MORE_MAP
from rulehall.engines.rooms.world import Item, MapProposal, Place, RegionProposal, Way
from rulehall.engines.rooms.worldsmith import check_next, check_opening
from rulehall.engines.sheet import PLAYER_ID, Gauge
from rulehall.engines.tunnelgoons.sheet import Goon
from rulehall.engines.tunnelgoons.world import TunnelGoonsGame

ONLY = "only"
HIDDEN = "hidden"
FAR_HALL = "far-hall"
FAR_VAULT = "far-vault"
FAR_ITEM = "far-item"
HALL = "hall"

THIN = MapProposal[Goon](
    places={ONLY: Place(id=ONLY, name="Only", brief="b", known=True, description="d")},
    start_id=ONLY,
)


def _tunnelgoons_game() -> TunnelGoonsGame:
    _, state = game(TUNNELGOONS)
    return narrowed(state, TunnelGoonsGame)


def _region() -> RegionProposal[Goon]:
    return RegionProposal[Goon](
        places={
            FAR_HALL: Place(id=FAR_HALL, name="Far Hall", brief="b", known=False, description="d"),
            FAR_VAULT: Place(
                id=FAR_VAULT, name="Far Vault", brief="b", known=False, description="d"
            ),
        },
        ways={FAR_HALL: [Way(to_id=FAR_VAULT)]},
        items={
            FAR_ITEM: Item(id=FAR_ITEM, name="Far Item", brief="b", known=False, holder_id=FAR_HALL)
        },
        start_id=FAR_HALL,
        recap="They pushed past the hall and found the vault beyond it.",
    )


def _wide_region() -> MapProposal[Goon]:
    canon = _tunnelgoons_game().world
    return MapProposal[Goon](
        places=canon.places,
        ways=canon.ways,
        npcs=canon.npcs,
        items=canon.items,
        start_id=canon.current.id,
    )


def test_a_one_place_map_with_no_ways_passes_the_map_bar() -> None:
    check_opening(THIN)


def test_a_region_of_one_hidden_place_with_no_ways_installs_hidden() -> None:
    draft = _tunnelgoons_game().draft()
    region = RegionProposal[Goon](
        places={HIDDEN: Place(id=HIDDEN, name="Hidden", brief="b", known=False, description="d")},
        start_id=HIDDEN,
        recap="They found a hidden way and pushed through it.",
    )
    check_next(region, draft.world)

    _ = ENGINE.install_next(draft, region)

    assert not draft.world.places[HIDDEN].known
    assert draft.world.find_way(draft.world.current.id, HIDDEN) is not None


def test_the_shipped_scenario_passes_the_map_bar() -> None:
    check_opening(_wide_region())


def test_a_living_npc_is_written_with_hp_above_zero() -> None:
    with pytest.raises(ValidationError, match="hp is above zero"):
        Goon(id="corpse", name="Corpse", brief="", place_id=ONLY, hp=Gauge(current=0, maximum=4))


def test_check_next_refuses_an_item_planted_on_the_player() -> None:
    world = _tunnelgoons_game().world
    region = RegionProposal[Goon](
        places={HIDDEN: Place(id=HIDDEN, name="Hidden", brief="b", known=False, description="d")},
        items={
            "planted": Item(
                id="planted", name="Planted", brief="b", known=True, holder_id=PLAYER_ID
            )
        },
        start_id=HIDDEN,
        recap="A hand slipped something into their pocket.",
    )
    with pytest.raises(Refusal, match="planted on the player"):
        check_next(region, world)


def test_check_next_refuses_a_recap_that_names_an_unmet_npc() -> None:
    world = _tunnelgoons_game().world
    unmet = next(person for person in world.people() if not person.known)
    region = _region().model_copy(update={"recap": f"They never found {unmet.name}."})
    with pytest.raises(Refusal, match="has not met"):
        check_next(region, world)


def test_check_next_accepts_an_unknown_place_naming_itself() -> None:
    region = _region()
    region.places[FAR_HALL].description = "Far Hall is a ruin."
    check_next(region, _tunnelgoons_game().world)


def _hiding_gremlin(
    place_id: str, *, known: bool, brief: str, description: str
) -> MapProposal[Goon]:
    gremlin = Goon(
        id="gremlin",
        name="Gremlin",
        brief="",
        place_id=place_id,
        known=False,
        hp=Gauge(current=4, maximum=4),
    )
    place = Place(
        id=place_id, name=place_id.title(), brief=brief, known=known, description=description
    )
    return MapProposal[Goon](
        places={place_id: place}, npcs={gremlin.id: gremlin}, start_id=place_id
    )


def test_check_opening_refuses_a_start_description_naming_a_hidden_dweller() -> None:
    draft = _hiding_gremlin(
        ONLY, known=True, brief="b", description="A Gremlin hides in the shadows."
    )
    with pytest.raises(Refusal, match="do not name"):
        check_opening(draft)


def test_attach_joins_at_the_current_place_and_the_world_validates() -> None:
    state = small_world()
    world = state.world
    anchor = world.current.id

    region = _region()
    world.apply_region(region)

    assert FAR_HALL in world.places
    assert FAR_VAULT in world.places
    assert world.find_way(anchor, FAR_HALL) is not None
    assert world.find_way(FAR_HALL, anchor) is not None


def test_a_region_reusing_an_id_already_in_the_world_is_refused() -> None:
    state = small_world()
    reused = _region().model_copy(
        update={
            "places": {
                HALL: Place(id=HALL, name="Hall Again", brief="b", known=False, description="d"),
                FAR_VAULT: Place(
                    id=FAR_VAULT, name="Far Vault", brief="b", known=False, description="d"
                ),
            },
            "ways": {HALL: [Way(to_id=FAR_VAULT)]},
            "start_id": HALL,
        }
    )

    with pytest.raises(Refusal, match="not already in the world"):
        check_next(reused, state.world)


def test_more_map_waits_for_no_open_way_and_a_joined_region_begins_as_an_unexplored_way() -> None:
    draft = small_world().draft()
    assert ENGINE.player_view(draft).moves == ()

    _ = draft.world.move(HALL, ())
    assert ENGINE.player_view(draft).moves == (MORE_MAP,)

    region = _region()
    draft.world.apply_region(region)
    view = ENGINE.player_view(draft.validated())
    assert view.moves == ()
    assert view.map is not None
    assert [node.name for node in view.map.nodes] == [
        "Start",
        "Hall",
        "???",
        "???",
    ]
