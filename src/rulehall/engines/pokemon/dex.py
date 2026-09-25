from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from rulehall.core.io import read_model
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.core.views import tag_of

DEX_FILE = Path(__file__).parent / "dex.json"
AVATARS_FILE = Path(__file__).parent / "avatars.json"


type Stats = Annotated[tuple[int, ...], Field(min_length=6, max_length=6)]
type EvoType = Literal[
    "levelExtra", "levelFriendship", "levelHold", "levelMove", "other", "trade", "useItem"
]


class Species(Frozen):
    name: str
    icon: int = Field(ge=0)
    types: tuple[str, ...]
    base_stats: Stats
    ev_yield: Stats
    abilities: tuple[str, ...] = Field(min_length=1)
    gender: Literal["M", "F", "N", ""]
    male_share: float
    evos: tuple[Slug, ...]
    evo_level: int | None
    evo_type: EvoType | None
    evo_item: str | None
    evo_condition: str | None
    evo_move: Slug | None
    evolutions_left: int
    tags: tuple[str, ...]
    levelup: tuple[tuple[int, Slug], ...]
    machines: tuple[Slug, ...]
    entry: str = Field(min_length=1)

    def types_text(self) -> str:
        return "/".join(self.types)


class Move(Frozen):
    name: str
    type: str
    category: Literal["Physical", "Special", "Status"]
    power: int = Field(ge=0)
    # None: the move never misses.
    accuracy: int | None
    pp: int
    tm: bool
    text: str


class Matchups(Frozen):
    strong: tuple[str, ...]
    weak: tuple[str, ...]
    none: tuple[str, ...]

    def text(self) -> str:
        return "; ".join(
            f"{label} {', '.join(types)}"
            for label, types in (
                ("strong vs", self.strong),
                ("weak vs", self.weak),
                ("no effect on", self.none),
            )
            if types
        )


class Dex(Frozen):
    species: dict[Slug, Species]
    moves: dict[Slug, Move]
    # Text by ability name, and by Showdown item id (the slug without dashes).
    abilities: dict[str, str]
    items: dict[str, str]
    type_chart: dict[str, Matchups]

    def require(self, species_id: str) -> Species:
        found = self.species.get(species_id)
        if found is None:
            raise Refusal(f"{species_id!r} is no species id of the dex")
        return found

    def tag(self, species_id: Slug) -> str:
        species = self.species[species_id]
        return f"{tag_of(species.name, species_id)} {species.types_text()}"

    def type_chart_text(self) -> str:
        return "\n".join(
            f"- {attacker}: {matchups.text()}" for attacker, matchups in self.type_chart.items()
        )


class Avatars(Frozen):
    player: tuple[Slug, ...] = Field(min_length=1)
    npc: tuple[Slug, ...] = Field(min_length=1)


@cache
def dex() -> Dex:
    return read_model(DEX_FILE, Dex)


@cache
def avatars() -> Avatars:
    return read_model(AVATARS_FILE, Avatars)
