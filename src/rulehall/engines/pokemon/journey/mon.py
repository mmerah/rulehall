from collections.abc import Collection, Iterable, Sequence
from random import Random
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.prompt import ref_of
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, slug, slugs
from rulehall.engines.pokemon.battle.models import (
    FRIENDSHIP_MAX,
    LEVEL_MAX,
    MOVES_MAX,
    BattleMove,
    Battler,
    Gender,
    Status,
)
from rulehall.engines.pokemon.dex import NATURES, Move, Species, Stats, dex
from rulehall.engines.pokemon.journey.items import (
    ITEMS,
    LINKING_CORD_ID,
    TM_PREFIX,
    TYPE_BOOSTERS,
    BagId,
    ItemId,
    bag_name,
    item_of,
    tm_move,
)
from rulehall.engines.pokemon.journey.rules import (
    ATK_VS_DEF,
    BUILT_ITEMS_AT,
    FRIENDSHIP_EVOLVE,
    FRIENDSHIP_PER_LEVEL,
    FRIENDSHIP_START,
    RosterSlot,
    attacks_physically,
    help_bonus,
    latest_moves,
    signature_moves,
)
from rulehall.engines.pokemon.rules import (
    EV_STAT_MAX,
    EV_TOTAL_MAX,
    IV_MAX,
    STAT_NAMES,
    check_species,
    max_hp,
    stats,
)
from rulehall.engines.sheet import Gauge

SHARED_MON_FIELDS = {
    "mon_id",
    "species_id",
    "level",
    "nature",
    "ability",
    "gender",
    "ivs",
    "evs",
    "friendship",
    "status",
}


class MoveSlot(Mutable):
    move_id: Slug
    pp: int = Field(ge=0)

    @model_validator(mode="after")
    def _a_move_of_the_dex(self) -> Self:
        if self.move_id not in dex().moves:
            raise ValueError(f"{self.move_id!r} is no move id of the dex")
        if self.pp > self.move.pp:
            raise ValueError(f"{self.move.name} has at most {self.move.pp} PP, not {self.pp}")
        return self

    @classmethod
    def full(cls, move_id: Slug) -> Self:
        return cls(move_id=move_id, pp=dex().moves[move_id].pp)

    @property
    def move(self) -> Move:
        return dex().moves[self.move_id]


class Learning(Frozen):
    mon_id: Slug
    move_id: Slug


class Evolving(Frozen):
    mon_id: Slug
    species_ids: tuple[Slug, ...] = Field(min_length=2)


