import re
from abc import abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from typing import Self

from pydantic import BaseModel, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.prompt import Sections
from rulehall.core.validation import Mutable, Refusal, Slug, check_unique
from rulehall.core.views import Rows, Subject, headline_of, tag_of

PLAYER_ID: Slug = "player"
ARC_TITLE = "THE ARC (the player has not found this)"
HIDDEN_TITLE = "HIDDEN HERE (the player has not found these)"
UNKNOWN_ID = "unknown id {entity_id!r}. Use only the ids you were shown."
IS_DEAD = "{name} is dead and takes no further part."
NO_SHEET = "{name} carries no sheet"
NOT_AN_ACTOR = "{name} is not the player or a hired party member"
NAME_WORD_LETTERS = 4
ARTICLES = ("the", "a", "an")


class OpeningProposal(BaseModel):
    @abstractmethod
    def premise(self) -> str: ...


class Gauge(Mutable):
    current: int
    maximum: int

    @model_validator(mode="after")
    def _within_bounds(self) -> Self:
        if self.current < 0:
            raise ValueError(f"{self.current} is below zero")
        if self.current > self.maximum:
            raise ValueError(f"{self.current} is above maximum {self.maximum}")
        return self

    def __str__(self) -> str:
        return f"{self.current}/{self.maximum}"

    @property
    def shortfall(self) -> int:
        return self.maximum - self.current

    def adjust(self, amount: int) -> int:
        before = self.current
        self.current = min(max(before + amount, 0), self.maximum)
        return self.current - before


class Thing(Mutable):
    id: Slug
    name: str = Field(min_length=1)
    brief: str
    known: bool = False

    @property
    def mention(self) -> str:
        return f"the player {self.tag}" if self.id == PLAYER_ID else self.tag

    @property
    def tag(self) -> str:
        return tag_of(self.name, self.id)

    @property
    def headline(self) -> str:
        return headline_of(self.name, self.id, self.brief)

    @property
    def met_label(self) -> str:
        return "met" if self.known else "unmet"

    def rows(self) -> Rows:
        return ()

    def line(self, *, rows: Rows | None = None, detail: str = "") -> str:
        parts = [f"- {self.headline}"]
        shown = self.rows() if rows is None else rows
        if sheet := "; ".join(f"{label.lower()}: {value}" for label, value in shown):
            parts.append(f"  {sheet}")
        if detail:
            parts.append(f"  {detail}")
        return "\n".join(parts)

    def fact(self, trace: str, *, card: str = "", dice: tuple[DiceEvent, ...] = ()) -> Fact:
        return Fact(trace=trace, told=self.known, card=card, dice=dice)

    def card_fact(self, line: str, dice: tuple[DiceEvent, ...] = ()) -> Fact:
        return self.fact(line, card=line, dice=dice)

    def card_line(self, line: str) -> str:
        return line if self.id == PLAYER_ID else f"{self.name}: {line}"

    def change(self, gauge: Gauge, amount: int, label: str, why: str) -> list[Fact]:
        delta = gauge.adjust(amount)
        if delta == 0:
            return []
        moved = f"{label} {delta:+d} → {gauge}"
        return [self.fact(f"{self.mention} {moved} ({why})", card=self.card_line(moved))]

    def reveal(self, *, card: str = "") -> list[Fact]:
        if self.known:
            return []
        self.known = True
        return [self.fact(f"learned of {self.mention}", card=card)]

    def subject(self) -> Subject:
        return Subject(id=self.id, name=self.name, brief=self.brief)


class Person(Thing):
    alive: SkipJsonSchema[bool] = True

    @property
    def headline(self) -> str:
        return headline_of(self.name, self.id, self.brief, alive=self.alive)

    def subject(self) -> Subject:
        return Subject(id=self.id, name=self.name, brief=self.brief, alive=self.alive)

    @property
    def hired(self) -> bool:
        return False

    def required(self) -> str:
        return "" if self.alive else "alive"


