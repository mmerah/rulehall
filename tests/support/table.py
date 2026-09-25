import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from itertools import islice
from pathlib import Path
from random import Random

import pytest
from pydantic import BaseModel, JsonValue, SecretStr
from pydantic_settings import SettingsConfigDict

from rulehall.app.launch import LaunchTarget
from rulehall.app.runtime import Runtime
from rulehall.app.session import GameService
from rulehall.app.spawn import RunResult
from rulehall.app.turn import Turn
from rulehall.config import ProviderConfig, Providers, Role, Settings
from rulehall.core.facts import Fact
from rulehall.core.io import Library
from rulehall.core.model import AnyGame, Check, RoleAnswer
from rulehall.core.play import Answer
from rulehall.core.prompt import Prompt
from rulehall.core.validation import EngineId, Refusal, Slug
from rulehall.engines.engine import AnyEngine
from rulehall.engines.registry import build_engines

# One tool call as a scripted game master makes it.
type Scripted = tuple[str, dict[str, JsonValue]]


class EnvFileFreeSettings(Settings):
    """The checkout's .env must not leak into tests; monkeypatched env vars still apply."""

    model_config = SettingsConfigDict(env_file=None)


REPOSITORY_ROOT = Path(__file__).parents[2]
SCENARIOS = REPOSITORY_ROOT / "scenarios"
CHARACTERS = REPOSITORY_ROOT / "characters"
# never exists: tests must not read the player's packs
NO_PACKS = REPOSITORY_ROOT / "tests" / "no-packs"
# never exists: a test names every root it reads
NO_SHIPPED = REPOSITORY_ROOT / "tests" / "no-shipped"
LIBRARY = Library(SCENARIOS, CHARACTERS, NO_SHIPPED)
LONER3E = EngineId("loner3e")
TUNNELGOONS = EngineId("tunnelgoons")
TWENTYFOURXX = EngineId("twentyfourxx")
POKEMON = EngineId("pokemon")
ENGINES_BUILT = build_engines(NO_PACKS)
ENGINE_IDS = tuple(ENGINES_BUILT)
SCENARIO_MODELS = {engine_id: engine.scenario for engine_id, engine in ENGINES_BUILT.items()}


def updated[T: BaseModel](model: T, **changes: object) -> T:
    """A validating copy. Production commits once per turn; a test wants the check right here."""
    return type(model).model_validate(model.model_dump(round_trip=True) | changes)


def scenario_for(engine_id: EngineId) -> Slug:
    """Read off the shipped content rather than tabulated, so a second one fails here loudly."""
    matches = [
        slug
        for slug, scenario in LIBRARY.read_scenarios(SCENARIO_MODELS)
        if scenario.engine_id == engine_id
    ]
    if len(matches) != 1:
        raise ValueError(f"{engine_id!r} ships {len(matches)} scenarios, not one: {matches}")
    return matches[0]


def game(engine_id: EngineId) -> tuple[AnyEngine, AnyGame]:
    engine = ENGINES_BUILT[engine_id]
    scenario_id = scenario_for(engine_id)
    selected_scenario = LIBRARY.read_scenario(scenario_id, SCENARIO_MODELS)
    selected_character = LIBRARY.read_character("kael", engine.id, engine.character)
    begun = engine.begin(scenario_id, selected_scenario, selected_character)
    return engine, begun


def change(engine: AnyEngine, draft: AnyGame, name: str, /, **args: JsonValue) -> list[Fact]:
    """`name` is positional-only: a tool's own `name` field must pass through as an argument."""
    return list(engine.tools[name].call(draft, args, Random(0)))


def run_action(engine: AnyEngine, draft: AnyGame, name: str, /, **args: JsonValue) -> list[Fact]:
    return list(engine.actions[name](draft, args, Random(0)))


def refused(engine: AnyEngine, draft: AnyGame, name: str, /, **args: JsonValue) -> str:
    with pytest.raises(Refusal) as raised:
        _ = change(engine, draft, name, **args)
    return str(raised.value)


def tool_call(name: str, **args: JsonValue) -> Scripted:
    return name, args


def the_way_on() -> Scripted:
    return "next_scene", {}


def narrated(body: str, speaker_id: str | None = None) -> str:
    return json.dumps({"lines": [{"speaker_id": speaker_id, "text": body}]})


def offline_settings(saves: Path | None = None, scenarios: Path = SCENARIOS) -> Settings:
    """A fake key lets a test switch media on."""
    return EnvFileFreeSettings(
        providers=Providers(
            openrouter=ProviderConfig(
                base_url="https://example.invalid/v1", api_key=SecretStr("test")
            )
        ),
        saves_dir=Path("saves") if saves is None else saves,
        scenarios_dir=scenarios,
        characters_dir=CHARACTERS,
        packs_dir=NO_PACKS,
    )


