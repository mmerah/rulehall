from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.log import Voice
from rulehall.core.prompt import headline_of
from rulehall.core.validation import Frozen, Refusal, Slug

SCENE_TAB = "Scene"

type Rows = tuple[tuple[str, str], ...]
type MapNodeKind = Literal["visited", "seen", "unexplored", "region"]


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

    def row(self) -> PanelRow:
        return PanelRow(name=self.name, brief=self.brief, icon_id=self.id, alive=self.alive)


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


class MapNode(Frozen):
    id: Slug
    name: str
    kind: MapNodeKind
    prefill: str


class MapEdge(Frozen):
    from_id: Slug
    to_id: Slug
    locked: bool


class MapView(Frozen):
    region_id: Slug
    region_name: str
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
    standing_options: tuple[ActionOption, ...] = ()
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
        yield from self.standing_options
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


class ScreenSlot(Frozen):
    """A screen the engine asks the page to host. An engine lists every screen slot it has, in every
    state: the page builds its screens once."""

    screen_id: Slug
    live: bool
    tab: str = ""
    view: Frozen | None = None


def nonblank_rows(*pairs: tuple[str, str]) -> Rows:
    return tuple(pair for pair in pairs if pair[1])


def require_view[V: Frozen](view: Frozen | None, model: type[V]) -> V:
    if not isinstance(view, model):
        raise TypeError(f"the engine shows {type(view).__name__}, not {model.__name__}")
    return view
