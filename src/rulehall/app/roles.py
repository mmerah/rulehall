import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path

from pydantic import BaseModel

from rulehall.app.spawn import Spawner
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.facts import Fact, traced
from rulehall.core.io import parse_text, partial_lines, read_cached_text
from rulehall.core.model import AnyGame, Check, RoleAnswer
from rulehall.core.play import Debrief, Narration, SpokenLine
from rulehall.core.prompt import Prompt, Sections, lines_of, render_history, section_if, sections
from rulehall.core.tools import schema_text
from rulehall.core.validation import Refusal
from rulehall.core.views import NarratorView
from rulehall.engines.engine import AnyEngine

LOGGER = logging.getLogger(__name__)

RETRIES = 1
PROMPTS_DIR = Path(__file__).parent / "prompts"
MASTER_ROLE = PROMPTS_DIR / "master.md"
WRITING_GUIDE = PROMPTS_DIR / "writing.md"
# Stated in the prompt, not checked: a model counts words badly, and a refusal loop costs the
# whole turn.
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


async def run_master(spawner: Spawner, turn: Turn) -> None:
    """A failed game master still played the turn when facts landed first."""
    prompt = render_master(
        turn.engine.instructions,
        turn.engine.master_sections(turn.draft),
        turn.draft,
        turn.master_input,
        notes=turn.notes,
    )
    try:
        await spawner.run("master", prompt, None, turn)
    except Refusal as failed:
        if not turn.landed:
            raise
        LOGGER.warning(
            "the game master failed after applying %d facts: %s", len(turn.facts), failed
        )


async def run_narrator(
    spawner: Spawner,
    engine: AnyEngine,
    draft: AnyGame,
    facts: tuple[Fact, ...],
    prompt: str,
    heard: Callable[[tuple[SpokenLine, ...]], None],
) -> tuple[SpokenLine, ...]:
    view = engine.narrator_view(draft)

    def overheard(text: str) -> None:
        here = (None, *view.speakers)
        heard(view.spoken([line for line in partial_lines(text) if line.speaker_id in here]))

    told = [fact for fact in facts if fact.told]
    evidence = traced(told) if told else f"- {UNSETTLED}"
    if (pending := draft.pending) is not None:
        evidence += f"\n- {PAUSED.format(prompt=pending.prompt)}"
    if draft.request is not None:
        evidence += f"\n- {REQUESTED}"
    if engine.in_battle(draft):
        evidence += f"\n- {BATTLING}"
    narration = await ask(
        spawner,
        "narrator",
        render_narrator(view, draft, evidence=evidence, prompt=prompt),
        Narration,
        view.check_narration,
        overheard,
    )
    return view.spoken(narration.lines)


async def run_debrief(spawner: Spawner, engine: AnyEngine, state: AnyGame) -> Debrief:
    view = engine.narrator_view(state)
    return await ask(
        spawner,
        "narrator",
        render_debrief(view, state),
        Debrief,
        Debrief.check,
    )


async def ask[T: BaseModel](
    spawner: Spawner,
    role: Role,
    prompt: Prompt,
    model: type[T],
    check: Check[T],
    heard: Callable[[str], None] | None = None,
) -> T:
    asked, refused, conversation = prompt, "", None
    for _ in range(RETRIES + 1):
        try:
            spoken = await spawner.run(role, asked, conversation, heard=heard)
            conversation = spoken.conversation
            answer = parse_text(model, spoken.text)
            check(answer)
        except Refusal as invalid:
            refused = str(invalid)
        else:
            return answer
        correction = f"Your last answer was refused: {refused}\nAnswer again. Correct the error."
        # The retry continues the refused attempt, which has read the prompt already.
        if conversation is not None:
            asked = Prompt(system="", user=correction)
        else:
            asked = replace(prompt, user=f"{prompt.user}\n\n{correction}")
    LOGGER.warning("the %s answered nothing usable: %s", role, refused)
    raise Refusal(f"the {role} answered nothing usable")


def role_answer(spawner: Spawner, role: Role) -> RoleAnswer:
    return partial(ask, spawner, role)


def render_master(
    instructions: str,
    engine_sections: Sections,
    state: AnyGame,
    action: str,
    *,
    notes: Sequence[str] = (),
) -> Prompt:
    played = sum(len(chapter.exchanges) for chapter in state.log)
    return Prompt(
        system=sections(
            (
                ("YOUR ROLE", read_cached_text(MASTER_ROLE)),
                ("THE RULES OF THIS GAME", instructions),
            )
        ),
        user=sections(
            (
                *section_if(
                    "SCENARIO",
                    f"{state.scenario.title}\n{state.scenario.premise}" if played == 0 else "",
                ),
                ("BACKDROP", state.scenario.backdrop),
                ("THE SCOPE OF PLAY", state.scenario.scope),
                *engine_sections,
                (f"RECENT PLAY (turn {played + 1})", render_history(state.log)),
                ("NOTES FROM THE RULES", lines_of(f"- {note}" for note in notes)),
                ("PLAYER ACTION", action),
            )
        ),
    )


def render_narrator(view: NarratorView, state: AnyGame, *, evidence: str, prompt: str) -> Prompt:
    return Prompt(
        system=sections(
            (
                (
                    "YOUR ROLE",
                    read_cached_text(PROMPTS_DIR / "narrator.md").format(words=NARRATION_WORDS),
                ),
                ("HOW TO WRITE", read_cached_text(WRITING_GUIDE)),
            )
        ),
        user=sections(
            (
                *_picture(view, state, evidence),
                ("PLAYER ACTION", prompt),
                ("ANSWER WITH", schema_text(Narration)),
            )
        ),
    )


def render_debrief(view: NarratorView, state: AnyGame) -> Prompt:
    history = state.exchanges()
    evidence = traced(history[-1].facts if history else (), told_only=True)
    return Prompt(
        system=sections(
            (
                ("YOUR ROLE", read_cached_text(PROMPTS_DIR / "debrief.md")),
                ("HOW TO WRITE", read_cached_text(WRITING_GUIDE)),
            )
        ),
        user=sections((*_picture(view, state, evidence), ("ANSWER WITH", schema_text(Debrief)))),
    )


def _picture(view: NarratorView, state: AnyGame, evidence: str) -> Sections:
    subjects = {subject.id: subject for subject in view.subjects}
    first, *rest = (subjects[member_id] for member_id in view.party)
    members = [f"with you: {member.headline}" for member in rest]
    party = "\n".join((f"you are {first.headline}", *(members or ["nobody travels with you"])))
    others = view.others()
    who_is_here = (
        lines_of(f"- {subject.headline}" for subject in others) if others else "(nobody else)"
    )
    opening = not any(chapter.exchanges for chapter in state.log)
    return (
        *section_if(
            "SCENARIO", f"{state.scenario.title}\n{state.scenario.premise}" if opening else ""
        ),
        ("BACKDROP", state.scenario.backdrop),
        ("SCENE", f"{view.title}\n{view.situation}"),
        ("WHO IS HERE", who_is_here),
        ("YOUR PARTY", party),
        ("THE PLAYER'S SHEET", lines_of(f"- {label}: {value}" for label, value in view.sheet)),
        ("WHAT THE PLAYER HAS READ", render_history(state.log)),
        ("WHAT HAPPENED", evidence),
    )
