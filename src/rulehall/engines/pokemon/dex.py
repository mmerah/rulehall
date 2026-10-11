import re
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from rulehall.core.prompt import ref_of
from rulehall.core.stores import read_model
from rulehall.core.validation import Frozen, Refusal, Slug

DEX_FILE = Path(__file__).parent / "dex.json"
AVATARS_FILE = Path(__file__).parent / "avatars.json"
SIGNATURE_EXCLUDED = frozenset(
    (
        *("hyperbeam", "gigaimpact", "lastresort", "focuspunch", "selfdestruct", "explosion"),
        *("futuresight", "doomdesire", "dreameater", "hiddenpower", "round", "snore", "fling"),
        *("beatup", "naturalgift", "belch", "synchronoise", "steelbeam", "mindblown"),
        *("blastburn", "frenzyplant", "hydrocannon", "rockwrecker", "solarbeam", "solarblade"),
        *("skyattack", "skullbash", "meteorbeam", "beakblast", "mistyexplosion", "memento"),
        *("healingwish", "finalgambit", "fakeout", "firstimpression", "suckerpunch"),
        *("poltergeist", "shelltrap", "spitup", "counter", "mirrorcoat", "metalburst"),
        *("comeuppance", "bide", "weatherball", "terablast", "multiattack", "revelationdance"),
        *("burnup", "doubleshock", "steelroller", "skydrop", "electroshot", "shadowforce"),
        *("fly", "dig", "dive", "bounce", "phantomforce", "geomancy"),
    )
)
# Journey item names that Showdown's dex spells otherwise or lacks.
ITEM_NAMES = {
    "poke-ball": "Poké Ball",
    "potion": "Potion",
    "super-potion": "Super Potion",
    "full-heal": "Full Heal",
    "revive": "Revive",
    "rare-candy": "Rare Candy",
    "everstone": "Everstone",
    "linking-cord": "Linking Cord",
    "black-augurite": "Black Augurite",
}
NATURES = (
    *("Hardy", "Lonely", "Brave", "Adamant", "Naughty"),
    *("Bold", "Docile", "Relaxed", "Impish", "Lax"),
    *("Timid", "Hasty", "Serious", "Jolly", "Naive"),
    *("Modest", "Mild", "Quiet", "Bashful", "Rash"),
    *("Calm", "Gentle", "Sassy", "Careful", "Quirky"),
)


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
    evolution_species_ids: tuple[Slug, ...]
    evo_level: int | None
    evo_type: EvoType | None
    evo_item: str | None
    evo_condition: str | None
    evolution_move_id: Slug | None
    evolutions_left: int
    tags: tuple[str, ...]
    levelup: tuple[tuple[int, Slug], ...]
    machines: tuple[Slug, ...]
    entry: str = Field(min_length=1)
    forme_only: bool = False

    def types_text(self) -> str:
        return "/".join(self.types)


class Move(Frozen):
    name: str
    type: str
    category: Literal["Physical", "Special", "Status"]
    target: str
    power: int = Field(ge=0)
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
    ability_names: dict[Slug, str]
    items: dict[str, str]
    item_names: dict[Slug, str]
    type_chart: dict[str, Matchups]

    def require_species(self, species_id: str) -> Species:
        found = self.species.get(species_id)
        if found is None:
            raise Refusal(f"{species_id!r} is no species id of the dex")
        return found

    def item_name(self, item_id: Slug) -> str:
        return ITEM_NAMES.get(item_id) or self.item_names.get(item_id.replace("-", ""), item_id)

    def item_text(self, item_id: Slug) -> str:
        return self.items.get(item_id.replace("-", ""), "")

    def species_ref(self, species_id: Slug) -> str:
        species = self.species[species_id]
        return f"{ref_of(species.name, species_id)} {species.types_text()}"

    def type_chart_text(self) -> str:
        return "\n".join(
            f"- {attacker}: {matchups.text()}" for attacker, matchups in self.type_chart.items()
        )


class Avatar(Frozen):
    id: Slug
    label: str


class NpcAvatars(Frozen):
    classes: tuple[Avatar, ...] = Field(min_length=1)
    leaders: tuple[Avatar, ...] = Field(min_length=1)
    evil_team: tuple[Avatar, ...] = Field(min_length=1)
    rivals: tuple[Avatar, ...] = Field(min_length=1)

    def listed(self) -> tuple[tuple[str, tuple[Avatar, ...]], ...]:
        return (
            ("classes", self.classes),
            ("leaders, Elite Four and champions", self.leaders),
            ("evil team grunts, admins and bosses", self.evil_team),
            ("rivals and professors", self.rivals),
        )


class Avatars(Frozen):
    player: tuple[Slug, ...] = Field(min_length=1)
    npc: NpcAvatars

    def npc_ids(self) -> tuple[Slug, ...]:
        return tuple(avatar.id for _, group in self.npc.listed() for avatar in group)

    def npc_group_lines(self) -> str:
        return "\n".join(
            f"{label}: " + ", ".join(f"{avatar.id} ({avatar.label})" for avatar in group)
            for label, group in self.npc.listed()
        )


@cache
def dex() -> Dex:
    return read_model(DEX_FILE, Dex)


@cache
def avatars() -> Avatars:
    return read_model(AVATARS_FILE, Avatars)


def move_stats(move: Move) -> str:
    accuracy = "sure hit" if move.accuracy is None else f"{move.accuracy}%"
    return " · ".join((*((f"{move.power} BP",) if move.power else ()), accuracy))


def move_brief(move: Move, pp: int | None = None) -> str:
    left = f"PP {move.pp}" if pp is None else f"PP {pp}/{move.pp}"
    return " · ".join((move.type, move.category, move_stats(move), left))


def move_summary(move: Move) -> str:
    return f"{move_stats(move)} · {move.text}" if move.text else move_stats(move)


def showdown_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def species_name(species_id: Slug) -> str:
    return dex().species[species_id].name
