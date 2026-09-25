import json
import re
from asyncio import Event, create_task, sleep
from pathlib import Path

import pytest
from support.game import TARGET, open_game, session, with_entity
from support.table import (
    POKEMON,
    TWENTYFOURXX,
    ScriptedSpawner,
    narrated,
    offline_settings,
    open_table,
    play_turn,
    scenario_for,
    tool_call,
    updated,
)

from rulehall.app.launch import LaunchTarget
from rulehall.app.runtime import Runtime
from rulehall.app.session import IN_FLIGHT_ELSEWHERE, NOTHING_TO_REWIND
from rulehall.config import Role
from rulehall.core.facts import Fact
from rulehall.core.io import FileStore
from rulehall.core.model import AnyGame, ScenarioMeta, WorldsmithRequest
from rulehall.core.play import Answer
from rulehall.core.validation import Refusal
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner3e.world import Loner3eEntity
from rulehall.engines.pokemon.world import PokemonGame


class _UnsavableStore(FileStore):
    """Overrides `save` alone: `FileStore` is frozen and slotted, so this cannot monkeypatch it."""

    def write(self, _slug: str, _state: AnyGame, /) -> None:
        raise OSError("disk is gone")


async def test_opening_does_not_save_and_restart_discards_durable_state(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    game = session(tmp_path)
    assert store.slugs() == ()

    store.write(TARGET.slug, game.state.model_copy(update={"notes": ["kept"]}).commit())
    assert session(tmp_path).state.notes == ["kept"]

    game = session(tmp_path)
    await game.restart()
    assert game.state.notes == []
    assert store.read(TARGET.slug) is None


def test_the_player_view_is_built_once_per_saved_state(tmp_path: Path) -> None:
    game = session(tmp_path)
    view = game.player_view()
    assert game.player_view() is view

    game.save(game.state.model_copy(update={"notes": ["kept"]}))
    assert game.player_view() is not view


async def test_rewind_restores_the_state_before_the_last_turn_and_the_saved_file(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    before = table.state

    state = await play_turn(table, "I wait.", narration="Nothing stirs.")
    assert state != before

    words = await table.service.rewind()

    assert words == "I wait."
    assert table.state == before
    assert table.saved() == before


async def test_a_second_rewind_right_after_the_first_finds_nothing_to_rewind(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    _ = await play_turn(table, "I wait.", narration="Nothing stirs.")
    _ = await table.service.rewind()

    with pytest.raises(Refusal, match=re.escape(NOTHING_TO_REWIND)):
        await table.service.rewind()


async def test_a_refused_input_leaves_the_rewind_on_the_turn_it_already_held(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    before = table.state
    played = await play_turn(table, "I wait.", narration="Nothing stirs.")

    with pytest.raises(Refusal):
        await table.service.play(Answer(option_id="no-such-option"))
    assert table.state == played

    assert await table.service.rewind() == "I wait."
    assert table.state == before


async def test_rewind_before_any_turn_finds_nothing_to_rewind(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    with pytest.raises(Refusal, match=re.escape(NOTHING_TO_REWIND)):
        await table.service.rewind()


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"character_id": "someone-else"}, "save is 'whispering-vault--someone-else'"),
        (
            {
                "scenario": ScenarioMeta(
                    title="Another Vault",
                    premise="Elsewhere.",
                    backdrop="Plain.",
                    scope="A single visit, brief.",
                )
            },
            "title",
        ),
    ),
    ids=("another origin", "a scenario edited since the save"),
)
def test_resume_refuses_a_save_that_is_not_this_game(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    game = session(tmp_path)
    FileStore(tmp_path).write(TARGET.slug, game.state.model_copy(update=change).commit())

    with pytest.raises(Refusal, match=message):
        session(tmp_path)


def test_one_open_game_per_slug(tmp_path: Path) -> None:
    runtime = Runtime(updated(offline_settings(), saves_dir=tmp_path), spawner=ScriptedSpawner())
    opened = runtime.session(TARGET)

    assert runtime.session(TARGET) is opened


async def test_the_opening_is_narrated_once_and_costs_a_turn(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    table.spawner.answers["narrator"] = [narrated("The abbot's study holds its breath.")]

    await table.service.open()

    history = table.service.state.exchanges()
    assert [exchange.cause for exchange in history] == ["opening"]
    assert len(history) == 1

    await table.service.open()
    assert len(table.service.state.exchanges()) == 1


async def test_a_failed_commit_still_frees_the_game(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    table.service.store = _UnsavableStore(table.service.store.directory)

    with pytest.raises(OSError):
        _ = await play_turn(table, "I take the map.")

    assert (table.service.working_role, table.service.turn) == (None, None)


def _scene(**changes: object) -> str:
    scene = {
        "place_id": "abbots-study",
        "title": "The Abbot's Study, Disturbed",
        "situation": "A second crew has forced the outer door, and torchlight swings wild across "
        "the ledgers while Mara flattens herself against the shelves.",
        "present": ["mara"],
        "hidden": [],
        "recap": "The player was keeping watch on the study door when a second crew broke in.",
        "arc": "",
    }
    return json.dumps(scene | changes)


async def test_a_complication_writes_and_installs_at_the_same_place(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    place = table.state.world.scene.place_id
    here_before = list(table.state.world.scene.here)
    table.spawner.answers["worldsmith"] = [_scene()]

    state = await play_turn(
        table,
        "I keep watch on the study door.",
        tool_call("next_scene", complication="A second crew breaches the study door."),
        arrival="Torchlight swings wild across the ledgers.",
    )

    exchanges = state.exchanges()
    assert len(exchanges) == 2
    assert exchanges[0].words == "I keep watch on the study door."
    assert exchanges[1].cause == "story"
    assert state.world.scene.place_id == place
    assert all(entity_id in state.world.cast for entity_id in here_before)
    assert [role for role, _ in table.spawner.prompts] == ["master", "worldsmith", "narrator"]
    assert state.request is None


async def test_a_failed_write_after_a_complication_leaves_the_turn_committed(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    title = table.state.world.scene.title

    state = await play_turn(
        table,
        "I keep watch on the study door.",
        tool_call("next_scene", complication="A second crew breaches the study door."),
    )

    exchange = state.exchanges()[-1]
    assert exchange.cause == "story"
    assert exchange.facts[0].card == (
        "Nothing new came down on this place after all. You are still where you were."
    )
    assert state.request is None
    assert state.world.scene.title == title


async def test_no_generation_runs_once_the_game_is_over(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    table.spawner.answers["worldsmith"] = [_scene()]

    state = await play_turn(
        table,
        "I keep watch, whatever comes.",
        tool_call("kill", target_id=PLAYER_ID),
        tool_call("next_scene", complication="A second crew breaches the study door."),
    )

    assert table.service.engine.ending(state) is not None
    assert not any(role == "worldsmith" for role, _ in table.spawner.prompts)
    assert len(state.world.scenes) == 1
    assert state.request is None
    assert table.saved().request is None


def test_a_save_never_carries_a_request(tmp_path: Path) -> None:
    game = session(tmp_path)
    draft = game.state.draft()
    draft.request = WorldsmithRequest(kind="complication", detail="A crew breaks in.")
    FileStore(tmp_path).write(TARGET.slug, draft)

    assert "request" not in json.loads(FileStore(tmp_path).read(TARGET.slug) or "")


async def test_two_concurrent_plays_on_different_sessions_cannot_both_open_a_turn(
    tmp_path: Path,
) -> None:
    spawner = ScriptedSpawner()
    gate = Event()

    async def hold_master(role: Role, prompt: str) -> None:
        del prompt
        if role == "master":
            await gate.wait()

    spawner.hooks.append(hold_master)
    runtime = Runtime(updated(offline_settings(), saves_dir=tmp_path), spawner=spawner)
    first = runtime.session(TARGET)
    second = runtime.session(
        LaunchTarget(scenario_id=scenario_for(TWENTYFOURXX), character_id="kael")
    )
    spawner.turns.append(lambda: None)
    spawner.answers["narrator"] = [narrated("You wait.")]

    first_play = create_task(first.play(Answer(text="I wait.")))
    await sleep(0)

    with pytest.raises(Refusal, match=re.escape(IN_FLIGHT_ELSEWHERE)):
        await second.play(Answer(text="I wait."))
    assert runtime.gate.status()["busy"]

    gate.set()
    await first_play

    assert len(first.state.exchanges()) == 1
    assert runtime.gate.status()["busy"] is False


async def test_a_team_page_option_applies_at_once_with_no_turn(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame)
    draft = table.state.draft()
    draft.world.player.require_sheet().add("oran-berry", 1)
    table.service.save(draft.commit())
    panels = table.service.player_view().panels
    option = next(
        option
        for panel in panels
        for row in panel.rows
        for option in row.options
        if option.args == {"mon_id": "charmander", "item_id": "oran-berry"}
    )

    await table.service.use_panel_option(option)

    sheet = table.state.world.player.require_sheet()
    assert sheet.require_mon("charmander").item_id == "oran-berry"
    assert "oran-berry" not in sheet.bag
    assert table.state.exchanges()[-1].words == option.name
    assert table.spawner.prompts == []


async def test_a_team_page_option_that_opens_a_decision_records_it(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame)
    draft = table.state.draft()
    charmander = draft.world.player.require_sheet().require_mon("charmander")
    charmander.level = 12
    charmander.exp = 12**3
    charmander.learn("smokescreen")
    table.service.save(draft.commit())
    panels = table.service.player_view().panels
    option = next(
        option
        for panel in panels
        for row in panel.rows
        for option in row.options
        if option.args == {"mon_id": "charmander", "move_id": "dragonbreath"}
    )

    await table.service.use_panel_option(option)

    pending = table.state.pending
    assert pending is not None
    assert pending.kind == "new-move"
    assert table.state.exchanges()[-1].decision == pending.prompt


async def test_an_option_with_a_refusal_is_shown_but_never_runs(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame)
    panels = table.service.player_view().panels
    option = next(
        option
        for panel in panels
        for row in panel.rows
        for option in row.options
        if option.args == {"mon_id": "charmander", "item_id": "potion"}
    )
    assert option.refusal

    with pytest.raises(Refusal):
        await table.service.use_panel_option(option)
    assert table.state.exchanges() == ()


async def test_the_debrief_prompt_holds_no_hidden_entity_and_no_untold_fact(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    hidden = Loner3eEntity(id="the-lurker", name="The Lurker", brief="It waits.", known=False)
    draft = with_entity(table.state, hidden).draft()
    facts = (Fact(trace="The door creaks.", told=True), Fact(trace="A trap arms below."))
    table.service.save(table.service.engine.record(draft, (), facts, words="I open the door."))
    table.spawner.answers["narrator"] = [
        json.dumps(
            {
                "story_so_far": "You came to the vault.",
                "current_aim": "Find the relic.",
                "open_threads": ["You could search the hall."],
                "last_beats": ["The door creaks."],
            }
        )
    ]

    debrief = await table.service.debrief()

    prompt = table.spawner.prompt("narrator")
    assert "The door creaks." in prompt
    assert "The Lurker" not in prompt
    assert "A trap arms below." not in prompt
    assert debrief.current_aim == "Find the relic."
