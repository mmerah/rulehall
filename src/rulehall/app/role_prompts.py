from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from rulehall.core.facts import Fact, render_traces
from rulehall.core.game import AnyGame
from rulehall.core.log import Narration
from rulehall.core.prompt import Prompt, Sections, lines_of, render_log, section_if, sections
from rulehall.core.stores import read_cached_text
from rulehall.core.tools import render_schema
from rulehall.core.validation import Frozen, Refusal
from rulehall.core.views import NarratorView

PROMPTS_DIR = Path(__file__).parent / "prompts"
MASTER_ROLE = PROMPTS_DIR / "master.md"
NARRATOR_ROLE = PROMPTS_DIR / "narrator.md"
DEBRIEF_ROLE = PROMPTS_DIR / "debrief.md"
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
        blank = [
            name
            for name, value in (
                ("story_so_far", (self.story_so_far,)),
                ("current_aim", (self.current_aim,)),
                ("open_threads", self.open_threads),
                ("last_beats", self.last_beats),
            )
            if not value or not all(line.strip() for line in value)
        ]
        if blank:
            raise Refusal(f"these fields are blank: {', '.join(blank)}")


def render_master(
    instructions: str,
    engine_sections: Sections,
    state: AnyGame,
    action: str,
    *,
    notes: Sequence[str] = (),
) -> Prompt:
    played = len(state.log_entries())
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
                (f"RECENT PLAY (turn {played + 1})", render_log(state.chapters)),
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
    entries = state.log_entries()
    evidence = render_traces(entries[-1].facts if entries else (), told_only=True)
    return Prompt(
        system=sections(
            (
                ("YOUR ROLE", read_cached_text(DEBRIEF_ROLE)),
                ("HOW TO WRITE", read_cached_text(WRITING_GUIDE)),
            )
        ),
        user=sections((*_picture(view, state, evidence), ("ANSWER WITH", render_schema(Debrief)))),
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


def _scenario_sections(state: AnyGame) -> Sections:
    opening = f"{state.scenario_description.title}\n{state.scenario_description.premise}"
    return (
        *section_if("SCENARIO", "" if state.log_entries() else opening),
        ("BACKDROP", state.scenario_description.backdrop),
    )
