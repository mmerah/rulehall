from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any, Protocol

from pydantic import BaseModel

from rulehall.core.creation import CreationStep, Picks, check_picks
from rulehall.core.facts import Fact
from rulehall.core.io import decode, read_cached_text, read_model
from rulehall.core.model import (
    AnyCharacter,
    AnyScenario,
    EngineHeader,
    Game,
    RoleAnswer,
    Scenario,
    ScenarioMeta,
    WorldsmithRequest,
)
from rulehall.core.play import Cause, Chapter, Exchange, PendingOption, Refused, SpokenLine
from rulehall.core.prompt import Prompt, Sections, sections
from rulehall.core.tools import Call, MasterTool, actions_of, tool, tools_of
from rulehall.core.validation import EngineId, Refusal, Slug, parse, parse_json, slug
from rulehall.core.views import Choice, Look, NarratorView, PlayerView, Rows, Sprite
from rulehall.engines.args import Direct, Kill, LeaveParty, Reveal
from rulehall.engines.entities import PLAYER_ID, OpeningProposal, Person, World
from rulehall.engines.packs import (
    Pack,
    PackBody,
    PackHead,
    PackSet,
    read_packs,
)
from rulehall.engines.worldsmith import BODY_ASK, HEAD_ASK, PACK_SO_FAR, render_worldsmith

type AnyEngine = Engine[Any, Any]


@dataclass(frozen=True, slots=True)
class Resolution:
    facts: tuple[Fact, ...]
    narrator_cue: str | None


class Transport(Protocol):
    async def send(self, lines: Sequence[str]) -> None: ...
    async def receive(self) -> tuple[str, ...]: ...
    async def close(self) -> None: ...


class BattleRun[G](Protocol):
    @property
    def log(self) -> Sequence[str]: ...
    @property
    def facts(self) -> Sequence[Fact]: ...
    def props(self) -> Mapping[str, str | bool]: ...
    @property
    def resolution(self) -> Resolution | None: ...
    def choices(self) -> tuple[Choice, ...]: ...
    async def choose(self, draft: G, command: str, rng: Random) -> None: ...
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RequestHandler[W: World[Any]]:
    write: Callable[[Game[W], WorldsmithRequest, RoleAnswer], Awaitable[Resolution]]
    failure_fact: Fact


