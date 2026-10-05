from collections import Counter
from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Loose, Mutable, Slug
from rulehall.core.views import Pip
from rulehall.engines.pokemon.dex import Stats, dex

type Policy = Literal["random", "scripted", "model"]
type Outcome = Literal["won", "lost", "fled", "caught"]
type Seat = Literal["player", "ally", "foe"]
type RoleSeat = Literal["ally", "foe"]
type Status = Literal["", "brn", "frz", "par", "psn", "tox", "slp"]
type Gender = Literal["M", "F", "N"]
type Edge = Literal[
    "foe-asleep",
    "foe-paralysed",
    "attack-up",
    "special-attack-up",
    "speed-up",
    "stealth-rock",
    "spikes",
    "bait",
]
type Weather = Literal["rain", "sun", "sand", "snow"]
type Terrain = Literal["electric", "grassy", "misty", "psychic"]
type BattleBackground = Literal[
    "gen6-aquacordetown",
    "gen6-beach",
    "gen6-city",
    "gen6-dampcave",
    "gen6-darkbeach",
    "gen6-darkcity",
    "gen6-darkmeadow",
    "gen6-deepsea",
    "gen6-desert",
    "gen6-earthycave",
    "gen6-elite4drake",
    "gen6-forest",
    "gen6-icecave",
    "gen6-leaderwallace",
    "gen6-library",
    "gen6-meadow",
    "gen6-orasdesert",
    "gen6-orassea",
    "gen6-skypillar",
    "gen5-beach",
    "gen5-beachshore",
    "gen5-city",
    "gen5-dampcave",
    "gen5-deepsea",
    "gen5-desert",
    "gen5-earthycave",
    "gen5-forest",
    "gen5-icecave",
    "gen5-meadow",
    "gen5-mountain",
    "gen5-river",
    "gen5-route",
    "gen5-thunderplains",
    "gen5-volcanocave",
    "gen4-cave",
    "gen4-indoors",
    "gen4-snow",
    "gen4-water",
    "gen3-arena",
    "gen3-cave",
    "gen3-forest",
    "gen3-ocean",
    "gen3-sand",
]
type BattleMusic = Literal["bw-trainer", "bw-rival", "bw2-kanto-gym-leader", "spl-elite4"]

STATUSES: tuple[Status, ...] = ("brn", "frz", "par", "psn", "tox", "slp")
TEAM_MAX = 6
DOUBLE_TEAM_MIN = 2
MOVES_MAX = 4
LEVEL_MAX = 100
FRIENDSHIP_MAX = 255
EDGES: dict[Edge, str] = {
    "foe-asleep": "{foe} is asleep",
    "foe-paralysed": "{foe} is paralysed",
    "attack-up": "your lead's Attack rises",
    "special-attack-up": "your lead's Sp. Atk rises",
    "speed-up": "your lead's Speed rises",
    "stealth-rock": "pointed stones hurt each foe that comes in",
    "spikes": "spikes hurt each foe that comes in",
    "bait": "the bait is out, so a ball catches more easily",
}


class FieldCondition(Frozen):
    text: str
    showdown_id: str
    colour_type: str


WEATHERS: dict[Weather, FieldCondition] = {
    "rain": FieldCondition(text="Rain falls", showdown_id="raindance", colour_type="Water"),
    "sun": FieldCondition(text="The sunlight is harsh", showdown_id="sunnyday", colour_type="Fire"),
    "sand": FieldCondition(text="A sandstorm rages", showdown_id="sandstorm", colour_type="Rock"),
    "snow": FieldCondition(text="Snow falls", showdown_id="snowscape", colour_type="Ice"),
}
TERRAINS: dict[Terrain, FieldCondition] = {
    "electric": FieldCondition(
        text="An electric current runs across the field",
        showdown_id="electricterrain",
        colour_type="Electric",
    ),
    "grassy": FieldCondition(
        text="Grass grows over the field", showdown_id="grassyterrain", colour_type="Grass"
    ),
    "misty": FieldCondition(
        text="Mist covers the field", showdown_id="mistyterrain", colour_type="Fairy"
    ),
    "psychic": FieldCondition(
        text="The field turns strange", showdown_id="psychicterrain", colour_type="Psychic"
    ),
}


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

    @property
    def species_name(self) -> str:
        return dex().species[self.species_id].name


class Ball(Frozen):
    item_id: Slug
    name: str
    count: int = Field(ge=1)


class Ally(Frozen):
    name: str = Field(min_length=1)
    style: str
    avatar_id: Slug
    team: tuple[Battler, ...] = Field(min_length=1, max_length=TEAM_MAX)


