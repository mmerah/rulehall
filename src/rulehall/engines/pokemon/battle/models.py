from collections import Counter
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Mutable, Slug
from rulehall.engines.pokemon.dex import Stats

type BattleKind = Literal["trainer", "wild"]
type Outcome = Literal["won", "lost", "fled", "caught"]
type Status = Literal["", "brn", "frz", "par", "psn", "tox", "slp"]
type Gender = Literal["M", "F", "N"]

STATUSES: tuple[Status, ...] = ("brn", "frz", "par", "psn", "tox", "slp")
TEAM_MAX = 6
MOVES_MAX = 4
LEVEL_MAX = 100
FRIENDSHIP_MAX = 255


class BattleMove(Frozen):
    move_id: Slug
    name: str
    type: str
    pp: int = Field(ge=0)


class Battler(Frozen):
    mon_id: Slug
    species_id: Slug
    name: str
    level: int = Field(ge=1, le=LEVEL_MAX)
    nature: str
    ability: str
    gender: Gender
    ivs: Stats
    evs: Stats
    friendship: int = Field(ge=0, le=FRIENDSHIP_MAX)
    item_id: Slug | None = None
    moves: tuple[BattleMove, ...] = Field(min_length=1, max_length=MOVES_MAX)
    hp: int = Field(ge=0)
    status: Status = ""


class Ball(Frozen):
    item_id: Slug
    name: str
    count: int = Field(ge=1)


class BattleSetup(Frozen):
    kind: BattleKind
    foe_id: Slug | None
    player_name: str = Field(min_length=1)
    foe_name: str = Field(min_length=1)
    player_avatar_id: Slug
    foe_avatar_id: Slug | None
    seed: tuple[int, int, int, int]
    team: tuple[Battler, ...] = Field(min_length=1, max_length=TEAM_MAX)
    foes: tuple[Battler, ...] = Field(min_length=1, max_length=TEAM_MAX)
    balls: tuple[Ball, ...] = ()

    @model_validator(mode="after")
    def _can_start(self) -> Self:
        if self.kind == "trainer" and self.foe_id is None:
            raise ValueError("a trainer battle needs the foe_id of the trainer")
        if self.kind == "wild" and self.foe_id is not None:
            raise ValueError("a wild battle has no foe_id")
        if self.kind == "wild" and len(self.foes) > 1:
            raise ValueError("a wild battle has one foe")
        if (self.kind == "trainer") != (self.foe_avatar_id is not None):
            raise ValueError("a trainer battle, and only a trainer battle, has a foe_avatar_id")
        # Showdown's `sethp` lifts 0 HP to 1, so a fainted Pokemon would fight again.
        if any(battler.hp == 0 for battler in (*self.team, *self.foes)):
            raise ValueError("a fainted Pokemon cannot enter a battle")
        return self


class BattleResult(Frozen):
    outcome: Outcome
    team: tuple[Battler, ...]
    fainted_foes: tuple[Battler, ...]
    on_field: tuple[Slug, ...]
    caught: Battler | None = None

    @model_validator(mode="after")
    def _caught_fits_the_outcome(self) -> Self:
        if (self.outcome == "caught") != (self.caught is not None):
            raise ValueError("a caught Pokemon comes with the outcome caught, and only with it")
        return self


class Throw(Frozen):
    ball_id: Slug
    caught: bool
    fact: Fact
    input_index: int = Field(ge=0)


class Battle(Mutable):
    setup: BattleSetup
    inputs: list[str] = Field(default_factory=list)
    throws: list[Throw] = Field(default_factory=list)

    def balls_left(self) -> tuple[Ball, ...]:
        used = Counter(throw.ball_id for throw in self.throws)
        return tuple(
            Ball(item_id=ball.item_id, name=ball.name, count=ball.count - used[ball.item_id])
            for ball in self.setup.balls
            if ball.count > used[ball.item_id]
        )

    def can_throw(self) -> bool:
        return (
            self.setup.kind == "wild"
            and all(throw.input_index != len(self.inputs) for throw in self.throws)
            and bool(self.balls_left())
        )
