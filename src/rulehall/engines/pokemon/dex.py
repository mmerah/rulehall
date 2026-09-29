from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from rulehall.core.prompt import ref_of
from rulehall.core.stores import read_model
from rulehall.core.validation import Frozen, Refusal, Slug

DEX_FILE = Path(__file__).parent / "dex.json"
AVATARS_FILE = Path(__file__).parent / "avatars.json"
LINKING_CORD = "Linking Cord"
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

    def types_text(self) -> str:
        return "/".join(self.types)


class Move(Frozen):
    name: str
    type: str
    category: Literal["Physical", "Special", "Status"]
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
    items: dict[str, str]
    type_chart: dict[str, Matchups]

    def require_species(self, species_id: str) -> Species:
        found = self.species.get(species_id)
        if found is None:
            raise Refusal(f"{species_id!r} is no species id of the dex")
        return found

    def species_ref(self, species_id: Slug) -> str:
        species = self.species[species_id]
        return f"{ref_of(species.name, species_id)} {species.types_text()}"

    def type_chart_text(self) -> str:
        return "\n".join(
            f"- {attacker}: {matchups.text()}" for attacker, matchups in self.type_chart.items()
        )


class Avatars(Frozen):
    player: tuple[Slug, ...] = Field(min_length=1)
    npc: tuple[Slug, ...] = Field(min_length=1)


class BagItem(Frozen):
    name: str
    price: int
    kind: Literal["ball", "potion", "full-heal", "revive", "candy", "held", "evolution", "tm"]
    catch_bonus: int = 0
    heal: int = 0
    text: str = ""


