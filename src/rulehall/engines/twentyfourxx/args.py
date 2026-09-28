from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import DiceEvent
from rulehall.core.tools import PlayerFacing
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.args import ACTOR, BE_SHORT, Attempt, ShortName
from rulehall.engines.twentyfourxx.world import NO_PAY_FIGURE

RISK_MAX = 100
RISK_SHORT = f"Say it in one short phrase, never more than {RISK_MAX} characters."
Risk = Annotated[PlayerFacing, Field(max_length=RISK_MAX)]


class NextScene(Frozen):
    pursuit: str = Field(
        default="",
        description="Where the player is going, in their own words. Empty to offer the way on.",
    )
    by_ship: bool = Field(
        default=False,
        description="True when the crew flies its own ship there with `pursuit`. The ship "
        "stays where it is docked otherwise.",
    )
    complication: str = Field(
        default="",
        description="What arrives or turns here, and why. Empty otherwise.",
    )

    @model_validator(mode="after")
    def _one_or_none(self) -> Self:
        if self.pursuit and self.complication:
            raise ValueError("a pursuit or a complication, not both")
        if self.by_ship and not self.pursuit:
            raise ValueError("by_ship needs the pursuit it flies to")
        return self


class ChangeHindrances(Frozen):
    gained: tuple[ShortName, ...] = Field(
        default=(), description=f"Hindrances the actor now carries. {BE_SHORT}"
    )
    lost: tuple[str, ...] = Field(default=(), description="Hindrances the actor no longer carries.")
    actor_id: Slug | None = Field(default=None, description=ACTOR)

    @model_validator(mode="after")
    def _some_change(self) -> Self:
        if not self.gained and not self.lost:
            raise ValueError("give a gained hindrance or a lost hindrance")
        return self


class GainItem(Frozen):
    name: ShortName = Field(min_length=1, description=f"The item's name. {BE_SHORT}")
    bulky: bool = Field(default=False, description="True when the item takes much space to carry.")
    breaks: int = Field(
        default=1,
        ge=1,
        description="How many times the item can break before it is broken until repaired.",
    )
    cost: int = Field(
        default=0,
        ge=0,
        description="Credits paid; most items cost ₡1. Use 0 for a thing found or given.",
    )
    actor_id: Slug | None = Field(default=None, description=ACTOR)


class RepairItem(Frozen):
    item_id: Slug = Field(
        description="Exact id of an item the actor carries, a ship function, or an item in THE "
        "HOLD while the ship is here."
    )
    cost: int = Field(default=0, ge=0, description="Credits spent on the repair.")
    actor_id: Slug | None = Field(default=None, description=ACTOR)


class Spend(Frozen):
    amount: int = Field(gt=0, description="Credits spent.")
    why: PlayerFacing = Field(min_length=1, description="What the credits pay for, in a few words.")
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    to_id: Slug | None = Field(
        default=None,
        description="Exact id of whoever gets the credits: a crew member keeps them, anyone "
        "else, such as a hire paid up front, takes them. Null when they pay for a thing.",
    )


class TakeLead(Frozen):
    member_id: Slug


class ShipUpgrade(Frozen):
    function_id: Slug = Field(description="Exact id of a ship function. The player pays ₡10.")
    upgrade: ShortName = Field(min_length=1, description=f"What the upgrade is. {BE_SHORT}")


class Defence(Frozen):
    item_id: Slug = Field(description="Exact id of a carried item, or of a ship function.")
    hindrance: ShortName = Field(
        default="",
        description="What the hit leaves behind after the item takes it, as a brief hindrance "
        f"that the engine removes at the next scene. Empty for an item that breaks with no harm. "
        f"{BE_SHORT}",
    )


class Defend(Defence):
    actor_id: Slug | None = Field(default=None, description=ACTOR)


class CarriedItem(Frozen):
    item_id: Slug = Field(description="Exact id of an item the actor carries.")
    actor_id: Slug | None = Field(default=None, description=ACTOR)


class FromHold(Frozen):
    item_id: Slug
    actor_id: Slug


class LoseHoldItem(Frozen):
    item_id: Slug = Field(description="Exact id of an item in THE HOLD.")
    why: ShortName = Field(
        min_length=1, description=f"What takes it: a raid, an impound or a theft. {BE_SHORT}"
    )