class Engine[W: World[Any], K: Pack](ABC):
    # Declared, not `ClassVar`: `type[W]` cannot be one.
    id: EngineId
    title: str
    worldsmith_guidance: str
    art_style: str
    portraits: bool = True
    directory: Path  # rules.md, look.json and a shipped packs/
    family_dir: Path
    assets: Path | None = None
    battle_script: Path | None = None
    world: type[W]
    pack: type[K]
    head: type[PackHead] = PackHead
    body: type[PackBody] = PackBody
    opening: type[OpeningProposal]
    scenario: type[AnyScenario]
    character: type[AnyCharacter]
    packs: PackSet[K]
    instructions: str
    look: Look
    tools: dict[str, MasterTool]
    actions: dict[str, Call]
    worldsmith_role: str
    opening_sections: Sections
    opening_intent: str

    def __init__(self, player_packs: Path) -> None:
        self.packs = read_packs(self.id, self.directory / "packs", player_packs, self.pack)
        self.packs.srd()  # an engine that ships no srd pack is a bug, not a refusal
        self.instructions = (
            f"{read_cached_text(self.directory / 'rules.md')}\n"
            f"{read_cached_text(self.family_dir / 'rules.md')}"
        )
        self.look = read_model(self.directory / "look.json", Look)
        if (every := self.world.meanwhile_every) < 2:
            raise ValueError(f"the {self.id!r} engine runs the meanwhile every {every} turns")
        self.tools = tools_of(self, lambda draft, texts: draft.world.check_unnamed(*texts))
        self.actions = actions_of(self)
        self.worldsmith_role = read_cached_text(self.family_dir / "worldsmith.md")
        self.scenario = Scenario[self.opening]

    @tool
    def reveal(self, draft: Game[W], args: Reveal, _rng: Random) -> list[Fact]:
        """Make a hidden entity here known to the player."""
        return draft.world.reveal_hidden(args.target_id)

    @tool
    def kill(self, draft: Game[W], args: Kill, _rng: Random) -> list[Fact]:
        """Kill someone here."""
        return draft.world.kill(args.target_id)

    @tool
    def leave_party(self, draft: Game[W], args: LeaveParty, _rng: Random) -> list[Fact]:
        """Make a party member stop travelling with the player."""
        return draft.world.leave_party(args.target_id)

    @tool
    def direct(self, draft: Game[W], args: Direct, _rng: Random) -> list[Fact]:
        """Call this last, once per turn. It ends the turn and gives notes to the narrator.
        Include the answer or result, its known reason, and facts needed for the next choice.
        Share only facts the player can know now. Use reveal first for hidden entities.
        Apply world changes through the other tools before calling direct."""
        draft.directed = True
        return [Fact(trace=f"the game master directs: {args.text}", told=True)]

    def install_pack(self, pack_id: Slug, pack: K) -> None:
        packs = self.packs
        self.packs = PackSet(packs.engine_id, packs.shipped, {**packs.written, pack_id: pack})

    def guidance_for(self, pack_id: Slug, /, *, opening: bool) -> str:
        block = self.packs.guidance(pack_id, opening=opening)
        return f"{self.worldsmith_guidance}\n\n{block}" if block else self.worldsmith_guidance

    def preview_character(self, character: AnyCharacter) -> Rows:
        return self.player_of(character).rows()

    def restore(self, raw: str) -> Game[W]:
        if (header := parse(EngineHeader, decode(raw))).engine_id != self.id:
            raise Refusal(f"the save plays {header.engine_id!r}, not {self.id!r}")
        state = parse_json(Game[self.world], raw)
        if state.request is not None:
            raise Refusal("the save carries a pending request")
        self.validate(state)
        self.packs.require(state.pack_id)
        return state

    def require_tool(self, name: str) -> MasterTool:
        found = self.tools.get(name)
        if found is None:
            raise Refusal(f"{name!r} is not a tool of the {self.id!r} engine.")
        return found

    def play_option(self, draft: Game[W], chosen: PendingOption, rng: Random) -> tuple[Fact, ...]:
        if chosen.refusal:
            raise Refusal(f"{chosen.name}: {chosen.refusal}")
        found = self.actions.get(chosen.action_name)
        if found is None:
            raise Refusal(f"{chosen.action_name!r} is not an action of the {self.id!r} engine.")
        return found(draft, chosen.args, rng)

    def in_battle(self, _state: Game[W], /) -> bool:
        return False

    def simulator_argv(self) -> tuple[str, ...]:
        raise NotImplementedError(f"the {self.id!r} engine runs no battle")

    async def open_battle(
        self, draft: Game[W], transport: Transport, opponent: RoleAnswer | None
    ) -> BattleRun[Game[W]]:
        raise NotImplementedError(f"the {self.id!r} engine runs no battle")

    def sprite(self, _state: Game[W], _entity_id: Slug, /) -> Sprite | None:
        return None

    def render_request(
        self, draft: Game[W], *, intent: str, guidance: str, answer_model: type[BaseModel]
    ) -> Prompt:
        return render_worldsmith(
            self.worldsmith_role,
            source=draft.source,
            backdrop=draft.scenario.backdrop,
            scope=draft.scenario.scope,
            world_sections=self.worldsmith_sections(draft),
            intent=intent,
            guidance=guidance,
            answer_model=answer_model,
        )

    def sheet_character(self, name: str, sheet: BaseModel) -> AnyCharacter:
        return self.character(id=slug(name, ()), engine_id=self.id, sheet=sheet)

    def build_scenario(
        self, meta: ScenarioMeta, pack_id: Slug, proposal: OpeningProposal, source: str
    ) -> AnyScenario:
        """No check here: `begin` is the one check an opening meets, and `check` always runs it."""
        return self.scenario(
            meta=meta.model_copy(update={"premise": meta.premise or proposal.premise()}),
            engine_id=self.id,
            pack_id=pack_id,
            source=source,
            opening=proposal,
        )

    async def write_opening(
        self,
        meta: ScenarioMeta,
        source: str,
        pack_id: Slug,
        worldsmith: RoleAnswer,
        check: Callable[[AnyScenario], None],
    ) -> AnyScenario:
        def built(proposal: OpeningProposal) -> AnyScenario:
            return self.build_scenario(meta, pack_id, proposal, source)

        prompt = render_worldsmith(
            self.worldsmith_role,
            source=source,
            backdrop=meta.backdrop,
            scope=meta.scope,
            world_sections=self.opening_sections,
            intent=self.opening_intent,
            guidance=self.guidance_for(pack_id, opening=True),
            answer_model=self.opening,
        )
        return built(await worldsmith(prompt, self.opening, lambda answer: check(built(answer))))

    async def write_pack(
        self, *, name: str, source: str, origin: str, license: str, worldsmith: RoleAnswer
    ) -> K:
        def built(from_head: PackHead, from_body: PackBody | None) -> K:
            return parse(
                self.pack,
                {
                    "name": name,
                    # The pack's `source` is its provenance; the material it was
                    # written from is not kept.
                    "source": origin,
                    "license": license,
                    **from_head.pack_fields(),
                    **({} if from_body is None else from_body.model_dump()),
                },
            )

        def check_head(answer: PackHead) -> None:
            built(answer, None)

        def asked(intent: str, world_sections: Sections, answer_model: type[BaseModel]) -> Prompt:
            return render_worldsmith(
                self.worldsmith_role,
                source=source,
                scope="",
                world_sections=world_sections,
                intent=intent,
                guidance=self.worldsmith_guidance,
                answer_model=answer_model,
            )

        head = await worldsmith(asked(HEAD_ASK, (), self.head), self.head, check_head)
        so_far = ((PACK_SO_FAR, sections(built(head, None).sections(opening=True))),)

        def check_body(answer: PackBody) -> None:
            built(head, answer)

        body = await worldsmith(asked(BODY_ASK, so_far, self.body), self.body, check_body)
        return built(head, body)

    def record(
        self,
        draft: Game[W],
        lines: tuple[SpokenLine, ...],
        facts: tuple[Fact, ...],
        *,
        words: str = "",
        cause: Cause | None = None,
        refused: tuple[Refused, ...] = (),
    ) -> Game[W]:
        exchange = Exchange(
            words=words,
            cause=cause,
            lines=lines,
            facts=facts,
            refused=refused,
            decision="" if draft.pending is None else draft.pending.prompt,
            context=self.context_lines(draft),
        )
        draft.log[-1].exchanges.append(exchange)
        return self.accept(draft)

    def open_chapter(self, draft: Game[W]) -> None:
        if draft.log and not draft.log[-1].exchanges:
            draft.log.pop()
        draft.log.append(
            Chapter(title=self.narrator_view(draft).title, context=self.context_lines(draft))
        )

    def accept(self, draft: Game[W]) -> Game[W]:
        self.validate(draft)
        return draft.commit()

    def count_turn(self, draft: Game[W]) -> None:
        draft.world.count_turn()

    def begin(self, scenario_id: Slug, scenario: AnyScenario, character: AnyCharacter) -> Game[W]:
        if scenario.engine_id != self.id:
            raise Refusal(
                f"{scenario_id!r} is authored for the {scenario.engine_id!r} rules. "
                f"The {self.id!r} engine does not play them."
            )
        if character.engine_id != self.id:
            raise Refusal(
                f"{character.id!r} is written for the {character.engine_id!r} rules. "
                f"The {self.id!r} engine does not play them."
            )
        self.packs.require(scenario.pack_id)
        state = parse(
            Game[self.world],
            {
                "scenario_id": scenario_id,
                "character_id": character.id,
                "scenario": scenario.meta,
                "engine_id": self.id,
                "pack_id": scenario.pack_id,
                "source": scenario.source,
                "world": self.new_game(scenario, character),
            },
        )
        self.open_chapter(state)
        return self.accept(state)

    def player_as[S: Person](self, character: AnyCharacter, sheet: type[S]) -> S:
        if character.sheet.id != PLAYER_ID or not character.sheet.known:
            raise Refusal("a character sheet is the player's: the id is 'player', and it is known")
        if not isinstance(character.sheet, sheet):
            raise Refusal(f"{character.id!r} is not a {self.title} sheet")
        return deepcopy(character.sheet)

    def ending(self, state: Game[W]) -> str | None:
        return "You died." if not state.world.player.alive else None

    def create_character(self, name: str, brief: str, pack_id: Slug, picks: Picks) -> AnyCharacter:
        check_picks(self.creation_steps(pack_id, picks), picks)
        return self.build_character(name, brief, pack_id, picks)

    def validate(self, state: Game[W]) -> None:
        """A family adds its own check after `super()`."""
        if not state.log:
            raise Refusal(f"a {self.id!r} game has no chapter open")
        request = state.request
        if request is not None and request.kind not in self.request_handlers():
            raise Refusal(f"the {self.id!r} engine writes no {request.kind!r}")

    @abstractmethod
    def player_of(self, character: AnyCharacter) -> Person: ...
    @abstractmethod
    def creation_steps(self, pack_id: Slug, picks: Picks, /) -> tuple[CreationStep, ...]: ...
    @abstractmethod
    def build_character(
        self, name: str, brief: str, pack_id: Slug, picks: Picks, /
    ) -> AnyCharacter: ...
    @abstractmethod
    def new_game(self, scenario: AnyScenario, character: AnyCharacter) -> W: ...
    @abstractmethod
    def master_sections(self, state: Game[W]) -> Sections: ...
    @abstractmethod
    def worldsmith_sections(self, draft: Game[W], /) -> Sections: ...
    @abstractmethod
    def narrator_view(self, state: Game[W]) -> NarratorView: ...
    @abstractmethod
    def context_lines(self, state: Game[W], /) -> str: ...
    @abstractmethod
    def player_view(self, state: Game[W]) -> PlayerView: ...
    @abstractmethod
    def take_way_on(self, draft: Game[W], way_on_id: Slug, words: str, /) -> None:
        """The way-on button against the state now: refuse it stale, else request or note."""

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {}
