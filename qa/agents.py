"""Scripted stand-ins for the three AI roles, driven from the player's own words.

The master reads PLAYER ACTION from its prompt like the real one. A line that starts with `!` is
a script: `!ask question="Does the door give?"` calls that tool,
`!crash` and `!refuse` fail the master's run, `!fail narrator` fails another role's next ask,
`!bad worldsmith` makes one answer garbage so the retry lands, `!hold narrator` holds its next
ask until `release`.
Plain words with no script get one engine-appropriate roll, so dice show up in the page; a
Loner question the player asks is rolled as `ask(question: null)`.

The narrator echoes what it was given, so every screenshot shows what the page was told. The
worldsmith answers each request shape with a small valid draft; a Pokemon region carries the evil
team's operation or its lair when the request asks. The opponent takes its first choice.
"""

import json
import logging
import re
import shlex
from asyncio import Event, sleep
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import Literal

from pydantic import JsonValue

from rulehall.app.roles import RoleReply
from rulehall.app.runtime import Runtime
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal

LOGGER = logging.getLogger("qa.agents")

type Fault = Literal["fail", "bad", "hold"]

DEFAULT_ROLLS: dict[str, tuple[str, dict[str, JsonValue]]] = {
    "loner4e": ("ask", {"question": "Does the player get what they want?"}),
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
    delay: float = 0
    runtime: Runtime | None = None
    faults: dict[Role, list[Fault]] = field(default_factory=dict)
    holds: dict[Role, Event] = field(default_factory=dict)
    log: list[Spoken] = field(default_factory=list)
    # The first prompt of each session: a resumed CLI still holds it, so a retry reads it too.
    first_prompts: dict[str, str] = field(default_factory=dict)
    scenes: "count[int]" = field(default_factory=lambda: count(1))

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        resume_id: str | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RoleReply:
        del heard
        text = prompt.text
        if resume_id is None:
            first = asked = text
        else:
            first = self.first_prompts[resume_id]
            asked = f"{first}\n\n{text}"
        next_resume_id = f"{role}-{len(self.log) + 1}"
        self.first_prompts[next_resume_id] = first
        spoken = await self._spoken(role, asked, text)
        return RoleReply(spoken.answer, next_resume_id)

    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None:
        del turn
        _ = await self._spoken("master", prompt.text, prompt.text)

    def arm(self, role: str, fault: str) -> None:
        self.faults.setdefault(_role(role), []).append(_fault(fault))

    def release(self, role: str | None = None) -> None:
        """Drops the armed holds of `role`, or of every role, and lets a waiting one answer."""
        released_roles: list[Role] = [*self.faults, *self.holds] if role is None else [_role(role)]
        for released in released_roles:
            armed = self.faults.get(released, [])
            self.faults[released] = [fault for fault in armed if fault != "hold"]
            if (held := self.holds.pop(released, None)) is not None:
                held.set()

    async def _spoken(self, role: Role, asked: str, text: str) -> Spoken:
        spoken = Spoken(role=role, prompt=text, answer="")
        self.log.append(spoken)
        await sleep(self.delay)
        try:
            spoken.answer = await self._answer(role, asked, spoken)
        except (OSError, Refusal) as failed:
            spoken.error = f"{type(failed).__name__}: {failed}"
            raise
        return spoken

    async def _answer(self, role: Role, prompt: str, spoken: Spoken) -> str:
        armed = self.faults.get(role, [])
        if armed:
            fault = armed.pop(0)
            if fault == "fail":
                raise Refusal(f"scripted: the {role} failed")
            if fault == "hold":
                held = self.holds[role] = Event()
                await held.wait()
            if fault == "bad":
                return "not json at all"
        if role == "master":
            await self._master(prompt, spoken)
            return "done"
        if role == "narrator":
            return self._narrator(prompt)
        if role == "opponent":
            return self._opponent(prompt)
        return self._worldsmith(prompt)

    async def _master(self, prompt: str, spoken: Spoken) -> None:
        action = _section(prompt, "PLAYER ACTION")
        scripts = [line[1:].strip() for line in action.splitlines() if line.startswith("!")]
        if not scripts:
            if "The player chose the option above" in action:
                return
            if _section(prompt, "THE PLAYER ASKS"):
                await self._call("ask", {"question": None}, spoken)
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
                case "fail" | "bad" | "hold":
                    self.arm(rest[0], head)
                case _:
                    await self._call(head, _args(rest), spoken)

    async def _call(self, name: str, args: dict[str, JsonValue], spoken: Spoken) -> None:
        try:
            answered = self._runtime().gate.require_turn().call_tool(name, args)
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

    def _opponent(self, prompt: str) -> str:
        first = re.search(r"^- (\w+ \d+):", _section(prompt, "THE CHOICES"), re.M)
        if first is None:
            raise Refusal("scripted: the opponent was offered no choice")
        return json.dumps({"command": first.group(1)})

    def _worldsmith(self, prompt: str) -> str:
        schema = _section(prompt, "ANSWER WITH")
        number = next(self.scenes)
        if '"boss_id"' in schema:
            asked = f"{_section(prompt, 'WHAT COMES NEXT')}\n{_section(prompt, 'DUE')}"
            return self._pokemon_region(asked, number)
        if '"ally"' in schema:
            return self._meanwhile(prompt, schema, number)
        if '"events"' in schema:
            return json.dumps(
                {
                    "people": [{"entity_id": "player", "line": f"People line {number}."}],
                    "places": [f"Places line {number}."],
                    "events": [f"Events line {number}."],
                }
            )
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
        sheet: dict[str, JsonValue] = {
            "specialty": "Medic",
            "origin": "Human",
            "increases": ["Medicine", "Piloting", "Labor"],
        }
        if '"sheet"' in schema:
            return json.dumps(
                {"name": f"QA Newcomer {number}", "brief": "A test operator.", "sheet": sheet}
            )
        if '"specialty"' in schema:
            return json.dumps(sheet)
        raise Refusal(f"scripted: no worldsmith answer for this schema: {schema[:200]}")

    def _pokemon_region(self, asked: str, number: int) -> str:
        room, person = f"qa-room-{number}", f"qa-chief-{number}"
        lair = "`boss_id`" in asked
        region: dict[str, JsonValue] = {
            "recap": f"Recap of the region before {number}.",
            "start_id": room,
            "places": {
                room: {
                    "id": room,
                    "name": f"QA Room {number}",
                    "brief": "A test room.",
                    "known": False,
                    "description": f"Room {number}, written by the scripted worldsmith.",
                }
            },
            "ways": {},
            "npcs": {
                person: {
                    "id": person,
                    "name": f"QA {'Boss' if lair else 'Chief'} {number}",
                    "brief": "A test member of the team.",
                    "known": False,
                    "place_id": room,
                    "roster": [{"species_id": "zubat", "level": 10}],
                    "style": "attacks at once",
                    "win_line": f"Win line {number}.",
                    "lose_line": f"Lose line {number}.",
                    "avatar_id": "roughneck",
                }
            },
            "items": {},
        }
        if "write `operation`" in asked:
            region["operation"] = {
                "place_id": room,
                "leader_id": person,
                "goal": f"Grunts dig under room {number}.",
                "consequence": "close_center",
            }
        if lair:
            region["boss_id"] = person
        return json.dumps(region)

    def _scene(self, schema: str, number: int, *, opening: bool) -> str:
        scene: dict[str, JsonValue] = {
            "place_id": f"qa-place-{number}",
            "title": f"QA Scene {number}",
            "situation": f"Scene {number}, written by the scripted worldsmith. Nothing is hidden.",
            "present_ids": [f"qa-npc-{number}"],
            "hidden_ids": [],
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
        if '"details"' in schema:
            scene["goal"] = f"Get through scene {number}"
            scene["details"] = ["Scripted Fog", "Loose Stones"]
        return json.dumps(scene)

    def _meanwhile(self, prompt: str, schema: str, number: int) -> str:
        """Moves the first cast entry off screen as the ally on a yes, and the second as the
        power."""
        away: list[str] = []
        for block in re.split(r"^- ", _section(prompt, "THE WHOLE CAST"), flags=re.M)[1:]:
            entity_id = re.search(r"\[([a-z0-9-]+)\]", block)
            if entity_id is None or entity_id.group(1) == "player" or "travels with" in block:
                continue
            away.append(entity_id.group(1))
        updates: list[JsonValue] = [
            {"entity_id": entity_id, "kind": "condition", "gained": [f"Qa Moved {number}"]}
            for entity_id in away[:2]
        ]
        ally = updates.pop(0) if updates and 'The oracle said "yes' in prompt else None
        dramatic = "write the next scene in `scene`" in prompt
        scene = json.loads(self._scene(schema, number, opening=False)) if dramatic else None
        return json.dumps({"power": updates, "ally": ally, "scene": scene})

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


def _fault(word: str) -> Fault:
    match word:
        case "fail" | "bad" | "hold":
            return word
        case _:
            raise Refusal(f"scripted: no fault {word!r}")


def _args(words: Sequence[str]) -> dict[str, JsonValue]:
    args: dict[str, JsonValue] = {}
    for word in words:
        key, _, raw = word.partition("=")
        try:
            args[key] = json.loads(raw)
        except ValueError:
            args[key] = raw
    return args
