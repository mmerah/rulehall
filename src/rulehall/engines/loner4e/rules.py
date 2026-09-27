# Loner 4e: Core Rules © 2026 Roberto Bisceglie. Licensed under CC BY-SA 4.0.
# https://lonersrd.zotiquestgames.com/core/loner-4e.html — http://creativecommons.org/licenses/by-sa/4.0/

import re
from typing import Literal

from rulehall.core.validation import Frozen, Slug

SCENE_ID = "scene"
# Cited in `hinders` for expertise the protagonist lacks; it is on no sheet.
UNTRAINED = "Untrained"
MEANWHILE_QUESTION = "Does an ally or wildcard act independently?"
LUCK_MAX = 6
GROUP_LUCK = 8
DIE_FACE = 6
DOUBLES_PER_TWIST = 3
STATUS_BOXES = 3
AND_AT = 4
BUT_AT = 3
OUTCOME_WORDING: dict[str, str] = {
    "yes-and": "yes, and better than hoped",
    "yes": "yes",
    "yes-but": "yes, but at a cost",
    "no-but": "no, but not badly",
    "no": "no",
    "no-and": "no, and worse",
}
OUTCOME_READING: dict[str, str] = {
    "yes-and": "You get what you want + an extra advantage",
    "yes": "You succeed in your action",
    "yes-but": "You succeed, but at a cost",
    "no-but": "You fail, but you gain a small compensation",
    "no": "You fail",
    "no-and": "You fail + something makes it worse",
}
TWIST_SUBJECTS: tuple[str, ...] = (
    "A third party",
    "The Protagonist",
    "An encounter",
    "A physical event",
    "An emotional event",
    "An object",
)
ALTERS_THE_LOCATION = "Alters the location"
CHANGES_THE_GOAL = "Changes the goal"
ENDS_THE_SCENE = "Ends the scene"
TWIST_ACTIONS: tuple[str, ...] = (
    "Appears",
    ALTERS_THE_LOCATION,
    "Helps the Protagonist",
    "Hinders the Protagonist",
    CHANGES_THE_GOAL,
    ENDS_THE_SCENE,
)

type TagKind = Literal["skill", "frailty", "gear", "condition", "relationship"]
type Position = Literal["advantage", "neutral", "disadvantage"]
type SceneKind = Literal["dramatic", "quiet"]
type Transition = Literal["dramatic", "quiet", "meanwhile"]
type CloseReason = Literal["resolved", "blocked", "abandoned", "turning_point"]
type ClosedBy = CloseReason | Literal["twist", "moved_on"]
type StatusColumn = Literal["physical", "social", "psychological"]
STATUS_TAGS: dict[StatusColumn, tuple[str, str, str]] = {
    "physical": ("Hurt", "Injured", "Overcome"),
    "social": ("Rattled", "On the Back Foot", "Humiliated"),
    "psychological": ("Unsettled", "Shaken", "Broken"),
}


class RollOutcome(Frozen):
    id: Slug
    harm: int
    doubles: bool = False

    @property
    def wording(self) -> str:
        """Story words only: the narrator never reads a rule id."""
        return OUTCOME_WORDING[self.id]

    @property
    def reading(self) -> str:
        return OUTCOME_READING[self.id]


def outcome_for(chance: int, risk: int) -> RollOutcome:
    if chance == risk:
        return RollOutcome(id="yes-but", harm=1, doubles=True)
    side, sign = ("yes", 1) if chance > risk else ("no", -1)
    if min(chance, risk) >= AND_AT:
        return RollOutcome(id=f"{side}-and", harm=3 * sign)
    if max(chance, risk) <= BUT_AT:
        return RollOutcome(id=f"{side}-but", harm=sign)
    return RollOutcome(id=side, harm=2 * sign)


def position_for(helps: int, hinders: int) -> Position:
    if helps > hinders:
        return "advantage"
    return "disadvantage" if hinders > helps else "neutral"


def faces_for(position: Position) -> tuple[tuple[int, ...], tuple[int, ...]]:
    chance = (DIE_FACE, DIE_FACE) if position == "advantage" else (DIE_FACE,)
    risk = (DIE_FACE, DIE_FACE) if position == "disadvantage" else (DIE_FACE,)
    return chance, risk


def transition_for(face: int) -> Transition:
    if face <= 3:
        return "dramatic"
    return "quiet" if face <= 5 else "meanwhile"


def and_for_commas(tag: object) -> object:
    """Tags are listed with commas, so a comma inside one reads as "and"."""
    return re.sub(r"\s*,\s*", " and ", tag) if isinstance(tag, str) else tag
