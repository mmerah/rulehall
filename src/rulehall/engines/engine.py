from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from random import Random
from typing import Any, Protocol

from pydantic import BaseModel, JsonValue

from rulehall.core.answer_repair import parse_with_repairs
from rulehall.core.creation import CreationStep, Picks, check_picks
from rulehall.core.decisions import ActionOption
from rulehall.core.facts import Fact
from rulehall.core.game import (
    AnyCharacter,
    AnyGame,
    AnyScenario,
    Character,
    Check,
    Game,
    RoleAnswer,
    Scenario,
    ScenarioDescription,
    WorldsmithRequest,
)
from rulehall.core.log import Cause, Chapter, LogEntry, RefusedCall, SpokenLine
from rulehall.core.prompt import Prompt, Sections, sections
from rulehall.core.stores import read_cached_text, read_model
from rulehall.core.tools import MasterTool, action, marked_methods, player_facing_texts, tool
from rulehall.core.validation import (
    EngineHeader,
    EngineId,
    Refusal,
    Slug,
    parse,
    parse_json,
    parse_strict_json,
    slug,
)
from rulehall.core.views import BattleChoice, Look, NarratorView, PlayerView, Rows, Sprite
from rulehall.engines.args import Direct, Kill, LeaveParty, Reveal
from rulehall.engines.packs import (
    Pack,
    PackBody,
    PackHead,
    PackSet,
    read_packs,
)
from rulehall.engines.sheet import PLAYER_ID, Person
from rulehall.engines.world import OpeningProposal, World
from rulehall.engines.worldsmith import BODY_ASK, HEAD_ASK, PACK_SO_FAR, render_worldsmith

type AnyEngine = Engine[Any, Any, Any, Any]


@dataclass(frozen=True, slots=True)
class Resolution:
    facts: tuple[Fact, ...]
    narrator_cue: str | None


@dataclass(frozen=True, slots=True)
class RequestHandler[W: World[Any]]:
    write: Callable[[Game[W], WorldsmithRequest, RoleAnswer], Awaitable[Resolution]]
    failure_fact: Fact


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
    def choices(self) -> tuple[BattleChoice, ...]: ...
    async def choose(self, draft: G, command: str, rng: Random) -> None: ...
    async def close(self) -> None: ...


class Revealing:
    @tool
    def reveal(self, draft: AnyGame, args: Reveal, _rng: Random) -> list[Fact]:
        """Make a hidden entity here known to the player. HIDDEN HERE lists what the player has
        not found: call this before you tell a hidden thing."""
        return draft.world.reveal_hidden(args.target_id)