class Sheeted[S: Mutable](Person):
    sheet: SkipJsonSchema[S | None] = None

    @property
    def hired(self) -> bool:
        return self.sheet is not None

    def require_sheet(self) -> S:
        if self.sheet is None:
            raise Refusal(NO_SHEET.format(name=self.name))
        return self.sheet

    def required(self) -> str:
        return joined(super().required(), "no sheet" if self.sheet is not None else "")


class World[M: Person](Mutable):
    player: M
    party: list[Slug] = Field(default_factory=list)

    @model_validator(mode="after")
    def _player_and_party(self) -> Self:
        if not self.player.known:
            raise ValueError("the player is unknown to themselves")
        check_unique("party", self.party)
        if self.player.id in self.party:
            raise ValueError("the player cannot travel with themselves")
        for member_id in self.party:
            member = self.person_of(member_id)
            if member is None or not member.known:
                raise ValueError(f"{member_id!r} travels with the player but is not known")
            if not member.alive:
                raise ValueError(f"{member_id!r} is dead and cannot travel with the player")
        if isinstance(player := self.player, Sheeted) and not player.hired:
            raise ValueError("the player carries no sheet")
        return self

    @abstractmethod
    def party_members(self) -> Sequence[M]: ...
    @abstractmethod
    def person_of(self, person_id: Slug) -> M | None: ...
    @abstractmethod
    def require_person_here(self, entity_id: Slug) -> M: ...

    @abstractmethod
    def reveal_hidden(self, entity_id: Slug) -> list[Fact]: ...
    @abstractmethod
    def kill(self, entity_id: Slug) -> list[Fact]: ...
    @abstractmethod
    def people(self) -> Iterable[M]: ...

    def hired_party_members(self) -> list[M]:
        return [member for member in self.party_members() if member.hired]

    def require_actor(self, actor_id: Slug | None) -> M:
        if actor_id is None or actor_id == self.player.id:
            return self.player
        person = self.require_person_here(actor_id)
        if person.hired and person.id in self.party:
            return person
        raise Refusal(NOT_AN_ACTOR.format(name=person.name))

    def leave_party(self, entity_id: Slug) -> list[Fact]:
        member = self.person_of(entity_id)
        if member is None:
            raise Refusal(UNKNOWN_ID.format(entity_id=entity_id))
        if member.id not in self.party:
            raise Refusal(f"{member.name} does not travel with the player")
        self.party.remove(member.id)
        trace = f"{member.tag} no longer travels with the player"
        return [member.fact(trace, card=f"{member.name} leaves your party")]

    def check_unnamed(self, *texts: str) -> None:
        if leaked := sorted({person.name for person in self.unmet_named(*texts)}):
            raise Refusal(f"this names what the player has not met: {leaked}. Say it another way.")

    def hear(self, *texts: str) -> None:
        pass

    def unmet_named(self, *texts: str) -> list[M]:
        return named_people("\n".join(texts), self.people())

    def absorb(self, proposal: OpeningProposal) -> None:
        pass

    def die(self, person: M) -> str:
        if not person.alive:
            raise Refusal(f"{person.name} is already dead")
        if person.id in self.party:
            self.party.remove(person.id)
        person.alive = False
        return "You are dead" if person.id == self.player.id else f"{person.name} is dead"

    def enter_if_stranger(self, _entity_id: Slug, /) -> list[Fact]:
        return []

    def join_party(self, entity_id: Slug) -> list[Fact]:
        return self.join(self.require_person_here(entity_id))

    def join(self, person: Person) -> list[Fact]:
        if person.id in self.party:
            raise Refusal(f"{person.name} already travels with the player")
        self.party.append(person.id)
        trace = f"{person.tag} travels with the player"
        return [person.fact(trace, card=f"{person.name} joins your party")]

    def sheet_rows(self) -> Rows:
        return self.player.rows()


