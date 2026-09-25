from collections.abc import Sequence
from typing import Literal

from rulehall.core.play import DecisionOption
from rulehall.core.validation import Frozen, Slug
from rulehall.core.views import Rows

LUCK_MAX = 6
DIE_FACE = 6  # one d6, and an SRD table column holds six rows
TIES_PER_TWIST = 3
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

type TagKind = Literal["skill", "frailty", "gear", "condition"]


class RollOutcome(Frozen):
    id: Slug
    harm: int

    @property
    def wording(self) -> str:
        """Story words only: the narrator never reads a rule id."""
        return OUTCOME_WORDING[self.id]


def outcome_for(chance: int, risk: int) -> RollOutcome:
    if chance == risk:
        return RollOutcome(id="yes-but", harm=1)
    side, sign = ("yes", 1) if chance > risk else ("no", -1)
    if min(chance, risk) >= AND_AT:
        return RollOutcome(id=f"{side}-and", harm=3 * sign)
    if max(chance, risk) <= BUT_AT:
        return RollOutcome(id=f"{side}-but", harm=sign)
    return RollOutcome(id=side, harm=2 * sign)


def twist_pairing(subject: int, action: int, twists: Rows) -> tuple[str, str]:
    return twists[subject - 1][0], twists[action - 1][1]


def pack_meanings(entries: Sequence[DecisionOption], tags: Sequence[str]) -> Rows:
    brief_of = {entry.name: entry.brief for entry in entries if entry.brief}
    return tuple((tag, brief_of[tag]) for tag in tags if tag in brief_of)
