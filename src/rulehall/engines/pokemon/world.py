from collections.abc import Collection, Iterable, Sequence
from random import Random
from typing import Annotated, Literal, Self, cast

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import Fact
from rulehall.core.model import Game
from rulehall.core.play import PendingDecision, PendingOption
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, check_unique, slug
from rulehall.core.views import Rows, tag_of
from rulehall.engines.entities import Gauge, OpeningProposal, Sheeted, joined
from rulehall.engines.pokemon.battle.models import (
    FRIENDSHIP_MAX,
    LEVEL_MAX,
    MOVES_MAX,
    TEAM_MAX,
    Ball,
    Battle,
    BattleMove,
    Battler,
    BattleResult,
    BattleSetup,
    Gender,
    Status,
)
from rulehall.engines.pokemon.dex import Move, Species, Stats, avatars, dex
from rulehall.engines.pokemon.rules import (
    ACE_BELOW_TABLE,
    ATK_VS_DEF,
    BADGE_LEVELS,
    BELOW_ACE,
    EV_STAT_MAX,
    EV_TOTAL_MAX,
    EXP_PER_LEVEL,
    FRIENDSHIP_EVOLVE,
    FRIENDSHIP_PER_LEVEL,
    FRIENDSHIP_START,
    ITEMS,
    IV_MAX,
    LINKING_CORD,
    NATURES,
    NICKNAME_MARKS,
    NICKNAME_MAX,
    PRIZE_PER_LEVEL,
    RANK_MAX,
    SEED_LIMIT,
    SKILL_USES,
    SKILLS,
    STARTER_LEVEL,
    STAT_NAMES,
    TM_PREFIX,
    TYPE_BOOSTERS,
    BagId,
    Challenge,
    ItemId,
    Skill,
    TmId,
    attacks_physically,
    check_species,
    evolved,
    item_of,
    latest_moves,
    level_for,
    max_hp,
    signature_moves,
    stats,
    tm_move,
)
from rulehall.engines.rooms.world import Dweller, MapProposal, RegionProposal, RoomWorld

SPECIES_ID = "A species id from SPECIES."
ROSTER = (
    "The Pokemon this person battles with, as species and level. Empty for a person who does "
    "not battle."
)
BADGE = "The badge this trainer gives when beaten, such as a gym leader's. Empty for most trainers."
AVATAR_ID = "How this person looks: exact id from TRAINER CLASSES."
STYLE = (
    "One line on how this gym leader or rival battles, such as 'sets up rain, then sweeps'. "
    "Empty for anyone else."
)
WIN_LINE = "What this gym leader or rival says on beating the player. Empty for anyone else."
LOSE_LINE = "What this gym leader or rival says when the player beats them. Empty for anyone else."
RIVAL = (
    "True for the one rival of the story, who stands in the opening map. A rival has no `roster`: "
    "code builds their team at each battle."
)
WILD = "The wild table of each new place, keyed by place id. A town or a building has no table."
RIVAL_WAITS = (
    "Your rival {name} waits here to battle. Voice them; call `start_battle` when the player "
    "agrees."
)
CENTERS = (
    "Ids of the places of this map that are a Pokemon Center, where the team heals. One in every "
    "town."
)
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


class WildSlot(Frozen):
    species_id: Slug = Field(description=SPECIES_ID)
    lowest: int = Field(ge=1, le=LEVEL_MAX, description="The lowest level it has here.")
    highest: int = Field(ge=1, le=LEVEL_MAX, description="The highest level it has here.")
    weight: int = Field(ge=1, description="How often it shows up, against the other rows.")

    @model_validator(mode="after")
    def _a_species_in_a_level_range(self) -> Self:
        check_species(self.species_id)
        if self.lowest > self.highest:
            raise ValueError(f"lowest {self.lowest} is above highest {self.highest}")
        return self


