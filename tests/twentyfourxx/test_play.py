import json
from pathlib import Path
from random import Random

from support.table import TWENTYFOURXX, open_table, play_turn, the_way_on, tool_call

from rulehall.core.play import Answer
from rulehall.engines.scenes.engine import MOVE_ON
from rulehall.engines.twentyfourxx.world import TwentyFourXXGame

# A setback (not a disaster or a success): the roll injures the player without killing them.
SETBACK_SEED = 1
# A disaster: the lead dies and, with a hired member alive, succession opens instead of ending.
DISASTER_SEED = 2

NEXT_SCENE = {
    "place_id": "cargo-bay",
    "title": "The Cargo Bay",
    "situation": "Stacked containers throw long shadows as the station's power hums back on.",
    "recap": "Kael slipped past Vessa's watch at the airlock, favouring a bruised leg.",
    "ship_here": True,
}


async def test_the_shipped_scenario_plays_several_turns(tmp_path: Path) -> None:
    table = open_table(
        tmp_path, engine_id=TWENTYFOURXX, state_type=TwentyFourXXGame, rng=Random(SETBACK_SEED)
    )

    state = await play_turn(
        table,
        "Slip past the dockhand before she clocks the override key.",
        tool_call(
            "roll", what="Slip past the dockhand", skill="Stealth", risk="a fall", deadly=True
        ),
    )
    world = state.world
    assert world.player.alive
    assert world.player.require_sheet().hindrances == ["Maimed — a fall"]

    state = await play_turn(table, "Ask what else this shift wants of Kael.", the_way_on())
    assert state.world.scene.way_offered

    before = len(state.exchanges())
    table.spawner.answers["worldsmith"] = [json.dumps(NEXT_SCENE)]
    pursuit = "Deeper into the station, past the dark corridor."
    state = await play_turn(
        table,
        pursuit,
        tool_call("next_scene", pursuit=pursuit),
        way_on=MOVE_ON.id,
        arrival="The docking ring falls away, and stacked containers rise up around you.",
    )

    assert state.world.scene.title == "The Cargo Bay"
    assert state.exchanges()[before].words == pursuit
    assert table.saved() == table.state


async def test_a_hired_member_survives_a_save_and_succeeds_the_dead_lead(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=TWENTYFOURXX, state_type=TwentyFourXXGame)
    member_id = "vessa-rune"
    sheet = {
        "specialty": "Face",
        "skills": {"Deception": 8},
        "items": ["Override key"],
    }

    table.spawner.answers["worldsmith"] = [json.dumps(sheet)]
    state = await play_turn(
        table,
        "Hire Vessa to keep the corridor guards talking.",
        tool_call("join_party", target_id=member_id, terms="Keep the corridor guards talking"),
        narration="Vessa pockets the terms and falls in step behind Kael.",
    )
    world = state.world
    member = world.cast[member_id]
    assert member.id in world.party
    assert member.sheet is not None
    assert member.sheet.specialty == "Face"

    reloaded = table.saved()
    hired = reloaded.world.cast[member_id]
    assert member_id in reloaded.world.party
    assert hired.sheet == member.sheet

    table.service.rng = Random(DISASTER_SEED)
    state = await play_turn(
        table,
        "Slip past the dockhand before she clocks the override key.",
        tool_call("roll", what="Slip past", skill="Stealth", risk="a fall", deadly=True),
    )
    assert not state.world.player.alive
    assert state.pending is not None
    assert state.pending.kind == "succession"
    assert [option.id for option in state.pending.options] == [member_id]
    assert table.service.engine.ending(state) is None

    state = await play_turn(table, Answer(option_id=member_id))

    world = state.world
    assert world.player.id == member_id
    assert world.player.sheet is not None
    assert world.player.sheet.specialty == "Face"
    assert world.player.sheet.skills == {"Deception": 8}
    assert "player" in world.cast
    assert not world.cast["player"].alive
    assert "player" in world.scene.here
    assert member_id not in world.party
    assert table.saved() == table.state
