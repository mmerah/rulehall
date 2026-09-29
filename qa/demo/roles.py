"""Scripted roles for the demo recording: the same story, the same dice, on every take.

`script.json` holds every answer. The master runs its tool calls through the real rules, so the
engines, the dice and the battle simulator stay real. Only the words are fixed.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import JsonValue

from rulehall.app.role_prompts import OPENING_NARRATION
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.log import Line
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Frozen, Refusal

LOGGER = logging.getLogger(__name__)

SCRIPT = Path(__file__).with_name("script.json")
# The narrator prompt tells what happened from here on; the log above it repeats old turns.
WHAT_HAPPENED = "# WHAT HAPPENED"
PROMPT_START = 120


class ScriptedTurn(Frozen):
    action: str
    seed: int | None = None
    calls: tuple[tuple[str, dict[str, JsonValue]], ...] = ()
    narration: tuple[Line, ...] = ()


class Cue(Frozen):
    when: str
    narration: tuple[Line, ...]


class WorldsmithAnswer(Frozen):
    when: str
    answer: dict[str, JsonValue]


class DemoScript(Frozen):
    openings: dict[str, tuple[Line, ...]]
    turns: tuple[ScriptedTurn, ...]
    cues: tuple[Cue, ...] = ()
    worldsmith: tuple[WorldsmithAnswer, ...] = ()

    @classmethod
    def read(cls, path: Path = SCRIPT) -> "DemoScript":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass(slots=True)
class DemoRoles:
    script: DemoScript
    queued: list[tuple[Line, ...]] = field(default_factory=list)

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        heard: Callable[[str], None] | None = None,
    ) -> str:
        match role:
            case "narrator":
                answer = _narrated(self._narration(prompt))
            case "worldsmith":
                answer = json.dumps(self._worldsmith(prompt))
            case "master" | "opponent":
                raise _unscripted(role, prompt)
        LOGGER.info("scripted %s answer: %s", role, answer)
        if heard is not None:
            heard(answer)
        return answer

    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None:
        self.queued.clear()
        words = turn.logged_words.strip()
        scripted = next((each for each in self.script.turns if each.action == words), None)
        if scripted is None:
            raise _unscripted("master", prompt, f"no turn for the action {words!r}")
        if scripted.seed is not None:
            turn.rng.seed(scripted.seed)
        for name, args in scripted.calls:
            LOGGER.info("scripted master call: %s %s", name, json.dumps(args))
            LOGGER.info("the rules answered: %s", turn.call_tool(name, args))
        if scripted.narration:
            self.queued.append(scripted.narration)

    def _narration(self, prompt: Prompt) -> tuple[Line, ...]:
        if OPENING_NARRATION in prompt.user:
            for title, lines in self.script.openings.items():
                if f"# SCENARIO\n{title}\n" in prompt.user:
                    return lines
            raise _unscripted("narrator", prompt, "no opening for this scenario")
        if self.queued:
            return self.queued.pop(0)
        happened = prompt.user.rpartition(WHAT_HAPPENED)[2]
        for cue in self.script.cues:
            if cue.when in happened:
                return cue.narration
        raise _unscripted("narrator", prompt, "no turn narration queued and no cue matches")

    def _worldsmith(self, prompt: Prompt) -> dict[str, JsonValue]:
        for scripted in self.script.worldsmith:
            if scripted.when in prompt.user:
                return scripted.answer
        raise _unscripted("worldsmith", prompt)


def _narrated(lines: tuple[Line, ...]) -> str:
    return json.dumps({"lines": [line.model_dump() for line in lines]})


def _unscripted(role: Role, prompt: Prompt, why: str = "no answer matches") -> Refusal:
    start = " ".join(prompt.user[-PROMPT_START:].split())
    return Refusal(f"the demo script has no {role} answer ({why}); the prompt ends: {start!r}")
