from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.tools import Told
from rulehall.core.validation import Frozen, Slug, check_unique
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.loner4e.rules import (
    SCENE_ID,
    UNTRAINED,
    CloseReason,
    StatusColumn,
    TagKind,
)
from rulehall.engines.loner4e.sheet import Tags
from rulehall.engines.loner4e.world import TagChange

PLAYER_OR_HERE = (
    f"`{PLAYER_ID}` for the protagonist, never their name, or the exact id of a living character "
    "here"
)


class CloseScene(Frozen):
    reason: CloseReason = Field(
        description="`resolved`: the goal is achieved or definitively failed. `blocked`: it "
        "cannot be pursued further here. `abandoned`: the protagonist commits to another course. "
        "`turning_point`: a quiet scene tips into urgency."
    )


class ChangeTags(TagChange):
    actor_id: Slug = Field(
        description=f"{PLAYER_OR_HERE}; a new id, such as `dock-guard`, brings in someone the "
        f"story just named; or `{SCENE_ID}`."
    )
    kind: TagKind | Literal["detail"] = Field(
        default_factory=lambda data: "detail" if data.get("actor_id") == SCENE_ID else "condition",
        description="`gear` for a thing taken or lost. `condition`, the default for a person, "
        "for a passing state such as `Poisoned`. `relationship` on an NPC for "
        "what the bond with the protagonist has become, such as `Uneasy Ally`. `detail`, the "
        "default for the scene, for a tag on the place, with `actor_id: scene` only.",
    )

    @model_validator(mode="after")
    def _a_change_the_actor_takes(self) -> Self:
        if (self.actor_id == SCENE_ID) != (self.kind == "detail"):
            raise ValueError("`detail` tags go with `actor_id: scene`, and only they do")
        if self.actor_id == PLAYER_ID and self.kind == "relationship":
            raise ValueError("a `relationship` tag goes on the NPC, never on the player")
        return self


class Drive(Frozen):
    actor_id: Slug = Field(description=f"{PLAYER_OR_HERE}, or `{SCENE_ID}` for the scene's goal.")
    goal: Told = Field(
        default="",
        description="What the character now wants, or what the protagonist is here for when "
        "`actor_id` is `scene`, in one line. Empty keeps the current goal.",
    )
    motive: Told = Field(
        default="",
        description="Why the character wants it, in one line. Empty keeps the current motive.",
    )
    nemesis: Told = Field(
        default="",
        description="Who or what is against the character. Empty keeps the current nemesis.",
    )
    concept: Told = Field(
        default="",
        description="The protagonist's concept rewritten by the growth, in one short phrase. "
        "Empty keeps it; the growth only.",
    )

    @model_validator(mode="after")
    def _a_drive_the_actor_takes(self) -> Self:
        if not (self.goal or self.motive or self.nemesis or self.concept):
            raise ValueError("give a goal, a motive, a nemesis or a concept")
        if self.actor_id == SCENE_ID and (
            self.motive or self.nemesis or self.concept or not self.goal
        ):
            raise ValueError("the scene takes a `goal` only")
        return self


class SpendLuck(Frozen):
    actor_id: Slug = Field(description=f"{PLAYER_OR_HERE}.")
    amount: int = Field(ge=1, description="The luck to spend. SPECIAL RULES prints the cost.")
    why: Told = Field(
        min_length=1, description="What the luck buys, in one line. The player reads this text."
    )


class Ask(Frozen):
    question: Told | None = Field(
        default=None,
        min_length=1,
        description="One closed question; yes is what the protagonist hopes. The player reads "
        "it. Leave it out when THE PLAYER ASKS is shown: the engine asks the player's question "
        "word for word.",
    )
    helps: Tags = Field(
        default=(),
        description="Exact tags here that bear on this moment and help.",
    )
    hinders: Tags = Field(
        default=(),
        description="Exact tags here that bear on this moment and hinder, and "
        f"`{UNTRAINED}` when the task needs expertise the protagonist lacks.",
    )
    against_id: Slug | None = Field(
        default=None,
        description="The id of the opponent in a Harm & Luck exchange; a new id, such as "
        "`dock-guard`, brings in an opponent the story just named. Null for one question or one "
        "key action. While a conflict is open, every ask is an exchange: null is against the "
        "opponent fought last.",
    )

    @model_validator(mode="after")
    def _each_tag_once_and_never_against_the_player(self) -> Self:
        check_unique("cited tags", [tag.casefold() for tag in (*self.helps, *self.hinders)])
        if UNTRAINED.casefold() in (tag.casefold() for tag in self.helps):
            raise ValueError(f"`{UNTRAINED}` hinders, never helps")
        if self.against_id in (PLAYER_ID, SCENE_ID):
            raise ValueError("`against_id` names an opponent, never the player or the scene")
        return self


class MarkStatus(Frozen):
    column: StatusColumn | None


class Fight(Frozen):
    opponent_id: Slug


class ConfirmEnd(Frozen):
    why: str = "the player chose to end it here"


class EndAdventure(Frozen):
    why: Told = Field(
        min_length=1,
        description="The sign that shows, in one line the player reads.",
    )
