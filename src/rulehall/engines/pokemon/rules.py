from collections.abc import Sequence
from typing import Annotated

from pydantic import AfterValidator

from rulehall.core.validation import Slug
from rulehall.engines.pokemon.battle.models import Battler
from rulehall.engines.pokemon.dex import ITEMS, NATURES, Species, Stats, dex

# Lambda: the check sits below the models, and a direct reference fails basedpyright.
type ItemId = Annotated[str, AfterValidator(lambda item_id: _check_item(item_id))]
IV_MAX = 31
EV_STAT_MAX = 252
EV_TOTAL_MAX = 510
STAT_NAMES = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
LEGENDARY_TAGS = frozenset(("Sub-Legendary", "Restricted Legendary", "Mythical"))
TIMES = "×"  # noqa: RUF001
# NATURES is in game order: index = 5 * raised + lowered, over Atk, Def, Spe, SpA, SpD.
NATURE_STATS = (1, 2, 5, 3, 4)


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


def is_legendary(species: Species) -> bool:
    return bool(LEGENDARY_TAGS.intersection(species.tags))


def check_species(species_id: Slug) -> None:
    if species_id not in dex().species:
        raise ValueError(f"{species_id!r} is no species id from SPECIES")


def effectiveness(attack: str, defender_types: Sequence[str]) -> float:
    matchups = dex().type_chart[attack]
    factor = 1.0
    for defender in defender_types:
        if defender in matchups.none:
            return 0.0
        if defender in matchups.strong:
            factor *= 2
        elif defender in matchups.weak:
            factor /= 2
    return factor


def _check_item(item_id: str) -> str:
    if item_id not in ITEMS:
        raise ValueError(f"{item_id!r} is no item id")
    return item_id
