from typing import Literal, Self

from pydantic import Field, model_validator

from rulehall.core.tools import Told
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.args import BE_SHORT, Attempt, ShortName
from rulehall.engines.loner3e.rules import DIE_FACE, TagKind

TWIST_NOTE = (
    "A twist interrupts the scene: {subject} / {action}. The narration showed the twist "
    "arrive. Develop the twist this turn. Tell what the twist starts. Tell what the twist "
    "costs. Tell what the twist changes."
)
DEFEAT_NOTE = (
    "{name} is out of luck and lost this conflict. Roll no more dice for this conflict. "
    "Tell how the conflict ends for them: captured, badly injured, driven off, cornered, "
    "or conceding. Write a lasting mark with `change_tags`, as a `condition`. Then let the "
    "story move on. They are marked defeated and take no new luck exchange. Call "
    "`restore_luck` to put the defeat behind them."
)

type Position = Literal["advantage", "neutral", "disadvantage"]


class ChangeTags(Frozen):
    actor_id: Slug = Field(description="Exact id of the player, or of a character here.")
    kind: TagKind = Field(
        description="`gear` for a thing taken or lost. `condition` for a lasting mark such as "
        "`Poisoned`."
    )
    gained: tuple[ShortName, ...] = Field(
        default=(), description=f"Tags gained, in title case, such as `Rusty Key`. {BE_SHORT}"
    )
    lost: tuple[str, ...] = Field(default=(), description="Exact tags lost, removed, or used up.")

    @model_validator(mode="after")
    def _at_least_one(self) -> Self:
        if not self.gained and not self.lost:
            raise ValueError("give at least one gained tag or one lost tag")
        return self


class Drive(Frozen):
    actor_id: Slug = Field(description="Exact id of the player or a living character here.")
    goal: Told = Field(
        default="",
        description="What the character now wants, in one line. Empty keeps the current goal.",
    )
    motive: Told = Field(
        default="",
        description="Why the character wants it, in one line. Empty keeps the current motive.",
    )
    nemesis: Told = Field(
        default="",
        description="Who or what is against the character. Empty keeps the current nemesis.",
    )

    @model_validator(mode="after")
    def _at_least_one(self) -> Self:
        if not self.goal and not self.motive and not self.nemesis:
            raise ValueError("give a goal, a motive or a nemesis")
        return self


class RestoreLuck(Frozen):
    actor_id: Slug = Field(description="Exact id of the player or a character here.")


class SpendLuck(Frozen):
    actor_id: Slug = Field(description="Exact id of the player or a living character here.")
    amount: int = Field(ge=1, description="The luck to spend. SPECIAL RULES prints the cost.")
    why: Told = Field(
        min_length=1, description="What the luck buys, in one line. The player reads this text."
    )


class Roll(Attempt):
    actor_id: Slug = Field(description="Exact id of the character here who acts.")
    question: str = Field(
        min_length=1,
        description="A closed question. Yes means the actor gets what they want. Only you "
        "read this question.",
    )
    position: Position = Field(
        default="neutral",
        description="Which side the tags and the situation help.",
    )
    edge: Told = Field(
        default="",
        description="The tag or the condition that sets the position. The player reads this "
        "text. Empty for neutral.",
    )
    target_id: Slug | None = Field(
        default=None,
        description="Exact id of the character here who loses luck. Use this field for a "
        "contest of luck exchanges. Null for one decisive question, or for one key action, "
        "even against a character who resists.",
    )

    def faces(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        chance = (DIE_FACE, DIE_FACE) if self.position == "advantage" else (DIE_FACE,)
        risk = (DIE_FACE, DIE_FACE) if self.position == "disadvantage" else (DIE_FACE,)
        return chance, risk
