from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.tools import PlayerFacing
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.args import Attempt
from rulehall.engines.pokemon.battle.models import Edge, Terrain, Weather
from rulehall.engines.pokemon.rules import NICKNAME_MAX, BagId, ItemId, Skill, TmId

type Difficulty = Literal["easy", "hard", "very-hard"]
DIFFICULTY: dict[Difficulty, int] = {"easy": 10, "hard": 15, "very-hard": 20}
ITEM_ID = "Exact id of the item."
BAG_ID = "Exact id of the item. A TM is tm-<move id>, such as tm-thunderbolt."
COUNT = "How many."
WEATHER = (
    "The weather of the battle, from the story: rain for a storm, sun for a sunny beach, sand "
    "for a desert, snow for a snowfield. It lasts the whole battle. Null for none."
)
TERRAIN = (
    "The terrain of the battle, from the story: electric for a power plant, grassy for a "
    "meadow, misty for a foggy marsh, psychic for a strange place. It lasts the whole battle. "
    "Null for none."
)


class SkillCheck(Attempt):
    skill: Skill = Field(description="The skill the player uses.")
    difficulty: Difficulty = Field(description="easy is DC 10, hard is DC 15, very-hard is DC 20.")
    helper_mon_id: Slug | None = Field(
        default=None,
        description="Exact id of a team Pokemon that helps. It must not be fainted. Null when "
        "none helps.",
    )
    reason: PlayerFacing = Field(
        default="",
        description="How the helper helps, such as 'Geodude breaks the rock'. The player reads "
        "it. Empty with no helper.",
    )
    edge: Edge | None = Field(
        default=None,
        description="The edge the attempt aims for in the next battle here, such as foe-asleep "
        "for a Stealth ambush or bait for a Nature trap. A success earns it. Null for none.",
    )

    @model_validator(mode="after")
    def _helper_with_reason(self) -> Self:
        if (self.helper_mon_id is None) != (not self.reason):
            raise ValueError("a helper_mon_id and a reason come together")
        return self


class ItemCount(Frozen):
    item_id: BagId = Field(description=BAG_ID)
    count: int = Field(default=1, ge=1, description=COUNT)


class GainMoney(Frozen):
    amount: int = Field(ge=1, description="How much money, in Pokedollars.")


class UseItem(Frozen):
    item_id: ItemId = Field(description=ITEM_ID)
    mon_id: Slug = Field(description="Exact id of the team Pokemon it is used on.")


class SwapMon(Frozen):
    team_mon_id: Slug = Field(description="Exact id of the team Pokemon that goes to the box.")
    box_mon_id: Slug = Field(description="Exact id of the box Pokemon that joins the team.")


class Nickname(Frozen):
    mon_id: Slug = Field(description="Exact id of the team or box Pokemon the player names.")
    name: str = Field(
        description=f"The nickname: 1 to {NICKNAME_MAX} letters, digits, spaces, ' or -. Not a "
        "species name, and not the name of another of the player's Pokemon."
    )


class ChosenMon(Frozen):
    mon_id: Slug


class HoldItem(Frozen):
    mon_id: Slug
    item_id: ItemId | None


class TeachMove(Frozen):
    mon_id: Slug
    item_id: TmId


class RelearnMove(Frozen):
    mon_id: Slug
    move_id: Slug


class StartBattle(Frozen):
    trainer_id: Slug = Field(description="Exact id of the trainer here who battles the player.")
    weather: Weather | None = Field(default=None, description=WEATHER)
    terrain: Terrain | None = Field(default=None, description=TERRAIN)
    tag: bool = Field(
        default=False,
        description="True for a tag battle: the first party member with a team fights beside "
        "the player, two-on-two. The trainer needs two Pokemon or more.",
    )


class StartWildBattle(Frozen):
    species_id: Slug | None = Field(
        default=None,
        description="A species id from WILD HERE. Null lets the engine roll on the table. Always "
        "null in a Nuzlocke.",
    )
    weather: Weather | None = Field(default=None, description=WEATHER)
    terrain: Terrain | None = Field(default=None, description=TERRAIN)


class WildPick(Frozen):
    species_id: Slug | None = None


class LearnMove(Frozen):
    mon_id: Slug
    move_id: Slug
    forget_id: Slug | None = None


class EvolveInto(Frozen):
    mon_id: Slug
    species_id: Slug


class RaiseSkill(Frozen):
    skill: Skill
