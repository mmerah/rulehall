import operator
from collections.abc import Callable, Collection, Iterable, Sequence
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, WithJsonSchema, model_validator

from rulehall.core.validation import Frozen, Slug
from rulehall.engines.pokemon.battle.models import LEVEL_MAX, MOVES_MAX, Battler
from rulehall.engines.pokemon.dex import ITEMS, SIGNATURE_EXCLUDED, BagItem, Move, Species, dex
from rulehall.engines.pokemon.rules import (
    EV_STAT_MAX,
    IV_MAX,
    ItemId,
    check_species,
    effectiveness,
    is_legendary,
    max_hp,
)

# Lambda: the check sits below the models, and a direct reference fails basedpyright.
type TmId = Annotated[str, AfterValidator(lambda item_id: _check_tm(item_id))]
type BagId = Annotated[
    ItemId | TmId,
    WithJsonSchema({"anyOf": [{"enum": list(ITEMS), "type": "string"}, {"type": "string"}]}),
]
type Skill = Literal["athletics", "stealth", "perception", "nature", "lore", "charm"]
type Challenge = Literal["relaxed", "hard", "nuzlocke"]
TM_PREFIX = "tm-"
TM_PRICE = 3000
SKILLS: tuple[Skill, ...] = ("athletics", "stealth", "perception", "nature", "lore", "charm")
SKILL_USES: dict[Skill, str] = {
    "athletics": "climb, swim, run, lift",
    "stealth": "hide, sneak, steal",
    "perception": "notice, search, track",
    "nature": "survive outdoors, read the behavior of wild Pokemon",
    "lore": "know facts, use machines, give first aid",
    "charm": "persuade, lie, calm, bargain",
}
CHALLENGES: dict[Challenge, str] = {
    "relaxed": "the journey as it is",
    "hard": "level caps at each gym",
    "nuzlocke": "level caps; a Pokemon that faints is gone; one catch per place",
}
RANK_MAX = 3
RANKS_AT_CREATION = 4
RANKS_PER_SKILL_AT_CREATION = 2
SKILL_BONUS = 2
HELP_BONUSES = ((200, 4), (120, 3), (0, 2))
FRIENDSHIP_PER_HELP = 3
STARTER_LEVEL = 5
START_MONEY = 3000
START_BAG: dict[BagId, int] = {"poke-ball": 5, "potion": 2}
BUILT_IV_START = 15
RIVAL_IV = BUILT_IV_START
BUILT_IV_PER_BADGE = 2
BUILT_EV_PER_BADGE = 32
BUILT_ITEMS_AT = 2
MACHINE_POWER_PER_LEVEL = 3
FRIENDSHIP_START = 70
FRIENDSHIP_PER_LEVEL = 5
FRIENDSHIP_EVOLVE = 160
EXP_PER_LEVEL = 20
CATCH_UP = 2
PRIZE_PER_LEVEL = 50
BADGE_LEVELS = (12, 18, 24, 30, 36, 42, 48, 54)
LEVEL_SPREAD = 2
ACE_BELOW_TABLE = 2
BELOW_ACE = 2
REGULAR_TRAINERS_MAX = 3
WILD_BELOW_ACE = (8, 3)
LEVEL_FLOOR = 2
BOSS_RISE = 2
LEGENDARY_AT = 3
SPECIES_ID = "A species id from SPECIES."
NICKNAME_MAX = 12
NICKNAME_MARKS = " '-"
SEED_LIMIT = 0x10000
CATCH_BASE = 80
CATCH_PER_LEVEL = 2
STATUS_BONUS = 10
BAIT_BONUS = 15
LEGENDARY_MALUS = -30
EVOLUTION_BONUS = {0: -10, 1: 0, 2: 10}
ATK_VS_DEF: dict[str, Callable[[int, int], bool]] = {
    "with an Atk stat > its Def stat": operator.gt,
    "with an Atk stat < its Def stat": operator.lt,
    "with an Atk stat equal to its Def stat": operator.eq,
}


class RosterSlot(Frozen):
    species_id: Slug = Field(description=SPECIES_ID)
    level: int = Field(ge=1, le=LEVEL_MAX, description="Its level.")

    @model_validator(mode="after")
    def _a_species(self) -> Self:
        check_species(self.species_id)
        return self

    def text(self) -> str:
        return f"{dex().species[self.species_id].name} L{self.level}"


def catch_rate(foe: Battler, ball_bonus: int, *, baited: bool) -> int:
    species = dex().species[foe.species_id]
    maximum = max_hp(foe)
    return (
        CATCH_BASE
        - CATCH_PER_LEVEL * foe.level
        + _hp_bonus(foe.hp, maximum)
        + (STATUS_BONUS if foe.status else 0)
        + EVOLUTION_BONUS[min(species.evolutions_left, 2)]
        + (LEGENDARY_MALUS if is_legendary(species) else 0)
        + ball_bonus
        + (BAIT_BONUS if baited else 0)
    )


