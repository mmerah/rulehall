from typing import Literal

from rulehall.core.validation import Frozen
from rulehall.engines.pokemon.battle.history import hp_percent

type Category = Literal["Physical", "Special", "Status"]
type StatLine = tuple[int, int, int, int, int]

FULL = 100


class Effect(Frozen):
    id: str
    name: str
    turns: int
    layers: int


class Hit(Frozen):
    hp: int
    maxhp: int
    damage: tuple[int, int] | None
    hits: tuple[int, int]
    multiplier: float
    shield: str
    endured: str
    one_hit_ko: bool

    @property
    def percents(self) -> tuple[int, int] | None:
        if self.damage is None or self.hp == 0:
            return None
        low, high = self.damage
        return FULL * low // self.hp, FULL * high // self.hp

    @property
    def knocks_out(self) -> bool:
        return (
            self.damage is not None
            and self.damage[0] >= self.hp
            and not self.endured
            and not self.one_hit_ko
        )

    @property
    def dealt_share(self) -> int:
        if self.damage is None or self.maxhp == 0:
            return 0
        return FULL * min(self.damage[0], self.hp) // self.maxhp


class AimedHit(Hit):
    target: int
    name: str


class Threat(Hit):
    user: str
    name: str
    type: str


class OwnMove(Frozen):
    name: str
    type: str
    category: Category
    priority: int
    pp: int
    maxpp: int
    lock: str
    target: str
    hits: tuple[AimedHit, ...]


class SeenMove(Frozen):
    move_id: str
    priority: int


class OwnMon(Frozen):
    slot: int
    name: str
    species: str
    level: int
    types: tuple[str, ...]
    hp: int
    maxhp: int
    status: str
    position: int
    boosts: dict[str, int]
    volatiles: tuple[str, ...]
    ability: str
    item: str
    stats: StatLine
    speed: int
    moves: tuple[OwnMove, ...]
    threats: tuple[Threat, ...]

    @property
    def active(self) -> bool:
        return self.position > 0


class SeenMon(Frozen):
    name: str
    species: str
    level: int
    types: tuple[str, ...]
    hp: int
    maxhp: int
    status: str
    position: int
    boosts: dict[str, int]
    volatiles: tuple[str, ...]
    # None: not revealed yet; an empty item: revealed as gone.
    ability: str | None
    abilities: tuple[str, ...]
    item: str | None
    stats: StatLine
    speed: int
    moves: tuple[SeenMove, ...]

    @property
    def active(self) -> bool:
        return self.position > 0

    @property
    def percent(self) -> int:
        return hp_percent(self.hp, self.maxhp)


class Assessment(Frozen):
    turn: int
    weather: Effect | None
    terrain: Effect | None
    rooms: tuple[Effect, ...]
    own_side: tuple[Effect, ...]
    foe_side: tuple[Effect, ...]
    team: tuple[OwnMon, ...]
    foes: tuple[SeenMon, ...]
    unseen: int