class RosterSlot(Frozen):
    species_id: Slug = Field(description=SPECIES_ID)
    level: int = Field(ge=1, le=LEVEL_MAX, description="Its level.")

    @model_validator(mode="after")
    def _a_species(self) -> Self:
        check_species(self.species_id)
        return self

    def text(self) -> str:
        return f"{dex().species[self.species_id].name} L{self.level}"


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
            raise ValueError(f"{ITEMS[self.item_id].name} is not a held item")
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
        species = dex().require(species_id)
        return cls._made(
            species_id,
            species,
            level,
            taken,
            nature=rng.choice(NATURES),
            ability=rng.choice(species.abilities),
            gender=species.gender or ("M" if rng.random() < species.male_share else "F"),
            ivs=tuple(rng.randint(0, IV_MAX) for _ in STAT_NAMES),
            evs=(0,) * len(STAT_NAMES),
            move_ids=latest_moves(species, level),
            item_id=None,
        )

    @classmethod
    def built(cls, species_id: Slug, level: int, taken: Iterable[Slug], *, ace: bool) -> Self:
        species = dex().require(species_id)
        physical = attacks_physically(species)
        return cls._made(
            species_id,
            species,
            level,
            taken,
            nature="Adamant" if physical else "Modest",
            ability=species.abilities[0],
            gender=species.gender or ("M" if species.male_share >= 0.5 else "F"),
            ivs=(IV_MAX,) * len(STAT_NAMES),
            evs=(4, EV_STAT_MAX, 0, 0, 0, EV_STAT_MAX)
            if physical
            else (4, 0, 0, EV_STAT_MAX, 0, EV_STAT_MAX),
            move_ids=signature_moves(species, level),
            item_id=TYPE_BOOSTERS[species.types[0]] if ace else "sitrus-berry",
        )

    @classmethod
    def _made(
        cls,
        species_id: Slug,
        species: Species,
        level: int,
        taken: Iterable[Slug],
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
            mon_id=slug(species.name, taken),
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
        tag = tag_of(self.label(), self.mon_id)
        held = "" if self.item_id is None else f"; holds {ITEMS[self.item_id].name}"
        moves = ", ".join(
            f"{slot.move.name} ({slot.move.type}) {slot.pp}/{slot.move.pp}" for slot in self.moves
        )
        return (
            f"- {tag} L{self.level} {self.species.types_text()}, {self._health()}{held}; "
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
            self.friendship = min(
                self.friendship + FRIENDSHIP_PER_LEVEL * len(reached), FRIENDSHIP_MAX
            )
            self._grow_hp()
        return reached, exp > room

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
        if self.item_id is not None and ITEMS[self.item_id].name == species.evo_item:
            self.item_id = None
        self._grow_hp()

    def heal(self) -> None:
        self.hp.current = self.hp.maximum
        for slot in self.moves:
            slot.pp = slot.move.pp
        self.status = ""

    def evolutions(self, species_pool: Collection[Slug]) -> tuple[Slug, ...]:
        species = dex().species
        return tuple(
            evo_id
            for evo_id in self.species.evos
            if evo_id in species_pool
            and self._fits(species[evo_id])
            and self._ready(species[evo_id])
        )

    def item_refusal(self, item_id: BagId, species_pool: Collection[Slug], cap: int) -> str:
        item = item_of(item_id)
        name = self.name
        match item.kind:
            case "ball":
                return "A ball is thrown on the battle screen."
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
            case "evolution" if self.evolution_by_item(species_pool, item.name) is None:
                return f"{item.name} does not evolve {name}"
            case "held" if self.item_id == item_id:
                return f"{name} already holds the {item.name}"
            case "tm" if not self.can_learn(item_id.removeprefix(TM_PREFIX)):
                return f"{name} cannot learn {tm_move(item_id).name} from a TM now"
            case _:
                return ""

    def evolution_by_item(self, species_pool: Collection[Slug], item_name: str) -> Slug | None:
        held = None if self.item_id is None else ITEMS[self.item_id].name
        for evo_id in self.species.evos:
            if evo_id not in species_pool:
                continue
            evolved = dex().species[evo_id]
            if not self._fits(evolved):
                continue
            if evolved.evo_type == "useItem" and evolved.evo_item == item_name:
                return evo_id
            by_cord = evolved.evo_type in ("trade", "other") and item_name == LINKING_CORD
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
                # The world has no clock, weather or console: every other condition counts as met.
                return (
                    evolved.evo_level is not None
                    and evolved.evo_level <= self.level
                    and (compare is None or compare(*self.stats()[1:3]))
                )
            case "levelHold":
                return self.item_id is not None and ITEMS[self.item_id].name == evolved.evo_item
            case "levelMove":
                return any(slot.move_id == evolved.evo_move for slot in self.moves)
            case "levelFriendship" | "levelExtra":
                return self.friendship >= FRIENDSHIP_EVOLVE
            case _:
                return False


class TrainerSheet(Mutable):
    skills: dict[Skill, Annotated[int, Field(ge=0, le=RANK_MAX)]]
    money: int = Field(ge=0)
    bag: dict[BagId, Annotated[int, Field(ge=1)]]
    badges: list[str] = Field(default_factory=list)
    team: list[Mon] = Field(min_length=1, max_length=TEAM_MAX)
    box: list[Mon] = Field(default_factory=list)
    challenge: Challenge
    caught_species: list[Slug] = Field(min_length=1)
    memorial: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_mons(self) -> Self:
        check_unique("mon ids over the team and the box", self.mon_ids())
        return self

    def require_mon(self, mon_id: Slug) -> Mon:
        return _require_in(self.team, mon_id, "on the team")

    def require_boxed(self, mon_id: Slug) -> Mon:
        return _require_in(self.box, mon_id, "in the box")

    def require_owned(self, mon_id: Slug) -> Mon:
        return _require_in(list(self.owned()), mon_id, "on the team or in the box")

    def level_cap(self) -> int:
        badges = len(self.badges)
        if self.challenge == "relaxed" or badges >= len(BADGE_LEVELS):
            return LEVEL_MAX
        return level_for(badges)

    def challenge_line(self) -> str:
        cap = self.level_cap()
        return self.challenge if cap == LEVEL_MAX else f"{self.challenge}: level cap {cap}"

    def nickname_refusal(self, mon: Mon, name: str) -> str:
        shaped = name == name.strip() and 0 < len(name) <= NICKNAME_MAX
        if not shaped or not all(char.isalnum() or char in NICKNAME_MARKS for char in name):
            return f"A nickname is 1 to {NICKNAME_MAX} letters, digits, spaces, ' or -"
        folded = name.casefold()
        if any(other is not mon and other.name.casefold() == folded for other in self.owned()):
            return f"Another Pokemon of the player is already called {name}"
        if any(species.name.casefold() == folded for species in dex().species.values()):
            return f"{name} is the name of a species"
        return ""

    def able(self) -> list[Mon]:
        return [mon for mon in self.team if not mon.fainted]

    def rankable(self) -> tuple[Skill, ...]:
        return tuple(skill for skill in SKILLS if self.skills.get(skill, 0) < RANK_MAX)

    def owned(self) -> tuple[Mon, ...]:
        return (*self.team, *self.box)

    def catch(self, mon: Mon) -> Literal["team", "box"]:
        self.caught_species.append(mon.species_id)
        if len(self.team) < TEAM_MAX:
            self.team.append(mon)
            return "team"
        self.box.append(mon)
        return "box"

    def mon_ids(self) -> list[Slug]:
        return [mon.mon_id for mon in self.owned()]

    def exp_shares(self, result: BattleResult, *, trainer: bool) -> dict[Slug, int]:
        total = sum(EXP_PER_LEVEL * foe.level for foe in result.fainted_foes)
        if trainer:
            total = total * 3 // 2
        if total == 0:
            return {}
        return {
            mon.mon_id: total if mon.mon_id in result.on_field else total // 2
            for mon in self.team
            if not mon.fainted
        }

    def pay(self, cost: int) -> None:
        if cost > self.money:
            raise Refusal(f"that costs ₽{cost}, and the player has only ₽{self.money}")
        self.money -= cost

    def add(self, item_id: BagId, count: int) -> None:
        self.bag[item_id] = self.bag.get(item_id, 0) + count

    def take(self, item_id: BagId) -> None:
        count = self.bag.get(item_id, 0)
        if count == 0:
            raise Refusal(f"the bag holds no {item_of(item_id).name}")
        if count == 1:
            del self.bag[item_id]
        else:
            self.bag[item_id] = count - 1

    def heal_team(self) -> None:
        for mon in self.owned():
            mon.heal()

    def swap(self, team_mon_id: Slug, box_mon_id: Slug) -> tuple[Mon, Mon]:
        """The leaving team mon, then the joining boxed one."""
        leaving = self.require_mon(team_mon_id)
        joining = self.require_boxed(box_mon_id)
        self.team[self.team.index(leaving)] = joining
        self.box[self.box.index(joining)] = leaving
        return leaving, joining

    def store(self, mon_id: Slug) -> Mon:
        mon = self.require_mon(mon_id)
        if refused := self.store_refusal(mon):
            raise Refusal(refused)
        self.team.remove(mon)
        self.box.append(mon)
        return mon

    def withdraw(self, mon_id: Slug) -> Mon:
        mon = self.require_boxed(mon_id)
        if refused := self.withdraw_refusal(mon):
            raise Refusal(refused)
        self.box.remove(mon)
        self.team.append(mon)
        return mon

    def lead(self, mon_id: Slug) -> Mon:
        mon = self.require_mon(mon_id)
        if refused := self.lead_refusal(mon):
            raise Refusal(refused)
        self.team.remove(mon)
        self.team.insert(0, mon)
        return mon

    def store_refusal(self, mon: Mon) -> str:
        if any(other is not mon for other in self.able()):
            return ""
        return "No other team Pokemon can fight"

    def withdraw_refusal(self, mon: Mon) -> str:
        if len(self.team) < TEAM_MAX:
            return ""
        return f"The team is full; swap {mon.name} in"

    def lead_refusal(self, mon: Mon) -> str:
        return f"{mon.name} leads the team already" if self.team[0] is mon else ""


class Trainer(Sheeted[TrainerSheet], Dweller):
    roster: tuple[RosterSlot, ...] = Field(default=(), max_length=TEAM_MAX, description=ROSTER)
    badge: str = Field(default="", description=BADGE)
    style: str = Field(default="", description=STYLE)
    win_line: str = Field(default="", description=WIN_LINE)
    lose_line: str = Field(default="", description=LOSE_LINE)
    rival: bool = Field(default=False, description=RIVAL)
    avatar_id: Slug = Field(description=AVATAR_ID)
    team: SkipJsonSchema[list[Mon]] = Field(default_factory=list)
    beaten: SkipJsonSchema[bool] = False
    last_battle_visit: SkipJsonSchema[int] = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _a_listed_avatar(self) -> Self:
        if self.sheet is not None and self.avatar_id not in avatars().player:
            raise ValueError(f"{self.avatar_id!r} is no player look")
        if self.sheet is None and self.avatar_id not in avatars().npc:
            raise ValueError(f"{self.avatar_id!r} is no id from TRAINER CLASSES")
        return self

    def is_key(self) -> bool:
        return bool(self.badge) or self.rival

    def rows(self) -> Rows:
        sheet = self.sheet
        if sheet is None:
            roster = ", ".join(slot.text() for slot in self.roster)
            shown = (
                ("Team", roster),
                ("Style", self.style if self.is_key() else ""),
                ("Badge", self.badge),
                ("Beaten", "yes" if self.beaten else ""),
            )
            return tuple((label, value) for label, value in shown if value)
        skills = " · ".join(
            f"{skill.title()} {rank}" for skill in SKILLS if (rank := sheet.skills.get(skill, 0))
        )
        return (
            ("Skills", skills),
            ("Money", f"₽{sheet.money}"),
            ("Badges", ", ".join(sheet.badges) or "none"),
            ("Team", ", ".join(mon.summary() for mon in sheet.team)),
            *((("Memorial", "; ".join(sheet.memorial)),) if sheet.memorial else ()),
        )

    def required(self) -> str:
        return joined(
            super().required(),
            "no team" if self.team else "",
            "not beaten" if self.beaten else "",
            "last_battle_visit 0" if self.last_battle_visit else "",
        )


class PokemonMap(MapProposal[Trainer]):
    wild: dict[Slug, tuple[WildSlot, ...]] = Field(default_factory=dict, description=WILD)
    centers: tuple[Slug, ...] = Field(default=(), description=CENTERS)


class PokemonRegion(PokemonMap, RegionProposal[Trainer]):
    pass


class PokemonWorld(RoomWorld[Trainer]):
    meanwhile_every = 4
    wild: dict[Slug, tuple[WildSlot, ...]] = Field(default_factory=dict)
    learning: list[Learning] = Field(default_factory=list)
    evolving: list[Evolving] = Field(default_factory=list)
    ranks_due: int = Field(default=0, ge=0)
    battle: Battle | None = None
    centers: list[Slug] = Field(default_factory=list)
    encounters: list[Slug] = Field(default_factory=list)
    rival_starter_id: Slug | None = None
    rival_fought_at: int = Field(default=-1, ge=-1)
    rival_due: bool = False
    rival_ledger: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _a_trainer_on_a_map(self) -> Self:
        if self.player.roster:
            raise ValueError("the player's team is `sheet.team`; `roster` is for npc trainers")
        if strays := unknown_wild_places(self.wild, self.places):
            raise ValueError(f"wild tables for places that do not exist: {strays}")
        if strays := sorted(set(self.centers) - set(self.places)):
            raise ValueError(f"Pokemon Centers that are no place: {strays}")
        if len([npc for npc in self.npcs.values() if npc.rival]) > 1:
            raise ValueError("a world has one rival at most")
        return self

    def kill(self, entity_id: Slug) -> list[Fact]:
        self._refuse_key(entity_id)
        return super().kill(entity_id)

    def join_party(self, entity_id: Slug) -> list[Fact]:
        self._refuse_key(entity_id)
        return super().join_party(entity_id)

    def centers_line(self) -> str:
        here = self.current.id
        return ", ".join(
            self.places[place_id].tag + (" (here)" if place_id == here else "")
            for place_id in self.centers
            if self.places[place_id].known
        )

    def rival(self) -> Trainer | None:
        return next((npc for npc in self.npcs.values() if npc.rival), None)

    def sheet_rows(self) -> Rows:
        rows = super().sheet_rows()
        return (*rows, ("Rival", "; ".join(self.rival_ledger))) if self.rival_ledger else rows

    def absorb(self, proposal: OpeningProposal) -> None:
        # Safe: the engine's `opening` and `next_proposal` make every proposal a PokemonMap.
        pokemon_map = cast(PokemonMap, proposal)
        self.wild.update(pokemon_map.wild)
        self.centers.extend(pokemon_map.centers)

    def next_decision(self) -> PendingDecision | None:
        return self._learning_decision() or self._evolution_decision() or self._rank_decision()

    def setup_battle(self, trainer: Trainer | None, foes: tuple[Battler, ...], rng: Random) -> None:
        player = self.player
        sheet = player.require_sheet()
        able = sheet.able()
        if not able:
            raise Refusal("No team Pokemon can fight. Heal the team first.")
        here = self.current.id
        first_here = here not in self.encounters
        catchable = trainer is None and (first_here or sheet.challenge != "nuzlocke")
        balls = (
            tuple(
                Ball(item_id=item_id, name=item_of(item_id).name, count=count)
                for item_id, count in sheet.bag.items()
                if item_of(item_id).kind == "ball"
            )
            if catchable
            else ()
        )
        if trainer is None and first_here:
            self.encounters.append(here)
        setup = BattleSetup(
            kind="wild" if trainer is None else "trainer",
            policy="random" if trainer is None else "model" if trainer.is_key() else "greedy",
            foe_style="" if trainer is None else trainer.style,
            foe_id=None if trainer is None else trainer.id,
            player_name=player.name,
            foe_name=f"Wild {foes[0].name}" if trainer is None else trainer.name,
            player_avatar_id=player.avatar_id,
            foe_avatar_id=None if trainer is None else trainer.avatar_id,
            seed=(
                rng.randrange(SEED_LIMIT),
                rng.randrange(SEED_LIMIT),
                rng.randrange(SEED_LIMIT),
                rng.randrange(SEED_LIMIT),
            ),
            team=tuple(mon.battler() for mon in able),
            foes=foes,
            balls=balls,
        )
        self.battle = Battle(setup=setup)

    def wild_rows(self, species_id: Slug | None) -> tuple[WildSlot, ...]:
        here = self.current
        rows = self.wild.get(here.id, ())
        if not rows:
            raise Refusal(f"{here.name} has no wild Pokemon")
        sheet = self.player.require_sheet()
        if sheet.challenge == "nuzlocke":
            if species_id is not None:
                raise Refusal("In a Nuzlocke the wild table decides: leave species_id null")
            if here.id in self.encounters:
                return rows
            return tuple(row for row in rows if row.species_id not in sheet.caught_species) or rows
        if species_id is None:
            return rows
        chosen = tuple(row for row in rows if row.species_id == species_id)
        if not chosen:
            raise Refusal(f"{species_id!r} is not in WILD HERE")
        return chosen

    def nickname(self, mon_id: Slug, name: str) -> list[Fact]:
        sheet = self.player.require_sheet()
        mon = sheet.require_owned(mon_id)
        if refused := sheet.nickname_refusal(mon, name):
            raise Refusal(refused)
        before = mon.name
        mon.nickname = name
        return [self.player.card_fact(f"{before} is now called {name}")]

    def heal_team(self) -> list[Fact]:
        if self.current.id not in self.centers:
            raise Refusal("No open Pokemon Center here")
        self.player.require_sheet().heal_team()
        return [self.player.card_fact("Team healed")]

    def trainer_team(
        self, trainer: Trainer, species_pool: Collection[Slug], rng: Random
    ) -> list[Mon]:
        if trainer.rival:
            return _built_team(self._rival_roster(species_pool))
        if trainer.badge:
            return _built_team(trainer.roster)
        if not trainer.team:
            for slot in trainer.roster:
                trainer.team.append(
                    Mon.new(slot.species_id, slot.level, rng, [mon.mon_id for mon in trainer.team])
                )
        return trainer.team

    def place_rival(self) -> tuple[list[Fact], list[str]]:
        rival = self.rival()
        here = self.current.id
        if not self.rival_due or rival is None or any(npc.badge for npc in self.at(here)):
            return [], []
        rival.place_id = here
        rival.known = True
        self.rival_due = False
        return [rival.card_fact(f"{rival.name} is here")], [RIVAL_WAITS.format(name=rival.name)]

    def settle_battle(
        self, result: BattleResult, species_pool: Collection[Slug]
    ) -> tuple[list[Fact], list[str]]:
        battle = self.battle
        assert battle is not None
        setup = battle.setup
        player = self.player
        sheet = player.require_sheet()
        facts = [throw.fact for throw in battle.throws]
        for battler in result.team:
            sheet.require_mon(battler.mon_id).apply(battler)
        caught = result.caught
        where = (
            None
            if caught is None
            else sheet.catch(
                Mon.from_battler(caught, f"caught at {self.current.name} at L{caught.level}")
            )
        )
        facts.append(player.card_fact(_outcome(setup, result, where)))
        cap = sheet.level_cap()
        shares = sheet.exp_shares(result, trainer=setup.kind == "trainer")
        for mon_id, exp in shares.items():
            mon = sheet.require_mon(mon_id)
            mon.train(result.fainted_foes)
            before = mon.exp
            reached, clipped = mon.gain(exp, cap)
            if gained := mon.exp - before:
                facts.append(player.card_fact(f"{mon.name} gains {gained} EXP"))
            if reached:
                facts.append(player.card_fact(f"{mon.name} grows to level {reached[-1]}"))
            if clipped:
                facts.append(player.card_fact(f"{mon.name} is at the level cap (L{cap})"))
            facts += self.grow(mon, reached, species_pool)
        if setup.foe_id is not None:
            facts += self._settle_trainer(self.npcs[setup.foe_id], setup, result)
        if sheet.challenge == "nuzlocke":
            facts += self._bury(setup)
        elif all(mon.fainted for mon in sheet.team):
            lost = sheet.money // 2
            sheet.money -= lost
            sheet.heal_team()
            facts.append(player.card_fact(f"You blacked out. -₽{lost}. Your team is healed."))
        self.battle = None
        return facts, []

    def swap_mon(self, team_mon_id: Slug, box_mon_id: Slug) -> list[Fact]:
        leaving, joining = self.player.require_sheet().swap(team_mon_id, box_mon_id)
        line = f"{leaving.name} to the box, {joining.name} to the team"
        return [self.player.card_fact(line)]

    def store_mon(self, mon_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().store(mon_id)
        return [self.player.card_fact(f"{mon.name} to the box")]

    def withdraw_mon(self, mon_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().withdraw(mon_id)
        return [self.player.card_fact(f"{mon.name} to the team")]

    def lead_mon(self, mon_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().lead(mon_id)
        return [self.player.card_fact(f"{mon.name} leads the team")]

    def hold_item(self, mon_id: Slug, item_id: ItemId | None) -> list[Fact]:
        sheet = self.player.require_sheet()
        mon = sheet.require_mon(mon_id)
        name = mon.name
        if item_id is None:
            if mon.item_id is None:
                raise Refusal(f"{name} holds nothing")
            line = f"Took the {ITEMS[mon.item_id].name} from {name}"
        else:
            item = ITEMS[item_id]
            if item.kind != "held":
                raise Refusal(f"{item.name} is not an item to hold")
            if refused := mon.item_refusal(item_id, (), sheet.level_cap()):
                raise Refusal(refused)
            sheet.take(item_id)
            line = f"{name} holds the {item.name}"
        if mon.item_id is not None:
            sheet.add(mon.item_id, 1)
        mon.item_id = item_id
        return [self.player.card_fact(line)]

    def teach_move(self, mon_id: Slug, item_id: TmId) -> list[Fact]:
        sheet = self.player.require_sheet()
        if item_id not in sheet.bag:
            raise Refusal(f"the bag holds no {item_of(item_id).name}")
        mon = sheet.require_mon(mon_id)
        if refused := mon.item_refusal(item_id, (), sheet.level_cap()):
            raise Refusal(refused)
        return self._learn_or_ask(mon, item_id.removeprefix(TM_PREFIX))

    def relearn_move(self, mon_id: Slug, move_id: Slug) -> list[Fact]:
        mon = self.player.require_sheet().require_mon(mon_id)
        if move_id not in mon.relearnable():
            raise Refusal(f"{mon.name} cannot remember {move_id!r}")
        return self._learn_or_ask(mon, move_id)

    def learn_move(self, mon_id: Slug, move_id: Slug, forget_id: Slug | None) -> list[Fact]:
        if self.learning[:1] != [Learning(mon_id=mon_id, move_id=move_id)]:
            raise Refusal("No new move waits on this answer.")
        mon = self.player.require_sheet().require_mon(mon_id)
        name = mon.name
        move = dex().moves[move_id].name
        if forget_id is None:
            line = f"{name} did not learn {move}"
        else:
            mon.learn(move_id, forget_id)
            line = f"{name} forgot {dex().moves[forget_id].name} and learned {move}"
        _ = self.learning.pop(0)
        return [self.player.card_fact(line)]

    def evolve(self, mon_id: Slug, species_id: Slug, species_pool: Collection[Slug]) -> list[Fact]:
        if not any(
            each.mon_id == mon_id and species_id in each.species_ids for each in self.evolving[:1]
        ):
            raise Refusal("No evolution waits on this answer.")
        mon = self.player.require_sheet().require_mon(mon_id)
        name = mon.name
        mon.evolve(species_id)
        _ = self.evolving.pop(0)
        facts = [self.player.card_fact(f"{name} evolved into {mon.species_name}")]
        return facts + self.evolve_chain(mon, species_pool)

    def raise_skill(self, skill: Skill) -> list[Fact]:
        if not self.ranks_due:
            raise Refusal("No skill rank waits.")
        sheet = self.player.require_sheet()
        rank = sheet.skills.get(skill, 0)
        if rank >= RANK_MAX:
            raise Refusal(f"{skill.title()} is already at rank {RANK_MAX}")
        sheet.skills[skill] = rank + 1
        self.ranks_due -= 1
        return [self.player.card_fact(f"{skill.title()} rises to rank {rank + 1}")]

    def use_item(self, item_id: ItemId, mon_id: Slug, species_pool: Collection[Slug]) -> list[Fact]:
        sheet = self.player.require_sheet()
        mon = sheet.require_mon(mon_id)
        item = ITEMS[item_id]
        if item.kind in ("ball", "held", "tm"):
            raise Refusal(f"{item.name} is given or taught on the Team page, not used")
        if refused := mon.item_refusal(item_id, species_pool, sheet.level_cap()):
            raise Refusal(refused)
        name = mon.name
        level = mon.level
        sheet.take(item_id)
        match item.kind:
            case "potion":
                healed = mon.hp.adjust(item.heal)
                line = f"{item.name} on {name}: HP +{healed} → {mon.hp}"
            case "full-heal":
                cured, mon.status = mon.status, ""
                line = f"{item.name} on {name}: {cured} cured"
            case "revive":
                mon.hp.current = mon.hp.maximum // 2
                line = f"{item.name} on {name}: HP {mon.hp}"
            case "candy":
                _ = mon.gain((mon.level + 1) ** 3 - mon.exp, sheet.level_cap())
                line = f"{item.name} on {name}: level {mon.level}"
            case "evolution":
                evolved_id = mon.evolution_by_item(species_pool, item.name)
                assert evolved_id is not None
                mon.evolve(evolved_id)
                line = f"{item.name} on {name}: it evolved into {mon.species_name}"
        facts = [self.player.card_fact(line)]
        return facts + self.grow(mon, list(range(level + 1, mon.level + 1)), species_pool)

    def grow(self, mon: Mon, reached: list[int], species_pool: Collection[Slug]) -> list[Fact]:
        facts: list[Fact] = []
        for level in reached:
            for move_id in mon.moves_at(level):
                if not mon.knows(move_id):
                    facts += self._learn_or_ask(mon, move_id)
        if reached and mon.item_id != "everstone":
            facts += self.evolve_chain(mon, species_pool)
        return facts

    def evolve_chain(self, mon: Mon, species_pool: Collection[Slug]) -> list[Fact]:
        facts: list[Fact] = []
        while len(found := mon.evolutions(species_pool)) == 1:
            name = mon.name
            mon.evolve(found[0])
            facts.append(self.player.card_fact(f"{name} evolved into {mon.species_name}"))
        if len(found) > 1:
            self.evolving.append(Evolving(mon_id=mon.mon_id, species_ids=found))
        return facts

    def _settle_trainer(
        self, trainer: Trainer, setup: BattleSetup, result: BattleResult
    ) -> list[Fact]:
        player = self.player
        sheet = player.require_sheet()
        facts: list[Fact] = []
        won = result.outcome == "won"
        trainer.last_battle_visit = len(self.visits)
        if won and trainer.is_key():
            for mon_id in result.on_field:
                sheet.require_mon(mon_id).wins.append(trainer.name)
        if won and (trainer.rival or not trainer.beaten):
            if not trainer.rival:
                trainer.beaten = True
            prize = PRIZE_PER_LEVEL * max(foe.level for foe in setup.foes)
            sheet.money += prize
            facts.append(player.fact(f"{trainer.name} pays ₽{prize}", card=f"+₽{prize}"))
            if trainer.badge and trainer.badge not in sheet.badges:
                sheet.badges.append(trainer.badge)
                facts.append(player.card_fact(f"You earned the {trainer.badge}"))
                self.rival_due = True
                if sheet.rankable():
                    self.ranks_due += 1
        if trainer.is_key() and (line := trainer.lose_line if won else trainer.win_line):
            facts.append(trainer.card_fact(f'{trainer.name}: "{line}"'))
        if trainer.rival:
            facts += self._rival_leaves(trainer, won=won)
        return facts

    def _rival_leaves(self, rival: Trainer, *, won: bool) -> list[Fact]:
        badges = len(self.player.require_sheet().badges)
        here = self.current
        self.rival_fought_at = badges
        winner = self.player.name if won else rival.name
        plural = "" if badges == 1 else "s"
        self.rival_ledger.append(f"{here.name}, {badges} badge{plural}: {winner} won")
        away = [
            *(place_id for place_id in reversed(self.visits) if place_id != here.id),
            *(way.to_id for way in self.ways.get(here.id, ()) if not way.locked),
        ]
        if not away:
            return []
        rival.place_id = away[0]
        return [rival.card_fact(f"{rival.name} leaves")]

    def _refuse_key(self, entity_id: Slug) -> None:
        person = self.person_of(entity_id)
        if person is not None and person.is_key():
            raise Refusal(f"{person.name} has a part to play; they do not die or join you")

    def _bury(self, setup: BattleSetup) -> list[Fact]:
        sheet = self.player.require_sheet()
        fallen = [mon for mon in sheet.team if mon.fainted]
        foe = setup.foe_name if setup.kind == "trainer" else f"a wild {setup.foes[0].name}"
        # A wiped team stays whole: the journey ends on it.
        if len(fallen) < len(sheet.team):
            for mon in fallen:
                sheet.team.remove(mon)
                sheet.memorial.append(mon.epitaph(foe))
        return [self.player.card_fact(f"{mon.name} has fallen") for mon in fallen]

    def _rival_roster(self, species_pool: Collection[Slug]) -> tuple[RosterSlot, ...]:
        assert self.rival_starter_id is not None
        badges = len(self.player.require_sheet().badges)
        if not badges:
            return (RosterSlot(species_id=self.rival_starter_id, level=STARTER_LEVEL),)
        ace_level = level_for(badges) - ACE_BELOW_TABLE
        ace_id = evolved(self.rival_starter_id, ace_level, species_pool)
        species = dex().species
        seen = {
            slot.species_id for place_id in set(self.visits) for slot in self.wild.get(place_id, ())
        }
        strongest = sorted(
            seen, key=lambda species_id: (-sum(species[species_id].base_stats), species_id)
        )
        others = dict.fromkeys(
            evolved(species_id, ace_level - BELOW_ACE, species_pool) for species_id in strongest
        )
        others.pop(ace_id, None)
        return (
            *(
                RosterSlot(species_id=species_id, level=ace_level - BELOW_ACE)
                for species_id in list(others)[: min(badges, TEAM_MAX - 1)]
            ),
            RosterSlot(species_id=ace_id, level=ace_level),
        )

    def _learn_or_ask(self, mon: Mon, move_id: Slug) -> list[Fact]:
        if len(mon.moves) < MOVES_MAX:
            mon.learn(move_id)
            learned = f"{mon.name} learned {dex().moves[move_id].name}"
            return [self.player.card_fact(learned)]
        self.learning.append(Learning(mon_id=mon.mon_id, move_id=move_id))
        return []

    def _learning_decision(self) -> PendingDecision | None:
        if not self.learning:
            return None
        learning = self.learning[0]
        mon = self.player.require_sheet().require_mon(learning.mon_id)
        move = dex().moves[learning.move_id].name
        return PendingDecision(
            kind="new-move",
            prompt=(
                f"{mon.name} wants to learn {move}. It knows four moves. "
                f"Forget one, or skip {move}?"
            ),
            options=tuple(
                PendingOption(
                    id=forget_id or "skip",
                    name=name,
                    action_name="learn_move",
                    args={
                        "mon_id": learning.mon_id,
                        "move_id": learning.move_id,
                        "forget_id": forget_id,
                    },
                )
                for forget_id, name in (
                    *((slot.move_id, f"Forget {slot.move.name}") for slot in mon.moves),
                    (None, f"Skip {move}"),
                )
            ),
            allows_text=False,
        )

    def _evolution_decision(self) -> PendingDecision | None:
        if not self.evolving:
            return None
        evolving = self.evolving[0]
        mon = self.player.require_sheet().require_mon(evolving.mon_id)
        return PendingDecision(
            kind="evolution",
            prompt=f"{mon.name} is ready to evolve. Into which?",
            options=tuple(
                PendingOption(
                    id=species_id,
                    name=dex().species[species_id].name,
                    action_name="evolve",
                    args={"mon_id": evolving.mon_id, "species_id": species_id},
                )
                for species_id in evolving.species_ids
            ),
            allows_text=False,
        )

    def _rank_decision(self) -> PendingDecision | None:
        options = tuple(
            PendingOption(
                id=skill,
                name=skill.title(),
                brief=SKILL_USES[skill],
                action_name="raise_skill",
                args={"skill": skill},
            )
            for skill in self.player.require_sheet().rankable()
        )
        if not (self.ranks_due and options):
            return None
        return PendingDecision(
            kind="badge-rank",
            prompt="Your new badge gives one skill rank. Which skill gains it?",
            options=options,
            allows_text=False,
        )


PokemonGame = Game[PokemonWorld]


def unknown_wild_places(wild: Collection[Slug], places: Collection[Slug]) -> list[Slug]:
    return sorted(place_id for place_id in wild if place_id not in places)


def _outcome(setup: BattleSetup, result: BattleResult, where: Literal["team", "box"] | None) -> str:
    match result.outcome:
        case "won" if setup.kind == "trainer":
            return f"You beat {setup.foe_name}"
        case "won":
            return f"The wild {setup.foes[0].name} fainted"
        case "lost":
            return "You lost the battle"
        case "fled":
            return "You got away"
        case "caught":
            assert result.caught is not None
            joins = "It joins your team." if where == "team" else "It goes to your box."
            return f"You caught {result.caught.name}. {joins}"


def _built_team(roster: Sequence[RosterSlot]) -> list[Mon]:
    ordered = sorted(roster, key=lambda slot: slot.level)
    team: list[Mon] = []
    for index, slot in enumerate(ordered, 1):
        taken = [mon.mon_id for mon in team]
        team.append(Mon.built(slot.species_id, slot.level, taken, ace=index == len(ordered)))
    return team


def _require_in(mons: list[Mon], mon_id: Slug, where: str) -> Mon:
    found = next((mon for mon in mons if mon.mon_id == mon_id), None)
    if found is None:
        held = ", ".join(mon.mon_id for mon in mons) or "(none)"
        raise Refusal(f"{mon_id!r} is not {where}; {where}: {held}")
    return found
