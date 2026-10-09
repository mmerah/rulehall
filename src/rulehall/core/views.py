from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.log import Line, Narration, SpokenLine, Voice
from rulehall.core.prompt import headline_of
from rulehall.core.validation import Frozen, Refusal, Slug, check_unique, slug

SCENE_TAB = "Scene"

type Rows = tuple[tuple[str, str], ...]


class Tag(Frozen):
    name: str
    colour: str = ""
    help: str = ""


class Meter(Frozen):
    name: str
    current: int = Field(ge=0)
    maximum: int = Field(gt=0)
    colour: str = ""
    help: str = ""


class Sprite(Frozen):
    path: Path
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class PanelRow(Frozen):
    name: str
    brief: str
    help: str = ""
    icon_id: Slug | None = None
    alive: bool = True
    tags: tuple[Tag, ...] = ()
    meters: tuple[Meter, ...] = ()
    options: tuple[ActionOption, ...] = ()
    detail: tuple["Panel", ...] = ()


class Subject(Frozen):
    id: Slug
    name: str = Field(min_length=1)
    brief: str = ""
    alive: bool = True
    voice: Voice

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
    help: str = ""
    tab: str = SCENE_TAB

    def options(self) -> Iterator[ActionOption]:
        for row in self.rows:
            yield from row.options
            for panel in row.detail:
                yield from panel.options()


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


class MapNode(Frozen):
    id: Slug
    name: str
    visited: bool
    unexplored: bool
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
    moves: tuple[ActionOption, ...] = ()
    hint: str
    allows_text: bool = True

    @model_validator(mode="after")
    def _options_are_unambiguous(self) -> Self:
        named: dict[str, ActionOption] = {}
        clashing = {
            option.id for option in self.options() if named.setdefault(option.id, option) != option
        }
        if clashing:
            raise ValueError(f"option ids that name two options: {sorted(clashing)}")
        return self

    def options(self) -> Iterator[ActionOption]:
        yield from self.moves
        if self.decision is not None:
            yield from self.decision.options
        for panel in self.panels:
            yield from panel.options()

    def require_option(self, option_id: Slug) -> ActionOption:
        found = next((option for option in self.options() if option.id == option_id), None)
        if found is None:
            raise Refusal(f"{option_id!r} is not an option now")
        return found


class Look(Frozen):
    palette: Mapping[str, str]
    tagline: str = Field(min_length=1)
    die_faces: int = Field(ge=2)
    pattern: Literal["dots", "grid", "scanlines", "rings"]


class Surface(Frozen):
    """A screen the engine asks the page to host. An engine lists every surface it has, in every
    state: the page builds its screens once."""

    surface_id: Slug
    live: bool
    tab: str = ""
    view: Frozen | None = None


def nonblank_rows(*pairs: tuple[str, str]) -> Rows:
    return tuple(pair for pair in pairs if pair[1])


def require_view[V: Frozen](view: Frozen | None, model: type[V]) -> V:
    if not isinstance(view, model):
        raise TypeError(f"the surface shows {type(view).__name__}, not {model.__name__}")
    return view
