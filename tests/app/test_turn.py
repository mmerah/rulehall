import json
from collections.abc import Callable
from pathlib import Path
from random import Random

import pytest
from support.game import MARA, TOMAS, initialized, loner_sheet, open_game
from support.table import NO_PACKS, Table, narrated, play_turn, tool_call
from support.twentyfourxx import TROUBLE_SEED, open_crew

from rulehall.app.role_prompts import UNSETTLED
from rulehall.app.turn import DIRECTED_ONCE, REQUEST_WAIT, Turn
from rulehall.core.decisions import PlayerInput
from rulehall.core.facts import NOTHING, Fact, told_cards
from rulehall.core.game import AnyGame
from rulehall.core.tools import NoArgs, tool
from rulehall.core.validation import Refusal
from rulehall.engines.loner4e.engine import SCENE_UNWRITTEN, Loner4eEngine
from rulehall.engines.loner4e.rules import outcome_for
from rulehall.engines.loner4e.world import Loner4eGame
from rulehall.engines.sheet import PLAYER_ID

FOUND = tool_call("enter", target_id=TOMAS)
NOWHERE = tool_call("leave_party", target_id="nowhere")
WARDEN = "warden-six"
# The transition die reads 2: a closed scene hands over to a dramatic one.
DRAMATIC_SEED = 1
TAKEN = tool_call("change_tags", actor_id=PLAYER_ID, kind="gear", gained=["the vault map"])
ASKED = tool_call("ask", question="Does the door give?")
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
        "present_ids": ["mara"],
        "recap": "The player left the abbot's study behind, lantern shuttered, and made for the "
        "cloister walk with Mara close behind them.",
        "arc": "Farther in, the chapter house still holds what Mara came for, and has not yet "
        "been found.",
        "goal": "Follow Mara to the chapter house",
        "details": ["Driving Rain", "Black Flagstones"],
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

    assert [role for role, _ in table.roles.prompts] == ["master", "narrator"]
    assert "the vault map" in state.world.player.tagged("gear")
    narrator = table.roles.prompt("narrator")
    assert "Elena" not in narrator
    # The sheets are the game master's: no tag the engine rolls by reaches the narrator.
    assert "concept" not in narrator
    assert len(state.log_entries()) == 1
    assert state.log_entries()[-1].words == "I search beneath the desk."


