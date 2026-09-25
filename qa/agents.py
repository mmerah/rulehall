"""Scripted stand-ins for the three AI roles, driven from the player's own words.

The master reads PLAYER ACTION from its prompt like the real one. A line that starts with `!` is
a script: `!roll what="Try the door" actor_id=player question="Does it give?"` calls that tool,
`!crash` and `!refuse` fail the spawn, `!fail narrator` fails another role's next ask (its retry
too), `!bad worldsmith` makes one answer garbage so the retry lands.
Plain words with no script get one engine-appropriate roll, so dice show up in the page.

The narrator echoes what it was given, so every screenshot shows what the page was told. The
worldsmith answers each request shape with a small valid draft.
"""

import json
import logging
import re
import shlex
from asyncio import sleep
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import Literal

from pydantic import JsonValue

from rulehall.app.roles import RETRIES
from rulehall.app.runtime import Runtime
from rulehall.app.spawn import RunResult
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal

LOGGER = logging.getLogger("qa.agents")

type Fault = Literal["fail", "bad", "slow"]

DEFAULT_ROLLS: dict[str, tuple[str, dict[str, JsonValue]]] = {
    "loner3e": (
        "roll",
        {
            "what": "Try it",
            "actor_id": "player",
            "question": "Does the player get what they want?",
        },
    ),
    "pokemon": ("check", {"what": "Try it", "skill": "athletics", "difficulty": "easy"}),
    "tunnelgoons": ("roll", {"what": "Try it", "ability": "skulker", "difficulty": 8}),
    "twentyfourxx": ("roll", {"what": "Try it", "skill": "Stealth"}),
}


@dataclass(slots=True)
class Spoken:
    role: Role
    prompt: str
    answer: str
    calls: list[tuple[str, dict[str, JsonValue], str]] = field(default_factory=list)
    error: str = ""


