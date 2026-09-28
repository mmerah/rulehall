import json
import logging
from asyncio import timeout
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Protocol

from pydantic import BaseModel, Field

from rulehall.app.api_roles import converse_master, stream_answer
from rulehall.app.cli_roles import DRIVERS, run_cli
from rulehall.app.turn import Turn
from rulehall.config import LiveSettings, Role, RoleConfig
from rulehall.core.answer_repair import parse_with_repairs
from rulehall.core.facts import Fact, render_traces
from rulehall.core.game import AnyGame, Check, RoleAnswer
from rulehall.core.log import Narration, SpokenLine, partial_lines
from rulehall.core.prompt import Prompt, Sections, lines_of, render_log, section_if, sections
from rulehall.core.stores import read_cached_text
from rulehall.core.tools import render_schema
from rulehall.core.validation import Frozen, Refusal, decode
from rulehall.core.views import NarratorView
from rulehall.engines.engine import AnyEngine

LOGGER = logging.getLogger(__name__)

RETRIES = 1
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


@dataclass(frozen=True, slots=True)
class RoleReply:
    text: str
    resume_id: str | None


class RoleRunner(Protocol):
    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        resume_id: str | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RoleReply: ...
    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None: ...


@dataclass(slots=True)
class ProviderRoleRunner:
    live_settings: LiveSettings

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        resume_id: str | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RoleReply:
        settings = self.live_settings.current
        config = settings.roles.for_name(role)
        match config.provider:
            case "claude" | "codex":
                driver = DRIVERS[config.provider]
                running = run_cli(role, config, driver, prompt, resume_id=resume_id, heard=heard)
                detail = "cold" if resume_id is None else "resumed"
                reply = await _within_budget(role, config, running, detail=detail)
                return RoleReply(reply.text, reply.resume_id)
            case "openrouter" | "local":
                provider = settings.providers.for_name(config.provider)
                running = stream_answer(role, config, provider, prompt, heard)
                return RoleReply(
                    await _within_budget(role, config, running, detail="over the API"), None
                )

    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None:
        settings = self.live_settings.current
        config = settings.roles.for_name("master")
        match config.provider:
            case "claude" | "codex":
                mcp_url = f"http://localhost:{settings.server.port}/mcp/"
                driver = DRIVERS[config.provider]
                running = run_cli("master", config, driver, prompt, mcp_url=mcp_url)
                await _within_budget("master", config, running, detail="cold")
            case "openrouter" | "local":
                provider = settings.providers.for_name(config.provider)
                running = converse_master(config, provider, prompt, turn)
                await _within_budget("master", config, running, detail="over the API")


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


async def run_master(runner: RoleRunner, turn: Turn) -> None:
    prompt = render_master(
        turn.engine.instructions,
        turn.engine.master_sections(turn.draft),
        turn.draft,
        turn.master_action_text,
        notes=turn.notes,
    )
    try:
        await runner.play_master_turn(prompt, turn)
    except Refusal as failed:
        if not turn.state_changed:
            raise
        LOGGER.warning(
            "the game master failed after applying %d facts: %s", len(turn.facts), failed
        )


async def run_narrator(
    runner: RoleRunner,
    engine: AnyEngine,
    draft: AnyGame,
    facts: tuple[Fact, ...],
    cue: str,
    heard: Callable[[tuple[SpokenLine, ...]], None],
    before: NarratorView | None = None,
) -> tuple[SpokenLine, ...]:
    view = engine.narrator_view(draft)
    if before is not None:
        view = view.after(before)

    def overheard(text: str) -> None:
        heard(view.spoken(partial_lines(text)))

    told = [fact for fact in facts if fact.told]
    evidence = render_traces(told) if told else f"- {UNSETTLED}"
    if (pending := draft.pending) is not None:
        evidence += f"\n- {PAUSED.format(prompt=pending.prompt)}"
    if draft.request is not None:
        evidence += f"\n- {REQUESTED}"
    if engine.in_battle(draft):
        evidence += f"\n- {BATTLING}"
    narration = await ask(
        runner,
        "narrator",
        render_narrator(view, draft, evidence=evidence, cue=cue),
        Narration,
        view.check_narration,
        overheard,
    )
    return view.spoken(narration.lines)


async def run_debrief(runner: RoleRunner, engine: AnyEngine, state: AnyGame) -> Debrief:
    view = engine.narrator_view(state)
    return await ask(
        runner,
        "narrator",
        render_debrief(view, state),
        Debrief,
        Debrief.check,
    )


async def ask[T: BaseModel](
    runner: RoleRunner,
    role: Role,
    prompt: Prompt,
    model: type[T],
    check: Check[T],
    heard: Callable[[str], None] | None = None,
) -> T:
    asked, refused, resume_id = prompt, "", None
    for _ in range(RETRIES + 1):
        reply = await runner.answer(role, asked, resume_id=resume_id, heard=heard)
        resume_id = reply.resume_id
        try:
            answer = parse_with_repairs(model, decode(final_message(reply.text)))
            check(answer)
        except Refusal as invalid:
            refused = str(invalid)
        else:
            return answer
        correction = f"Your last answer was refused: {refused}\nAnswer again. Correct the error."
        if resume_id is not None:
            asked = Prompt(system="", user=correction)
        else:
            asked = replace(prompt, user=f"{prompt.user}\n\n{correction}")
    LOGGER.warning("the %s answered nothing usable: %s", role, refused)
    raise Refusal(f"the {role} answered nothing usable")


def role_answer(runner: RoleRunner, role: Role) -> RoleAnswer:
    return partial(ask, runner, role)


def final_message(output: str) -> str:
    fenced = output.rsplit("```", 2)
    if len(fenced) == 3:
        body = fenced[1]
        if body.startswith("json") and "\n" in body:
            body = body.split("\n", 1)[1]
        else:
            body = body.removeprefix("json")
        with suppress(json.JSONDecodeError, RecursionError):
            json.loads(body)
            return body
    tail = output.rstrip()
    start = tail.find("{")
    if start != -1:
        try:
            _, end = json.JSONDecoder().raw_decode(tail, start)
        except (json.JSONDecodeError, RecursionError):
            pass
        else:
            if end == len(tail):
                return tail[start:]
    return output


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


async def _within_budget[T](
    role: Role, config: RoleConfig, running: Awaitable[T], *, detail: str
) -> T:
    started = monotonic()
    try:
        async with timeout(config.timeout):
            result = await running
    except TimeoutError:
        raise Refusal(f"the {role} answered nothing in {config.timeout:.0f}s") from None
    LOGGER.info(
        "%s answered: provider=%s model=%s effort=%s %s in %.1fs",
        role,
        config.provider,
        config.model,
        config.effort,
        detail,
        monotonic() - started,
    )
    return result


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
