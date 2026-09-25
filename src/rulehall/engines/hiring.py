from abc import abstractmethod
from collections.abc import Mapping
from random import Random
from typing import Any

from pydantic import BaseModel, Field

from rulehall.core.facts import Fact
from rulehall.core.model import AnyGame, Check, Game, RoleAnswer, WorldsmithRequest
from rulehall.core.tools import tool
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.args import JoinParty
from rulehall.engines.engine import Engine, RequestHandler, Resolution
from rulehall.engines.entities import Person, World
from rulehall.engines.packs import Pack

HIRE: Slug = "hire"
SIGNED_ON = "{name} has signed on with the player. Tell it in a line or two. Settle nothing else."
HIRED = "The player has hired {name}, {brief}, on these terms: {terms}. "
UNWRITTEN_CAST = (
    "The cast carries no dice until the player hires them in play. An npc is a name, a brief, "
    "and whether the player has met them. A threat is a brief that the player's own roll meets, "
    "never a stat block. "
)
HIRE_PENDING = (
    "the worldsmith writes {name}'s sheet once this turn ends: {terms}. Nothing more happens "
    "this turn; stop and exit"
)
ALREADY_SHEETED = "{name} already carries a sheet"
SIGNS_ON = "{who} signs on — {summary}"
HIRE_UNWRITTEN = Fact(
    told=True,
    trace="the hire could not be written",
    card="The hire could not be written; nobody signed on.",
)


class HireOrJoin(JoinParty):
    target_id: Slug = Field(description="Exact id of who here joins or is hired.")
    terms: str = Field(
        default="",
        description="Empty when they only come along. When the player hires them to work: what "
        "for and on what terms, as agreed.",
    )


class Joining:
    @tool
    def join_party(self, draft: AnyGame, args: JoinParty, _rng: Random) -> list[Fact]:
        """Make a person here travel with the player."""
        return draft.world.join_party(args.target_id)


class Hiring[W: World[Any], K: Pack, P: Person, A: BaseModel](Engine[W, K]):
    """The worldsmith writes the sheet of whom the player hires; the engine gives the hooks."""

    hire_model: type[A]
    hire_intent: str  # a template of `name`, `brief` and `terms`

    @tool
    def join_party(self, draft: Game[W], args: HireOrJoin, _rng: Random) -> list[Fact]:
        """Make a person here travel with the player. Set `terms` when the player hires them to
        work, also someone who already travels with the player: the worldsmith writes their sheet
        at the end of the turn, and nothing more happens this turn. Leave `terms` empty for
        someone who only comes along."""
        if not args.terms:
            return draft.world.join_party(args.target_id)
        person = require_hireable(draft.world, args.target_id)
        draft.request = WorldsmithRequest(kind=HIRE, detail=args.terms, target_id=person.id)
        return [Fact(trace=HIRE_PENDING.format(name=person.name, terms=args.terms))]

    def request_handlers(self) -> Mapping[Slug, RequestHandler[W]]:
        return {**super().request_handlers(), HIRE: RequestHandler(self.write_hire, HIRE_UNWRITTEN)}

    async def write_hire(
        self, draft: Game[W], request: WorldsmithRequest, worldsmith: RoleAnswer
    ) -> Resolution:
        assert request.target_id is not None
        world = draft.world
        person: P = require_hireable(world, request.target_id)
        prompt = self.render_request(
            draft,
            intent=self.hire_intent.format(
                name=person.name, brief=person.brief, terms=request.detail
            ),
            guidance=self.hire_guidance(draft),
            answer_model=self.hire_model,
        )
        answer = await worldsmith(prompt, self.hire_model, self.hire_check(draft))
        summary = self.sign_on(person, answer)
        facts = world.join(person) if person.id not in world.party else []
        facts.append(
            person.fact(
                SIGNS_ON.format(who=person.mention, summary=summary),
                card=SIGNS_ON.format(who=person.name, summary=summary),
            )
        )
        return Resolution(tuple(facts), SIGNED_ON.format(name=person.name))

    def hire_check(self, _draft: Game[W], /) -> Check[A]:
        return lambda _answer: None

    @abstractmethod
    def hire_guidance(self, draft: Game[W], /) -> str: ...
    @abstractmethod
    def sign_on(self, person: P, answer: A, /) -> str:
        """Write the answer onto the hired person's sheet; return the summary."""


def require_hireable[M: Person](world: World[M], entity_id: Slug) -> M:
    person = world.require_person_here(entity_id)
    if person.hired:
        raise Refusal(ALREADY_SHEETED.format(name=person.name))
    return person
