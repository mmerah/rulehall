from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.play import PendingOption
from rulehall.core.tools import Told
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.args import ACTOR, BE_SHORT, Attempt, ShortName
from rulehall.engines.twentyfourxx.world import NO_PAY_FIGURE

RISK_MAX = 100
RISK_SHORT = f"Say it in one short phrase, never more than {RISK_MAX} characters."
Risk = Annotated[Told, Field(max_length=RISK_MAX)]

MOVING_ON = (
    "The player moves on. PLAYER ACTION says where the player means to go. Play the leaving if "
    "nothing stops the player. Then call `next_scene` with `pursuit` in the player's own words. "
    "The worldsmith writes the crossing after this turn."
)
CROSSING = (
    "The player is leaving {left} for the place in SCENE{how}. The narrator told the leaving "
    "already. Write the arrival in the place that SCENE describes, and nothing the player "
    "planned for it. Give the distance and the time in the fewest words that make them real. "
    "End on what the player sees first. WHAT HAPPENED names everyone who travelled with the "
    "player. The player has not acted in the new place, so settle nothing."
)
TURNING = (
    "The situation changes where the player stands. The player did nothing to cause the "
    "change. Write what arrives or changes, as the player sees it, from SCENE and WHAT "
    "HAPPENED. End on what the new situation asks of the player. The player has not answered "
    "it, so settle nothing."
)
BY_SHIP = ", flying there in the crew's own ship. Tell a flight and a landing, not a walk"
JOINING = (
    "{name} joins the crew here, in SCENE, and leads now. Tell the arrival in a line or two. "
    "Settle nothing else."
)
NEW_LEAD_HERE = (
    "{name} leads now and is here, in {scene}, where the dead operator fell. Play them here, "
    "never anywhere else."
)
SCENE_LEFT = "the worldsmith writes the crossing once this turn ends. Stop here and exit."
WAY_OFFERED = (
    "This scene offers a way on. Ask the player what they want to pursue next. Ask in the "
    "fiction, and name what the scene left open. Never ask with a list of choices. The player "
    "can also stay and keep playing here, so ask; do not push the player out."
)

MOVE_ON = PendingOption(
    id="move-on",
    name="Move on",
    brief="Say where you go and move on.",
    action_name="move_on",
)
WAY_UNWRITTEN = Fact(
    told=True,
    trace="the crossing could not be written yet: the player arrives once they move on again",
    card="The crossing is not written yet. Move on again to arrive.",
)
COMPLICATION_UNWRITTEN = Fact(
    told=True,
    trace="the complication could not be written",
    card="Nothing new came down on this place after all. You are still where you were.",
)
NEW_LOCATION = "no new `location`: a complication happens where the player is; leave it empty"
GEAR_TOOK_THE_HIT = (
    "the gear took the hit: do not apply `risk`; the engine removes the brief hindrance at the "
    "next scene"
)
TWO_JOBS = (
    "offer two jobs with `direct`; the player picks in their words; `job` `take` records the pick"
)
ODD_JOB = (
    "offer one job with `direct`, and let something about it seem off; write what seems off in "
    "`terms` when the player takes it"
)
NO_JOB = (
    "no work, unless the crew takes a job that leaves them owing somebody: offer that with "
    "`direct`; write the debt in `terms` when the player takes it"
)
JOB_PAID = (
    "the job is over, done or failed: the credits each operator earned above are their cut for "
    "the work done. Tell them as that pay; never say that no pay came"
)
FLOWN = (
    "a new `place_id`: the crew flew away from {place_id}. Land them at the place that WHAT "
    "COMES NEXT names"
)
RAISE_PROMPT = "The job is done. Which skill do you raise? Pick one, or name a new one."
NEWCOMER_PROMPT = "{name} is dead. Who joins the crew? Describe them in your own words."
RAISE_OWED = "A raise is owed: when the player names a skill, call `raise_skill` with it."
CANNOT_SUCCEED = "Cannot succeed without help."


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
    why: Told = Field(min_length=1, description="What the credits pay for, in a few words.")
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    to_id: Slug | None = Field(
        default=None,
        description="Exact id of whoever gets the credits: a crew member keeps them, anyone "
        "else, such as a hire paid up front, takes them. Null when they pay for a thing.",
    )


class TakeLead(Frozen):
    actor_id: Slug


class ShipUpgrade(Frozen):
    function_id: Slug = Field(description="Exact id of a ship function. The player pays ₡10.")
    upgrade: ShortName = Field(default="", description=f"What the upgrade is. {BE_SHORT}")


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
    hindered: Told = Field(
        default="", description="Why the helper is hindered. Empty when nothing hinders them."
    )
    skill: str = Field(
        default="",
        description="The skill the helper rolls; a d6 when their sheet lacks it. Empty rolls their "
        "best skill die.",
    )


class Roll(Staked, Attempt):
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    skill: str = Field(default="", description="The skill to roll. Empty rolls the plain d6.")
    helped: Told = Field(
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
    hindered: Told = Field(
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
    skill: Told = Field(
        min_length=1,
        description="The skill that the job used for this member. A skill that is not on "
        "their sheet is added at d8.",
    )


class RaiseSkill(Frozen):
    skill: Told = Field(
        min_length=1,
        description="The skill the player named for their raise after a job; a new one starts "
        "at d8.",
    )


class BringIn(Frozen):
    who: Told = Field(min_length=1, description="The new operator in the player's words.")


class Job(Frozen):
    verb: Literal["find", "take", "finish"] = Field(
        description="`find` looks for work. `take` records agreed work, or new terms for the "
        "open job. `finish` closes the job."
    )
    where: Told = Field(
        default="",
        description="Where the player looks for work, in a few words. Required with `find`.",
    )
    terms: Told = Field(
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
        # The fields of another verb are ignored, so a stray one costs no retry.
        needed = {"find": ("where", self.where), "take": ("terms", self.terms)}.get(self.verb)
        if needed is not None and not needed[1]:
            raise ValueError(f"{self.verb} needs {needed[0]}")
        return self
