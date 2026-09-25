from support.game import initialized, with_entity
from support.table import ENGINES_BUILT, LONER3E, refused

from rulehall.app.roles import render_master, render_narrator
from rulehall.app.turn import ANSWERED_BY_OPTION
from rulehall.core.play import Chapter, Exchange, SpokenLine
from rulehall.core.prompt import Prompt
from rulehall.core.views import NarratorView
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner3e.world import Loner3eEntity, Loner3eGame

SECRET = "hidden-actor"
UNREVEALED = "Unrevealed canon."


def _state() -> Loner3eGame:
    """An unmet character and a known one, both here, so both leak paths are open at once."""
    _, state = initialized()
    state = with_entity(
        state,
        Loner3eEntity(id=SECRET, name="The Secret", brief=UNREVEALED, concept="A Watcher"),
    )
    return with_entity(
        state,
        Loner3eEntity(id="ledger", name="a ledger", brief="Mara's notes.", known=True),
    )


def _engine() -> AnyEngine:
    return ENGINES_BUILT[LONER3E]


def _master_prompt(state: Loner3eGame, prompt: str, *, notes: tuple[str, ...] = ()) -> Prompt:
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
        prompt="What does Mara say?",
    ).text

    assert "Mara" in prompt
    assert "The Secret" not in prompt
    assert "hidden-actor" not in prompt
    assert UNREVEALED not in prompt


def test_the_narrator_prompt_carries_the_id_of_each_subject_here() -> None:
    state = _state()

    prompt = render_narrator(
        _engine().narrator_view(state), state, evidence="- (nothing changed)", prompt="I wait."
    ).text

    who_is_here = prompt.split("# WHO IS HERE\n", 1)[1].split("\n\n", 1)[0]
    assert "a ledger[ledger] — Mara's notes." in who_is_here


def test_the_narrator_prompt_carries_only_what_the_player_has_read() -> None:
    state = _state()
    state.log.append(
        Chapter(
            title="t", exchanges=[Exchange(words="p", lines=(SpokenLine(text="Water drips."),))]
        )
    )

    prompt = render_narrator(
        _engine().narrator_view(state),
        state,
        evidence="- the map was found",
        prompt="What does Mara say?",
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
