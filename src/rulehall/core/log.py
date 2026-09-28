from collections.abc import Sequence
from typing import Literal, Self

from pydantic import Field, TypeAdapter, model_validator
from pydantic_core import from_json

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Mutable, Slug

type Cause = Literal["opening", "story", "battle"]


class Line(Frozen):
    speaker_id: Slug | None = Field(
        default=None,
        description="Exact id of the speaker. Null for narration.",
    )
    text: str = Field(
        min_length=1, description="One passage of narration, or only what the speaker says."
    )


class SpokenLine(Frozen):
    speaker_id: Slug | None = None
    speaker: str = ""
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _named_when_spoken(self) -> Self:
        if (self.speaker_id is None) != (not self.speaker):
            raise ValueError("a spoken line names its speaker; narration names nobody")
        return self

    @property
    def said(self) -> str:
        return f"{self.speaker}: {self.text}" if self.speaker else self.text


class Narration(Frozen):
    """The prose the player reads, split into narration and dialogue."""

    lines: tuple[Line, ...] = Field(description="All narration and dialogue, in order.")


class RefusedCall(Frozen):
    tool: str
    reason: str
    after_facts: int = Field(ge=0)


class LogEntry(Frozen):
    words: str
    by_option: bool = False
    cause: Cause | None = None
    lines: tuple[SpokenLine, ...]
    facts: tuple[Fact, ...] = ()
    refused: tuple[RefusedCall, ...] = ()
    decision: str = ""
    context: str = ""

    def transcript(self) -> str:
        return "\n".join(line.said for line in self.lines)


class Chapter(Mutable):
    title: str
    context: str = ""
    recap: str = ""
    entries: list[LogEntry] = Field(default_factory=list)


LINES = TypeAdapter(list[Line])


def partial_lines(raw: str) -> tuple[Line, ...]:
    start = raw.find("{")
    if start == -1:
        return ()
    try:
        partial = from_json(raw[start:], allow_partial="trailing-strings")
        return tuple(
            LINES.validate_python(partial.get("lines", []), experimental_allow_partial=True)
        )
    except ValueError:
        return ()


def facts_and_refusals(
    facts: Sequence[Fact], refused: Sequence[RefusedCall], *, refusals: bool
) -> tuple[Fact | RefusedCall, ...]:
    placed: list[tuple[int, int, Fact | RefusedCall]] = [
        (index, 1, fact) for index, fact in enumerate(facts)
    ]
    if refusals:
        placed.extend((each.after_facts, 0, each) for each in refused)
    return tuple(entry for *_, entry in sorted(placed, key=lambda slot: slot[:2]))
