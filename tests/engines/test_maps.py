import json

import pytest
from pydantic import JsonValue, ValidationError
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
    WELL,
    YARD,
    keep,
    small_world,
)

from rulehall.core.decisions import Decision
from rulehall.core.facts import Fact, told_cards
from rulehall.core.game import WorldsmithRequest
from rulehall.core.tools import tool_schema
from rulehall.core.validation import Refusal
from rulehall.engines.bases.maps.args import Meanwhile
from rulehall.engines.bases.maps.engine import MEANWHILE_FIRST, MOVED_CARD, MOVES_OFFSCREEN
from rulehall.engines.bases.maps.panels import map_view
from rulehall.engines.bases.maps.world import (
    EXTEND_REQUEST,
    MEANWHILE_EVERY,
    OFF_MAP_ID,
    Place,
    RegionProposal,
    Way,
)
from rulehall.engines.bases.maps.worldsmith import check_next
from rulehall.engines.sheet import PLAYER_ID, Gauge
from rulehall.engines.tunnelgoons.sheet import Goon
from rulehall.engines.tunnelgoons.world import TunnelGoonsGame, TunnelGoonsWorld

MOAT = "moat"
TOWER = "tower"


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


def test_extend_map_is_refused_with_a_frontier_and_requests_the_region_at_the_edge() -> None:
    draft = small_world()
    assert draft.world.has_frontier()
    _ = refused(ENGINE, draft, "extend_map", heading="north")
    assert draft.request is None

    _ = draft.world.move(HALL, ())
    assert not draft.world.has_frontier()
    _ = change(ENGINE, draft, "extend_map", heading="north")

    assert draft.request == WorldsmithRequest(kind=EXTEND_REQUEST, detail="north")


