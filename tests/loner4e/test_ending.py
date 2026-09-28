import json
from pathlib import Path
from random import Random

import pytest
from support.game import ENGINE, character, initialized, open_game, scenario
from support.table import (
    Table,
    change,
    narrated,
    offline_settings,
    play_turn,
    refused,
    run_action,
    tool_call,
    updated,
)

from rulehall.core.decisions import PlayerInput
from rulehall.core.stores import Library
from rulehall.core.validation import Refusal
from rulehall.engines.loner4e.panels import END_HERE
from rulehall.engines.loner4e.sheet import Loner4eEntity
from rulehall.engines.loner4e.world import Loner4eGame
from rulehall.engines.sheet import PLAYER_ID

NEXT_SCENE: dict[str, object] = {
    "place_id": "cloister",
    "title": "The Cloister",
    "situation": "A frost-rimed colonnade around a dead garden, unswept for a long while.",
    "recap": "He left the study.",
    "goal": "Find the stair down",
    "details": ["Frost-Rimed Colonnade"],
}
LIVING_WORLD = {
    "people": [{"entity_id": "mara", "line": "trusts him now."}],
    "places": ["The study stands empty."],
    "events": ["The vault stays sealed."],
}
ENDED = tool_call("end_adventure", why="The vault is found.")
DIRECTED = tool_call("direct", text="It ends here.")


async def _proposed_and_ended(table: Table[Loner4eGame]) -> None:
    _ = await play_turn(table, "I have it.", ENDED)
    await table.session.play(PlayerInput(option_id="end-it"))


async def test_close_scene_and_end_adventure_leave_only_the_ending_and_play_on_hands_over(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path, rng=Random(1))

    closed = tool_call("close_scene", reason="resolved")
    ending = await play_turn(table, "I have it.", closed, ENDED)

    assert ending.pending is not None
    assert (ending.pending.kind, ending.world.frame.next) == ("ending", "dramatic")
    table.roles.answers["worldsmith"] = [json.dumps(NEXT_SCENE)]
    state = await play_turn(table, PlayerInput(option_id="play-on"), DIRECTED, arrival="Frost.")
    assert (state.world.end_why, state.world.frame.goal) == ("", "Find the stair down")


async def test_a_typed_word_cannot_end_the_adventure(tmp_path: Path) -> None:
    table = open_game(tmp_path, rng=Random(1))
    _ = await play_turn(table, "I have it.", ENDED)

    with pytest.raises(Refusal, match="takes one of its options"):
        await table.session.play(PlayerInput(text="Yes, end it: patience."))

    assert table.state.pending is not None
    assert (table.state.pending.kind, table.state.world.end_why) == ("ending", "")


async def test_the_player_ends_the_adventure_from_the_sheet_and_is_asked_the_growth_once(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path, rng=Random(1))

    await table.session.use_panel_option(END_HERE)

    assert table.state.pending is not None
    assert (table.state.pending.kind, table.state.pending.prompt) == (
        "growth",
        "What did Kael learn?",
    )
    table.roles.answers["worldsmith"] = [json.dumps(LIVING_WORLD)]
    _ = await play_turn(table, "Yes: patience.", DIRECTED, then=[narrated("The end.")])
    assert ENGINE.ending(table.state) == "The adventure is over."


