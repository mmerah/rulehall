import json
from pathlib import Path
from random import Random

from support.table import TUNNELGOONS, open_table, play_turn, tool_call

from rulehall.core.play import Answer
from rulehall.engines.rooms.engine import MORE_MAP
from rulehall.engines.tunnelgoons.world import GoonSheet, TunnelGoonsGame, level_up_decision

GRIX = "grix"

# A miss against the crawler's DS 6 (brute 1 + 2d6[1,1] = 3): the margin lands on the player.
FIGHT_SEED = 2
MARGIN = 3

REGION = {
    "places": {
        "deep-vault": {
            "id": "deep-vault",
            "name": "Deep Vault",
            "brief": "Past the flooded cellar",
            "known": False,
            "description": "A dry vault the flood never reached.",
        },
        "black-stair": {
            "id": "black-stair",
            "name": "Black Stair",
            "brief": "Down further still",
            "known": False,
            "description": "A stair cut into raw rock, going down.",
        },
    },
    "ways": {"deep-vault": [{"to_id": "black-stair", "known": False}]},
    "npcs": {},
    "items": {
        "old-coin": {
            "id": "old-coin",
            "name": "Old Coin",
            "brief": "Green with age",
            "known": False,
            "holder_id": "deep-vault",
        }
    },
    "start_id": "deep-vault",
    "recap": "They left the corridor behind and pressed on into the flooded cellar.",
}


async def test_the_shipped_map_plays_start_to_finish(tmp_path: Path) -> None:
    table = open_table(
        tmp_path, engine_id=TUNNELGOONS, state_type=TunnelGoonsGame, rng=Random(FIGHT_SEED)
    )

    state = await play_turn(
        table,
        "Down the corridor, into the storeroom, then back to face the thing in the roots.",
        tool_call("move", to_id="corridor"),
        tool_call("move", to_id="storeroom"),
        tool_call("move", to_id="corridor"),
        tool_call(
            "roll",
            what="Fight the crawler",
            ability="brute",
            target_id="crawler",
            dangerous=True,
        ),
    )
    world = state.world
    assert world.current.id == "corridor"
    assert world.npcs["crawler"].alive
    assert world.player.hp.current == world.player.hp.maximum - MARGIN

    state = await play_turn(
        table,
        "Back to the storeroom, force the sealed cell, and rest once it is safe.",
        tool_call("move", to_id="storeroom"),
        tool_call("unlock_way", to_id="sealed-cell"),
        tool_call("move", to_id="sealed-cell"),
        tool_call("rest"),
    )
    world = state.world
    assert world.current.id == "sealed-cell"
    assert world.player.hp.current == world.player.hp.maximum

    state = await play_turn(
        table,
        "Back out and down into the flooded cellar.",
        tool_call("move", to_id="storeroom"),
        tool_call("move", to_id="corridor"),
        tool_call("move", to_id="cellar"),
    )
    assert table.service.player_view().way_on == MORE_MAP

    before_turn = len(state.exchanges())
    table.spawner.answers["worldsmith"] = [json.dumps(REGION)]
    after = await play_turn(table, "Deeper in.", way_on=MORE_MAP.id)

    # The region lands hidden, then the words play as a turn that sees the new way out.
    assert set(REGION["places"]) <= set(after.world.places)
    assert all(not after.world.places[place].known for place in REGION["places"])
    assert [role for role, _ in table.spawner.prompts[-3:]] == ["worldsmith", "master", "narrator"]
    assert "Deep Vault" in table.spawner.prompts[-2][1]
    assert after.exchanges()[before_turn].words == "Deeper in."
    assert table.service.player_view().way_on is None


async def test_a_region_that_cannot_be_written_files_the_players_words(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=TUNNELGOONS, state_type=TunnelGoonsGame)
    _ = await play_turn(
        table,
        "Through every room, down to the flooded cellar.",
        tool_call("move", to_id="corridor"),
        tool_call("move", to_id="storeroom"),
        tool_call("unlock_way", to_id="sealed-cell"),
        tool_call("move", to_id="sealed-cell"),
        tool_call("move", to_id="storeroom"),
        tool_call("move", to_id="corridor"),
        tool_call("move", to_id="cellar"),
    )
    assert table.service.player_view().way_on == MORE_MAP
    before = len(table.state.exchanges())

    await table.service.take_way_on(MORE_MAP.id, "Deeper in.")
    after = table.state

    unwritten = after.exchanges()
    assert len(unwritten) == before + 1
    assert unwritten[-1].words == "Deeper in."
    assert (
        unwritten[-1].facts[0].card == "The map could not be written. You are still where you were."
    )
    assert table.spawner.prompts[-1][0] == "worldsmith"
    assert table.service.player_view().way_on == MORE_MAP


async def test_the_clock_does_not_count_a_turn_the_master_never_played(tmp_path: Path) -> None:
    """A level-up cascade re-suspends without a master, so `Turn.landed()` would over-count it."""
    table = open_table(tmp_path, engine_id=TUNNELGOONS, state_type=TunnelGoonsGame)
    world = table.state.world
    world.npcs[GRIX].sheet = GoonSheet(abilities={"brute": 1, "skulker": 1, "erudite": 1})
    world.party.append(GRIX)
    suspended = table.state.draft()
    suspended.pending = level_up_decision(suspended.world.player)
    table.service.save(suspended.commit())

    state = await play_turn(table, Answer(option_id="brute-health"))

    assert state.exchanges()[-1].facts
    assert state.world.turns_since_meanwhile == 0
    assert "master" not in [role for role, _ in table.spawner.prompts]
