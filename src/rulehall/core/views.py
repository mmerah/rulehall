from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.log import Line, Narration, SpokenLine
from rulehall.core.validation import Frozen, Refusal, Slug, check_unique

SCENE_TAB = "Scene"

type Rows = tuple[tuple[str, str], ...]


class Tag(Frozen):
    name: str
    colour: str = ""
    hint: str = ""


class Meter(Frozen):
    name: str
    current: int = Field(ge=0)
    maximum: int = Field(gt=0)
    colour: str = ""
    hint: str = ""


class Sprite(Frozen):
    path: Path
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class PanelRow(Frozen):
    name: str
    brief: str
    icon_id: Slug | None = None
    alive: bool = True
    tags: tuple[Tag, ...] = ()
    meters: tuple[Meter, ...] = ()
    options: tuple[ActionOption, ...] = ()
    detail: tuple["Panel", ...] = ()


class BattleChoice(Frozen):
    command: str
    name: str
    brief: str = ""
    group: str = ""
    refusal: str = ""
    tags: tuple[Tag, ...] = ()


class Subject(Frozen):
    id: Slug
    name: str = Field(min_length=1)
    brief: str = ""
    alive: bool = True

    @property
    def headline(self) -> str:
        return headline_of(self.name, self.id, self.brief, alive=self.alive)

    def row(self, options: tuple[ActionOption, ...] = ()) -> PanelRow:
        return PanelRow(
            name=self.name, brief=self.brief, icon_id=self.id, alive=self.alive, options=options
        )


class Panel(Frozen):
    title: str
    rows: tuple[PanelRow, ...]
    tab: str = SCENE_TAB


PanelRow.model_rebuild()


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
        voices = {subject.id: subject for subject in self.subjects if subject.id in self.speakers}
        voices.update((subject.id, subject) for subject in self.departed)

        def spoken_line(line: Line) -> SpokenLine:
            who = None if line.speaker_id is None else voices.get(line.speaker_id)
            if who is None:
                return SpokenLine(text=line.text)
            return SpokenLine(speaker_id=who.id, speaker=who.name, text=line.text)

        return tuple(spoken_line(line) for line in lines)

    def check_narration(self, narration: Narration) -> None:
        if not narration.lines:
            raise Refusal("write the narration lines: an empty answer shows the player nothing")


class MapNode(Frozen):
    id: Slug
    name: str
    visited: bool
    prefill: str


class MapEdge(Frozen):
    from_id: Slug
    to_id: Slug
    locked: bool


class MapView(Frozen):
    nodes: tuple[MapNode, ...]
    edges: tuple[MapEdge, ...]
    here_id: Slug


class PlayerView(Frozen):
    premise: str
    player: Subject
    scene_title: str
    situation: str
    panels: tuple[Panel, ...]
    decision: Decision | None
    ending: str | None
    map: MapView | None = None
    composer_option: ActionOption | None = None
    composer_only: bool = False


class Look(Frozen):
    palette: Mapping[str, str]


def nonblank_rows(*pairs: tuple[str, str]) -> Rows:
    return tuple(pair for pair in pairs if pair[1])


def tag_of(name: str, entity_id: Slug) -> str:
    return f"{name}[{entity_id}]"


def headline_of(name: str, entity_id: Slug, brief: str, *, alive: bool = True) -> str:
    return tag_of(name, entity_id) + (f" — {brief}" if brief else "") + ("" if alive else " (dead)")