def test_a_known_way_into_an_unknown_place_is_a_stub_that_hides_its_end() -> None:
    world = small_world().world
    _ = world.move(HALL, ())
    world.ways[HALL].append(Way(to_id=CRYPT))

    view = map_view(world)

    assert [(node.id, node.name, node.kind, node.prefill) for node in view.nodes] == [
        (START, "Start", "visited", "I go to Start"),
        (HALL, "Hall", "visited", ""),
        ("way-2-2", "???", "unexplored", "I take the unknown way out of Hall"),
        ("way-2-3", "???", "unexplored", "I take the unknown way out of Hall"),
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


def _moat_world() -> TunnelGoonsWorld:
    world = small_world().world
    _ = world.move(HALL, ())
    world.apply_region(
        RegionProposal[Goon](
            places={
                MOAT: Place(id=MOAT, name="Moat", brief="b", known=False, description="d"),
                TOWER: Place(id=TOWER, name="Tower", brief="b", known=False, description="d"),
            },
            ways={MOAT: [Way(to_id=TOWER)]},
            start_id=MOAT,
            region_name="The Outer Ward",
            recap="They left the dungeon.",
        ),
        Way,
    )
    _ = world.move(MOAT, ())
    return world


def test_an_earlier_region_is_one_box_linked_to_the_place_it_joins() -> None:
    world = _moat_world()

    view = map_view(world)

    assert (view.region_id, view.region_name) == (MOAT, "The Outer Ward")
    assert [(node.id, node.kind, node.prefill) for node in view.nodes] == [
        (MOAT, "visited", ""),
        ("way-1-1", "unexplored", "I take the unknown way out of Moat"),
        (START, "region", "I head back to The Test Dungeon"),
    ]
    assert (MOAT, START, False) in {(edge.from_id, edge.to_id, edge.locked) for edge in view.edges}
    shown = view.model_dump_json().lower()
    assert all(hidden_id not in shown for hidden_id in (TOWER, VAULT, CRYPT))
    assert world.region_lines().splitlines() == [
        "the player is in The Outer Ward",
        "- The Test Dungeon: Hall[hall] ⇄ The Outer Ward: Moat[moat]",
    ]


def test_walking_back_boxes_the_region_the_player_left() -> None:
    world = _moat_world()
    _ = world.move(HALL, ())

    view = map_view(world)

    assert view.region_id == START
    assert [node.id for node in view.nodes if node.kind == "region"] == [MOAT]
    assert (HALL, MOAT, False) in {(edge.from_id, edge.to_id, edge.locked) for edge in view.edges}
    assert "- Moat[moat] — known; leads into The Outer Ward" in world.ways_lines().splitlines()


def test_the_map_edge_counts_only_the_region_the_player_is_in() -> None:
    world = small_world().world
    _ = world.move(HALL, ())
    world.ways[HALL].append(Way(to_id=CRYPT))
    world.apply_region(
        RegionProposal[Goon](
            places={MOAT: Place(id=MOAT, name="Moat", brief="b", known=False, description="d")},
            start_id=MOAT,
            region_name="The Outer Ward",
            recap="They left the dungeon.",
        ),
        Way,
    )
    _ = world.move(MOAT, ())

    assert world.at_map_edge()

    _ = world.move(HALL, ())

    assert not world.at_map_edge()


def test_a_place_in_no_region_is_refused() -> None:
    world = small_world().world
    dumped = world.model_dump()
    dumped["regions"][0]["place_ids"].remove(CRYPT)

    with pytest.raises(ValidationError, match="places in no region"):
        _ = TunnelGoonsWorld.model_validate(dumped)


def test_drop_here_puts_a_carried_item_in_this_place_and_refuses_one_on_the_floor() -> None:
    draft = small_world().draft()

    _ = run_action(ENGINE, draft, "drop_here", item_id=ROPE)

    assert draft.world.items[ROPE].holder_id == START
    with pytest.raises(Refusal):
        _ = run_action(ENGINE, draft, "drop_here", item_id=LANTERN)


def _walked(begun_map: TunnelGoonsGame) -> TunnelGoonsGame:
    """At CELLAR, having walked GATE and YARD: every power has something legal."""
    begun_map.world.move(YARD, ())
    begun_map.world.move(CELLAR, ())
    return begun_map.draft()


def _meanwhile(draft: TunnelGoonsGame, *changes: dict[str, JsonValue]) -> list[Fact]:
    draft.world.meanwhile_due = True
    return change(ENGINE, draft, "meanwhile", changes=list(changes))


def _refused_meanwhile(draft: TunnelGoonsGame, *changes: dict[str, JsonValue]) -> str:
    draft.world.meanwhile_due = True
    return refused(ENGINE, draft, "meanwhile", changes=list(changes))


def _walk(dweller_id: str, to_id: str) -> dict[str, JsonValue]:
    return {"kind": "walk", "dweller_id": dweller_id, "to_id": to_id}


def _carry(item_id: str, to_id: str) -> dict[str, JsonValue]:
    return {"kind": "carry", "item_id": item_id, "to_id": to_id}


def _way(kind: str, from_id: str, to_id: str) -> dict[str, JsonValue]:
    return {"kind": kind, "from_id": from_id, "to_id": to_id}


def _fall(dweller_id: str) -> dict[str, JsonValue]:
    return {"kind": "fall", "dweller_id": dweller_id}


def _offscreen(draft: TunnelGoonsGame) -> list[Fact]:
    """One armed call away from the player: the warden walks and the lantern moves."""
    return _meanwhile(draft, _walk(WARDEN, YARD), _carry(LANTERN, GATE))


def test_meanwhile_applies_its_changes_in_one_call() -> None:
    draft = _walked(keep())

    _ = _offscreen(draft)

    world = draft.world
    assert world.npcs[WARDEN].place_id == YARD
    assert world.items[LANTERN].holder_id == GATE
    assert not world.meanwhile_due


def test_meanwhile_never_reaches_the_narrator() -> None:
    draft = _walked(keep())

    facts = _offscreen(draft)

    told = [fact for fact in facts if fact.told]
    assert len(told) == 1
    only = told[0]
    assert only.card == MOVED_CARD
    assert only.trace == MOVES_OFFSCREEN
    for name in ("Warden", "Lantern", "Gate", "Yard"):
        assert name not in only.trace
        assert name not in only.card
    assert told_cards(facts) == (only,)


def test_a_walk_along_a_locked_way_or_no_way_is_refused() -> None:
    draft = _walked(keep())
    draft.world.npcs[WARDEN].place_id = YARD

    assert "no unlocked way" in _refused_meanwhile(draft, _walk(WARDEN, WELL))
    assert "no unlocked way" in _refused_meanwhile(draft, _walk(WARDEN, GATE))


def test_a_known_dweller_who_walks_in_is_told_with_no_generic_card() -> None:
    draft = _walked(keep())
    draft.world.npcs[WARDEN].place_id = YARD

    facts = _meanwhile(draft, _walk(WARDEN, CELLAR))

    assert [fact.card for fact in told_cards(facts)] == ["Warden walks in"]
    assert draft.world.npcs[WARDEN].place_id == CELLAR


def test_an_unknown_dweller_who_walks_in_stays_unknown_and_untold() -> None:
    draft = _walked(keep())
    warden = draft.world.npcs[WARDEN]
    warden.place_id = YARD
    warden.known = False

    facts = _meanwhile(draft, _walk(WARDEN, CELLAR))

    assert [fact.card for fact in told_cards(facts)] == [MOVED_CARD]
    assert not warden.known
    assert warden.place_id == CELLAR


def test_a_walk_out_of_the_player_s_place_is_told_only_for_a_known_dweller() -> None:
    for known, cards in ((True, ["Warden leaves"]), (False, [MOVED_CARD])):
        draft = _walked(keep())
        warden = draft.world.npcs[WARDEN]
        warden.place_id = CELLAR
        warden.known = known

        facts = _meanwhile(draft, _walk(WARDEN, WELL))

        assert [fact.card for fact in told_cards(facts)] == cards


def test_a_dead_dweller_does_not_walk() -> None:
    world = _walked(keep()).world
    warden = world.npcs[WARDEN]
    warden.alive = False

    with pytest.raises(Refusal, match="is dead"):
        _ = world.walk(warden, world.require_place(YARD))


def test_a_walk_along_a_secret_way_names_no_end() -> None:
    draft = _walked(keep())
    draft.world.npcs[WARDEN].place_id = YARD
    way = draft.world.find_way(YARD, CELLAR)
    assert way is not None
    way.known = False

    facts = _meanwhile(draft, _walk(WARDEN, CELLAR))

    assert [(fact.trace, fact.card) for fact in told_cards(facts)] == [
        ("Warden[warden] walks in", "Warden walks in")
    ]


def test_a_carry_that_starts_and_ends_at_the_player_s_place_is_refused() -> None:
    draft = _walked(keep())
    draft.world.npcs[WARDEN].place_id = CELLAR
    draft.world.items[LANTERN].holder_id = CELLAR

    assert "move_item" in _refused_meanwhile(draft, _carry(LANTERN, WARDEN))


def test_a_told_carry_out_never_names_where_the_item_went() -> None:
    draft = _walked(keep())
    lantern = draft.world.items[LANTERN]
    lantern.holder_id = CELLAR
    lantern.known = True

    facts = _meanwhile(draft, _carry(LANTERN, YARD))

    assert [(fact.trace, fact.card) for fact in told_cards(facts)] == [
        ("Lantern[lantern] is gone", "Lantern is gone")
    ]


def test_a_carry_into_the_hands_of_an_unknown_dweller_here_is_untold() -> None:
    draft = _walked(keep())
    warden = draft.world.npcs[WARDEN]
    warden.place_id = CELLAR
    warden.known = False
    draft.world.items[LANTERN].known = True

    facts = _meanwhile(draft, _carry(LANTERN, WARDEN))

    assert [fact.card for fact in told_cards(facts)] == [MOVED_CARD]


def test_an_item_is_carried_to_a_dweller_and_refused_where_it_already_is() -> None:
    draft = _walked(keep())

    _ = _meanwhile(draft, _carry(LANTERN, WARDEN))

    assert draft.world.items[LANTERN].holder_id == WARDEN
    assert "already there" in _refused_meanwhile(draft, _carry(LANTERN, WARDEN))


def test_a_known_item_carried_from_a_dweller_at_the_player_s_place_is_told() -> None:
    draft = _walked(keep())
    draft.world.npcs[WARDEN].place_id = CELLAR
    lantern = draft.world.items[LANTERN]
    lantern.holder_id = WARDEN
    lantern.known = True

    facts = _meanwhile(draft, _carry(LANTERN, GATE))

    assert [fact.card for fact in told_cards(facts)] == ["Lantern is gone"]


def test_a_hidden_item_carried_away_from_the_player_s_place_stays_hidden() -> None:
    draft = _walked(keep())
    lantern = draft.world.items[LANTERN]
    lantern.holder_id = CELLAR

    facts = _meanwhile(draft, _carry(LANTERN, GATE))

    assert [fact.card for fact in told_cards(facts)] == [MOVED_CARD]
    assert not lantern.known
    assert lantern.holder_id == GATE


def test_a_shut_locks_both_sides() -> None:
    draft = _walked(keep())
    draft.world.ways[YARD].append(Way(to_id=GATE))

    _ = _meanwhile(draft, _way("shut", GATE, YARD))

    for start, end in ((GATE, YARD), (YARD, GATE)):
        way = draft.world.find_way(start, end)
        assert way is not None
        assert way.locked


def test_a_shut_of_an_unknown_or_locked_way_is_refused() -> None:
    draft = small_world().draft()

    assert "has not found" in _refused_meanwhile(draft, _way("shut", START, VAULT))
    assert "already shut" in _refused_meanwhile(draft, _way("shut", HALL, VAULT))


def test_a_shut_at_the_player_s_place_is_told() -> None:
    draft = _walked(keep())
    draft.world.ways[CELLAR].append(Way(to_id=YARD))

    facts = _meanwhile(draft, _way("shut", CELLAR, YARD))

    assert [fact.card for fact in told_cards(facts)] == ["The way to Yard shuts"]


def test_a_shut_that_leaves_the_player_no_way_out_is_refused() -> None:
    draft = _walked(keep())

    message = _refused_meanwhile(draft, _way("shut", CELLAR, WELL))

    assert "no open way out" in message


def test_an_open_unlocks_both_sides_and_refuses_a_way_that_is_not_locked() -> None:
    draft = small_world().draft()
    back = draft.world.find_way(VAULT, HALL)
    assert back is not None
    back.locked = True

    _ = _meanwhile(draft, _way("open", HALL, VAULT))

    way = draft.world.find_way(HALL, VAULT)
    assert way is not None
    assert not way.locked
    assert not back.locked
    assert "not locked" in _refused_meanwhile(draft, _way("open", START, HALL))


def test_a_fall_kills_the_dweller_and_leaves_what_it_holds_at_its_place() -> None:
    draft = _walked(keep())
    draft.world.items[LANTERN].holder_id = WARDEN

    _ = _meanwhile(draft, _fall(WARDEN))

    assert not draft.world.npcs[WARDEN].alive
    assert draft.world.items[LANTERN].holder_id == GATE


def test_a_fall_at_the_player_s_place_is_refused() -> None:
    message = _refused_meanwhile(keep().draft(), _fall(WARDEN))

    assert "call kill" in message


@pytest.mark.parametrize(("visited", "cap"), [(8, 2), (9, 3), (30, 6)])
def test_the_cap_follows_the_visited_places(visited: int, cap: int) -> None:
    world = keep().world
    room_ids = [f"room-{index}" for index in range(visited)]
    for room_id in room_ids:
        world.places[room_id] = Place(
            id=room_id, name=room_id, brief="b", known=True, description="d"
        )
    world.visited_place_ids = room_ids

    assert world.meanwhile_cap() == cap


def test_a_list_longer_than_the_cap_is_refused() -> None:
    draft = _walked(keep())

    message = _refused_meanwhile(
        draft, _walk(WARDEN, YARD), _carry(LANTERN, GATE), _way("shut", YARD, CELLAR)
    )

    assert "at most 2 changes" in message


def test_a_subject_in_two_changes_of_one_call_is_refused() -> None:
    draft = _walked(keep())

    assert "duplicate" in _refused_meanwhile(draft, _walk(WARDEN, YARD), _fall(WARDEN))
    assert "duplicate" in _refused_meanwhile(
        draft, _way("shut", YARD, CELLAR), _way("open", CELLAR, YARD)
    )


def test_the_party_and_what_it_holds_never_change() -> None:
    draft = keep().draft()
    _ = change(ENGINE, draft, "join_party", target_id=WARDEN)
    lantern = draft.world.items[LANTERN]
    lantern.known = True

    assert "travels with the player" in _refused_meanwhile(draft, _walk(WARDEN, YARD))
    assert "travels with the player" in _refused_meanwhile(draft, _fall(WARDEN))
    for holder_id in (PLAYER_ID, WARDEN):
        lantern.holder_id = holder_id
        _ = _refused_meanwhile(draft, _carry(LANTERN, YARD))
        assert lantern.holder_id == holder_id


def test_meanwhile_refuses_to_walk_an_npc_who_left_the_map() -> None:
    draft = _walked(keep())
    draft.world.npcs[WARDEN].place_id = OFF_MAP_ID

    message = _refused_meanwhile(draft, _walk(WARDEN, YARD))

    assert "has left the map" in message


def test_a_region_with_an_npc_off_the_map_is_refused() -> None:
    world = keep().world
    stray = Goon(
        id="stray",
        name="Stray",
        voice="other",
        brief="Lost",
        known=False,
        place_id=OFF_MAP_ID,
        hp=Gauge(current=4, maximum=4),
    )
    region = RegionProposal[Goon](
        places={"moat": Place(id="moat", name="Moat", brief="b", known=False, description="d")},
        npcs={stray.id: stray},
        start_id="moat",
        region_name="Beyond",
        recap="They left the keep.",
    )

    with pytest.raises(Refusal, match="every npc in a place"):
        check_next(region, world)


def test_the_clock_counts_only_a_turn_that_acted_and_arms_at_the_tempo() -> None:
    draft = _walked(keep())

    ENGINE.after_master_turn(draft, acted=False)
    assert draft.world.turns_since_meanwhile == 0

    for _ in range(MEANWHILE_EVERY):
        ENGINE.after_master_turn(draft, acted=True)

    assert (draft.world.turns_since_meanwhile, draft.world.meanwhile_due) == (0, True)


def test_the_armed_flag_stays_over_counted_turns_and_the_counter_waits() -> None:
    draft = _walked(keep())
    draft.world.meanwhile_due = True

    for _ in range(MEANWHILE_EVERY + 1):
        ENGINE.after_master_turn(draft, acted=True)

    assert (draft.world.turns_since_meanwhile, draft.world.meanwhile_due) == (0, True)


def test_the_clock_arms_only_when_something_offscreen_can_change() -> None:
    for place_ids, lantern_holder_id, armed in (
        ([GATE, YARD], YARD, True),
        ([GATE, YARD], PLAYER_ID, False),
        ([GATE], YARD, False),
    ):
        draft = keep().draft()
        draft.world.regions[0].place_ids = place_ids
        draft.world.items[LANTERN].holder_id = lantern_holder_id

        for _ in range(MEANWHILE_EVERY):
            ENGINE.after_master_turn(draft, acted=True)

        assert draft.world.meanwhile_due == armed


def test_direct_waits_for_meanwhile_and_an_empty_call_clears_the_window() -> None:
    draft = keep().draft()
    draft.world.meanwhile_due = True

    assert refused(ENGINE, draft, "direct", text="On.") == MEANWHILE_FIRST

    assert change(ENGINE, draft, "meanwhile", changes=[]) == []
    assert not draft.world.meanwhile_due
    assert change(ENGINE, draft, "direct", text="On.")[0].told


def test_direct_works_while_a_decision_is_pending() -> None:
    draft = keep().draft()
    draft.world.meanwhile_due = True
    draft.pending = Decision(kind="pick", prompt="Pick.", options=(), allows_text=True)

    assert change(ENGINE, draft, "direct", text="On.")[0].told


def test_a_place_one_way_from_the_player_is_marked_next_to_the_player() -> None:
    world = _walked(keep()).world

    lines = world.elsewhere_lines().splitlines()

    assert lines[0] == "at most 2 changes in one call"
    assert [line.startswith("- Yard[yard] (next to the player) — ") for line in lines[1:]] == [
        False,
        True,
        False,
    ]
    assert "Well[well] (locked) (unfound)" not in lines[2]
    assert "Well[well] (locked)" in lines[2]


def test_the_meanwhile_schema_lists_the_five_changes_in_an_any_of() -> None:
    schema = json.dumps(tool_schema(Meanwhile))

    kinds = json.loads(schema)["properties"]["changes"]["items"]["anyOf"]

    assert [kind["properties"]["kind"]["const"] for kind in kinds] == [
        "walk",
        "carry",
        "shut",
        "open",
        "fall",
    ]
    assert "oneOf" not in schema
    assert "$ref" not in schema


def test_the_arc_reaches_the_master_and_the_worldsmith_and_nobody_else() -> None:
    begun_map = keep()
    arc = "The Warden answers to the Gremlin Queen."
    begun_map.world.arc = arc

    assert arc in str(ENGINE.master_sections(begun_map))
    assert arc in str(ENGINE.worldsmith_sections(begun_map))
    assert arc not in str(ENGINE.narrator_view(begun_map).model_dump())
    assert arc not in str(ENGINE.player_view(begun_map).model_dump())