class BattleSetup(Frozen):
    policy: Policy
    foe_style: str
    foe_id: Slug | None
    player_name: str = Field(min_length=1)
    foe_name: str = Field(min_length=1)
    player_avatar_id: Slug
    foe_avatar_id: Slug | None
    seed: tuple[int, int, int, int]
    battle_background: BattleBackground
    battle_music: BattleMusic
    team: tuple[Battler, ...] = Field(min_length=1, max_length=TEAM_MAX)
    foes: tuple[Battler, ...] = Field(min_length=1, max_length=TEAM_MAX)
    balls: tuple[Ball, ...] = ()
    edge: Edge | None = None
    weather: Weather | None = None
    terrain: Terrain | None = None
    double: bool = False
    ally: Ally | None = None

    @model_validator(mode="after")
    def _can_start(self) -> Self:
        fewest = min(len(self.player_side()), len(self.foes))
        if self.double and (self.wild or fewest < DOUBLE_TEAM_MIN):
            raise ValueError("a double battle is a trainer battle with two Pokemon a side or more")
        if self.ally is not None and not self.double:
            raise ValueError("an ally fights only in a double battle")
        if self.edge == "bait" and not self.wild:
            raise ValueError("bait works only in a wild battle")
        if self.wild and len(self.foes) > 1:
            raise ValueError("a wild battle has one foe")
        if self.wild != (self.foe_avatar_id is None):
            raise ValueError("a trainer battle, and only a trainer battle, has a foe_avatar_id")
        if self.wild != (self.policy == "random"):
            raise ValueError("a wild battle, and only a wild battle, picks at random")
        # Showdown's `sethp` lifts 0 HP to 1, so a fainted Pokemon would fight again.
        if any(battler.hp == 0 for battler in (*self.player_side(), *self.foes)):
            raise ValueError("a fainted Pokemon cannot enter a battle")
        return self

    @property
    def wild(self) -> bool:
        return self.foe_id is None

    def player_side(self) -> tuple[Battler, ...]:
        return self.team if self.ally is None else (*self.team, *self.ally.team)

    def condition_texts(self) -> tuple[str, ...]:
        lead = self.foes[0].name
        foe = f"the wild {lead}" if self.wild else f"{self.foe_name}'s {lead}"
        return (
            *(() if self.weather is None else (WEATHERS[self.weather].text,)),
            *(() if self.terrain is None else (TERRAINS[self.terrain].text,)),
            *(() if self.edge is None else (f"Edge: {EDGES[self.edge].format(foe=foe)}",)),
        )


class BattleResult(Frozen):
    outcome: Outcome
    team: tuple[Battler, ...]
    sent_out_foes: tuple[Battler, ...]
    on_field_mon_ids: tuple[Slug, ...]
    caught: Battler | None = None
    highlights: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _caught_fits_the_outcome(self) -> Self:
        if (self.outcome == "caught") != (self.caught is not None):
            raise ValueError("a caught Pokemon comes with the outcome caught, and only with it")
        return self

    def fainted_foes(self) -> tuple[Battler, ...]:
        return tuple(foe for foe in self.sent_out_foes if foe.hp == 0)

    def defeated_foes(self) -> tuple[Battler, ...]:
        return (*self.fainted_foes(), *(() if self.caught is None else (self.caught,)))


class DumpMon(Loose):
    slot: int
    hp: int
    status: str
    pp: tuple[int, ...]
    out: int
    held: bool
    active: bool
    boosts: dict[str, int]

    @property
    def pip(self) -> Pip:
        return "fainted" if self.hp == 0 else "able" if self.out else "reserve"


class Throw(Frozen):
    ball_id: Slug
    caught: bool
    fact: Fact
    input_index: int = Field(ge=0)


class Battle(Mutable):
    setup: BattleSetup
    inputs: list[str] = Field(default_factory=list)
    throws: list[Throw] = Field(default_factory=list)
    legendary_id: Slug | None = None

    def balls_left(self) -> tuple[Ball, ...]:
        used = Counter(throw.ball_id for throw in self.throws)
        return tuple(
            Ball(item_id=ball.item_id, name=ball.name, count=ball.count - used[ball.item_id])
            for ball in self.setup.balls
            if ball.count > used[ball.item_id]
        )

    def can_throw(self) -> bool:
        return (
            self.setup.wild
            and all(throw.input_index != len(self.inputs) for throw in self.throws)
            and bool(self.balls_left())
        )
