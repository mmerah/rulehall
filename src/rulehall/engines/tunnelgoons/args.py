from typing import Self

from pydantic import Field, model_validator

from rulehall.core.validation import Frozen, Slug
from rulehall.engines.args import ACTOR, Attempt
from rulehall.engines.tunnelgoons.world import Ability, Boost


class Roll(Attempt):
    ability: Ability = Field(description="The ability that the action uses.")
    item_ids: tuple[Slug, ...] = Field(
        default=(), description="Exact ids of items the actor carries and that clearly help."
    )
    difficulty: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description=(
            "Difficulty Score: 8 easy, 10 moderate, 12 hard. Null when `target_id` is set."
        ),
    )
    target_id: Slug | None = Field(
        default=None,
        description="Exact id of an npc here that the actor acts on, in a fight or in talk. "
        "The Health of that npc is the Difficulty Score.",
    )
    dangerous: bool = Field(
        default=False,
        description="True when a miss would hurt. Talk is not dangerous unless the story says so.",
    )
    actor_id: Slug | None = Field(default=None, description=ACTOR)

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.difficulty is None) == (self.target_id is None):
            raise ValueError("give a difficulty, or an npc to roll against, not both/neither")
        return self


class LevelUp(Frozen):
    ability: Ability | None = Field(
        default=None, description="The ability to raise by 1. Null asks the player."
    )
    boost: Boost | None = Field(
        default=None,
        description="Health or Inventory: which one to raise by 1. Null asks the player.",
    )

    @model_validator(mode="after")
    def _both_or_neither(self) -> Self:
        if (self.ability is None) != (self.boost is None):
            raise ValueError("give both an ability and a boost, or give neither")
        return self
