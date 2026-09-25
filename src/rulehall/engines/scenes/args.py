from typing import Self

from pydantic import Field, model_validator

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Slug

MOVING_ON = (
    "The player takes the way on that this scene offered. PLAYER ACTION says where the player "
    "means to go. Play the leaving if nothing stops the player. Then call `next_scene` with "
    "`pursuit` in the player's own words. The worldsmith writes the crossing after this turn."
)

SCENE_LEFT = Fact(
    trace=(
        "the player has left this place; close the scene on the leaving and describe nothing "
        "of where the player arrives: the worldsmith writes the crossing next"
    ),
    told=True,
)


class Enter(Frozen):
    target_id: Slug = Field(description="Exact id of a cast member not already here.")


class Leave(Frozen):
    target_id: Slug = Field(description="Exact id of someone here.")


class NextScene(Frozen):
    pursuit: str = Field(
        default="",
        description="Where the player is going, in their own words. Empty to offer the way on.",
    )
    complication: str = Field(
        default="",
        description="What arrives or turns here, and why. Empty otherwise.",
    )

    @model_validator(mode="after")
    def _one_or_none(self) -> Self:
        if self.pursuit and self.complication:
            raise ValueError("a pursuit or a complication, not both")
        return self