ITEMS: dict[str, BagItem] = {
    "poke-ball": BagItem(name="Poké Ball", price=200, kind="ball"),
    "great-ball": BagItem(name="Great Ball", price=600, kind="ball", catch_bonus=10),
    "ultra-ball": BagItem(name="Ultra Ball", price=800, kind="ball", catch_bonus=20),
    "potion": BagItem(name="Potion", price=200, kind="potion", heal=20),
    "super-potion": BagItem(name="Super Potion", price=700, kind="potion", heal=60),
    "full-heal": BagItem(name="Full Heal", price=400, kind="full-heal"),
    "revive": BagItem(name="Revive", price=2000, kind="revive"),
    "rare-candy": BagItem(name="Rare Candy", price=0, kind="candy"),
    "oran-berry": BagItem(name="Oran Berry", price=200, kind="held"),
    "sitrus-berry": BagItem(name="Sitrus Berry", price=500, kind="held"),
    "cheri-berry": BagItem(name="Cheri Berry", price=200, kind="held"),
    "chesto-berry": BagItem(name="Chesto Berry", price=200, kind="held"),
    "pecha-berry": BagItem(name="Pecha Berry", price=200, kind="held"),
    "rawst-berry": BagItem(name="Rawst Berry", price=200, kind="held"),
    "aspear-berry": BagItem(name="Aspear Berry", price=200, kind="held"),
    "lum-berry": BagItem(name="Lum Berry", price=500, kind="held"),
    "leftovers": BagItem(name="Leftovers", price=4000, kind="held"),
    "everstone": BagItem(
        name="Everstone", price=1000, kind="held", text="Holder does not evolve at a level-up."
    ),
    "silk-scarf": BagItem(name="Silk Scarf", price=1000, kind="held"),
    "charcoal": BagItem(name="Charcoal", price=1000, kind="held"),
    "mystic-water": BagItem(name="Mystic Water", price=1000, kind="held"),
    "miracle-seed": BagItem(name="Miracle Seed", price=1000, kind="held"),
    "magnet": BagItem(name="Magnet", price=1000, kind="held"),
    "never-melt-ice": BagItem(name="Never-Melt Ice", price=1000, kind="held"),
    "black-belt": BagItem(name="Black Belt", price=1000, kind="held"),
    "poison-barb": BagItem(name="Poison Barb", price=1000, kind="held"),
    "soft-sand": BagItem(name="Soft Sand", price=1000, kind="held"),
    "sharp-beak": BagItem(name="Sharp Beak", price=1000, kind="held"),
    "twisted-spoon": BagItem(name="Twisted Spoon", price=1000, kind="held"),
    "silver-powder": BagItem(name="Silver Powder", price=1000, kind="held"),
    "hard-stone": BagItem(name="Hard Stone", price=1000, kind="held"),
    "spell-tag": BagItem(name="Spell Tag", price=1000, kind="held"),
    "dragon-fang": BagItem(name="Dragon Fang", price=1000, kind="held"),
    "black-glasses": BagItem(name="Black Glasses", price=1000, kind="held"),
    "metal-coat": BagItem(name="Metal Coat", price=1000, kind="held"),
    "fairy-feather": BagItem(name="Fairy Feather", price=1000, kind="held"),
    "fire-stone": BagItem(name="Fire Stone", price=3000, kind="evolution"),
    "water-stone": BagItem(name="Water Stone", price=3000, kind="evolution"),
    "thunder-stone": BagItem(name="Thunder Stone", price=3000, kind="evolution"),
    "leaf-stone": BagItem(name="Leaf Stone", price=3000, kind="evolution"),
    "moon-stone": BagItem(name="Moon Stone", price=3000, kind="evolution"),
    "linking-cord": BagItem(
        name=LINKING_CORD,
        price=3000,
        kind="evolution",
        text="Evolves a Pokemon that other games evolve by trade or a special event.",
    ),
    "sun-stone": BagItem(name="Sun Stone", price=3000, kind="evolution"),
    "shiny-stone": BagItem(name="Shiny Stone", price=3000, kind="evolution"),
    "dusk-stone": BagItem(name="Dusk Stone", price=3000, kind="evolution"),
    "dawn-stone": BagItem(name="Dawn Stone", price=3000, kind="evolution"),
    "ice-stone": BagItem(name="Ice Stone", price=3000, kind="evolution"),
    "black-augurite": BagItem(
        name="Black Augurite", price=3000, kind="evolution", text="Evolves Scyther into Kleavor."
    ),
    "tart-apple": BagItem(name="Tart Apple", price=3000, kind="evolution"),
    "sweet-apple": BagItem(name="Sweet Apple", price=3000, kind="evolution"),
    "cracked-pot": BagItem(name="Cracked Pot", price=3000, kind="evolution"),
    "auspicious-armor": BagItem(name="Auspicious Armor", price=3000, kind="evolution"),
    "malicious-armor": BagItem(name="Malicious Armor", price=3000, kind="evolution"),
    "kings-rock": BagItem(name="King's Rock", price=3000, kind="held"),
    "dragon-scale": BagItem(name="Dragon Scale", price=3000, kind="held"),
    "up-grade": BagItem(name="Up-Grade", price=3000, kind="held"),
    "dubious-disc": BagItem(name="Dubious Disc", price=3000, kind="held"),
    "protector": BagItem(name="Protector", price=3000, kind="held"),
    "electirizer": BagItem(name="Electirizer", price=3000, kind="held"),
    "magmarizer": BagItem(name="Magmarizer", price=3000, kind="held"),
    "reaper-cloth": BagItem(name="Reaper Cloth", price=3000, kind="held"),
    "prism-scale": BagItem(name="Prism Scale", price=3000, kind="held"),
    "deep-sea-tooth": BagItem(name="Deep Sea Tooth", price=3000, kind="held"),
    "deep-sea-scale": BagItem(name="Deep Sea Scale", price=3000, kind="held"),
    "sachet": BagItem(name="Sachet", price=3000, kind="held"),
    "whipped-dream": BagItem(name="Whipped Dream", price=3000, kind="held"),
    "oval-stone": BagItem(name="Oval Stone", price=3000, kind="held"),
    "razor-claw": BagItem(name="Razor Claw", price=3000, kind="held"),
    "razor-fang": BagItem(name="Razor Fang", price=3000, kind="held"),
}
TYPE_BOOSTERS: dict[str, str] = {
    "Normal": "silk-scarf",
    "Fire": "charcoal",
    "Water": "mystic-water",
    "Grass": "miracle-seed",
    "Electric": "magnet",
    "Ice": "never-melt-ice",
    "Fighting": "black-belt",
    "Poison": "poison-barb",
    "Ground": "soft-sand",
    "Flying": "sharp-beak",
    "Psychic": "twisted-spoon",
    "Bug": "silver-powder",
    "Rock": "hard-stone",
    "Ghost": "spell-tag",
    "Dragon": "dragon-fang",
    "Dark": "black-glasses",
    "Steel": "metal-coat",
    "Fairy": "fairy-feather",
}


@cache
def dex() -> Dex:
    return read_model(DEX_FILE, Dex)


@cache
def avatars() -> Avatars:
    return read_model(AVATARS_FILE, Avatars)