def item_of(item_id: BagId) -> BagItem:
    if item_id in ITEMS:
        return ITEMS[item_id]
    move = tm_move(item_id)
    return BagItem(name=f"TM {move.name}", price=TM_PRICE, kind="tm")


def tm_move(item_id: TmId) -> Move:
    return dex().moves[item_id.removeprefix(TM_PREFIX)]


def help_bonus(friendship: int) -> int:
    return next(bonus for floor, bonus in HELP_BONUSES if friendship >= floor)


def level_for(badges: int) -> int:
    return BADGE_LEVELS[min(badges, len(BADGE_LEVELS) - 1)]


def built_iv(badges: int) -> int:
    return min(BUILT_IV_START + BUILT_IV_PER_BADGE * badges, IV_MAX)


def built_ev(badges: int) -> int:
    return min(BUILT_EV_PER_BADGE * badges, EV_STAT_MAX)


def rival_ev(badges: int) -> int:
    return built_ev(badges) // 2


def evolved(species_id: Slug, level: int, pool: Collection[Slug]) -> Slug:
    species = dex().species
    while steps := sorted(
        evo_id
        for evo_id in species[species_id].evolution_species_ids
        if evo_id in pool and _levels_into(species[evo_id], level)
    ):
        species_id = steps[0]
    return species_id


def rescaled(
    roster: Sequence[RosterSlot], ace_level: int, pool: Collection[Slug]
) -> tuple[RosterSlot, ...]:
    shift = ace_level - max(slot.level for slot in roster)
    slots: list[RosterSlot] = []
    for slot in roster:
        level = max(slot.level + shift, LEVEL_FLOOR)
        slots.append(RosterSlot(species_id=evolved(slot.species_id, level, pool), level=level))
    return tuple(slots)


def attacks_physically(species: Species) -> bool:
    return species.base_stats[1] >= species.base_stats[3]


def signature_moves(species: Species, level: int) -> tuple[Slug, ...]:
    moves = dex().moves
    learned: dict[Slug, int] = {}
    for learned_at, move_id in species.levelup:
        if learned_at <= level:
            learned[move_id] = max(learned_at, learned.get(move_id, 0))
    machines = (
        move_id
        for move_id in species.machines
        if 0 < moves[move_id].power <= MACHINE_POWER_PER_LEVEL * level
    )
    candidates = sorted({*learned, *machines} - SIGNATURE_EXCLUDED)
    physical = attacks_physically(species)

    def score(move_id: Slug) -> int:
        move = moves[move_id]
        value = move.power * (move.accuracy or 100)
        return value if (move.category == "Physical") == physical else value // 2

    damaging = sorted(
        (move_id for move_id in candidates if moves[move_id].power > 0),
        key=lambda move_id: (-score(move_id), move_id),
    )
    same_type = [move_id for move_id in damaging if moves[move_id].type in species.types]
    other_type = [move_id for move_id in damaging if moves[move_id].type not in species.types]
    status = sorted(
        (move_id for move_id in candidates if move_id in learned and moves[move_id].power == 0),
        key=lambda move_id: (-learned[move_id], move_id),
    )
    picked = [first for group in (same_type, other_type, status) for first in group[:1]]
    picked += [move_id for move_id in damaging if move_id not in picked]
    return tuple(picked[:MOVES_MAX]) or latest_moves(species, level)


def latest_moves(species: Species, level: int) -> tuple[Slug, ...]:
    learned = [move_id for learned_at, move_id in species.levelup if learned_at <= level]
    return tuple(reversed(list(dict.fromkeys(reversed(learned)))[:MOVES_MAX]))


def counter_pick(pool: Iterable[Slug], target_types: Sequence[str], level: int) -> Slug:
    species = dex().species
    moves = dex().moves
    candidates = [
        species_id
        for species_id in pool
        if not is_legendary(species[species_id])
        and species[species_id].evo_type is None
        and (species[species_id].evo_level or 0) <= level
    ]

    def rank(species_id: Slug) -> tuple[int, bool, int, Slug]:
        candidate = species[species_id]
        attacks = {
            moves[move_id].type
            for learned_at, move_id in candidate.levelup
            if learned_at <= level
            and moves[move_id].power > 0
            and moves[move_id].type in candidate.types
        }
        hit = sum(
            any(effectiveness(attack, (target,)) > 1 for attack in attacks)
            for target in target_types
        )
        weak = any(effectiveness(attack, candidate.types) > 1 for attack in target_types)
        return (-hit, weak, -sum(candidate.base_stats), species_id)

    return min(candidates, key=rank)


def succeeds(face: int, total: int, dc: int) -> bool:
    return face == 20 or (face != 1 and total >= dc)


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


def _levels_into(evolution: Species, level: int) -> bool:
    reached = evolution.evo_level is not None and evolution.evo_level <= level
    return evolution.evo_type is None and reached


def _check_tm(item_id: str) -> str:
    move = dex().moves.get(item_id.removeprefix(TM_PREFIX))
    if not item_id.startswith(TM_PREFIX) or move is None or not move.tm:
        raise ValueError(f"{item_id!r} is no TM. A TM is tm-<move id>, such as tm-thunderbolt")
    return item_id
