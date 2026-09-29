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

from rulehall.core.facts import Fact, told_cards
from rulehall.core.validation import Refusal
from rulehall.engines.rooms.args import MOVED_CARD, MOVES_OFFSCREEN
from rulehall.engines.rooms.panels import map_view
from rulehall.engines.rooms.world import MEANWHILE_EVERY, Way
from rulehall.engines.sheet import PLAYER_ID
from rulehall.engines.tunnelgoons.engine import TunnelGoonsEngine
from rulehall.engines.tunnelgoons.world import TunnelGoonsGame


def test_a_member_joins_and_leaves_the_party() -> None:
    draft = keep().draft()

    _ = change(ENGINE, draft, "join_party", target_id=WARDEN)

    assert WARDEN in draft.world.party_ids

    _ = change(ENGINE, draft, "leave_party", target_id=WARDEN)

    assert draft.world.party_ids == []


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


def test_the_frontier_skips_a_locked_way_and_a_place_the_player_cannot_reach() -> None:
    world = small_world().world
    _ = world.move(HALL, ())
    assert not world.has_frontier()

    world.ways[START][1].known = True
    assert world.has_frontier()

    for way in world.ways[HALL]:
        way.locked = True
    assert not world.has_frontier()


def test_a_known_way_into_an_unknown_place_is_a_stub_that_hides_its_end() -> None:
    world = small_world().world
    _ = world.move(HALL, ())
    world.ways[HALL].append(Way(to_id=CRYPT))

    view = map_view(world)

    assert [(node.id, node.name, node.visited, node.prefill) for node in view.nodes] == [
        (START, "Start", True, "I go to Start"),
        (HALL, "Hall", True, ""),
        ("way-2-2", "???", False, "I take the unknown way out of Hall"),
        ("way-2-3", "???", False, "I take the unknown way out of Hall"),
    ]
    assert {(edge.from_id, edge.to_id, edge.locked) for edge in view.edges} == {
        (HALL, START, False),
        (HALL, "way-2-2", True),
        (HALL, "way-2-3", False),
    }
    assert view.here_id == HALL
    shown = view.model_dump_json().lower()
    assert VAULT not in shown
    assert CRYPT not in shown
    assert "- Vault[vault] — known; destination unknown to the player; locked" in (
        world.ways_lines().splitlines()
    )


def test_walking_one_stub_leaves_the_other_stub_its_id() -> None:
    world = small_world().world
    _ = world.move(HALL, ())
    world.ways[HALL].append(Way(to_id=CRYPT))
    before = [node.id for node in map_view(world).nodes]

    _ = world.unlock_way(VAULT)
    _ = world.move(VAULT, ())

    assert before == [START, HALL, "way-2-2", "way-2-3"]
    assert [node.id for node in map_view(world).nodes] == [START, HALL, VAULT, "way-2-3"]


def test_an_unlocked_stub_names_the_place_its_card_names() -> None:
    world = small_world().world
    _ = world.move(HALL, ())

    facts = world.unlock_way(VAULT)

    assert [fact.card for fact in told_cards(facts)] == ["Vault unlocked"]
    assert [node.name for node in map_view(world).nodes] == ["Start", "Hall", "Vault"]


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
    way = world.find_way(GATE, YARD)
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
    assert told_cards(facts) == (only,)


def test_the_clock_counts_only_a_turn_that_acted_and_arms_at_the_tempo() -> None:
    draft = _walked(keep())

    ENGINE.end_turn(draft, acted=False)
    assert draft.world.turns_since_meanwhile == 0

    for _ in range(MEANWHILE_EVERY):
        ENGINE.end_turn(draft, acted=True)

    assert (draft.world.turns_since_meanwhile, draft.world.meanwhile_due) == (0, True)


def test_a_counted_turn_spends_the_armed_flag() -> None:
    draft = _walked(keep())
    draft.world.meanwhile_due = True

    ENGINE.end_turn(draft, acted=True)

    assert not draft.world.meanwhile_due


def test_the_arc_reaches_the_master_and_the_worldsmith_and_nobody_else() -> None:
    begun_room = keep()
    arc = "The Warden answers to the Gremlin Queen."
    begun_room.world.arc = arc

    assert arc in str(ENGINE.master_sections(begun_room))
    assert arc in str(ENGINE.worldsmith_sections(begun_room))
    assert arc not in str(ENGINE.narrator_view(begun_room).model_dump())
    assert arc not in str(ENGINE.player_view(begun_room).model_dump())
