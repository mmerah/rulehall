import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from random import Random

import pytest
from pydantic import BaseModel, JsonValue, SecretStr
from pydantic_settings import SettingsConfigDict

from rulehall.app.catalog import SavedGameKey
from rulehall.app.game_session import GameSession
from rulehall.app.runtime import Runtime
from rulehall.app.turn import Turn
from rulehall.config import ProviderConfig, Providers, Role, Settings
from rulehall.core.decisions import ActionOption, PlayerInput
from rulehall.core.facts import Fact
from rulehall.core.game import AnyGame, Check, RoleAnswer
from rulehall.core.prompt import Prompt
from rulehall.core.stores import Library
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
LONER4E = EngineId("loner4e")
TUNNELGOONS = EngineId("tunnelgoons")
TWENTYFOURXX = EngineId("twentyfourxx")
POKEMON = EngineId("pokemon")
ENGINES_BUILT = build_engines(NO_PACKS)
ENGINE_IDS = tuple(ENGINES_BUILT)
SCENARIO_MODELS = {engine_id: engine.scenario_model for engine_id, engine in ENGINES_BUILT.items()}


def updated[T: BaseModel](model: T, **changes: object) -> T:
    """A validating copy. Production commits once per turn; a test wants the check right here."""
    return type(model).model_validate(model.model_dump(round_trip=True) | changes)


def scenario_for(engine_id: EngineId) -> Slug:
    """Read off the shipped content rather than tabulated, so a second one fails here loudly."""
    matches = [
        scenario_id
        for scenario_id, scenario in LIBRARY.read_scenarios(SCENARIO_MODELS)
        if scenario.engine_id == engine_id
    ]
    if len(matches) != 1:
        raise ValueError(f"{engine_id!r} ships {len(matches)} scenarios, not one: {matches}")
    return matches[0]


def game(engine_id: EngineId) -> tuple[AnyEngine, AnyGame]:
    engine = ENGINES_BUILT[engine_id]
    scenario_id = scenario_for(engine_id)
    selected_scenario = LIBRARY.read_scenario(scenario_id, SCENARIO_MODELS)
    selected_character = LIBRARY.read_character("kael", engine.id, engine.character_model)
    begun = engine.begin(scenario_id, selected_scenario, selected_character)
    return engine, begun


def change(engine: AnyEngine, draft: AnyGame, name: str, /, **args: JsonValue) -> list[Fact]:
    """`name` is positional-only: a tool's own `name` field must pass through as an argument."""
    return list(engine.call_tool(draft, name, args, Random(0)))


def run_action(engine: AnyEngine, draft: AnyGame, name: str, /, **args: JsonValue) -> list[Fact]:
    option = ActionOption(id="chosen", name=name, action_name=name, args=args)
    return list(engine.play_option(draft, option, Random(0)))


def refused(engine: AnyEngine, draft: AnyGame, name: str, /, **args: JsonValue) -> str:
    with pytest.raises(Refusal) as raised:
        _ = change(engine, draft, name, **args)
    return str(raised.value)


def tool_call(name: str, **args: JsonValue) -> Scripted:
    return name, args


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
class ScriptedRoles:
    """Answers from a per-role list and records every prompt it was given."""

    turns: list[Callable[[], None]] = field(default_factory=list)
    answers: dict[Role, list[str]] = field(default_factory=dict)
    prompts: list[tuple[Role, str]] = field(default_factory=list)
    hooks: list[Callable[[Role, str], Awaitable[None]]] = field(default_factory=list)

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        heard: Callable[[str], None] | None = None,
    ) -> str:
        await self._record(role, prompt)
        answers = self.answers.get(role)
        if not answers:
            raise Refusal(f"the scripted {role} has no answer left")
        answer = answers.pop(0)
        if heard is not None:
            heard(answer)
        return answer

    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None:
        del turn
        await self._record("master", prompt)
        if self.turns:
            self.turns.pop(0)()

    def prompt(self, role: Role, nth: int = 0) -> str:
        """The nth prompt the role was given; the golden prompts come from here."""
        matches = (text for name, text in self.prompts if name == role)
        return next(islice(matches, nth, None))

    async def _record(self, role: Role, prompt: Prompt) -> None:
        for hook in self.hooks:
            await hook(role, prompt.text)
        self.prompts.append((role, prompt.text))


def stub_worldsmith(answer: Mapping[str, object]) -> RoleAnswer:
    async def answered[M: BaseModel](_prompt: Prompt, model: type[M], _check: Check[M]) -> M:
        return model.model_validate_json(json.dumps(answer))

    return answered


@dataclass(slots=True)
class Table[G: AnyGame]:
    """A live game and the tool surface a scripted game master plays it through."""

    runtime: Runtime
    session: GameSession
    roles: ScriptedRoles
    state_type: type[G]
    refusals: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)

    def call(self, name: str, args: dict[str, JsonValue]) -> str:
        """A refusal is an error result the CLI reads and carries on from, not a crash."""
        try:
            answered = self.runtime.gate.require_turn().call_tool(name, args)
        except Refusal as refused:
            self.refusals.append(str(refused))
            answered = str(refused)
        self.answers.append(answered)
        return answered

    def plays(self, calls: Sequence[Scripted]) -> Callable[[], None]:
        def run() -> None:
            for name, args in calls:
                _ = self.call(name, args)
            # Snapshotted here: the session drops the turn once it is filed.
            if (turn := self.session.turn) is not None:
                self.facts = list(turn.facts)

        return run

    @property
    def state(self) -> G:
        state = self.session.state
        assert isinstance(state, self.state_type), (
            f"the session holds an unexpected {self.state_type.__name__}"
        )
        return state

    def saved(self) -> G:
        raw = self.session.store.read(self.session.key.save_id)
        assert raw is not None
        restored = self.session.engine.restore(raw)
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
    character_id: Slug = "kael",
) -> Table[G]:
    settings = settings or offline_settings(saves)
    roles = ScriptedRoles()
    runtime = Runtime(settings, roles=roles)
    selected_engine = ENGINES_BUILT[engine_id] if engine is None else engine
    runtime.engines[engine_id] = selected_engine
    scenario_id = scenario_for(engine_id)
    session = runtime.session_for(SavedGameKey(scenario_id=scenario_id, character_id=character_id))
    if rng is not None:
        session.rng = rng
    return Table(runtime=runtime, session=session, roles=roles, state_type=state_type)


async def play_turn[G: AnyGame](
    table: Table[G],
    prompt: str | PlayerInput,
    *calls: Scripted,
    narration: str = "You wait.",
    arrival: str | None = None,
    move: ActionOption | None = None,
    then: Sequence[str] = (),
) -> G:
    """`then` queues answers for a spawn after the turn, such as the battle-end narration."""
    table.roles.turns.append(table.plays(calls))
    canned = table.roles.answers.setdefault("narrator", [])
    canned.append(narrated(narration))
    # The arrival is its own narrator spawn, so a turn that installs a scene answers twice.
    if arrival is not None:
        canned.append(narrated(arrival))
    canned.extend(then)
    if isinstance(prompt, str):
        prompt = PlayerInput(option_id=None if move is None else move.id, text=prompt)
    await table.session.choose(prompt)
    return table.state


def narrowed[M](value: object, model: type[M]) -> M:
    assert isinstance(value, model), f"{type(value).__name__} is not a {model.__name__}"
    return value
