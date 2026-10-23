from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from rulehall.core.facts import Fact, render_traces
from rulehall.core.game import AnyGame
from rulehall.core.narration import Narration, NarratorView
from rulehall.core.prompt import Prompt, Sections, lines_of, render_log, section_if, sections
from rulehall.core.stores import read_cached_text
from rulehall.core.tools import render_schema
from rulehall.core.validation import Frozen, Refusal

PROMPTS_DIR = Path(__file__).parent / "prompts"
MASTER_ROLE = PROMPTS_DIR / "master.md"
NARRATOR_ROLE = PROMPTS_DIR / "narrator.md"
DEBRIEF_ROLE = PROMPTS_DIR / "debrief.md"
EPILOGUE_ROLE = PROMPTS_DIR / "epilogue.md"
WRITING_GUIDE = PROMPTS_DIR / "writing.md"
# Stated in the prompt, not checked: a model counts words badly; a refusal loop costs the turn.
NARRATION_WORDS = 180
PAUSED = (
    'play pauses here on the player\'s decision: "{prompt}" End at the pause. Settle nothing that '
    "the player has not answered."
)
REQUESTED = (
    "play stops here while the world grows. End at this moment. Settle nothing more than what "
    "happened."
)
BATTLING = "play pauses here for a battle. End on the challenge. Settle nothing of the fight."
UNSETTLED = (
    "the rules settled nothing this turn. Answer the player in the fiction. Let the people here "
    "act from what they want. Settle nothing new."
)
OPENING_NARRATION = (
    "The story starts here. The player has read nothing yet. Tell the player four things, in the "
    "story and in this order. First, who the player is (YOUR PARTY gives the name first) and "
    "where the player stands. Second, what is in front of the player, the situation as the player "
    "sees it now. Third, what the player is here to do. Take it from SCENARIO. Say it as the "
    "thing that pulls at the player. Fourth, two or three things that the player can do first, "
    "offered by the place and the people. Write all of it in prose, never as a list. Write six "
    f"to eight sentences, under {NARRATION_WORDS} words. The player has not acted, so settle "
    "nothing."
)


class Debrief(Frozen):
    """A recap for a player coming back to the game: only what the player has read."""

    story_so_far: str = Field(
        description="The story from the start to now, in a few sentences. Tell it to the player."
    )
    current_aim: str = Field(description="What the player is trying to do now, in one sentence.")
    open_threads: tuple[str, ...] = Field(
        description=(
            "Each question, promise or problem that is still open, one sentence each. A thread "
            'can suggest a next step, for example "You could return to the smith with the ore."'
        )
    )
    last_beats: tuple[str, ...] = Field(
        description="The last things that happened, in order. Write each as a short bullet line."
    )

    def check(self) -> None:
        _refuse_blank(
            (
                ("story_so_far", (self.story_so_far,)),
                ("current_aim", (self.current_aim,)),
                ("open_threads", self.open_threads),
                ("last_beats", self.last_beats),
            )
        )


class Epilogue(Frozen):
    """What became of the player years after the adventure: built only on what the player read."""

    paragraphs: tuple[str, ...] = Field(
        description=(
            "Two to four paragraphs on what became of the player, the people and the places "
            'the player knew, in the years later. Tell it to the player as "you".'
        )
    )
    open_trouble: str = Field(
        description=(
            "One sentence: a trouble in that later time that a new adventure could start from."
        )
    )

    def check(self) -> None:
        _refuse_blank((("paragraphs", self.paragraphs), ("open_trouble", (self.open_trouble,))))

    def render(self) -> str:
        return "\n\n".join((*self.paragraphs, self.open_trouble))


def years_later(years: int) -> str:
    return f"{years} year{'' if years == 1 else 's'} later"


def render_master(
    instructions: str,
    engine_sections: Sections,
    state: AnyGame,
    action: str,
    *,
    notes: Sequence[str] = (),
) -> Prompt:
    return Prompt(
        system=sections(
            (
                ("YOUR ROLE", read_cached_text(MASTER_ROLE)),
                ("THE RULES OF THIS GAME", instructions),
            )
        ),
        user=sections(
            (
                *_scenario_sections(state),
                ("THE SCOPE OF PLAY", state.scenario_description.scope),
                *engine_sections,
                *section_if(
                    "YOUR PRIVATE NOTES (only you see these; oldest first)",
                    "\n".join(f"- {note}" for note in state.master_notes),
                ),
                (f"RECENT PLAY (turn {state.turn_number()})", render_log(state.chapters)),
                ("NOTES FROM THE RULES", lines_of(f"- {note}" for note in notes)),
                ("PLAYER ACTION", action),
            )
        ),
    )