async def test_the_confirmed_end_grows_the_sheet_writes_the_living_world_and_writes_it_back(
    tmp_path: Path,
) -> None:
    settings = offline_settings(tmp_path)
    settings = settings.model_copy(update={"characters_dir": tmp_path / "characters"})
    mira = updated(character(), id="mira", person=updated(character().person, name="Mira"))
    Library(settings.scenarios_dir, settings.characters_dir).write_character(mira)
    table = open_game(tmp_path, rng=Random(1), settings=settings, character_id="mira")
    await _proposed_and_ended(table)
    table.roles.answers["worldsmith"] = [json.dumps(LIVING_WORLD)]

    grown = tool_call("change_tags", actor_id="player", kind="skill", gained=["Patient Watcher"])
    state = await play_turn(table, "Yes: patience.", grown, DIRECTED, then=[narrated("The end.")])

    assert ENGINE.ending(state) == "The adventure is over."
    card = state.log_entries()[-1].facts[0].card
    assert card.startswith("The Living World\nMara: trusts him now.")
    written = table.runtime.library.read_character("mira", ENGINE.id, ENGINE.character_model)
    assert written == table.session.character
    assert isinstance(written.person, Loner4eEntity)
    assert "Patient Watcher" in written.person.tagged("skill")
    assert written.person.living_world == [
        "Mara: trusts him now.",
        "The study stands empty.",
        "The vault stays sealed.",
    ]


def test_a_new_game_gives_the_worldsmith_what_the_protagonist_carries_forward() -> None:
    carried = updated(character().person, living_world=["Mara trusts him now."])
    state = ENGINE.begin("whispering-vault", scenario(), updated(character(), person=carried))

    sections = dict(ENGINE.worldsmith_sections(state))

    assert sections["WHAT THE PROTAGONIST CARRIES FORWARD"] == "- Mara trusts him now."


async def test_a_failed_living_world_is_retried_from_its_option_with_no_master_turn(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path, rng=Random(1))
    await _proposed_and_ended(table)

    failed = await play_turn(table, "Yes: patience.", DIRECTED)

    assert failed.pending is not None
    assert (failed.pending.kind, failed.world.ended) == ("living-world", False)
    masters = sum(role == "master" for role, _ in table.roles.prompts)
    table.roles.answers["worldsmith"] = [json.dumps(LIVING_WORLD)]
    table.roles.answers["narrator"] = [narrated("The end.")]
    await table.session.play(PlayerInput(option_id="living-world"))
    assert ENGINE.ending(table.state) == "The adventure is over."
    assert sum(role == "master" for role, _ in table.roles.prompts) == masters


def test_the_oracle_asks_nothing_while_the_end_waits_so_no_decision_opens() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.world.end_why = "The vault is found."

    assert "adventure is ending" in refused(ENGINE, draft, "ask", question="Do I win?")


async def test_a_living_world_that_fails_twice_still_waits_on_its_write(tmp_path: Path) -> None:
    table = open_game(tmp_path, rng=Random(1))
    await _proposed_and_ended(table)
    _ = await play_turn(table, "Yes: patience.", DIRECTED)

    await table.session.play(PlayerInput(option_id="living-world"))

    assert table.state.pending is not None
    assert table.state.pending.kind == "living-world"
    assert table.session.player_view().composer_option is None


def test_no_scene_closes_while_the_end_waits_and_an_ended_game_offers_no_option() -> None:
    _, state = initialized()
    draft = state.draft()
    draft.world.end_why = "The vault is found."

    assert "adventure is ending" in refused(ENGINE, draft, "close_scene", reason="resolved")
    draft.world.ended = True
    draft.world.frame.next = "quiet"
    assert ENGINE.composer(draft) == (None, False)


def test_the_growth_after_a_closed_scene_writes_a_nemesis_and_rewords_the_concept() -> None:
    _, state = initialized()
    draft = state.draft()
    _ = change(ENGINE, draft, "close_scene", reason="blocked")
    reworded = {"actor_id": PLAYER_ID, "concept": "A scribe who stopped counting"}
    assert "only in the growth" in refused(ENGINE, draft, "drive", **reworded)

    _ = run_action(ENGINE, draft, "confirm_end")
    _ = change(ENGINE, draft, "drive", actor_id=PLAYER_ID, nemesis="The Order")
    _ = change(ENGINE, draft, "drive", **reworded)

    player = draft.world.player
    assert (player.nemesis, player.concept) == ("The Order", "A scribe who stopped counting")