class Engine[P: Person, W: World[Any], K: Pack, R: BaseModel](ABC):
    # Declared, not `ClassVar`: `type[W]` cannot be one.
    id: EngineId
    title: str
    worldsmith_guidance: str
    art_style: str
    portraits: bool = True
    directory: Path
    family_dir: Path
    assets: Path | None = None
    battle_script: Path | None = None
    person_model: type[P]
    world_model: type[W]
    pack_model: type[K]
    pack_head_model: type[PackHead] = PackHead
    pack_body_model: type[PackBody] = PackBody
    opening_model: type[OpeningProposal]
    scenario_model: type[AnyScenario]
    character_model: type[AnyCharacter]
    next_proposal_model: type[R]
    packs: PackSet[K]
    instructions: str
    look: Look
    tools: dict[str, MasterTool]
    actions: dict[str, MasterTool]
    worldsmith_role: str
    opening_sections: Sections
    opening_intent: str

    def __init__(self, player_packs: Path) -> None:
        self.packs = read_packs(self.id, self.directory / "packs", player_packs, self.pack_model)
        self.packs.srd()  # an engine that ships no srd pack is a bug, not a refusal
        self.instructions = (
            f"{read_cached_text(self.directory / 'rules.md')}\n"
            f"{read_cached_text(self.family_dir / 'rules.md')}"
        )
        self.look = read_model(self.directory / "look.json", Look)
        self.tools = marked_methods(self, "tool")
        self.actions = marked_methods(self, "action")
        self.worldsmith_role = read_cached_text(self.family_dir / "worldsmith.md")
        self.character_model = Character[self.person_model]
        self.scenario_model = Scenario[self.opening_model]

    @tool
    def kill(self, draft: Game[W], args: Kill, _rng: Random) -> list[Fact]:
        """Kill someone here."""
        return draft.world.kill(args.target_id)

    @tool
    @action
    def leave_party(self, draft: Game[W], args: LeaveParty, _rng: Random) -> list[Fact]:
        """Make a party member stop travelling with the player."""
        return draft.world.leave_party(args.target_id)

    @tool
    def direct(self, _draft: Game[W], args: Direct, _rng: Random) -> list[Fact]:
        """End the turn and give notes to the narrator. Call this last, once per turn.
        Include the answer or result, its known reason, and facts needed for the next choice.
        Share only facts the player can know now.
        Apply world changes through the other tools before calling direct."""
        return [Fact(trace=f"the game master directs: {args.text}", told=True)]

    def install_pack(self, pack_id: Slug, pack: K) -> None:
        packs = self.packs
        self.packs = replace(
            packs,
            installed={**packs.installed, pack_id: pack},
            written_ids=packs.written_ids | {pack_id},
        )

    def guidance_for(self, pack_id: Slug, /, *, opening: bool) -> str:
        block = self.packs.guidance(pack_id, opening=opening)
        return f"{self.worldsmith_guidance}\n\n{block}" if block else self.worldsmith_guidance

    def preview_character(self, character: AnyCharacter) -> Rows:
        return self.player_of(character).rows()

    def restore(self, raw: str) -> Game[W]:
        if (header := parse_strict_json(EngineHeader, raw)).engine_id != self.id:
            raise Refusal(f"the save plays {header.engine_id!r}, not {self.id!r}")
        state = parse_json(Game[self.world_model], raw)
        if state.request is not None:
            raise Refusal("the save carries a pending request")
        self.validate(state)
        self.packs.require(state.pack_id)
        return state

    def published(self, _state: Game[W], /) -> tuple[MasterTool, ...]:
        return tuple(self.tools.values())

    def call_tool(self, draft: Game[W], name: str, raw: JsonValue, rng: Random) -> tuple[Fact, ...]:
        found = next(
            (candidate for candidate in self.published(draft) if candidate.name == name), None
        )
        if found is None:
            raise Refusal(f"{name!r} is not a tool now")
        args = parse_with_repairs(found.args, raw)
        texts = tuple(player_facing_texts(args))
        draft.world.hear(*texts)
        draft.world.refuse_unmet_names(*texts)
        return self._run_marked(draft, name, args, rng)

    def play_option(self, draft: Game[W], chosen: ActionOption, rng: Random) -> tuple[Fact, ...]:
        if chosen.refusal:
            raise Refusal(f"{chosen.name}: {chosen.refusal}")
        found = self.actions[chosen.action_name]
        return self._run_marked(draft, found.name, parse_with_repairs(found.args, chosen.args), rng)

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

    async def ask_worldsmith[A: BaseModel](
        self,
        draft: Game[W],
        worldsmith: RoleAnswer,
        intent: str,
        answer_model: type[A],
        check: Check[A],
        *,
        guidance: str | None = None,
    ) -> A:
        if guidance is None:
            guidance = self.guidance_for(draft.pack_id, opening=False)
        prompt = render_worldsmith(
            self.worldsmith_role,
            source=draft.source,
            backdrop=draft.scenario_description.backdrop,
            scope=draft.scenario_description.scope,
            world_sections=self.worldsmith_sections(draft),
            intent=intent,
            guidance=guidance,
            answer_model=answer_model,
        )
        return await worldsmith(prompt, answer_model, check)

    async def write_next(
        self,
        draft: Game[W],
        intent: str,
        worldsmith: RoleAnswer,
        *,
        extra_needs: Callable[[R], list[str]] = lambda _: [],
    ) -> R:
        def check(answer: R) -> None:
            faults = [f"the answer needs {need}" for need in extra_needs(answer)]
            try:
                self.check_next(draft, answer)
            except Refusal as refused:
                faults.insert(0, str(refused))
            if faults:
                raise Refusal("; ".join(faults))

        return await self.ask_worldsmith(draft, worldsmith, intent, self.next_proposal_model, check)

    def character_of(self, name: str, person: BaseModel) -> AnyCharacter:
        return self.character_model(id=slug(name, ()), engine_id=self.id, person=person)

    def build_scenario(
        self,
        description: ScenarioDescription,
        pack_id: Slug,
        proposal: OpeningProposal,
        source: str,
    ) -> AnyScenario:
        return self.scenario_model(
            description=description.model_copy(
                update={"premise": description.premise or proposal.premise()}
            ),
            engine_id=self.id,
            pack_id=pack_id,
            source=source,
            opening=proposal,
        )

    async def write_opening(
        self,
        description: ScenarioDescription,
        source: str,
        pack_id: Slug,
        worldsmith: RoleAnswer,
        check: Callable[[AnyScenario], None],
    ) -> AnyScenario:
        def built(proposal: OpeningProposal) -> AnyScenario:
            return self.build_scenario(description, pack_id, proposal, source)

        prompt = render_worldsmith(
            self.worldsmith_role,
            source=source,
            backdrop=description.backdrop,
            scope=description.scope,
            world_sections=self.opening_sections,
            intent=self.opening_intent,
            guidance=self.guidance_for(pack_id, opening=True),
            answer_model=self.opening_model,
        )
        return built(
            await worldsmith(prompt, self.opening_model, lambda answer: check(built(answer)))
        )

    async def write_pack(
        self, *, name: str, source: str, origin: str, license: str, worldsmith: RoleAnswer
    ) -> K:
        def built(from_head: PackHead, from_body: PackBody | None) -> K:
            return parse(
                self.pack_model,
                {
                    "name": name,
                    "origin": origin,
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

        head = await worldsmith(
            asked(HEAD_ASK, (), self.pack_head_model), self.pack_head_model, check_head
        )
        so_far = ((PACK_SO_FAR, sections(built(head, None).sections(opening=True))),)

        def check_body(answer: PackBody) -> None:
            built(head, answer)

        body = await worldsmith(
            asked(BODY_ASK, so_far, self.pack_body_model), self.pack_body_model, check_body
        )
        return built(head, body)

    def record(
        self,
        draft: Game[W],
        lines: tuple[SpokenLine, ...],
        facts: tuple[Fact, ...],
        *,
        words: str = "",
        by_option: bool = False,
        cause: Cause | None = None,
        refused: tuple[RefusedCall, ...] = (),
    ) -> Game[W]:
        self.before_record(draft)
        entry = LogEntry(
            words=words,
            by_option=by_option,
            cause=cause,
            lines=lines,
            facts=facts,
            refused=refused,
            decision="" if draft.pending is None else draft.pending.prompt,
            context=self.context_lines(draft),
        )
        draft.chapters[-1].entries.append(entry)
        draft.world.hear(*(line.text for line in lines))
        return self.accept(draft)

    def before_record(self, draft: Game[W], /) -> None:  # noqa: B027
        pass

    def open_chapter(self, draft: Game[W]) -> None:
        if draft.chapters and not draft.chapters[-1].entries:
            draft.chapters.pop()
        draft.chapters.append(
            Chapter(title=self.narrator_view(draft).title, context=self.context_lines(draft))
        )

    def accept(self, draft: Game[W]) -> Game[W]:
        self.validate(draft)
        return draft.validated()

    def end_turn(self, draft: Game[W], /, *, acted: bool) -> None:  # noqa: B027
        pass

    def begin(self, scenario_id: Slug, scenario: AnyScenario, character: AnyCharacter) -> Game[W]:
        if scenario.engine_id != self.id:
            raise Refusal(
                f"{scenario_id!r} is authored for the {scenario.engine_id!r} rules, which the "
                f"{self.id!r} engine does not play"
            )
        if character.engine_id != self.id:
            raise Refusal(
                f"{character.id!r} is written for the {character.engine_id!r} rules, which the "
                f"{self.id!r} engine does not play"
            )
        self.packs.require(scenario.pack_id)
        state = parse(
            Game[self.world_model],
            {
                "scenario_id": scenario_id,
                "character_id": character.id,
                "scenario_description": scenario.description,
                "engine_id": self.id,
                "pack_id": scenario.pack_id,
                "source": scenario.source,
                "world": self.new_game(scenario, character),
            },
        )
        self.open_chapter(state)
        return self.accept(state)

    def player_of(self, character: AnyCharacter) -> P:
        if character.person.id != PLAYER_ID or not character.person.known:
            raise Refusal("a character sheet is the player's: the id is 'player', and it is known")
        if not isinstance(person := character.person, self.person_model):
            raise Refusal(f"{character.id!r} is not a {self.title} sheet")
        return deepcopy(person)

    def ending(self, state: Game[W]) -> str | None:
        return "You died." if not state.world.player.alive else None

    def grown_character(self, _state: Game[W], /) -> AnyCharacter | None:
        return None

    def create_character(self, name: str, brief: str, pack_id: Slug, picks: Picks) -> AnyCharacter:
        check_picks(self.creation_steps(pack_id, picks), picks)
        return self.build_character(name, brief, pack_id, picks)

    def validate(self, state: Game[W]) -> None:
        if not state.chapters:
            raise Refusal(f"a {self.id!r} game has no chapter open")
        request = state.request
        if request is not None and request.kind not in self.request_handlers():
            raise Refusal(f"the {self.id!r} engine writes no {request.kind!r}")

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
    def check_next(self, draft: Game[W], proposal: R, /) -> None: ...
    @abstractmethod
    def install_next(self, draft: Game[W], proposal: R, /) -> list[Fact]: ...
    @abstractmethod
    def narrator_view(self, state: Game[W]) -> NarratorView: ...
    @abstractmethod
    def context_lines(self, state: Game[W], /) -> str: ...
    @abstractmethod
    def player_view(self, state: Game[W]) -> PlayerView: ...

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {}

    def _run_marked(
        self, draft: Game[W], name: str, args: BaseModel, rng: Random
    ) -> tuple[Fact, ...]:
        method: Callable[[Game[W], BaseModel, Random], Sequence[Fact]] = getattr(self, name)
        return tuple(method(draft, args, rng))
