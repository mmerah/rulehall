import json
from collections.abc import Callable
from pathlib import Path
from random import Random

import pytest
from support.game import initialized, loner_sheet, open_game
from support.table import Table, narrated, play_turn, tool_call

from rulehall.app.roles import UNSETTLED
from rulehall.app.turn import DIRECTED_WAIT, REQUEST_WAIT, Turn
from rulehall.core.facts import NOTHING, Fact, cards
from rulehall.core.model import AnyGame
from rulehall.core.play import Answer
from rulehall.core.validation import Refusal
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner3e.rules import outcome_for
from rulehall.engines.loner3e.world import Loner3eGame
from rulehall.engines.scenes.engine import WAY_UNWRITTEN

MAP = "vault-map"
FOUND = tool_call("reveal", target_id="vault-map")
TAKEN = tool_call("change_tags", actor_id=PLAYER_ID, kind="gear", gained=["the vault map"])
ASKED = tool_call("roll", what="Try the door", actor_id=PLAYER_ID, question="Does the door give?")
DIRECTION = "the cold off the stone reaches him and the quiet begins to press"
DIRECTED = tool_call("direct", text=DIRECTION)


def _scene(**changes: object) -> str:
    scene = {
        "place_id": "cloister-walk",
        "title": "The Cloister Walk",
        "situation": (
            "Rain drums the open arcade and the flagstones run black with it, and Mara waits "
            "at the far end with the lantern shuttered to a slit."
        ),
        "present": ["mara"],
        "hidden": [],
        "recap": "The player left the abbot's study behind, lantern shuttered, and made for the "
        "cloister walk with Mara close behind them.",
        "arc": "Farther in, the chapter house still holds what Mara came for, and has not yet "
        "been found.",
    }
    return json.dumps(scene | changes)


