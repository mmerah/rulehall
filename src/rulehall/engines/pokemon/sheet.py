from collections.abc import Collection, Iterable, Sequence
from random import Random
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.validation import (
    Frozen,
    Mutable,
    Refusal,
    Slug,
    check_unique,
    refuse,
    slug,
    slugs,
)
from rulehall.core.views import Rows, tag_of
from rulehall.engines.pokemon.battle.models import (
    FRIENDSHIP_MAX,
    LEVEL_MAX,
    MOVES_MAX,
    TEAM_MAX,
    BattleMove,
    Battler,
    BattleResult,
    Gender,
    Status,
)
from rulehall.engines.pokemon.dex import (
    ITEMS,
    LINKING_CORD,
    NATURES,
    TYPE_BOOSTERS,
    Move,
    Species,
    Stats,
    avatars,
    dex,
)
from rulehall.engines.pokemon.rules import (
    ATK_VS_DEF,
    BADGE_LEVELS,
    EV_STAT_MAX,
    EV_TOTAL_MAX,
    EXP_PER_LEVEL,
    FRIENDSHIP_EVOLVE,
    FRIENDSHIP_PER_LEVEL,
    FRIENDSHIP_START,
    IV_MAX,
    NICKNAME_MARKS,
    NICKNAME_MAX,
    RANK_MAX,
    SKILLS,
    STAT_NAMES,
    TM_PREFIX,
    BagId,
    Challenge,
    ItemId,
    RosterSlot,
    Skill,
    attacks_physically,
    check_species,
    item_of,
    latest_moves,
    level_for,
    max_hp,
    signature_moves,
    stats,
    tm_move,
)
from rulehall.engines.rooms.world import Dweller
from rulehall.engines.sheet import Gauge, Sheeted, joined

ROSTER = (
    "The Pokemon this person battles with, as species and level. Empty for a person who does "
    "not battle."
)
BADGE = "The badge this trainer gives when beaten, such as a gym leader's. Empty for most trainers."
AVATAR_ID = "How this person looks: exact id from TRAINER CLASSES."
KEY_TRAINER = "key trainer (a gym leader, the rival, an operation's leader or the team's boss)"
STYLE = (
    f"One line on how this {KEY_TRAINER} battles, such as 'sets up rain, then sweeps'. Empty for "
    "anyone else."
)
WIN_LINE = f"What this {KEY_TRAINER} says on beating the player. Empty for anyone else."
LOSE_LINE = f"What this {KEY_TRAINER} says when the player beats them. Empty for anyone else."
RIVAL = (
    "True for the one rival of the story, who stands in the opening map. A rival has no `roster`: "
    "code builds their team at each battle."
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
    def built(cls, species_id: Slug, level: int, mon_id: Slug, *, ace: bool) -> Self:
        species = dex().require(species_id)
        physical = attacks_physically(species)
        return cls._made(
            species_id,
            species,
            level,
            mon_id,
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
            for evo_id in self.species.evolution_species_ids
            if evo_id in species_pool
            and self._fits(species[evo_id])
            and self._ready(species[evo_id])
        )

    def item_refusal(self, item_id: BagId, species_pool: Collection[Slug], cap: int) -> str:
        item = item_of(item_id)
        name = self.name
        match item.kind:
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
        for evo_id in self.species.evolution_species_ids:
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
                return (
                    evolved.evo_level is not None
                    and evolved.evo_level <= self.level
                    and (compare is None or compare(*self.stats()[1:3]))
                )
            case "levelHold":
                return self.item_id is not None and ITEMS[self.item_id].name == evolved.evo_item
            case "levelMove":
                return any(slot.move_id == evolved.evolution_move_id for slot in self.moves)
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
    caught_species_ids: list[Slug] = Field(min_length=1)
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

    def table_level(self) -> int:
        return level_for(len(self.badges))

    def level_cap(self) -> int:
        if self.challenge == "relaxed" or len(self.badges) >= len(BADGE_LEVELS):
            return LEVEL_MAX
        return self.table_level()

    def challenge_line(self) -> str:
        cap = self.level_cap()
        return self.challenge if cap == LEVEL_MAX else f"{self.challenge}: level cap {cap}"

    def nickname_refusal(self, mon: Mon, name: str) -> str:
        shaped = name == name.strip() and 0 < len(name) <= NICKNAME_MAX
        if not shaped or not all(char.isalnum() or char in NICKNAME_MARKS for char in name):
            return f"a nickname is 1 to {NICKNAME_MAX} letters, digits, spaces, ' or -"
        folded = name.casefold()
        if any(other is not mon and other.name.casefold() == folded for other in self.owned()):
            return f"another Pokemon of the player is already called {name}"
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
        self.caught_species_ids.append(mon.species_id)
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
            mon.mon_id: total if mon.mon_id in result.on_field_mon_ids else total // 2
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
        leaving = self.require_mon(team_mon_id)
        joining = self.require_boxed(box_mon_id)
        self.team[self.team.index(leaving)] = joining
        self.box[self.box.index(joining)] = leaving
        return leaving, joining

    def store(self, mon_id: Slug) -> Mon:
        mon = self.require_mon(mon_id)
        refuse(self.store_refusal(mon))
        self.team.remove(mon)
        self.box.append(mon)
        return mon

    def withdraw(self, mon_id: Slug) -> Mon:
        mon = self.require_boxed(mon_id)
        refuse(self.withdraw_refusal(mon))
        self.box.remove(mon)
        self.team.append(mon)
        return mon

    def lead(self, mon_id: Slug) -> Mon:
        mon = self.require_mon(mon_id)
        refuse(self.lead_refusal(mon))
        self.team.remove(mon)
        self.team.insert(0, mon)
        return mon

    def store_refusal(self, mon: Mon) -> str:
        if any(other is not mon for other in self.able()):
            return ""
        return "no other team Pokemon can fight"

    def withdraw_refusal(self, mon: Mon) -> str:
        if len(self.team) < TEAM_MAX:
            return ""
        return f"the team is full; swap {mon.name} in"

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

    def is_key(self, named_ids: Collection[Slug]) -> bool:
        return bool(self.badge) or self.rival or self.id in named_ids

    def rows(self) -> Rows:
        sheet = self.sheet
        if sheet is None:
            roster = ", ".join(slot.text() for slot in self.roster)
            shown = (
                ("Team", roster),
                ("Style", self.style),
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

    def authoring_fault(self) -> str:
        return joined(
            super().authoring_fault(),
            "no team" if self.team else "",
            "not beaten" if self.beaten else "",
            "last_battle_visit 0" if self.last_battle_visit else "",
        )


def built_team(roster: Sequence[RosterSlot]) -> list[Mon]:
    ordered = sorted(roster, key=lambda slot: slot.level)
    mon_ids = slugs(dex().require(slot.species_id).name for slot in ordered)
    return [
        Mon.built(slot.species_id, slot.level, mon_id, ace=index == len(ordered))
        for index, (slot, mon_id) in enumerate(zip(ordered, mon_ids, strict=True), 1)
    ]


def _require_in(mons: list[Mon], mon_id: Slug, where: str) -> Mon:
    found = next((mon for mon in mons if mon.mon_id == mon_id), None)
    if found is None:
        held = ", ".join(mon.mon_id for mon in mons) or "(none)"
        raise Refusal(f"{mon_id!r} is not {where}; {where}: {held}")
    return found
