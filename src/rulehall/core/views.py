from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.play import (
    DecisionOption,
    Line,
    Narration,
    PendingDecision,
    PendingOption,
    SpokenLine,
)
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


# A picture, or one frame of a sheet; a zero size means the whole picture.
class Sprite(Frozen):
    path: Path
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


# Three row shapes, in order: entity (`icon_id`), named value (`brief`, tags or meters), or bare
# name. A row with options or a detail opens its own dialog; a detail row's own are not read.
class PanelRow(Frozen):
    name: str
    brief: str
    icon_id: Slug | None = None
    alive: bool = True
    tags: tuple[Tag, ...] = ()
    meters: tuple[Meter, ...] = ()
    options: tuple[PendingOption, ...] = ()
    detail: tuple["Panel", ...] = ()


class Choice(Frozen):
    command: str
    name: str
    brief: str = ""
    group: str = ""
    # Why it cannot be chosen now; empty when it can. It shows greyed and never runs.
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

    def row(self, options: tuple[PendingOption, ...] = ()) -> PanelRow:
        return PanelRow(
            name=self.name, brief=self.brief, icon_id=self.id, alive=self.alive, options=options
        )


class Panel(Frozen):
    title: str
    rows: tuple[PanelRow, ...]
    portrait: bool = False
    tab: str = SCENE_TAB


PanelRow.model_rebuild()


class NarratorView(Frozen):
    """The Narrator's input type: it has no field that can hold hidden canon."""

    # The place, as the art cache names it: two scenes in one place share one picture.
    place_id: Slug
    title: str
    situation: str
    subjects: tuple[Subject, ...]
    speakers: tuple[Slug, ...]
    # The player first, then who travels with them.
    party: tuple[Slug, ...] = Field(min_length=1)
    # The player's own sheet: theirs to know, so the narrator may show it through detail.
    sheet: Rows

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

    def spoken(self, lines: Sequence[Line]) -> tuple[SpokenLine, ...]:
        here = {subject.id: subject for subject in self.subjects if subject.id in self.speakers}

        def spoken_line(line: Line) -> SpokenLine:
            if line.speaker_id is None:
                return SpokenLine(text=line.text)
            who = here.get(line.speaker_id)
            if who is None:
                raise Refusal(f"nobody here has id {line.speaker_id!r}")
            return SpokenLine(speaker_id=who.id, speaker=who.name, text=line.text)

        return tuple(spoken_line(line) for line in lines)

    def check_narration(self, narration: Narration) -> None:
        if not narration.lines:
            raise Refusal("Write the narration lines. An empty answer shows the player nothing.")
        spoken = {line.speaker_id for line in narration.lines if line.speaker_id is not None}
        if strangers := sorted(spoken - set(self.speakers)):
            raise Refusal(
                f"nobody here has id {', '.join(strangers)}. Only the player, or a person here "
                "with the player, speaks. Use null for `speaker_id` in narration."
            )


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
    decision: PendingDecision | None
    way_on: DecisionOption | None
    ending: str | None
    map: MapView | None = None


class Look(Frozen):
    palette: Mapping[str, str]


def filled(*pairs: tuple[str, str]) -> Rows:
    return tuple(pair for pair in pairs if pair[1])


def tag_of(name: str, entity_id: Slug) -> str:
    return f"{name}[{entity_id}]"


def headline_of(name: str, entity_id: Slug, brief: str, *, alive: bool = True) -> str:
    return tag_of(name, entity_id) + (f" — {brief}" if brief else "") + ("" if alive else " (dead)")