@dataclass(slots=True)
class ScriptedAgents:
    delay: float = 0.3
    runtime: Runtime | None = None
    faults: dict[Role, list[Fault]] = field(default_factory=dict)
    log: list[Spoken] = field(default_factory=list)
    # The first prompt of each session: a resumed CLI still holds it, so a retry reads it too.
    conversations: dict[str, str] = field(default_factory=dict)
    scenes: "count[int]" = field(default_factory=lambda: count(1))

    async def run(
        self,
        role: Role,
        prompt: Prompt,
        conversation: str | None,
        turn: Turn | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RunResult:
        del turn, heard
        text = prompt.text
        spoken = Spoken(role=role, prompt=text, answer="")
        self.log.append(spoken)
        if conversation is None:
            first = asked = text
        else:
            first = self.conversations[conversation]
            asked = f"{first}\n\n{text}"
        conversation_id = f"{role}-{len(self.log)}"
        self.conversations[conversation_id] = first
        await sleep(self.delay)
        try:
            spoken.answer = await self._answer(role, asked, spoken)
        except (OSError, Refusal) as failed:
            spoken.error = f"{type(failed).__name__}: {failed}"
            raise
        return RunResult(spoken.answer, conversation_id)

    async def _answer(self, role: Role, prompt: str, spoken: Spoken) -> str:
        armed = self.faults.get(role, [])
        if armed:
            fault = armed.pop(0)
            if fault == "fail":
                raise Refusal(f"scripted: the {role} failed")
            if fault == "slow":
                await sleep(6)
            if fault == "bad":
                return "not json at all"
        if role == "master":
            await self._master(prompt, spoken)
            return "done"
        if role == "narrator":
            return self._narrator(prompt)
        return self._worldsmith(prompt)

    async def _master(self, prompt: str, spoken: Spoken) -> None:
        action = _section(prompt, "PLAYER ACTION")
        scripts = [line[1:].strip() for line in action.splitlines() if line.startswith("!")]
        if not scripts:
            if "The player chose the option above" in action:
                return
            name, args = DEFAULT_ROLLS[self._engine_id()]
            await self._call(name, args, spoken)
            return
        for script in scripts:
            words = shlex.split(script)
            head, rest = words[0], words[1:]
            match head:
                case "crash":
                    raise OSError("scripted: the game master crashed")
                case "refuse":
                    raise Refusal("scripted: the game master refused")
                case "none":
                    continue
                case "fail" | "bad" | "slow":
                    role = _role(rest[0])
                    # A failure holds through the retry: the ask fails, not one spawn of it.
                    times = RETRIES + 1 if head == "fail" else 1
                    self.faults.setdefault(role, []).extend([head] * times)
                case _:
                    await self._call(head, _args(rest), spoken)

    async def _call(self, name: str, args: dict[str, JsonValue], spoken: Spoken) -> None:
        try:
            answered = self._runtime().gate.require_turn().call(name, args)
        except Refusal as refused:
            answered = f"REFUSED: {refused}"
        spoken.calls.append((name, args, answered))
        LOGGER.info("master %s(%s) -> %s", name, json.dumps(args), answered.replace("\n", " | "))

    def _narrator(self, prompt: str) -> str:
        happened = _section(prompt, "WHAT HAPPENED")
        action = _section(prompt, "PLAYER ACTION")
        speak = re.search(r'\[say (\S+) "([^"]*)"\]', action)
        lines: list[dict[str, JsonValue]] = [
            {"speaker_id": None, "text": f"[narration] {action[:80]}"},
            {"speaker_id": None, "text": f"[happened] {happened.replace(chr(10), ' ')[:400]}"},
        ]
        if speak is not None:
            lines.append({"speaker_id": speak.group(1), "text": speak.group(2)})
        return json.dumps({"lines": lines})

    def _worldsmith(self, prompt: str) -> str:
        schema = _section(prompt, "ANSWER WITH")
        number = next(self.scenes)
        # A scene draft nests its cast sheet, so its schema also carries the hire probes below.
        if '"situation"' in schema:
            opening = _section(prompt, "THE SCENE NOW") == "(none yet)"
            return self._scene(schema, number, opening=opening)
        if '"places"' in schema:
            opening = "(no map yet)" in prompt
            room = f"qa-room-{number}"
            # Only a region written in play recaps what the player leaves; an opening map cannot.
            recap = (
                {"recap": f"Recap of the region before {number}."} if '"recap"' in schema else {}
            )
            return json.dumps(
                {
                    **recap,
                    "start_id": room,
                    "places": {
                        room: {
                            "id": room,
                            "name": f"QA Room {number}",
                            "brief": "A test room.",
                            "known": opening,
                            "description": f"Room {number}, written by the scripted worldsmith.",
                        }
                    },
                    "ways": {},
                    "npcs": {
                        f"qa-npc-{number}": {
                            "id": f"qa-npc-{number}",
                            "name": f"QA Npc {number}",
                            "brief": "A test dweller.",
                            "known": opening,
                            "place_id": room,
                            "hp": {"current": 8, "maximum": 8},
                        }
                    },
                    "items": {},
                }
            )
        if '"abilities"' in schema:
            return json.dumps({"abilities": {"brute": 1, "skulker": 1, "erudite": 1}})
        if '"specialty"' in schema:
            return json.dumps(
                {
                    "specialty": "Medic",
                    "skills": {"Medicine": 8},
                    "items": ["Med kit"],
                    "hindrances": [],
                }
            )
        raise Refusal(f"scripted: no worldsmith answer for this schema: {schema[:200]}")

    def _scene(self, schema: str, number: int, *, opening: bool) -> str:
        scene: dict[str, JsonValue] = {
            "place_id": f"qa-place-{number}",
            "title": f"QA Scene {number}",
            "situation": f"Scene {number}, written by the scripted worldsmith. Nothing is hidden.",
            "present": [f"qa-npc-{number}"],
            "hidden": [],
            "cast": {
                f"qa-npc-{number}": {
                    "id": f"qa-npc-{number}",
                    "name": f"QA Npc {number}",
                    "brief": "A test person.",
                }
            },
            "arc": "",
        }
        if '"location"' in schema:
            scene["location"] = "QA Harbour" if opening else ""
        if '"recap"' in schema:
            scene["recap"] = f"Recap of the scene before {number}."
        return json.dumps(scene)

    def _runtime(self) -> Runtime:
        assert self.runtime is not None
        return self.runtime

    def _engine_id(self) -> str:
        playing = self._runtime().gate.turn
        assert playing is not None
        return playing.engine.id


def _section(prompt: str, name: str) -> str:
    match = re.search(rf"^# {re.escape(name)}[^\n]*\n(.*?)(?=^# |\Z)", prompt, re.S | re.M)
    return match.group(1).strip() if match else ""


def _role(word: str) -> Role:
    match word:
        case "master" | "narrator" | "worldsmith":
            return word
        case _:
            raise Refusal(f"scripted: no role {word!r}")


def _args(words: Sequence[str]) -> dict[str, JsonValue]:
    args: dict[str, JsonValue] = {}
    for word in words:
        key, _, raw = word.partition("=")
        try:
            args[key] = json.loads(raw)
        except ValueError:
            args[key] = raw
    return args
