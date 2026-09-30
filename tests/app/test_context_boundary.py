from support.table import ENGINES_BUILT, TWENTYFOURXX, game, narrowed, refused

from rulehall.app.role_prompts import render_master, render_narrator
from rulehall.app.turn import ANSWERED_BY_OPTION
from rulehall.core.log import Chapter, LogEntry, SpokenLine
from rulehall.core.prompt import Prompt
from rulehall.core.views import NarratorView
from rulehall.engines.engine import AnyEngine
from rulehall.engines.twentyfourxx.sheet import Crewmate
from rulehall.engines.twentyfourxx.world import TwentyFourXXGame

SECRET = "hidden-actor"
UNREVEALED = "Unrevealed canon."


def _state() -> TwentyFourXXGame:
    """An unmet character and a known one, both here, so both leak paths are open at once."""
    _, begun = game(TWENTYFOURXX)
    draft = narrowed(begun, TwentyFourXXGame).draft()
    for entity in (
        Crewmate(id=SECRET, name="The Secret", voice="other", brief=UNREVEALED),
        Crewmate(id="ledger", name="a ledger", voice="other", brief="Vessa's notes.", known=True),
    ):
        draft.world.cast[entity.id] = entity
        draft.world.scene.here_ids.append(entity.id)
    return draft.validated()


def _engine() -> AnyEngine:
    return ENGINES_BUILT[TWENTYFOURXX]


def _master_prompt(state: TwentyFourXXGame, prompt: str, *, notes: tuple[str, ...] = ()) -> Prompt:
    return render_master(
        _engine().instructions,
        _engine().master_sections(state),
        state,
        prompt,
        notes=notes,
    )


def test_the_narrators_view_has_no_field_that_could_hold_unrevealed_canon() -> None:
    state = _state()
    narrator = _engine().narrator_view(state)
    master = _engine().master_sections(state)

    assert set(NarratorView.model_fields) == {
        "place_id",
        "title",
        "situation",
        "subjects",
        "speakers",
        "party",
        "sheet",
        "departed",
    }
    dumped = str(narrator.model_dump())
    assert "The Secret" not in dumped
    assert UNREVEALED not in dumped
    assert UNREVEALED in str(master)


def test_the_master_is_shown_the_whole_cast_met_or_not() -> None:
    state = _state()

    master = _master_prompt(state, "I look around.").text

    assert "a ledger[ledger]" in master
    assert "The Secret[hidden-actor]" in master


def test_the_narrator_prompt_carries_only_what_the_player_has_met() -> None:
    state = _state()

    prompt = render_narrator(
        _engine().narrator_view(state),
        state,
        evidence="- the map was found",
        cue="What does Vessa say?",
    ).text

    assert "Vessa Rune" in prompt
    assert "The Secret" not in prompt
    assert "hidden-actor" not in prompt
    assert UNREVEALED not in prompt


def test_the_narrator_prompt_carries_the_id_of_each_subject_here() -> None:
    state = _state()

    prompt = render_narrator(
        _engine().narrator_view(state), state, evidence="- (nothing changed)", cue="I wait."
    ).text

    who_is_here = prompt.split("# WHO IS HERE\n", 1)[1].split("\n\n", 1)[0]
    assert "a ledger[ledger] — Vessa's notes." in who_is_here


def test_the_narrator_prompt_carries_only_what_the_player_has_read() -> None:
    state = _state()
    state.chapters.append(
        Chapter(title="t", entries=[LogEntry(words="p", lines=(SpokenLine(text="Water drips."),))])
    )

    prompt = render_narrator(
        _engine().narrator_view(state),
        state,
        evidence="- the map was found",
        cue="What does Vessa say?",
    ).text

    assert "Water drips." in prompt


def test_a_chosen_option_is_not_shown_as_the_players_own_words() -> None:
    note = (
        'The rules paused play to ask the player: "A hit is coming." They chose: Take the hit. '
        "Already resolved:\n- the hit lands in full"
    )

    master = _master_prompt(_state(), ANSWERED_BY_OPTION, notes=(note,)).text

    assert master.count("Take the hit") == 1
    assert master.endswith(f"# PLAYER ACTION\n{ANSWERED_BY_OPTION}")


def test_a_direction_that_names_someone_the_player_has_not_met_is_refused() -> None:
    state = _state()

    reason = refused(_engine(), state.draft(), "direct", text="The Secret steps out of the dark.")

    assert "The Secret" in reason
