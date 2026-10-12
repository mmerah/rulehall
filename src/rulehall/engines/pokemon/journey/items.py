from typing import Annotated, Literal

from pydantic import AfterValidator, WithJsonSchema

from rulehall.core.validation import Frozen
from rulehall.engines.pokemon.dex import Move, dex

# Lambda: the check sits below the models, and a direct reference fails basedpyright.
type ItemId = Annotated[str, AfterValidator(lambda item_id: _check_item(item_id))]
type TmId = Annotated[str, AfterValidator(lambda item_id: _check_tm(item_id))]
LINKING_CORD_ID = "linking-cord"
TM_PREFIX = "tm-"
TM_PRICE = 3000


class BagItem(Frozen):
    price: int
    kind: Literal["ball", "potion", "full-heal", "revive", "candy", "held", "evolution", "tm"]
    catch_bonus: int = 0
    heal: int = 0
    text: str = ""


ITEMS: dict[str, BagItem] = {
    "poke-ball": BagItem(price=200, kind="ball"),
    "great-ball": BagItem(price=600, kind="ball", catch_bonus=10),
    "ultra-ball": BagItem(price=800, kind="ball", catch_bonus=20),
    "potion": BagItem(price=200, kind="potion", heal=20),
    "super-potion": BagItem(price=700, kind="potion", heal=60),
    "full-heal": BagItem(price=400, kind="full-heal"),
    "revive": BagItem(price=2000, kind="revive"),
    "rare-candy": BagItem(price=0, kind="candy"),
    "oran-berry": BagItem(price=200, kind="held"),
    "sitrus-berry": BagItem(price=500, kind="held"),
    "cheri-berry": BagItem(price=200, kind="held"),
    "chesto-berry": BagItem(price=200, kind="held"),
    "pecha-berry": BagItem(price=200, kind="held"),
    "rawst-berry": BagItem(price=200, kind="held"),
    "aspear-berry": BagItem(price=200, kind="held"),
    "lum-berry": BagItem(price=500, kind="held"),
    "leftovers": BagItem(price=4000, kind="held"),
    "everstone": BagItem(price=1000, kind="held", text="Holder does not evolve at a level-up."),
    "silk-scarf": BagItem(price=1000, kind="held"),
    "charcoal": BagItem(price=1000, kind="held"),
    "mystic-water": BagItem(price=1000, kind="held"),
    "miracle-seed": BagItem(price=1000, kind="held"),
    "magnet": BagItem(price=1000, kind="held"),
    "never-melt-ice": BagItem(price=1000, kind="held"),
    "black-belt": BagItem(price=1000, kind="held"),
    "poison-barb": BagItem(price=1000, kind="held"),
    "soft-sand": BagItem(price=1000, kind="held"),
    "sharp-beak": BagItem(price=1000, kind="held"),
    "twisted-spoon": BagItem(price=1000, kind="held"),
    "silver-powder": BagItem(price=1000, kind="held"),
    "hard-stone": BagItem(price=1000, kind="held"),
    "spell-tag": BagItem(price=1000, kind="held"),
    "dragon-fang": BagItem(price=1000, kind="held"),
    "black-glasses": BagItem(price=1000, kind="held"),
    "metal-coat": BagItem(price=1000, kind="held"),
    "fairy-feather": BagItem(price=1000, kind="held"),
    "fire-stone": BagItem(price=3000, kind="evolution"),
    "water-stone": BagItem(price=3000, kind="evolution"),
    "thunder-stone": BagItem(price=3000, kind="evolution"),
    "leaf-stone": BagItem(price=3000, kind="evolution"),
    "moon-stone": BagItem(price=3000, kind="evolution"),
    "linking-cord": BagItem(
        price=3000,
        kind="evolution",
        text="Evolves a Pokemon that other games evolve by trade or a special event.",
    ),
    "sun-stone": BagItem(price=3000, kind="evolution"),
    "shiny-stone": BagItem(price=3000, kind="evolution"),
    "dusk-stone": BagItem(price=3000, kind="evolution"),
    "dawn-stone": BagItem(price=3000, kind="evolution"),
    "ice-stone": BagItem(price=3000, kind="evolution"),
    "black-augurite": BagItem(price=3000, kind="evolution", text="Evolves Scyther into Kleavor."),
    "tart-apple": BagItem(price=3000, kind="evolution"),
    "sweet-apple": BagItem(price=3000, kind="evolution"),
    "cracked-pot": BagItem(price=3000, kind="evolution"),
    "auspicious-armor": BagItem(price=3000, kind="evolution"),
    "malicious-armor": BagItem(price=3000, kind="evolution"),
    "kings-rock": BagItem(price=3000, kind="held"),
    "dragon-scale": BagItem(price=3000, kind="held"),
    "up-grade": BagItem(price=3000, kind="held"),
    "dubious-disc": BagItem(price=3000, kind="held"),
    "protector": BagItem(price=3000, kind="held"),
    "electirizer": BagItem(price=3000, kind="held"),
    "magmarizer": BagItem(price=3000, kind="held"),
    "reaper-cloth": BagItem(price=3000, kind="held"),
    "prism-scale": BagItem(price=3000, kind="held"),
    "deep-sea-tooth": BagItem(price=3000, kind="held"),
    "deep-sea-scale": BagItem(price=3000, kind="held"),
    "sachet": BagItem(price=3000, kind="held"),
    "whipped-dream": BagItem(price=3000, kind="held"),
    "oval-stone": BagItem(price=3000, kind="held"),
    "razor-claw": BagItem(price=3000, kind="held"),
    "razor-fang": BagItem(price=3000, kind="held"),
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
type BagId = Annotated[
    ItemId | TmId,
    WithJsonSchema({"anyOf": [{"enum": list(ITEMS), "type": "string"}, {"type": "string"}]}),
]


def item_of(item_id: BagId) -> BagItem:
    if item_id in ITEMS:
        return ITEMS[item_id]
    return BagItem(price=TM_PRICE, kind="tm")


def bag_name(item_id: BagId) -> str:
    if item_id in ITEMS:
        return dex().item_name(item_id)
    return f"TM {tm_move(item_id).name}"


def tm_move(item_id: TmId) -> Move:
    return dex().moves[item_id.removeprefix(TM_PREFIX)]


def _check_item(item_id: str) -> str:
    if item_id not in ITEMS:
        raise ValueError(f"{item_id!r} is no item id")
    return item_id


def _check_tm(item_id: str) -> str:
    move = dex().moves.get(item_id.removeprefix(TM_PREFIX))
    if not item_id.startswith(TM_PREFIX) or move is None or not move.tm:
        raise ValueError(f"{item_id!r} is no TM. A TM is tm-<move id>, such as tm-thunderbolt")
    return item_id
