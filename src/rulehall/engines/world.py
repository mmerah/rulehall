from abc import abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from typing import Self

from pydantic import BaseModel, Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.prompt import Sections
from rulehall.core.validation import Mutable, Refusal, Slug, check_unique
from rulehall.core.views import Rows
from rulehall.engines.name_leaks import unmet_people_named
from rulehall.engines.sheet import Entity, Person, Sheeted

ARC_TITLE = "THE ARC (the player has not found this)"
ARC_SO_FAR_TITLE = "THE ARC SO FAR"
HIDDEN_TITLE = "HIDDEN HERE (the player has not found these)"
UNKNOWN_ID = "unknown id {entity_id!r}; use only the ids you were shown"
IS_DEAD = "{name} is dead and takes no further part"
NOT_AN_ACTOR = "{name} is not the player or a hired party member"


class OpeningProposal(BaseModel):
    @abstractmethod
    def premise(self) -> str: ...


class World[P: Person](Mutable):
    player: P
    party_ids: list[Slug] = Field(default_factory=list)

    @model_validator(mode="after")
    def _player_and_party(self) -> Self:
        if not self.player.known:
            raise ValueError("the player is unknown to themselves")
        check_unique("party", self.party_ids)
        if self.player.id in self.party_ids:
            raise ValueError("the player cannot travel with themselves")
        for member_id in self.party_ids:
            member = self.find_person(member_id)
            if member is None or not member.known:
                raise ValueError(f"{member_id!r} travels with the player but is not known")
            if not member.alive:
                raise ValueError(f"{member_id!r} is dead and cannot travel with the player")
        if isinstance(player := self.player, Sheeted) and not player.has_sheet:
            raise ValueError("the player carries no sheet")
        return self

    @property
    @abstractmethod
    def roster(self) -> Mapping[Slug, P]: ...
    @abstractmethod
    def here(self) -> Iterable[P]: ...
    @abstractmethod
    def require_person_here(self, entity_id: Slug) -> P: ...
    @abstractmethod
    def reveal_hidden(self, entity_id: Slug) -> list[Fact]: ...
    @abstractmethod
    def kill(self, entity_id: Slug) -> list[Fact]: ...

    def party_members(self) -> list[P]:
        return [self.roster[member_id] for member_id in self.party_ids]

    def find_person(self, person_id: Slug) -> P | None:
        return self.roster.get(person_id)

    def people(self) -> Iterable[P]:
        return (self.player, *self.roster.values())

    def hired_party_members(self) -> list[P]:
        return [member for member in self.party_members() if member.has_sheet]

    def require_actor(self, actor_id: Slug | None) -> P:
        if actor_id is None or actor_id == self.player.id:
            return self.player
        person = self.require_person_here(actor_id)
        if person.has_sheet and person.id in self.party_ids:
            return person
        raise Refusal(NOT_AN_ACTOR.format(name=person.name))

    def leave_party(self, entity_id: Slug) -> list[Fact]:
        member = self.find_person(entity_id)
        if member is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        if member.id not in self.party_ids:
            raise Refusal(f"{member.name} does not travel with the player")
        self.party_ids.remove(member.id)
        trace = f"{member.ref} no longer travels with the player"
        return [member.fact(trace, card=f"{member.name} leaves your party")]

    def refuse_unmet_names(self, *texts: str) -> None:
        named = unmet_people_named("\n".join(texts), self.people())
        if leaked := sorted({person.name for person in named}):
            raise Refusal(f"this names what the player has not met: {leaked}; say it another way")

    def hear(self, *texts: str) -> None:
        pass

    def die(self, person: P) -> str:
        if not person.alive:
            raise Refusal(f"{person.name} is already dead")
        if person.id in self.party_ids:
            self.party_ids.remove(person.id)
        person.alive = False
        return "You are dead" if person.id == self.player.id else f"{person.name} is dead"

    def enter_if_stranger(self, _entity_id: Slug, /) -> list[Fact]:
        return []

    def join(self, person: P) -> list[Fact]:
        if person.id in self.party_ids:
            raise Refusal(f"{person.name} already travels with the player")
        self.party_ids.append(person.id)
        trace = f"{person.ref} travels with the player"
        return [person.fact(trace, card=f"{person.name} joins your party")]

    def sheet_rows(self) -> Rows:
        return self.player.rows()


def party_section(members: Sequence[Entity]) -> Sections:
    if not members:
        return ()
    return (("THE PARTY (led by the player)", "\n".join(member.line() for member in members)),)


def check_filing(pool: Mapping[Slug, Entity]) -> None:
    for key, entity in pool.items():
        if key != entity.id:
            raise Refusal(f"entity {entity.id!r} is filed under {key!r}")