async def test_the_turn_holds_its_facts_in_resolver_order(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(
        table,
        "I take the map and listen.",
        FOUND,
        TAKEN,
        tool_call("change_tags", actor_id="player", kind="condition", gained=["Listening"]),
    )

    expected = ["Brother Tomas arrives", "Took the vault map", "Now: Listening"]
    exchange = state.log_entries()[-1]
    assert [fact.card for fact in told_cards(table.facts)] == expected
    assert [fact.card for fact in told_cards(exchange.facts)] == expected
    assert len(exchange.facts) >= len(told_cards(exchange.facts))


async def test_a_narrator_failure_still_commits_the_turn_with_no_prose(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    table.roles.turns.append(table.plays((FOUND, TAKEN)))

    await table.session.choose(PlayerInput(text="I take the map."))

    exchange = table.session.state.log_entries()[-1]
    assert exchange.lines == ()
    assert "the vault map" in table.session.state.world.player.tagged("gear")


async def test_a_narrator_failure_with_nothing_landed_refuses_and_keeps_the_words(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    table.roles.turns.append(table.plays(()))
    before = len(table.session.state.log_entries())

    with pytest.raises(Refusal, match="narrator"):
        await table.session.choose(PlayerInput(text="I take the map."))

    assert len(table.session.state.log_entries()) == before


async def test_the_engine_rolls_the_outcome_the_facts_then_record(tmp_path: Path) -> None:
    table = open_game(tmp_path, rng=Random(2))

    state = await play_turn(
        table,
        "I plead with the door.",
        tool_call("ask", question="Does the door give before the whispering finds him?"),
        narration="You falter.",
    )

    fired = table.facts
    answer = next(fact for fact in fired if fact.dice)
    chance, risk = answer.dice
    rolled = [fact.trace for fact in fired[:2]]
    for die, trace in zip(answer.dice, rolled, strict=True):
        assert trace.endswith(f"[{', '.join(str(v) for v in die.rolled)}]")
    wording = outcome_for(max(chance.rolled), max(risk.rolled)).wording
    assert answer.card.splitlines()[1] == wording
    table.session.engine.validate(state)
    assert not any(fact.told for fact in fired[:2])


async def test_an_illegal_tool_call_is_refused_with_the_reason(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(table, "I wait.", NOWHERE, FOUND)

    assert state.world.require_entity(TOMAS).known
    assert any("unknown id 'nowhere'" in refusal for refusal in table.refusals)


async def test_a_later_call_in_one_turn_sees_the_earlier_calls_draft(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)

    wants = tool_call("drive", actor_id=TOMAS, goal="Guard the vault")
    state = await play_turn(table, "I wait for the knock.", FOUND, wants)

    assert state.world.require_entity(TOMAS).goal == "Guard the vault"
    assert table.refusals == []


async def test_a_call_after_the_ask_answers_handoff_wait_and_changes_nothing(
    tmp_path: Path,
) -> None:
    table = open_crew(tmp_path, rng=Random(TROUBLE_SEED))
    complication = "A second crew breaches the airlock."

    state = await play_turn(
        table,
        "I keep watch.",
        tool_call("next_scene", complication=complication),
        tool_call("enter", target_id=WARDEN),
    )

    assert table.answers[1] == REQUEST_WAIT
    assert not state.world.require_entity(WARDEN).known


def _narrated_lines(*lines: dict[str, object]) -> str:
    return json.dumps({"lines": list(lines)})


async def test_an_unknown_speaker_is_refused_and_one_who_left_this_turn_still_speaks(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    table.roles.answers["narrator"] = [
        _narrated_lines({"speaker_id": "elena", "text": "You should not be here."}),
        _narrated_lines(
            {"speaker_id": None, "text": "You should not be here."},
            {"speaker_id": MARA, "text": "Keep the lamp."},
        ),
    ]
    table.roles.turns.append(table.plays((tool_call("leave", target_id=MARA),)))

    await table.session.choose(PlayerInput(text="I wait."))

    narrator_prompts = [prompt for role, prompt in table.roles.prompts if role == "narrator"]
    assert len(narrator_prompts) == 2
    assert "'elena' cannot speak now" in narrator_prompts[1]
    newest = table.session.state.log_entries()[-1]
    assert [(line.speaker_id, line.text) for line in newest.lines] == [
        (None, "You should not be here."),
        (MARA, "Keep the lamp."),
    ]


async def test_an_unlisted_speaker_lands_named_in_the_narrator_voice(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    table.roles.answers["narrator"] = [
        _narrated_lines(
            {"speaker_id": None, "unlisted_speaker": "Fish vendor", "text": "Fresh fish!"}
        )
    ]

    await table.session.choose(PlayerInput(text="I wait."))

    (line,) = table.session.state.log_entries()[-1].lines
    assert (line.speaker, line.voice, line.text) == ("Fish vendor", None, "Fresh fish!")
    assert line.speaker_id == "unlisted-fish-vendor"


@pytest.mark.parametrize(
    "line",
    [
        {"speaker_id": MARA, "unlisted_speaker": "Fish vendor", "text": "Fresh fish!"},
        {"speaker_id": None, "unlisted_speaker": "Mara", "text": "Fresh fish!"},
    ],
)
async def test_a_misused_unlisted_speaker_is_refused_for_the_retry(
    tmp_path: Path, line: dict[str, object]
) -> None:
    table = open_game(tmp_path)
    table.roles.answers["narrator"] = [
        _narrated_lines(line),
        _narrated_lines({"speaker_id": None, "text": "The market hums."}),
    ]

    await table.session.choose(PlayerInput(text="I wait."))

    narrator_prompts = [prompt for role, prompt in table.roles.prompts if role == "narrator"]
    assert len(narrator_prompts) == 2


def _exploding_after_the_find(table: Table[Loner4eGame]) -> Callable[[], None]:
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
    table.roles.turns.append(_exploding_after_the_find(table))
    table.roles.answers["narrator"] = [narrated("The map is in hand.")]

    await table.session.choose(PlayerInput(text="I take the map and read it."))

    assert len(table.session.state.log_entries()) == 1
    assert table.session.state.world.require_entity(TOMAS).known


async def test_a_master_that_crashed_after_a_tool_landed_is_not_spawned_again(
    tmp_path: Path,
) -> None:
    """A second spawn would replay the prompt and apply the same mutation twice."""
    table = open_game(tmp_path)
    _ = await play_turn(table, "I look around.")
    table.roles.turns.append(_exploding_after_the_find(table))
    table.roles.answers["narrator"] = [narrated("The map is in hand.")]
    spawned = len(table.roles.prompts)

    await table.session.choose(PlayerInput(text="I take the map."))

    assert [role for role, _ in table.roles.prompts[spawned:]].count("master") == 1


async def test_a_turn_that_applied_nothing_and_failed_is_refused(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    before = table.session.state.model_dump_json()
    table.roles.turns += [_never_started, _never_started]

    with pytest.raises(Refusal, match="never started"):
        await table.session.choose(PlayerInput(text="I take the map."))

    assert table.session.state.model_dump_json() == before


async def test_two_rolls_in_one_turn_do_not_read_the_same_dice(tmp_path: Path) -> None:
    table = open_game(tmp_path, rng=Random(1))

    _ = await play_turn(table, "I try the door twice.", ASKED, ASKED)

    first, second = (fact.dice for fact in table.facts if len(fact.dice) == 2)
    assert first != second


class RefusingEngine(Loner4eEngine):
    @tool
    def roll_then_refuse(self, _draft: AnyGame, _args: NoArgs, rng: Random) -> tuple[Fact, ...]:
        """Roll the dice, then refuse."""
        _ = rng.random()
        raise Refusal("the rules said no")


def test_a_refused_call_leaves_the_turn_the_dice_it_had() -> None:
    _, state = initialized()
    turn = Turn.begin(RefusingEngine(NO_PACKS), state, PlayerInput(text="I try."), Random(1))
    before = turn.rng.getstate()

    with pytest.raises(Refusal, match="the rules said no"):
        _ = turn.call_tool("roll_then_refuse", {})

    assert turn.rng.getstate() == before


async def test_a_re_filed_cast_member_takes_the_new_brief_and_keeps_their_name_and_sheet(
    tmp_path: Path,
) -> None:
    """The brief is the worldsmith's between scenes; the name and the sheet are the rules'."""
    table = open_game(tmp_path, rng=Random(DRAMATIC_SEED))
    before = loner_sheet(table.state, "mara")
    table.roles.answers["worldsmith"] = [
        _scene(
            cast={
                "mara": {
                    "id": "mara",
                    "name": "Mara",
                    "brief": "Waiting under the arcade with the lantern shuttered.",
                    "voice": "feminine",
                }
            },
        )
    ]

    state = await play_turn(
        table,
        "Out into the cloister walk.",
        tool_call("close_scene", reason="resolved"),
        arrival="Rain takes the arcade.",
    )

    mara = state.world.require_entity("mara")
    assert state.world.scene.title == "The Cloister Walk"
    assert mara.name == "Mara"
    assert mara.brief == "Waiting under the arcade with the lantern shuttered."
    assert (mara.concept, mara.tags) == (before.concept, before.tags)
    assert SCENE_UNWRITTEN not in state.log_entries()[-1].facts


def test_a_played_turn_with_no_facts_still_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = open_game(tmp_path)
    engine = table.session.engine
    ended: list[bool] = []

    def end_turn(_draft: AnyGame, /, *, acted: bool) -> None:
        ended.append(acted)

    monkeypatch.setattr(engine, "end_turn", end_turn)
    turn = Turn.begin(engine, table.state, PlayerInput(text="I wait."), Random())

    _ = turn.finish(())

    assert ended == [False]


async def test_a_turn_whose_only_call_directs_lands_and_hands_the_narrator_the_direction(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    before = table.state.world.cast

    state = await play_turn(table, "I wait.", DIRECTED)

    assert state.world.cast == before
    assert not told_cards(table.facts)
    assert len(state.log_entries()) == 1
    narrator = table.roles.prompt("narrator")
    assert DIRECTION in narrator
    assert NOTHING not in narrator


async def test_a_call_after_the_direction_lands_and_the_direction_is_told_last(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)
    again = tool_call("direct", text="say instead that the rain has stopped")

    state = await play_turn(table, "I keep watch.", DIRECTED, again, FOUND)

    assert table.answers[1] == DIRECTED_ONCE
    assert TOMAS in state.world.scene.here_ids
    assert table.facts[-1].trace.endswith(DIRECTION)
    narrator = table.roles.prompt("narrator")
    assert "the rain has stopped" not in narrator
    assert narrator.index("[brother-tomas] arrives") < narrator.index(DIRECTION)


async def test_a_turn_after_a_directed_one_plays_its_tools(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    _ = await play_turn(table, "I wait.", DIRECTED)

    state = await play_turn(table, "I search beneath the desk.", FOUND)

    assert state.world.require_entity(TOMAS).known


async def test_a_turn_with_no_tool_call_gives_the_narrator_the_beat_line(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    _ = await play_turn(table, "I look around.")

    narrator = table.roles.prompt("narrator")
    assert UNSETTLED in narrator
    assert NOTHING not in narrator