class Mon(Mutable):
    mon_id: Slug
    species_id: Slug
    level: int = Field(ge=1, le=LEVEL_MAX)
    exp: int = Field(ge=0)
    nature: str
    ability: str
    gender: Gender
    ivs: Stats
    evs: Stats
    friendship: int = Field(ge=0, le=FRIENDSHIP_MAX)
    item_id: ItemId | None = None
    moves: list[MoveSlot] = Field(min_length=1, max_length=MOVES_MAX)
    hp: Gauge
    status: Status = ""
    nickname: str = ""
    met: str = ""
    wins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _a_legal_mon(self) -> Self:
        check_species(self.species_id)
        if self.item_id is not None and ITEMS[self.item_id].kind != "held":
            raise ValueError(f"{dex().item_name(self.item_id)} is not a held item")
        if self.nature not in NATURES:
            raise ValueError(f"{self.nature!r} is no nature")
        if any(not 0 <= iv <= IV_MAX for iv in self.ivs):
            raise ValueError(f"each IV is 0 to {IV_MAX}, not {self.ivs}")
        if any(not 0 <= ev <= EV_STAT_MAX for ev in self.evs) or sum(self.evs) > EV_TOTAL_MAX:
            raise ValueError(
                f"each EV is 0 to {EV_STAT_MAX}, {EV_TOTAL_MAX} at most in all, not {self.evs}"
            )
        return self

    @classmethod
    def from_battler(cls, battler: Battler, met: str) -> Self:
        return cls(
            **battler.model_dump(include=SHARED_MON_FIELDS),
            exp=battler.level**3,
            moves=[MoveSlot(move_id=move.move_id, pp=move.pp) for move in battler.moves],
            hp=Gauge(current=battler.hp, maximum=max_hp(battler)),
            met=met,
        )

    @classmethod
    def new(cls, species_id: Slug, level: int, rng: Random, taken: Iterable[Slug]) -> Self:
        species = dex().require_species(species_id)
        return cls._made(
            species_id,
            species,
            level,
            slug(species.name, taken),
            nature=rng.choice(NATURES),
            ability=rng.choice(species.abilities),
            gender=species.gender or ("M" if rng.random() < species.male_share else "F"),
            ivs=tuple(rng.randint(0, IV_MAX) for _ in STAT_NAMES),
            evs=(0,) * len(STAT_NAMES),
            move_ids=latest_moves(species, level),
            item_id=None,
        )

    @classmethod
    def built(
        cls, species_id: Slug, level: int, mon_id: Slug, *, ace: bool, badges: int, iv: int, ev: int
    ) -> Self:
        species = dex().require_species(species_id)
        physical = attacks_physically(species)
        item_id = None
        if badges >= BUILT_ITEMS_AT:
            item_id = TYPE_BOOSTERS[species.types[0]] if ace else "sitrus-berry"
        return cls._made(
            species_id,
            species,
            level,
            mon_id,
            nature="Adamant" if physical else "Modest",
            ability=species.abilities[0],
            gender=species.gender or ("M" if species.male_share >= 0.5 else "F"),
            ivs=(iv,) * len(STAT_NAMES),
            evs=(0, ev, 0, 0, 0, ev) if physical else (0, 0, 0, ev, 0, ev),
            move_ids=signature_moves(species, level),
            item_id=item_id,
        )

    @classmethod
    def _made(
        cls,
        species_id: Slug,
        species: Species,
        level: int,
        mon_id: Slug,
        *,
        nature: str,
        ability: str,
        gender: Gender,
        ivs: Stats,
        evs: Stats,
        move_ids: tuple[Slug, ...],
        item_id: ItemId | None,
    ) -> Self:
        hp = stats(species, level, nature, ivs, evs)[0]
        return cls(
            mon_id=mon_id,
            species_id=species_id,
            level=level,
            exp=level**3,
            nature=nature,
            ability=ability,
            gender=gender,
            ivs=ivs,
            evs=evs,
            friendship=FRIENDSHIP_START,
            item_id=item_id,
            moves=[MoveSlot.full(move_id) for move_id in move_ids],
            hp=Gauge(current=hp, maximum=hp),
        )

    @property
    def fainted(self) -> bool:
        return self.hp.current == 0

    @property
    def species(self) -> Species:
        return dex().species[self.species_id]

    @property
    def species_name(self) -> str:
        return self.species.name

    @property
    def name(self) -> str:
        return self.nickname or self.species_name

    def label(self) -> str:
        return f"{self.nickname} ({self.species_name})" if self.nickname else self.species_name

    def summary(self) -> str:
        devoted = ", devoted" if self.friendship >= FRIENDSHIP_EVOLVE else ""
        wins = len(self.wins)
        record = f"{wins} key win{'' if wins == 1 else 's'}, last {self.wins[-1]}" if wins else ""
        head = f"{self.label()} L{self.level}, {self._health()}, {self.nature}{devoted}"
        return "; ".join(part for part in (head, self.met, record) if part)

    def epitaph(self, foe: str) -> str:
        title = f"{self.nickname} the {self.species_name}" if self.nickname else self.species_name
        return ", ".join(part for part in (title, self.met, f"fell to {foe}") if part)

    def stats(self) -> Stats:
        return stats(self.species, self.level, self.nature, self.ivs, self.evs)

    def line(self) -> str:
        ref = ref_of(self.label(), self.mon_id)
        held = "" if self.item_id is None else f"; holds {dex().item_name(self.item_id)}"
        moves = ", ".join(
            f"{slot.move.name} ({slot.move.type}) {slot.pp}/{slot.move.pp}" for slot in self.moves
        )
        return (
            f"- {ref} L{self.level} {self.species.types_text()}, {self._health()}, "
            f"help +{help_bonus(self.friendship)}{held}; "
            f"moves: {moves} — {self.species.entry}"
        )

    def battler(self) -> Battler:
        return Battler(
            **self.model_dump(include=SHARED_MON_FIELDS),
            name=self.name,
            item_id=self.item_id,
            moves=tuple(
                BattleMove(
                    move_id=slot.move_id, name=slot.move.name, type=slot.move.type, pp=slot.pp
                )
                for slot in self.moves
            ),
            hp=self.hp.current,
        )

    def apply(self, battler: Battler) -> None:
        self.hp.current = battler.hp
        self.status = battler.status
        for slot, move in zip(self.moves, battler.moves, strict=True):
            slot.pp = move.pp
        if battler.item_id is None:
            self.item_id = None

    def train(self, foes: Iterable[Battler]) -> None:
        evs = list(self.evs)
        for foe in foes:
            for index, gained in enumerate(dex().species[foe.species_id].ev_yield):
                evs[index] += min(gained, EV_STAT_MAX - evs[index], EV_TOTAL_MAX - sum(evs))
        self.evs = tuple(evs)
        self._grow_hp()

    def gain(self, exp: int, cap: int) -> tuple[list[int], bool]:
        room = cap**3 - self.exp if self.level < cap else 0
        self.exp += min(exp, room)
        reached: list[int] = []
        while self.level < LEVEL_MAX and (self.level + 1) ** 3 <= self.exp:
            self.level += 1
            reached.append(self.level)
        if reached:
            self.befriend(FRIENDSHIP_PER_LEVEL * len(reached))
            self._grow_hp()
        return reached, exp > room

    def befriend(self, amount: int) -> None:
        self.friendship = min(self.friendship + amount, FRIENDSHIP_MAX)

    def moves_at(self, level: int) -> tuple[Slug, ...]:
        return tuple(move_id for learned_at, move_id in self.species.levelup if learned_at == level)

    def can_learn(self, move_id: Slug) -> bool:
        return move_id in self.species.machines and not self.knows(move_id)

    def knows(self, move_id: Slug) -> bool:
        return any(slot.move_id == move_id for slot in self.moves)

    def relearnable(self) -> tuple[Slug, ...]:
        return tuple(
            dict.fromkeys(
                move_id
                for learned_at, move_id in self.species.levelup
                if learned_at <= self.level and not self.knows(move_id)
            )
        )

    def learn(self, move_id: Slug, forget_id: Slug | None = None) -> None:
        slot = MoveSlot.full(move_id)
        if forget_id is None:
            self.moves.append(slot)
            return
        ids = [known.move_id for known in self.moves]
        if forget_id not in ids:
            raise Refusal(f"{self.name} does not know {forget_id!r}")
        self.moves[ids.index(forget_id)] = slot

    def evolve(self, species_id: Slug) -> None:
        index = self.species.abilities.index(self.ability)
        self.species_id = species_id
        species = self.species
        abilities = species.abilities
        self.ability = abilities[index] if index < len(abilities) else abilities[-1]
        if species.gender == "N":
            self.gender = "N"
        if self.item_id is not None and dex().item_name(self.item_id) == species.evo_item:
            self.item_id = None
        self._grow_hp()

    def heal(self) -> None:
        self.hp.current = self.hp.maximum
        for slot in self.moves:
            slot.pp = slot.move.pp
        self.status = ""

    def evolutions(self, species_ids: Collection[Slug]) -> tuple[Slug, ...]:
        species = dex().species
        return tuple(
            evo_id
            for evo_id in self.species.evolution_species_ids
            if evo_id in species_ids
            and self._fits(species[evo_id])
            and self._ready(species[evo_id])
        )

    def item_refusal(self, item_id: BagId, species_ids: Collection[Slug], cap: int) -> str:
        kind, item_name, name = item_of(item_id).kind, bag_name(item_id), self.name
        match kind:
            case "potion" | "candy" if self.fainted:
                return f"{name} has fainted; only a revive helps it"
            case "potion" if self.hp.shortfall == 0:
                return f"{name} already has full HP"
            case "candy" if self.level == LEVEL_MAX:
                return f"{name} is at level {LEVEL_MAX}"
            case "candy" if self.level >= cap:
                return f"{name} is at the level cap (L{cap})"
            case "full-heal" if not self.status:
                return f"{name} has no status to heal"
            case "revive" if not self.fainted:
                return f"{name} has not fainted"
            case "evolution" if self.evolution_by_item(species_ids, item_name) is None:
                return f"{item_name} does not evolve {name}"
            case "held" if self.item_id == item_id:
                return f"{name} already holds the {item_name}"
            case "tm" if not self.can_learn(item_id.removeprefix(TM_PREFIX)):
                return f"{name} cannot learn {tm_move(item_id).name} from a TM now"
            case _:
                return ""

    def evolution_by_item(self, species_ids: Collection[Slug], item_name: str) -> Slug | None:
        held = None if self.item_id is None else dex().item_name(self.item_id)
        for evo_id in self.species.evolution_species_ids:
            if evo_id not in species_ids:
                continue
            evolved = dex().species[evo_id]
            if not self._fits(evolved):
                continue
            if evolved.evo_type == "useItem" and evolved.evo_item == item_name:
                return evo_id
            by_cord = evolved.evo_type in ("trade", "other") and item_name == dex().item_name(
                LINKING_CORD_ID
            )
            if by_cord and evolved.evo_item in (None, held):
                return evo_id
        return None

    def _grow_hp(self) -> None:
        maximum = self.stats()[0]
        self.hp.current += maximum - self.hp.maximum
        self.hp.maximum = maximum

    def _health(self) -> str:
        status = f", {self.status}" if self.status else ""
        return f"{self.hp} HP{status}"

    def _fits(self, evolved: Species) -> bool:
        return evolved.gender in ("", "N", self.gender)

    def _ready(self, evolved: Species) -> bool:
        match evolved.evo_type:
            case None:
                compare = ATK_VS_DEF.get(evolved.evo_condition or "")
                return (
                    evolved.evo_level is not None
                    and evolved.evo_level <= self.level
                    and (compare is None or compare(*self.stats()[1:3]))
                )
            case "levelHold":
                return (
                    self.item_id is not None and dex().item_name(self.item_id) == evolved.evo_item
                )
            case "levelMove":
                return any(slot.move_id == evolved.evolution_move_id for slot in self.moves)
            case "levelFriendship" | "levelExtra":
                return self.friendship >= FRIENDSHIP_EVOLVE
            case _:
                return False


def built_team(roster: Sequence[RosterSlot], badges: int, *, iv: int, ev: int) -> list[Mon]:
    ordered = sorted(roster, key=lambda slot: slot.level)
    mon_ids = slugs(dex().require_species(slot.species_id).name for slot in ordered)
    return [
        Mon.built(
            slot.species_id,
            slot.level,
            mon_id,
            ace=index == len(ordered),
            badges=badges,
            iv=iv,
            ev=ev,
        )
        for index, (slot, mon_id) in enumerate(zip(ordered, mon_ids, strict=True), 1)
    ]