@dataclass(slots=True)
class ScriptedSpawner:
    """Answers from a per-role list and records every prompt it was given."""

    turns: list[Callable[[], None]] = field(default_factory=list)
    answers: dict[Role, list[str]] = field(default_factory=dict)
    prompts: list[tuple[Role, str]] = field(default_factory=list)
    hooks: list[Callable[[Role, str], Awaitable[None]]] = field(default_factory=list)

    async def run(
        self,
        role: Role,
        prompt: Prompt,
        conversation: str | None,
        turn: Turn | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RunResult:
        del conversation, turn
        text = prompt.text
        for hook in self.hooks:
            await hook(role, text)
        self.prompts.append((role, text))
        # A conversation every time, so a test exercises the resumed path the real CLIs take.
        spoke = partial(RunResult, conversation=f"{role}-1")
        if role == "master":
            if self.turns:
                self.turns.pop(0)()
            return spoke(text)
        answers = self.answers.get(role)
        if not answers:
            raise Refusal(f"the scripted {role} has no answer left")
        answer = answers.pop(0)
        if heard is not None:
            heard(answer)
        return spoke(answer)

    def prompt(self, role: Role, nth: int = 0) -> str:
        """The nth prompt the role was given; the golden prompts come from here."""
        matches = (text for name, text in self.prompts if name == role)
        return next(islice(matches, nth, None))


def stub_worldsmith(answer: Mapping[str, object]) -> RoleAnswer:
    async def answered[M: BaseModel](_prompt: Prompt, model: type[M], _check: Check[M]) -> M:
        return model.model_validate_json(json.dumps(answer))

    return answered


@dataclass(slots=True)
class Table[G: AnyGame]:
    """A live game and the tool surface a scripted game master plays it through."""

    runtime: Runtime
    service: GameService
    spawner: ScriptedSpawner
    state_type: type[G]
    refusals: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)

    def call(self, name: str, args: dict[str, JsonValue]) -> str:
        """A refusal is an error result the CLI reads and carries on from, not a crash."""
        try:
            answered = self.runtime.gate.require_turn().call(name, args)
        except Refusal as refused:
            self.refusals.append(str(refused))
            answered = str(refused)
        self.answers.append(answered)
        return answered

    def plays(self, calls: Sequence[Scripted]) -> Callable[[], None]:
        def run() -> None:
            for name, args in calls:
                _ = self.call(name, args)
            # Snapshotted here: the service drops the turn once it is filed.
            if (turn := self.service.turn) is not None:
                self.facts = list(turn.facts)

        return run

    @property
    def state(self) -> G:
        state = self.service.state
        assert isinstance(state, self.state_type), (
            f"the service holds an unexpected {self.state_type.__name__}"
        )
        return state

    def saved(self) -> G:
        raw = self.service.store.read(self.service.target.slug)
        assert raw is not None
        restored = self.service.engine.restore(raw)
        assert isinstance(restored, self.state_type), (
            f"the save restored an unexpected {self.state_type.__name__}"
        )
        return restored


def open_table[G: AnyGame](
    saves: Path,
    *,
    engine_id: EngineId,
    state_type: type[G],
    rng: Random | None = None,
    settings: Settings | None = None,
    engine: AnyEngine | None = None,
) -> Table[G]:
    settings = settings or offline_settings(saves)
    spawner = ScriptedSpawner()
    runtime = Runtime(settings, spawner=spawner)
    selected_engine = ENGINES_BUILT[engine_id] if engine is None else engine
    runtime.engines[engine_id] = selected_engine
    scenario_id = scenario_for(engine_id)
    service = runtime.session(LaunchTarget(scenario_id=scenario_id, character_id="kael"))
    if rng is not None:
        service.rng = rng
    return Table(runtime=runtime, service=service, spawner=spawner, state_type=state_type)


async def play_turn[G: AnyGame](
    table: Table[G],
    prompt: str | Answer,
    *calls: Scripted,
    narration: str = "You wait.",
    arrival: str | None = None,
    way_on: Slug | None = None,
    then: Sequence[str] = (),
) -> G:
    """`then` queues answers for a spawn after the turn, such as the battle-end narration."""
    table.spawner.turns.append(table.plays(calls))
    canned = table.spawner.answers.setdefault("narrator", [])
    canned.append(narrated(narration))
    # The arrival is its own narrator spawn, so a turn that installs a scene answers twice.
    if arrival is not None:
        canned.append(narrated(arrival))
    canned.extend(then)
    if way_on is not None:
        assert isinstance(prompt, str)
        await table.service.take_way_on(way_on, prompt)
    else:
        answer = Answer(text=prompt) if isinstance(prompt, str) else prompt
        await table.service.play(answer)
    return table.state


def narrowed[M](value: object, model: type[M]) -> M:
    assert isinstance(value, model), f"{type(value).__name__} is not a {model.__name__}"
    return value
