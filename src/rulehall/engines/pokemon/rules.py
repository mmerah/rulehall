import operator
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import AfterValidator, WithJsonSchema

from rulehall.core.validation import Frozen, Slug
from rulehall.engines.pokemon.battle.models import Battler
from rulehall.engines.pokemon.dex import Move, Species, Stats, dex

type Skill = Literal["athletics", "stealth", "perception", "nature", "lore", "charm"]
# Lambdas: the checks sit below the models, and a direct reference fails basedpyright.
type ItemId = Annotated[str, AfterValidator(lambda item_id: _check_item(item_id))]
type TmId = Annotated[str, AfterValidator(lambda item_id: _check_tm(item_id))]
SKILLS: tuple[Skill, ...] = ("athletics", "stealth", "perception", "nature", "lore", "charm")
SKILL_USES: dict[Skill, str] = {
    "athletics": "climb, swim, run, lift",
    "stealth": "hide, sneak, steal",
    "perception": "notice, search, track",
    "nature": "survive outdoors, read the behavior of wild Pokemon",
    "lore": "know facts, use machines, give first aid",
    "charm": "persuade, lie, calm, bargain",
}
RANK_MAX = 3
RANKS_AT_CREATION = 4
RANKS_PER_SKILL_AT_CREATION = 2
SKILL_BONUS = 2
HELP_BONUS = 2
STARTER_LEVEL = 5
START_MONEY = 3000
TM_PREFIX = "tm-"
TM_PRICE = 3000
LINKING_CORD = "Linking Cord"
IV_MAX = 31
EV_STAT_MAX = 252
EV_TOTAL_MAX = 510
STAT_NAMES = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
FRIENDSHIP_START = 70
FRIENDSHIP_PER_LEVEL = 5
FRIENDSHIP_EVOLVE = 160
EXP_PER_LEVEL = 20
PRIZE_PER_LEVEL = 50
SEED_LIMIT = 0x10000
CATCH_BASE = 80
CATCH_PER_LEVEL = 2
STATUS_BONUS = 10
LEGENDARY_MALUS = -30
EVOLUTION_BONUS = {0: -10, 1: 0, 2: 10}
LEGENDARY_TAGS = frozenset(("Sub-Legendary", "Restricted Legendary", "Mythical"))
ATK_VS_DEF: dict[str, Callable[[int, int], bool]] = {
    "with an Atk stat > its Def stat": operator.gt,
    "with an Atk stat < its Def stat": operator.lt,
    "with an Atk stat equal to its Def stat": operator.eq,
}
TIMES = "×"  # noqa: RUF001
NATURES = (
    *("Hardy", "Lonely", "Brave", "Adamant", "Naughty"),
    *("Bold", "Docile", "Relaxed", "Impish", "Lax"),
    *("Timid", "Hasty", "Serious", "Jolly", "Naive"),
    *("Modest", "Mild", "Quiet", "Bashful", "Rash"),
    *("Calm", "Gentle", "Sassy", "Careful", "Quirky"),
)
# NATURES is in game order: index = 5 * raised + lowered, over Atk, Def, Spe, SpA, SpD.
NATURE_STATS = (1, 2, 5, 3, 4)


class Item(Frozen):
    name: str
    price: int
    kind: Literal["ball", "potion", "full-heal", "revive", "candy", "held", "evolution", "tm"]
    catch_bonus: int = 0
    heal: int = 0
    # Only where the dex has no text for the item.
    text: str = ""