def render_narrator(view: NarratorView, state: AnyGame, *, evidence: str, cue: str) -> Prompt:
    return Prompt(
        system=sections(
            (
                (
                    "YOUR ROLE",
                    read_cached_text(NARRATOR_ROLE).format(words=NARRATION_WORDS),
                ),
                ("HOW TO WRITE", read_cached_text(WRITING_GUIDE)),
            )
        ),
        user=sections(
            (
                *_picture(view, state, evidence),
                ("PLAYER ACTION", cue),
                ("ANSWER WITH", render_schema(Narration)),
            )
        ),
    )


def render_debrief(view: NarratorView, state: AnyGame) -> Prompt:
    return Prompt(
        system=sections(
            (
                ("YOUR ROLE", read_cached_text(DEBRIEF_ROLE)),
                ("HOW TO WRITE", read_cached_text(WRITING_GUIDE)),
            )
        ),
        user=sections(
            (*_picture(view, state, _last_told(state)), ("ANSWER WITH", render_schema(Debrief)))
        ),
    )


def render_epilogue(view: NarratorView, state: AnyGame, years: int) -> Prompt:
    return Prompt(
        system=sections(
            (
                ("YOUR ROLE", read_cached_text(EPILOGUE_ROLE)),
                ("HOW TO WRITE", read_cached_text(WRITING_GUIDE)),
            )
        ),
        user=sections(
            (
                *_picture(view, state, _last_told(state)),
                ("THE TIME JUMP", years_later(years)),
                ("ANSWER WITH", render_schema(Epilogue)),
            )
        ),
    )


def render_evidence(facts: Sequence[Fact], state: AnyGame, *, in_battle: bool) -> str:
    told = [fact for fact in facts if fact.told]
    evidence = render_traces(told) if told else f"- {UNSETTLED}"
    if (pending := state.pending) is not None:
        evidence += f"\n- {PAUSED.format(prompt=pending.prompt)}"
    if state.request is not None:
        evidence += f"\n- {REQUESTED}"
    if in_battle:
        evidence += f"\n- {BATTLING}"
    return evidence


def _picture(view: NarratorView, state: AnyGame, evidence: str) -> Sections:
    subjects = {subject.id: subject for subject in view.subjects}
    first, *rest = (subjects[member_id] for member_id in view.party)
    members = [f"with you: {member.headline}" for member in rest]
    party = "\n".join((f"you are {first.headline}", *(members or ["nobody travels with you"])))
    others = view.others()
    who_is_here = (
        lines_of(f"- {subject.headline}" for subject in others) if others else "(nobody else)"
    )
    return (
        *_scenario_sections(state),
        ("SCENE", f"{view.title}\n{view.situation}"),
        ("WHO IS HERE", who_is_here),
        ("YOUR PARTY", party),
        ("THE PLAYER'S SHEET", lines_of(f"- {label}: {value}" for label, value in view.sheet)),
        ("WHAT THE PLAYER HAS READ", render_log(state.chapters)),
        ("WHAT HAPPENED", evidence),
    )


def _last_told(state: AnyGame) -> str:
    entries = state.log_entries()
    return render_traces(entries[-1].facts if entries else (), told_only=True)


def _scenario_sections(state: AnyGame) -> Sections:
    opening = f"{state.scenario_description.title}\n{state.scenario_description.premise}"
    return (
        *section_if("SCENARIO", "" if state.log_entries() else opening),
        ("BACKDROP", state.scenario_description.backdrop),
    )


def _refuse_blank(fields: Sequence[tuple[str, Sequence[str]]]) -> None:
    blank = [name for name, value in fields if not value or not all(line.strip() for line in value)]
    if blank:
        raise Refusal(f"these fields are blank: {', '.join(blank)}")