async def test_a_turn_runs_the_master_then_the_narrator_on_a_safe_prompt(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(
        table,
        "I search beneath the desk.",
        FOUND,
        TAKEN,
        narration="A creased chart slides into your hand.",
    )

    assert [role for role, _ in table.spawner.prompts] == ["master", "narrator"]
    assert "the vault map" in state.world.player.tagged("gear")
    narrator = table.spawner.prompt("narrator")
    assert "Elena" not in narrator
    # The sheets are the game master's: no tag the engine rolls by reaches the narrator.
    assert "concept" not in narrator
    assert len(state.exchanges()) == 1
    assert state.exchanges()[-1].words == "I search beneath the desk."


async def test_the_turn_holds_its_facts_in_resolver_order(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(
        table,
        "I take the map and listen.",
        FOUND,
        TAKEN,
        tool_call("change_tags", actor_id="player", kind="condition", gained=["Listening"]),
    )

    expected = ["The vault map discovered", "Took the vault map", "Now: Listening"]
    exchange = state.exchanges()[-1]
    assert [fact.card for fact in cards(table.facts)] == expected
    assert [fact.card for fact in cards(exchange.facts)] == expected
    assert len(exchange.facts) >= len(cards(exchange.facts))


async def test_the_exchange_keeps_each_refused_call_where_it_happened(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(
        table, "I search beneath the desk.", tool_call("reveal", target_id="nowhere"), FOUND
    )

    (refused,) = state.exchanges()[-1].refused
    assert (refused.tool, refused.after_facts) == ("reveal", 0)
    assert refused.reason == table.refusals[0]


async def test_a_narrator_failure_still_commits_the_turn_with_no_prose(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    table.spawner.turns.append(table.plays((FOUND, TAKEN)))

    await table.service.play(Answer(text="I take the map."))

    exchange = table.service.state.exchanges()[-1]
    assert exchange.lines == ()
    assert "the vault map" in table.service.state.world.player.tagged("gear")


async def test_a_narrator_failure_with_nothing_landed_refuses_and_keeps_the_words(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    table.spawner.turns.append(table.plays(()))
    before = len(table.service.state.exchanges())

    with pytest.raises(Refusal, match="narrator"):
        await table.service.play(Answer(text="I take the map."))

    assert len(table.service.state.exchanges()) == before


async def test_the_engine_rolls_the_outcome_the_facts_then_record(tmp_path: Path) -> None:
    table = open_game(tmp_path, rng=Random(2))

    state = await play_turn(
        table,
        "I plead with the door.",
        tool_call(
            "roll",
            what="Try the door",
            actor_id="player",
            question="Does the door give before the whispering finds him?",
        ),
        narration="You falter.",
    )

    fired = table.facts
    answer = next(fact for fact in fired if fact.dice)
    chance, risk = answer.dice
    rolled = [fact.trace for fact in fired[:2]]
    for die, trace in zip(answer.dice, rolled, strict=True):
        assert trace.endswith(f"[{', '.join(str(v) for v in die.rolled)}]")
    assert answer.card.endswith(f": {outcome_for(max(chance.rolled), max(risk.rolled)).wording}")
    table.service.engine.validate(state)
    assert not any(fact.told for fact in fired[:2])


async def test_an_illegal_tool_call_is_refused_with_the_reason(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(table, "I wait.", tool_call("reveal", target_id="nowhere"), FOUND)

    assert state.world.require(MAP).known
    assert any("unknown id 'nowhere'" in refusal for refusal in table.refusals)


async def test_a_later_call_in_one_turn_sees_the_earlier_calls_draft(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)

    state = await play_turn(
        table, "I close the book.", tool_call("next_scene"), tool_call("next_scene")
    )

    assert state.world.scene.way_offered
    assert any("already offers" in refusal for refusal in table.refusals)


async def test_a_call_after_the_ask_answers_handoff_wait_and_changes_nothing(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    complication = "A second crew breaches the study door."

    state = await play_turn(
        table, "I keep watch.", tool_call("next_scene", complication=complication), FOUND
    )

    assert table.answers[1] == REQUEST_WAIT
    assert not state.world.require(MAP).known


async def test_a_line_spoken_by_someone_not_here_is_re_prompted_with_the_id(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    table.spawner.answers["narrator"] = [
        narrated("You should not be here.", "elena"),
        narrated("The door settles."),
    ]
    table.spawner.turns.append(table.plays(()))

    await table.service.play(Answer(text="I wait."))

    assert any("elena" in prompt for role, prompt in table.spawner.prompts if role == "narrator")
    newest = table.service.state.exchanges()[-1]
    assert [line.text for line in newest.lines] == ["The door settles."]


def _exploding_after_the_find(table: Table[Loner3eGame]) -> Callable[[], None]:
    def crash() -> None:
        _ = table.call(*FOUND)
        raise Refusal("the game master exploded")

    return crash


def _never_started() -> None:
    raise Refusal("the game master never started")


async def test_a_master_that_crashes_after_applying_still_commits_what_it_applied(
    tmp_path: Path,
) -> None:
    """The exit is the only end signal: what it legally applied is the turn."""
    table = open_game(tmp_path)
    table.spawner.turns.append(_exploding_after_the_find(table))
    table.spawner.answers["narrator"] = [narrated("The map is in hand.")]

    await table.service.play(Answer(text="I take the map and read it."))

    assert len(table.service.state.exchanges()) == 1
    assert table.service.state.world.require(MAP).known


async def test_a_master_that_crashed_after_a_tool_landed_is_not_spawned_again(
    tmp_path: Path,
) -> None:
    """A second spawn would replay the prompt and apply the same mutation twice."""
    table = open_game(tmp_path)
    _ = await play_turn(table, "I look around.")
    table.spawner.turns.append(_exploding_after_the_find(table))
    table.spawner.answers["narrator"] = [narrated("The map is in hand.")]
    spawned = len(table.spawner.prompts)

    await table.service.play(Answer(text="I take the map."))

    assert [role for role, _ in table.spawner.prompts[spawned:]].count("master") == 1


async def test_a_turn_that_applied_nothing_and_failed_is_refused(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    before = table.service.state.model_dump_json()
    table.spawner.turns += [_never_started, _never_started]

    with pytest.raises(Refusal, match="never started"):
        await table.service.play(Answer(text="I take the map."))

    assert table.service.state.model_dump_json() == before


async def test_two_rolls_in_one_turn_do_not_read_the_same_dice(tmp_path: Path) -> None:
    table = open_game(tmp_path, rng=Random(1))

    _ = await play_turn(table, "I try the door twice.", ASKED, ASKED)

    first, second = (fact.dice for fact in table.facts if len(fact.dice) == 2)
    assert first != second


def test_a_refused_call_leaves_the_turn_the_dice_it_had() -> None:
    engine, state = initialized()
    turn = Turn.begin(engine, state, Answer(text="I try the door."), Random(1))
    before = turn.rng.getstate()

    with pytest.raises(ValueError, match="the rules said no"):
        _ = turn.apply(_rolls_then_refuses)

    assert turn.rng.getstate() == before


def _rolls_then_refuses(draft: AnyGame, rng: Random) -> tuple[Fact, ...]:
    del draft
    _ = rng.random()
    raise ValueError("the rules said no")


async def test_a_re_filed_cast_member_takes_the_new_brief_and_keeps_their_name_and_sheet(
    tmp_path: Path,
) -> None:
    """The brief is the worldsmith's between scenes; the name and the sheet are the rules'."""
    table = open_game(tmp_path)
    before = loner_sheet(table.state, "mara")
    table.spawner.answers["worldsmith"] = [
        _scene(
            cast={
                "mara": {
                    "id": "mara",
                    "name": "Another Mara",
                    "brief": "Waiting under the arcade with the lantern shuttered.",
                }
            },
        )
    ]

    state = await play_turn(
        table,
        "Out into the cloister walk.",
        tool_call("next_scene", pursuit="Out into the cloister walk."),
        arrival="Rain takes the arcade.",
    )

    mara = state.world.require("mara")
    assert state.world.scene.title == "The Cloister Walk"
    assert mara.name == "Mara"
    assert mara.brief == "Waiting under the arcade with the lantern shuttered."
    assert (mara.concept, mara.tags) == (before.concept, before.tags)
    assert WAY_UNWRITTEN not in state.exchanges()[-1].facts


async def test_the_clock_counts_only_a_turn_that_played_and_landed_facts(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(table, "I search beneath the desk.", FOUND)
    assert state.world.turns_since_meanwhile == 1

    state = await play_turn(table, "I wait.")
    assert state.world.turns_since_meanwhile == 1


async def test_a_turn_whose_only_call_directs_lands_and_hands_the_narrator_the_direction(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    before = table.state.world.cast

    state = await play_turn(table, "I wait.", DIRECTED)

    assert state.world.cast == before
    assert not cards(table.facts)
    assert len(state.exchanges()) == 1
    narrator = table.spawner.prompt("narrator")
    assert DIRECTION in narrator
    assert NOTHING not in narrator


async def test_a_call_after_the_direction_answers_the_wait_and_changes_nothing(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    again = tool_call("direct", text="say instead that the rain has stopped")

    state = await play_turn(table, "I keep watch.", DIRECTED, again, FOUND)

    assert table.answers[1:] == [DIRECTED_WAIT, DIRECTED_WAIT]
    assert not state.world.require(MAP).known
    assert "the rain has stopped" not in table.spawner.prompt("narrator")


async def test_a_turn_after_a_directed_one_plays_its_tools(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    _ = await play_turn(table, "I wait.", DIRECTED)

    state = await play_turn(table, "I search beneath the desk.", FOUND)

    assert state.world.require(MAP).known


async def test_a_turn_with_no_tool_call_gives_the_narrator_the_beat_line(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    _ = await play_turn(table, "I look around.")

    narrator = table.spawner.prompt("narrator")
    assert UNSETTLED in narrator
    assert NOTHING not in narrator