ITEMS: dict[str, Item] = {
    "poke-ball": Item(name="Poké Ball", price=200, kind="ball"),
    "great-ball": Item(name="Great Ball", price=600, kind="ball", catch_bonus=10),
    "ultra-ball": Item(name="Ultra Ball", price=800, kind="ball", catch_bonus=20),
    "potion": Item(name="Potion", price=200, kind="potion", heal=20),
    "super-potion": Item(name="Super Potion", price=700, kind="potion", heal=60),
    "full-heal": Item(name="Full Heal", price=400, kind="full-heal"),
    "revive": Item(name="Revive", price=2000, kind="revive"),
    "rare-candy": Item(name="Rare Candy", price=0, kind="candy"),
    "oran-berry": Item(name="Oran Berry", price=200, kind="held"),
    "sitrus-berry": Item(name="Sitrus Berry", price=500, kind="held"),
    "cheri-berry": Item(name="Cheri Berry", price=200, kind="held"),
    "chesto-berry": Item(name="Chesto Berry", price=200, kind="held"),
    "pecha-berry": Item(name="Pecha Berry", price=200, kind="held"),
    "rawst-berry": Item(name="Rawst Berry", price=200, kind="held"),
    "aspear-berry": Item(name="Aspear Berry", price=200, kind="held"),
    "lum-berry": Item(name="Lum Berry", price=500, kind="held"),
    "leftovers": Item(name="Leftovers", price=4000, kind="held"),
    "everstone": Item(
        name="Everstone", price=1000, kind="held", text="Holder does not evolve at a level-up."
    ),
    "silk-scarf": Item(name="Silk Scarf", price=1000, kind="held"),
    "charcoal": Item(name="Charcoal", price=1000, kind="held"),
    "mystic-water": Item(name="Mystic Water", price=1000, kind="held"),
    "miracle-seed": Item(name="Miracle Seed", price=1000, kind="held"),
    "magnet": Item(name="Magnet", price=1000, kind="held"),
    "never-melt-ice": Item(name="Never-Melt Ice", price=1000, kind="held"),
    "black-belt": Item(name="Black Belt", price=1000, kind="held"),
    "poison-barb": Item(name="Poison Barb", price=1000, kind="held"),
    "soft-sand": Item(name="Soft Sand", price=1000, kind="held"),
    "sharp-beak": Item(name="Sharp Beak", price=1000, kind="held"),
    "twisted-spoon": Item(name="Twisted Spoon", price=1000, kind="held"),
    "silver-powder": Item(name="Silver Powder", price=1000, kind="held"),
    "hard-stone": Item(name="Hard Stone", price=1000, kind="held"),
    "spell-tag": Item(name="Spell Tag", price=1000, kind="held"),
    "dragon-fang": Item(name="Dragon Fang", price=1000, kind="held"),
    "black-glasses": Item(name="Black Glasses", price=1000, kind="held"),
    "metal-coat": Item(name="Metal Coat", price=1000, kind="held"),
    "fairy-feather": Item(name="Fairy Feather", price=1000, kind="held"),
    "fire-stone": Item(name="Fire Stone", price=3000, kind="evolution"),
    "water-stone": Item(name="Water Stone", price=3000, kind="evolution"),
    "thunder-stone": Item(name="Thunder Stone", price=3000, kind="evolution"),
    "leaf-stone": Item(name="Leaf Stone", price=3000, kind="evolution"),
    "moon-stone": Item(name="Moon Stone", price=3000, kind="evolution"),
    "linking-cord": Item(
        name=LINKING_CORD,
        price=3000,
        kind="evolution",
        text="Evolves a Pokemon that other games evolve by trade or a special event.",
    ),
    "sun-stone": Item(name="Sun Stone", price=3000, kind="evolution"),
    "shiny-stone": Item(name="Shiny Stone", price=3000, kind="evolution"),
    "dusk-stone": Item(name="Dusk Stone", price=3000, kind="evolution"),
    "dawn-stone": Item(name="Dawn Stone", price=3000, kind="evolution"),
    "ice-stone": Item(name="Ice Stone", price=3000, kind="evolution"),
    "black-augurite": Item(
        name="Black Augurite", price=3000, kind="evolution", text="Evolves Scyther into Kleavor."
    ),
    "tart-apple": Item(name="Tart Apple", price=3000, kind="evolution"),
    "sweet-apple": Item(name="Sweet Apple", price=3000, kind="evolution"),
    "cracked-pot": Item(name="Cracked Pot", price=3000, kind="evolution"),
    "auspicious-armor": Item(name="Auspicious Armor", price=3000, kind="evolution"),
    "malicious-armor": Item(name="Malicious Armor", price=3000, kind="evolution"),
    "kings-rock": Item(name="King's Rock", price=3000, kind="held"),
    "dragon-scale": Item(name="Dragon Scale", price=3000, kind="held"),
    "up-grade": Item(name="Up-Grade", price=3000, kind="held"),
    "dubious-disc": Item(name="Dubious Disc", price=3000, kind="held"),
    "protector": Item(name="Protector", price=3000, kind="held"),
    "electirizer": Item(name="Electirizer", price=3000, kind="held"),
    "magmarizer": Item(name="Magmarizer", price=3000, kind="held"),
    "reaper-cloth": Item(name="Reaper Cloth", price=3000, kind="held"),
    "prism-scale": Item(name="Prism Scale", price=3000, kind="held"),
    "deep-sea-tooth": Item(name="Deep Sea Tooth", price=3000, kind="held"),
    "deep-sea-scale": Item(name="Deep Sea Scale", price=3000, kind="held"),
    "sachet": Item(name="Sachet", price=3000, kind="held"),
    "whipped-dream": Item(name="Whipped Dream", price=3000, kind="held"),
    "oval-stone": Item(name="Oval Stone", price=3000, kind="held"),
    "razor-claw": Item(name="Razor Claw", price=3000, kind="held"),
    "razor-fang": Item(name="Razor Fang", price=3000, kind="held"),
}
type BagId = Annotated[
    ItemId | TmId,
    WithJsonSchema({"anyOf": [{"enum": list(ITEMS), "type": "string"}, {"type": "string"}]}),
]
START_BAG: dict[BagId, int] = {"poke-ball": 5, "potion": 2}