def party_section(members: Sequence[Thing]) -> Sections:
    if not members:
        return ()
    return (("THE PARTY (led by the player)", "\n".join(member.line() for member in members)),)


def changed_tags(
    owner: str, kind: str, current: Sequence[str], gained: Sequence[str], lost: Sequence[str]
) -> list[str]:
    check_unique(f"{kind} tags", (tag.casefold() for tag in (*gained, *lost)))
    carried = {tag.casefold() for tag in current}
    if already := [tag for tag in gained if tag.casefold() in carried]:
        raise Refusal(f"{owner} already carries the {kind} {already[0]!r}")
    if missing := [tag for tag in lost if tag.casefold() not in carried]:
        carried_now = ", ".join(map(repr, current)) or "none"
        raise Refusal(f"{owner} carries no {kind} {missing[0]!r}; it carries: {carried_now}")
    dropped = {tag.casefold() for tag in lost}
    return [tag for tag in (*current, *gained) if tag.casefold() not in dropped]


def tag_delta(gained: Sequence[str], lost: Sequence[str]) -> str:
    return ", ".join((*(f"+{tag}" for tag in gained), *(f"-{tag}" for tag in lost)))


def tag_card(
    gained: Sequence[str], lost: Sequence[str], now: str, gone: str, *, joiner: str = "; "
) -> str:
    parts = [f"{now}{', '.join(gained)}"] if gained else []
    if lost:
        parts.append(f"{gone}{', '.join(lost)}")
    return joiner.join(parts)


def joined(*parts: str) -> str:
    return ", ".join(part for part in parts if part)


def check_filing(pool: Mapping[Slug, Thing]) -> None:
    for key, entity in pool.items():
        if key != entity.id:
            raise Refusal(f"entity {entity.id!r} is filed under {key!r}")


def required_needs(pool: Mapping[Slug, Person], filed: Iterable[Slug]) -> list[str]:
    already = set(filed)
    return [
        f"{entity_id}: {why}"
        for entity_id, entry in pool.items()
        if entity_id not in already and (why := entry.required())
    ]


def named_unmet(text: str, entities: Iterable[Thing]) -> list[str]:
    return [entity.name for entity in entities if _mentions(text, entity.name)]


def named_people[P: Person](text: str, people: Iterable[P]) -> list[P]:
    everyone = list(people)
    unmet = [person for person in everyone if not person.known]
    met = [person for person in everyone if person.known]
    named = {*named_unmet(text, unmet), *named_by_word(text, unmet, met)}
    return [person for person in unmet if person.name in named]


def named_by_word(text: str, people: Iterable[Person], met: Iterable[Person]) -> list[str]:
    shared = {word for person in met for word in _capitalised(person.name)}
    return [
        person.name
        for person in people
        if any(
            re.search(rf"(?<!\w){word}(?!\w)", text) is not None
            for word in _name_words(person.name)
            if word not in shared
        )
    ]


def leaked_names(read: str, things: Iterable[Thing], hidden: Sequence[Thing]) -> set[str]:
    leaked = set(named_unmet(read, hidden))
    for thing in things:
        text = "\n".join((thing.brief, *(value for _, value in thing.rows())))
        leaked.update(named_unmet(text, (other for other in hidden if other.id != thing.id)))
    return leaked


def _mentions(text: str, name: str) -> bool:
    folded = name.strip().casefold()
    return (
        bool(folded)
        and re.search(rf"(?<!\w){re.escape(folded)}(?!\w)", text.casefold()) is not None
    )


def _words(name: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", name)


def _capitalised(name: str) -> list[str]:
    return [word for word in _words(name) if word[0].isupper() and len(word) >= NAME_WORD_LETTERS]


def _name_words(name: str) -> list[str]:
    words = _words(name)
    return [] if not words or words[0].casefold() in ARTICLES else _capitalised(name)
