from abc import abstractmethod
from collections.abc import Mapping
from random import Random
from typing import Any

from pydantic import BaseModel

from rulehall.core.facts import Fact
from rulehall.core.game import AnyGame, Game, RoleAnswer, WorldsmithRequest
from rulehall.core.tools import tool
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.args import HireOrJoin, JoinParty
from rulehall.engines.engine import Engine, RequestHandler, Resolution
from rulehall.engines.packs import Pack
from rulehall.engines.sheet import Person
from rulehall.engines.world import World

HIRE: Slug = "hire"
SIGNED_ON = "{name} has signed on with the player. Tell it in a line or two. Settle nothing else."
HIRED = "The player has hired {name}, {brief}, on these terms: {terms}. "
UNWRITTEN_CAST = (
    "The cast carries no dice until the player hires them in play. An npc is a name, a brief, "
    "and whether the player has met them. A threat is a brief that the player's own roll meets, "
    "never a stat block. "
)
HIRE_PENDING = (
    "the worldsmith writes {name}'s sheet once this turn ends: {terms}; nothing more happens "
    "this turn, so stop and exit"
)
ALREADY_SHEETED = "{name} already carries a sheet"
SIGNS_ON = "{who} signs on — {summary}"
HIRE_UNWRITTEN = Fact(
    told=True,
    trace="the hire could not be written",
    card="The hire could not be written; nobody signed on.",
)


class Joining:
    @tool
    def join_party(self, draft: AnyGame, args: JoinParty, _rng: Random) -> list[Fact]:
        """Make a person here travel with the player."""
        world = draft.world
        return world.join(world.require_person_here(args.target_id))


class Hiring[P: Person, W: World[Any], K: Pack, R: BaseModel, A: BaseModel](Engine[P, W, K, R]):
    hire_model: type[A]
    hire_intent: str

    @tool
    def join_party(self, draft: Game[W], args: HireOrJoin, _rng: Random) -> list[Fact]:
        """Make a person here travel with the player. Set `terms` when the player hires them to
        work, also someone who already travels with the player: the worldsmith writes their sheet
        at the end of the turn, and nothing more happens this turn. Leave `terms` empty for
        someone who only comes along."""
        filed = draft.world.enter_if_stranger(args.target_id)
        person = draft.world.require_person_here(args.target_id)
        # A member let go keeps their sheet, so hiring them again only brings them back.
        if not args.terms or person.has_sheet:
            return [*filed, *draft.world.join(person)]
        draft.request = WorldsmithRequest(kind=HIRE, detail=args.terms, target_id=person.id)
        return [*filed, Fact(trace=HIRE_PENDING.format(name=person.name, terms=args.terms))]

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {**super().request_handlers(), HIRE: RequestHandler(self.write_hire, HIRE_UNWRITTEN)}

    async def write_hire(
        self, draft: Game[W], request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        assert request.target_id is not None
        world = draft.world
        person: P = require_hireable(world, request.target_id)
        answer = await self.ask_worldsmith(
            draft,
            worldsmith,
            self.hire_intent.format(name=person.name, brief=person.brief, terms=request.detail),
            self.hire_model,
            lambda answer: self.check_hire(draft, answer),
            guidance=self.hire_guidance(draft),
        )
        summary = self.sign_on(draft, person, answer)
        facts = world.join(person) if person.id not in world.party_ids else []
        facts.append(signed_on(person, summary))
        return Resolution(tuple(facts), SIGNED_ON.format(name=person.name))

    def check_hire(self, _draft: Game[W], _answer: A, /) -> None:
        pass

    @abstractmethod
    def hire_guidance(self, draft: Game[W], /) -> str: ...
    @abstractmethod
    def sign_on(self, draft: Game[W], person: P, answer: A, /) -> str: ...


def signed_on(person: Person, summary: str) -> Fact:
    return person.fact(
        SIGNS_ON.format(who=person.mention, summary=summary),
        card=SIGNS_ON.format(who=person.name, summary=summary),
    )


def require_hireable[P: Person](world: World[P], entity_id: Slug) -> P:
    person = world.require_person_here(entity_id)
    if person.has_sheet:
        raise Refusal(ALREADY_SHEETED.format(name=person.name))
    return person
