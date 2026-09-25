from collections.abc import Sequence
from random import Random
from typing import Self

from pydantic import model_validator

from rulehall.core.validation import Frozen

NOTHING = "- (nothing changed)"


class DiceEvent(Frozen):
    label: str
    faces: tuple[int, ...]
    rolled: tuple[int, ...]
    highlight: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _rolled_matches_faces(self) -> Self:
        if len(self.rolled) != len(self.faces):
            raise ValueError("one rolled value per face")
        for die, face in zip(self.rolled, self.faces, strict=True):
            if not 1 <= die <= face:
                raise ValueError(f"a d{face} cannot show {die}")
        for index in self.highlight:
            if not 0 <= index < len(self.rolled):
                raise ValueError(f"highlight {index} names no rolled die")
        return self


class Fact(Frozen):
    trace: str
    told: bool = False
    card: str = ""
    dice: tuple[DiceEvent, ...] = ()


class Rolled(Frozen):
    event: DiceEvent
    fact: Fact

    @property
    def kept(self) -> int:
        return max(self.event.rolled)

    @property
    def total(self) -> int:
        return sum(self.event.rolled)

    @property
    def face(self) -> int:
        if len(self.event.rolled) != 1:
            raise ValueError(f"{self.event.label} rolled {len(self.event.rolled)} dice, not one")
        return self.event.rolled[0]


def cards(facts: Sequence[Fact]) -> tuple[Fact, ...]:
    return tuple(fact for fact in facts if fact.told and fact.card)


def traced(facts: Sequence[Fact], *, told_only: bool = False) -> str:
    return "\n".join(f"- {fact.trace}" for fact in facts if fact.told or not told_only) or NOTHING


def roll(
    faces: Sequence[int], reason: str, rng: Random, *, label: str = "", highlight_kept: bool = False
) -> Rolled:
    if not faces:
        raise ValueError("a dice pool rolls at least one die")
    drawn = tuple(rng.randint(1, face) for face in faces)
    highlight = (drawn.index(max(drawn)),) if highlight_kept and len(faces) > 1 else ()
    notation = _notation(faces)
    event = DiceEvent(
        label=label or notation, faces=tuple(faces), rolled=drawn, highlight=highlight
    )
    shown = ", ".join(str(die) for die in drawn)
    fact = Fact(trace=f"{reason}: {notation} [{shown}]")
    return Rolled(event=event, fact=fact)


def _notation(faces: Sequence[int]) -> str:
    if len(faces) == 1:
        return f"d{faces[0]}"
    if len(set(faces)) == 1:
        return f"{len(faces)}d{faces[0]}"
    return "+".join(f"d{face}" for face in faces)