class Staked(Frozen):
    risk: Risk = Field(
        default="",
        description="What they take in full on a disaster: an injury, a loss, a cost or an "
        "alarm. Name it before the roll; set `harm` when it hurts them, and then name the "
        "injury. A roll with no risk is not a roll; a helper's empty `risk` shares the actor's "
        f"`risk`, `harm` and `deadly`. {RISK_SHORT}",
    )
    deadly: bool = Field(
        default=False,
        description="True when `risk` is death. A disaster then kills them, and they do not get "
        "`risk` as a hindrance. A setback then maims them.",
    )
    harm: bool = Field(
        default=False,
        description="True when `risk` hurts them: an injury or a wound. `risk` then names the "
        "injury itself, such as `Burned hands`, never the event that causes it. The engine "
        "writes a disaster's `risk` on the sheet as a hindrance and a setback as a brief one, "
        "and the player can break gear to turn a disaster into a brief one. False for a loss, a "
        "cost or an alarm.",
    )
    defend: Defence | None = Field(
        default=None,
        description="The gear that the player named before the roll to break and protect them. "
        "Null when nothing protects them.",
    )


class Helper(Staked):
    actor_id: Slug = Field(description="Exact id of the hired member who helps.")
    hindered: PlayerFacing = Field(
        default="", description="Why the helper is hindered. Empty when nothing hinders them."
    )
    skill: str = Field(
        default="",
        description="The skill the helper rolls. Empty rolls the roll's own `skill`. A d6 when "
        "their sheet lacks it.",
    )


class Roll(Staked, Attempt):
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    skill: str = Field(default="", description="The skill to roll. Empty rolls the plain d6.")
    helped: PlayerFacing = Field(
        default="",
        description="The circumstance that helps: an advantage the story has already set up for "
        "this action, such as a position won earlier, a tool made for this task, or help from a "
        "party member who is not hired. Never scenery, what makes the action possible at all, or "
        "the skill the die already counts. Empty otherwise.",
    )
    helped_by: Helper | None = Field(
        default=None,
        description="The hired member who helps. They roll their skill die and share the risk. "
        "Null when nobody helps.",
    )
    hindered: PlayerFacing = Field(
        default="", description="Why the actor is hindered. Empty when nothing hinders them."
    )
    committed: bool = Field(
        default=False,
        description="True only when the player's own words for this action name this danger and "
        "accept it, such as 'I jump even if I fall'. A bare 'I shoot him' accepts nothing. That "
        "the story told the danger before is never enough.",
    )

    @model_validator(mode="after")
    def _a_risk(self) -> Self:
        if not self.risk:
            raise ValueError("name the `risk`: a roll with no risk is not a roll")
        return self


class FindAgain(Frozen):
    where: str


class DefendHit(Frozen):
    roll: Roll
    rolled: DiceEvent
    choices: dict[Slug, Slug | None]


class Raise(Frozen):
    actor_id: Slug = Field(description="Exact id of a living hired member.")
    skill: PlayerFacing = Field(
        min_length=1,
        description="The skill that the job used for this member. A skill that is not on "
        "their sheet is added at d8.",
    )


class RaiseSkill(Frozen):
    skill: PlayerFacing = Field(
        min_length=1,
        description="The skill the player named for their raise after a job; a new one starts "
        "at d8.",
    )


class BringIn(Frozen):
    who: PlayerFacing = Field(min_length=1, description="The new operator in the player's words.")


class Job(Frozen):
    verb: Literal["find", "take", "finish"] = Field(
        description="`find` looks for work. `take` records agreed work, or new terms for the "
        "open job. `finish` closes the job."
    )
    where: PlayerFacing = Field(
        default="",
        description="Where the player looks for work, in a few words. Required with `find`.",
    )
    terms: PlayerFacing = Field(
        default="",
        description=f"Who wants the work and what the work is, as agreed. {NO_PAY_FIGURE} "
        "Required with `take`.",
    )
    raises: tuple[Raise, ...] = Field(
        default=(),
        description="With `finish`, one per living hired member. The player picks their own raise.",
    )

    @model_validator(mode="after")
    def _fields_for_verb(self) -> Self:
        needed = {"find": ("where", self.where), "take": ("terms", self.terms)}.get(self.verb)
        if needed is not None and not needed[1]:
            raise ValueError(f"{self.verb} needs {needed[0]}")
        return self
