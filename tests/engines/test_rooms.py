import pytest
from support.table import (
    change,
    refused,
    run_action,
)
from support.tunnelgoons import (
    CELLAR,
    CRYPT,
    ENGINE,
    GATE,
    HALL,
    KEY,
    LANTERN,
    MIRA,
    ROPE,
    START,
    VAULT,
    WARDEN,
    YARD,
    keep,
    small_world,
)

from rulehall.core.facts import Fact, cards
from rulehall.core.validation import Refusal
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.rooms.args import MOVED_CARD, MOVES_OFFSCREEN
from rulehall.engines.rooms.panels import map_view
from rulehall.engines.rooms.world import MapProposal
from rulehall.engines.tunnelgoons.engine import TunnelGoonsEngine
from rulehall.engines.tunnelgoons.world import Goon, TunnelGoonsGame


def test_a_member_joins_and_leaves_the_party() -> None:
    draft = keep().draft()

    _ = change(ENGINE, draft, "join_party", target_id=WARDEN)

    assert WARDEN in draft.world.party

    _ = change(ENGINE, draft, "leave_party", target_id=WARDEN)

    assert draft.world.party == []


def test_killing_the_player_leaves_them_dead_and_a_second_kill_is_refused() -> None:
    draft = small_world().draft()

    facts = change(ENGINE, draft, "kill", target_id=PLAYER_ID)

    assert not draft.world.player.alive
    death = [fact for fact in facts if fact.card.startswith("You are dead")]
    assert len(death) == 1
    assert death[0].told

    message = refused(ENGINE, draft, "kill", target_id=PLAYER_ID)

    assert "already dead" in message


def test_a_dead_npc_drops_only_its_known_items_into_the_telling() -> None:
    draft = small_world().draft()
    draft.world.items[KEY].holder_id = MIRA
    draft.world.items[LANTERN].holder_id = MIRA

    facts = change(ENGINE, draft, "kill", target_id=MIRA)

    told = "\n".join(fact.trace + fact.card for fact in facts if fact.told)
    assert "Lantern" in told
    assert "Key" not in told
    assert draft.world.items[KEY].holder_id == START


def test_frontier_skips_places_behind_a_locked_way() -> None:
    world = small_world().world
    world.visits.append(HALL)
    for way in world.ways[START]:
        way.locked = way.to_id == VAULT

    assert world.frontier() == 0


def test_the_map_holds_visited_places_and_the_far_ends_of_known_ways_only() -> None:
    world = small_world().world
    _ = world.move(HALL, ())

    view = map_view(world)

    assert [(node.id, node.visited, node.prefill) for node in view.nodes] == [
        (START, True, "I go to Start"),
        (HALL, True, ""),
        (VAULT, False, "I try the way to Vault"),
    ]
    assert CRYPT not in {node.id for node in view.nodes}
    assert {(edge.from_id, edge.to_id, edge.locked) for edge in view.edges} == {
        (HALL, START, False),
        (HALL, VAULT, True),
    }
    assert view.here_id == HALL


def test_the_map_edge_follows_the_way_from_here_when_the_way_back_is_locked() -> None:
    world = small_world().world
    _ = world.move(HALL, ())
    for way in world.ways[START]:
        way.locked = way.to_id == HALL

    view = map_view(world)

    assert (START, "I go to Start") in {(node.id, node.prefill) for node in view.nodes}
    assert (HALL, START, False) in {(edge.from_id, edge.to_id, edge.locked) for edge in view.edges}


def test_drop_here_puts_a_carried_item_in_this_place_and_refuses_one_on_the_floor() -> None:
    draft = small_world().draft()

    _ = run_action(ENGINE, draft, "drop_here", item_id=ROPE)

    assert draft.world.items[ROPE].holder_id == START
    with pytest.raises(Refusal):
        _ = run_action(ENGINE, draft, "drop_here", item_id=LANTERN)


def _walked(begun_room: TunnelGoonsGame) -> TunnelGoonsGame:
    """At CELLAR, having walked GATE and YARD: every power has something legal."""
    begun_room.world.move(YARD, ())
    begun_room.world.move(CELLAR, ())
    return begun_room.draft()


def _all_three(engine: TunnelGoonsEngine, draft: TunnelGoonsGame) -> list[Fact]:
    """One armed call spending every power: the warden walks, the lantern moves, a way shuts."""
    draft.world.meanwhile_due = True
    return change(
        engine,
        draft,
        "meanwhile",
        dweller_id=WARDEN,
        dweller_to_id=YARD,
        item_id=LANTERN,
        item_to_id=GATE,
        shut_from_id=GATE,
        shut_to_id=YARD,
    )


def test_meanwhile_moves_all_three_things_in_one_call() -> None:
    draft = _walked(keep())

    _ = _all_three(ENGINE, draft)

    world = draft.world
    assert world.npcs[WARDEN].place_id == YARD
    assert world.items[LANTERN].holder_id == GATE
    way = world.way(GATE, YARD)
    assert way is not None
    assert way.locked
    assert not world.meanwhile_due


def test_meanwhile_never_reaches_the_narrator() -> None:
    draft = _walked(keep())

    facts = _all_three(ENGINE, draft)

    told = [fact for fact in facts if fact.told]
    assert len(told) == 1
    only = told[0]
    assert only.card == MOVED_CARD
    assert only.trace == MOVES_OFFSCREEN
    for name in ("Warden", "Lantern", "Gate", "Yard"):
        assert name not in only.trace
        assert name not in only.card
    assert cards(facts) == (only,)


def test_a_counted_turn_spends_the_armed_flag() -> None:
    draft = _walked(keep())
    draft.world.meanwhile_due = True

    ENGINE.count_turn(draft)

    assert not draft.world.meanwhile_due


def test_the_arc_reaches_the_master_and_the_worldsmith_and_nobody_else() -> None:
    begun_room = keep()
    arc = "The Warden answers to the Gremlin Queen."
    begun_room.world.arc = arc

    written = ENGINE.render_request(
        begun_room, intent="More map.", guidance="", answer_model=MapProposal[Goon]
    ).text

    assert arc in str(ENGINE.master_sections(begun_room))
    assert arc in written
    assert arc not in str(ENGINE.narrator_view(begun_room).model_dump())
    assert arc not in str(ENGINE.player_view(begun_room).model_dump())
