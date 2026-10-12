from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Mutable, Slug

type Cause = Literal["opening", "story", "battle"]
type Voice = Literal["feminine", "masculine", "other"]


class SpokenLine(Frozen):
    speaker_id: Slug | None = None
    speaker: str = ""
    voice: Voice | None = None
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _named_when_spoken(self) -> Self:
        if (self.speaker_id is None) != (not self.speaker):
            raise ValueError("a spoken line names its speaker; narration names nobody")
        if self.speaker_id is None and self.voice is not None:
            raise ValueError("narration has no voice")
        return self

    @property
    def said(self) -> str:
        return f"{self.speaker}: {self.text}" if self.speaker else self.text


class LogEntry(Frozen):
    words: str
    by_option: bool = False
    cause: Cause | None = None
    lines: tuple[SpokenLine, ...]
    facts: tuple[Fact, ...] = ()
    decision: str = ""
    context: str = ""

    def transcript(self) -> str:
        return "\n".join(line.said for line in self.lines)


class Chapter(Mutable):
    title: str
    context: str = ""
    recap: str = ""
    entries: list[LogEntry] = Field(default_factory=list)
