from collections.abc import Sequence
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import Fact
from rulehall.core.validation import Refusal, as_tuple
from rulehall.core.views import Rows, nonblank_rows
from rulehall.engines.args import ShortName
from rulehall.engines.loner4e.rules import (
    LUCK_MAX,
    TagKind,
    and_for_commas,
)
from rulehall.engines.sheet import Gauge, Person, changed_tags, tag_card, tag_delta

Tag = Annotated[str, BeforeValidator(and_for_commas)]
TagName = Annotated[ShortName, BeforeValidator(and_for_commas)]
Tags = Annotated[tuple[str, ...], BeforeValidator(as_tuple)]


class Loner4eEntity(Person):
    """A character is a person, an object, a vehicle or a curse."""

    known: SkipJsonSchema[bool] = True
    concept: str = ""
    tags: dict[TagKind, list[Tag]] = Field(default_factory=dict)
    goal: str = ""
    motive: str = ""
    nemesis: str = ""
    luck: SkipJsonSchema[Gauge] = Field(
        default_factory=lambda: Gauge(current=LUCK_MAX, maximum=LUCK_MAX)
    )
    living_world: SkipJsonSchema[list[str]] = Field(default_factory=list)

    def tagged(self, kind: TagKind) -> list[str]:
        return self.tags.get(kind, [])

    def rows(self) -> Rows:
        return (*self.traits(), ("Luck", str(self.luck)))

    def traits(self) -> Rows:
        return nonblank_rows(
            ("Concept", self.concept),
            ("Skills", ", ".join(self.tagged("skill"))),
            ("Frailties", ", ".join(self.tagged("frailty"))),
            ("Gear", ", ".join(self.tagged("gear"))),
            ("Conditions", ", ".join(self.tagged("condition"))),
            ("Relationships", ", ".join(self.tagged("relationship"))),
            ("Goal", self.goal),
            ("Motive", self.motive),
            ("Nemesis", self.nemesis),
        )

    def change_tags(self, kind: TagKind, gained: Sequence[str], lost: Sequence[str]) -> list[Fact]:
        here = [tag for tag in lost if self._carrier(tag, kind) == kind]
        for tag in lost:
            if (carrier := self._carrier(tag, kind)) != kind:
                self.tags[carrier] = changed_tags(
                    self.name, carrier, self.tagged(carrier), (), [tag]
                )
        self.tags[kind] = changed_tags(self.name, kind, self.tagged(kind), gained, here)
        trace = f"{self.mention} {kind} {tag_delta(gained, lost)}"
        now, gone = ("Took ", "Lost ") if kind == "gear" else ("Now: ", "No longer: ")
        return [self.fact(trace, card=self.card_line(tag_card(gained, lost, now, gone)))]

    def _carrier(self, tag: str, kind: TagKind) -> TagKind:
        folded = tag.casefold()
        for other in (kind, *self.tags):
            if folded in map(str.casefold, self.tagged(other)):
                return other
        return kind

    def drive(self, *, goal: str, motive: str, nemesis: str, concept: str) -> list[Fact]:
        parts: list[str] = []
        if concept:
            self.concept = concept
            parts.append(f"concept: {concept}")
        if goal:
            self.goal = goal
            parts.append(f"goal: {goal}")
        if motive:
            self.motive = motive
            parts.append(f"motive: {motive}")
        if nemesis:
            self.nemesis = nemesis
            parts.append(f"nemesis: {nemesis}")
        trace = f"{self.mention} " + "; ".join(parts)
        shown = (goal, concept and f"Concept: {concept}", nemesis and f"Nemesis: {nemesis}")
        card = "; ".join(part for part in shown if part)
        return [self.fact(trace, card=self.card_line(card) if card else "")]

    def refill(self, why: str) -> list[Fact]:
        return self.change(self.luck, self.luck.shortfall, "Luck", why)

    def spend_luck(self, amount: int, why: str) -> list[Fact]:
        if amount > self.luck.current:
            raise Refusal(f"{self.name} has {self.luck.current} luck, not {amount}")
        return self.change(self.luck, -amount, "Luck", why)
