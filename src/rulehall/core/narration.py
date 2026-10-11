from collections.abc import Sequence
from typing import Self

from pydantic import Field, TypeAdapter, model_validator
from pydantic_core import from_json

from rulehall.core.log import SpokenLine
from rulehall.core.validation import Frozen, Refusal, Slug, check_unique, slug
from rulehall.core.views import Rows, Subject


class Line(Frozen):
    speaker_id: Slug | None = Field(
        default=None,
        description="Exact id of the speaker. Null for narration or an unlisted speaker.",
    )
    unlisted_speaker: str = Field(
        default="",
        description=(
            "Only with a null speaker_id: a short description of an unlisted passer-by who"
            " speaks, such as Fish vendor. Never a proper name. Empty for narration."
        ),
    )
    text: str = Field(
        min_length=1, description="One passage of narration, or only what the speaker says."
    )


class Narration(Frozen):
    """The prose the player reads, split into narration and dialogue."""

    lines: tuple[Line, ...] = Field(description="All narration and dialogue, in order.")


class NarratorView(Frozen):
    """The Narrator's input type: it has no field that can hold hidden canon."""

    place_id: Slug
    title: str
    situation: str
    subjects: tuple[Subject, ...]
    speakers: tuple[Slug, ...]
    party: tuple[Slug, ...] = Field(min_length=1)
    sheet: Rows
    departed: tuple[Subject, ...] = ()

    @model_validator(mode="after")
    def _everyone_is_a_subject(self) -> Self:
        here = {subject.id for subject in self.subjects}
        if strangers := sorted(set(self.speakers) - here):
            raise ValueError(f"speakers who are not subjects: {strangers}")
        if party_strangers := sorted(set(self.party) - here):
            raise ValueError(f"party members who are not subjects: {party_strangers}")
        check_unique("party members", self.party)
        return self

    def others(self) -> tuple[Subject, ...]:
        return tuple(subject for subject in self.subjects if subject.id not in self.party)

    def after(self, before: "NarratorView") -> "NarratorView":
        departed = tuple(
            subject
            for subject in before.subjects
            if subject.id in before.speakers and subject.id not in self.speakers
        )
        return self.model_copy(update={"departed": departed})

    def spoken(self, lines: Sequence[Line]) -> tuple[SpokenLine, ...]:
        voices = self._voices()

        def spoken_line(line: Line) -> SpokenLine:
            if line.speaker_id is None and line.unlisted_speaker:
                try:
                    unlisted_id = self._unlisted_id(line.unlisted_speaker)
                except Refusal:
                    # streamed partials reach spoken before check_narration
                    return SpokenLine(text=line.text)
                return SpokenLine(
                    speaker_id=unlisted_id, speaker=line.unlisted_speaker, text=line.text
                )
            who = None if line.speaker_id is None else voices.get(line.speaker_id)
            if who is None:
                return SpokenLine(text=line.text)
            return SpokenLine(speaker_id=who.id, speaker=who.name, voice=who.voice, text=line.text)

        return tuple(spoken_line(line) for line in lines)

    def check_narration(self, narration: Narration) -> None:
        if not narration.lines:
            raise Refusal("write the narration lines: an empty answer shows the player nothing")
        voices = self._voices()
        named = {subject.name.casefold(): subject.id for subject in voices.values()}
        for line in narration.lines:
            if line.speaker_id is not None and line.speaker_id not in voices:
                raise Refusal(
                    f"{line.speaker_id!r} cannot speak now. Use the id of someone here:"
                    f" {sorted(voices)}. For anyone else, set speaker_id to null and describe them"
                    " in unlisted_speaker"
                )
            if line.speaker_id is not None and line.unlisted_speaker:
                raise Refusal("give unlisted_speaker only with a null speaker_id")
            if line.unlisted_speaker:
                if (listed_id := named.get(line.unlisted_speaker.casefold())) is not None:
                    raise Refusal(
                        f"{line.unlisted_speaker} is listed: use speaker_id {listed_id!r}"
                    )
                _ = self._unlisted_id(line.unlisted_speaker)

    def _voices(self) -> dict[Slug, Subject]:
        voices = {subject.id: subject for subject in self.subjects if subject.id in self.speakers}
        voices.update((subject.id, subject) for subject in self.departed)
        return voices

    def _unlisted_id(self, label: str) -> Slug:
        return slug(f"unlisted {label}", self._voices())


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
