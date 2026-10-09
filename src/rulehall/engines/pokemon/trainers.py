from collections.abc import Iterable, Sequence
from typing import Protocol

from pydantic import Field

from rulehall.core.prompt import Sections
from rulehall.core.validation import Mutable, Refusal, Slug

AVATAR_ID = "How this person looks: exact id from TRAINER LOOKS."
STYLE = "One line on how this {key_trainer} battles, such as '{example}'. Empty for anyone else."
WIN_LINE = "What this {key_trainer} says on beating the player. Empty for anyone else."
LOSE_LINE = "What this {key_trainer} says when the player beats them. Empty for anyone else."
RIVAL = "True for the one rival of the {span}, who stands in the opening map."


class Trainer(Protocol):
    @property
    def id(self) -> Slug: ...

    @property
    def ref(self) -> str: ...

    @property
    def rival(self) -> bool: ...

    @property
    def style(self) -> str: ...

    @property
    def win_line(self) -> str: ...

    @property
    def lose_line(self) -> str: ...


class RivalLedger(Mutable):
    lines: list[str] = Field(default_factory=list)

    def record_battle(self, occasion: str, winner: str, highlights: Sequence[str]) -> None:
        best = f". {highlights[0]}" if highlights else ""
        self.lines.append(f"{occasion}: {winner} won{best}")

    def section(self, rival: Trainer | None) -> Sections:
        if rival is None:
            return ()
        lines = (f"- {line}" for line in self.lines)
        return (("THE RIVAL", "\n".join((f"{rival.ref}; style: {rival.style}", *lines))),)


def find_rival[T: Trainer](npcs: Iterable[T]) -> T | None:
    return next((npc for npc in npcs if npc.rival), None)


def check_one_rival(npcs: Iterable[Trainer]) -> None:
    if len([npc for npc in npcs if npc.rival]) > 1:
        raise ValueError("a world has one rival at most")


def check_rivals(trainers: Iterable[Trainer], *, opening: bool) -> None:
    rivals = [npc for npc in trainers if npc.rival]
    if opening and len(rivals) != 1:
        raise Refusal(f"the opening map needs exactly one rival, not {len(rivals)}")
    if not opening and rivals:
        raise Refusal("the rival stands in the opening map; a new map adds no rival")


def check_key_lines(keys: Iterable[Trainer], key_trainer: str) -> None:
    if mute := [npc.id for npc in keys if not (npc.style and npc.win_line and npc.lose_line)]:
        raise Refusal(f"each {key_trainer} needs a style, a win_line and a lose_line: {mute}")
