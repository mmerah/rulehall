import json
from pathlib import Path
from random import Random

from support.table import TWENTYFOURXX, open_table, play_turn, tool_call, updated
from support.twentyfourxx import open_crew

from rulehall.core.play import Answer
from rulehall.engines.twentyfourxx.engine import WAY_UNWRITTEN
from rulehall.engines.twentyfourxx.panels import MOVE_ON
from rulehall.engines.twentyfourxx.sheet import STARTING_CREDITS
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
}
LEFT = tool_call("next_scene", pursuit="Deeper into the station.")
DEADLY_FALL = tool_call(
    "roll", what="Slip past", skill="Stealth", risk="a fall", deadly=True, committed=True
)
TAKE_IT = Answer(option_id="take-it")


async def test_the_shipped_scenario_plays_several_turns(tmp_path: Path) -> None:
    table = open_table(
        tmp_path, engine_id=TWENTYFOURXX, state_type=TwentyFourXXGame, rng=Random(SETBACK_SEED)
    )

    state = await play_turn(
        table,
        "Slip past the dockhand before she clocks the override key.",
        tool_call(
            "roll",
            what="Slip past the dockhand",
            skill="Stealth",
            risk="a fall",
            deadly=True,
            committed=True,
        ),
    )
    state = await play_turn(table, TAKE_IT)
    world = state.world
    assert world.player.alive
    assert world.player.require_sheet().hindrances == ["Maimed"]

    state = await play_turn(
        table, "Ask what else this shift wants of Kael.", tool_call("next_scene")
    )

    before = len(state.exchanges())
    table.spawner.answers["worldsmith"] = [json.dumps(NEXT_SCENE)]
    pursuit = "Deeper into the station, past the dark corridor."
    state = await play_turn(
        table,
        pursuit,
        tool_call("next_scene", pursuit=pursuit),
        composer=MOVE_ON,
        arrival="The docking ring falls away, and stacked containers rise up around you.",
    )

    assert state.world.scene.title == "The Cargo Bay"
    assert state.exchanges()[before].words == pursuit
    assert table.saved() == table.state


async def test_a_hired_member_survives_a_save_and_succeeds_the_dead_lead(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=TWENTYFOURXX, state_type=TwentyFourXXGame)
    member_id = "vessa-rune"
    sheet = {"specialty": "Face", "origin": "Alien", "traits": ["Wings", "Six-limbed"]}

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
        DEADLY_FALL,
    )
    state = await play_turn(table, TAKE_IT)
    assert not state.world.player.alive
    assert state.pending is not None
    assert state.pending.kind == "succession"
    assert [option.id for option in state.pending.options] == [member_id]
    assert table.service.engine.ending(state) is None

    state = await play_turn(table, Answer(option_id=member_id))

    world = state.world
    assert world.player.name == "Vessa Rune"
    assert world.player.sheet is not None
    assert world.player.sheet.specialty == "Face"
    assert world.player.sheet.skills == {"Reading People": 8, "Deception": 8}
    assert not world.cast["kael"].alive
    assert "kael" in world.scene.here
    assert member_id not in world.party
    assert table.saved() == table.state


async def test_next_scene_asks_the_player_and_writes_nothing_yet(tmp_path: Path) -> None:
    table = open_crew(tmp_path)

    state = await play_turn(
        table,
        "I have what I came for.",
        tool_call("next_scene"),
        narration="The airlock cycles shut behind you.",
    )

    assert len(state.exchanges()) == 1
    # An offer, not a decision: nothing waits on the player and the scene is still playable.
    assert state.pending is None
    assert not any(role == "worldsmith" for role, _ in table.spawner.prompts)


async def test_a_departure_crosses_after_the_leaving_turn_and_keeps_the_notes(
    tmp_path: Path,
) -> None:
    """One adjudication: the master played the leaving, so the crossing needs no second turn."""
    table = open_crew(tmp_path)
    table.spawner.answers["worldsmith"] = [json.dumps(NEXT_SCENE)]
    table.service.save(updated(table.state, notes=["the adventure's end applies"]))

    state = await play_turn(table, "I go.", LEFT, arrival="The corridor lights stutter on.")

    assert [role for role, _ in table.spawner.prompts] == [
        "master",
        "narrator",
        "worldsmith",
        "narrator",
    ]
    assert state.notes == []
    assert state.log[-2].exchanges[-1].words == "I go."
    assert state.world.scene.title == "The Cargo Bay"


async def test_a_scene_the_world_has_outgrown_is_dropped(tmp_path: Path) -> None:
    """The bar sees the turn's own changes: a scene hiding someone met this turn is refused."""
    table = open_crew(tmp_path)
    outgrown = json.dumps(NEXT_SCENE | {"hidden": ["warden-six"]})
    table.spawner.answers["worldsmith"] = [outgrown, outgrown]

    state = await play_turn(table, "I go.", tool_call("enter", target_id="warden-six"), LEFT)

    unwritten = state.exchanges()[-1]
    assert unwritten.cause == "story"
    assert unwritten.facts[0] == WAY_UNWRITTEN
    assert state.world.scene.title == "The Docking Ring"
    assert state.request is None


async def test_a_worldsmith_that_fails_leaves_the_scene_unchanged_and_says_why(
    tmp_path: Path,
) -> None:
    table = open_crew(tmp_path)

    state = await play_turn(table, "I go.", LEFT)

    assert state.exchanges()[-1].facts[0] == WAY_UNWRITTEN
    assert table.service.state.world.scene.title == "The Docking Ring"


async def test_a_lone_death_brings_in_a_newcomer_who_leads_here(tmp_path: Path) -> None:
    table = open_crew(tmp_path, rng=Random(DISASTER_SEED))
    _ = await play_turn(table, "I slip past.", DEADLY_FALL)
    state = await play_turn(table, TAKE_IT)
    assert state.pending is not None
    assert state.pending.kind == "newcomer"
    table.spawner.turns.clear()  # the death re-suspended play, so no master ran that turn

    state = await play_turn(table, "Juno joins.", tool_call("bring_in", who="Juno, a pilot"))
    assert state.pending is not None
    assert state.pending.kind == "newcomer"

    newcomer = {
        "name": "Juno",
        "brief": "A pilot who owes the dead a favour",
        "sheet": {
            "specialty": "Tech",
            "origin": "Android",
            "body": "Case",
            "increases": ["Electronics"],
        },
    }
    table.spawner.answers["worldsmith"] = [json.dumps(newcomer)]
    state = await play_turn(
        table, "Juno, a pilot, joins us.", tool_call("bring_in", who="Juno, a pilot")
    )

    assert state.world.player.name == "Juno"
    assert state.world.player.alive
    sheet = state.world.player.require_sheet()
    assert sheet.credits == 2 * STARTING_CREDITS  # the dead lead's credits pass on
    assert sheet.skills == {"Hacking": 8, "Electronics": 10}
    assert [item.name for item in sheet.items.values()] == [
        "Comm",
        "Repair tools",
        "Custom computer",
        "Case",
    ]
    assert state.pending is None
    worldsmith_prompts = [text for role, text in table.spawner.prompts if role == "worldsmith"]
    assert "They join in THE SCENE NOW" in worldsmith_prompts[-1]
    here = f"Juno leads now and is here, in {state.world.scene.title}"
    assert any(note.startswith(here) for note in state.notes)
