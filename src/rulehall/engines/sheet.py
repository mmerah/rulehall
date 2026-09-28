from collections.abc import Sequence
from typing import Self

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.validation import Mutable, Refusal, Slug, check_unique
from rulehall.core.views import Rows, Subject, tag_of

PLAYER_ID: Slug = "player"
NO_SHEET = "{name} carries no sheet"


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


class Entity(Mutable):
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
        return self.subject().headline

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


class Person(Entity):
    alive: SkipJsonSchema[bool] = True

    def subject(self) -> Subject:
        return Subject(id=self.id, name=self.name, brief=self.brief, alive=self.alive)

    @property
    def has_sheet(self) -> bool:
        return False

    def authoring_fault(self) -> str:
        return "" if self.alive else "alive"


class Sheeted[S: Mutable](Person):
    sheet: SkipJsonSchema[S | None] = None

    @property
    def has_sheet(self) -> bool:
        return self.sheet is not None

    def require_sheet(self) -> S:
        if self.sheet is None:
            raise Refusal(NO_SHEET.format(name=self.name))
        return self.sheet

    def authoring_fault(self) -> str:
        return joined(super().authoring_fault(), "no sheet" if self.sheet is not None else "")


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