def stats(species: Species, level: int, nature: str, ivs: Stats, evs: Stats) -> Stats:
    raised, lowered = nature_effect(nature) or (None, None)
    shown: list[int] = []
    for index, (base, iv, ev) in enumerate(zip(species.base_stats, ivs, evs, strict=True)):
        core = (2 * base + iv + ev // 4) * level // 100
        if index == 0:
            shown.append(core + level + 10)
            continue
        value = core + 5
        if index == raised:
            value = value * 110 // 100
        if index == lowered:
            value = value * 90 // 100
        shown.append(value)
    return tuple(shown)


def nature_effect(nature: str) -> tuple[int, int] | None:
    raised, lowered = divmod(NATURES.index(nature), 5)
    return None if raised == lowered else (NATURE_STATS[raised], NATURE_STATS[lowered])


def max_hp(battler: Battler) -> int:
    species = dex().species[battler.species_id]
    return stats(species, battler.level, battler.nature, battler.ivs, battler.evs)[0]


def item_of(item_id: BagId) -> Item:
    if item_id in ITEMS:
        return ITEMS[item_id]
    move = tm_move(item_id)
    return Item(name=f"TM {move.name}", price=TM_PRICE, kind="tm")


def tm_move(item_id: TmId) -> Move:
    return dex().moves[item_id.removeprefix(TM_PREFIX)]


def catch_rate(foe: Battler, ball_bonus: int) -> int:
    species = dex().species[foe.species_id]
    maximum = max_hp(foe)
    return (
        CATCH_BASE
        - CATCH_PER_LEVEL * foe.level
        + _hp_bonus(foe.hp, maximum)
        + (STATUS_BONUS if foe.status else 0)
        + EVOLUTION_BONUS[min(species.evolutions_left, 2)]
        + (LEGENDARY_MALUS if LEGENDARY_TAGS.intersection(species.tags) else 0)
        + ball_bonus
    )


def check_species(species_id: Slug) -> None:
    if species_id not in dex().species:
        raise ValueError(f"{species_id!r} is no species id from SPECIES")


def succeeds(face: int, total: int, dc: int) -> bool:
    return face == 20 or (face != 1 and total >= dc)


def _check_item(item_id: str) -> str:
    if item_id not in ITEMS:
        raise ValueError(f"{item_id!r} is no item id")
    return item_id


def _check_tm(item_id: str) -> str:
    move = dex().moves.get(item_id.removeprefix(TM_PREFIX))
    if not item_id.startswith(TM_PREFIX) or move is None or not move.tm:
        raise ValueError(f"{item_id!r} is no TM. A TM is tm-<move id>, such as tm-thunderbolt")
    return item_id


def _hp_bonus(hp: int, maximum: int) -> int:
    if hp == 1:
        return 30
    if 4 * hp <= maximum:
        return 15
    if 2 * hp <= maximum:
        return 0
    if 4 * hp <= 3 * maximum:
        return -15
    return -30
