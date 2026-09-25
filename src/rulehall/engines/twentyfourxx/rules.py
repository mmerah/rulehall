from typing import Literal

type SkillDie = Literal[8, 10, 12]
LADDER: tuple[SkillDie, ...] = (8, 10, 12)
DEFAULT_DIE = 6
HINDERED_DIE = 4
HELP_DIE = 6


def outcome_band(face: int, low: str, mid: str, high: str) -> str:
    return low if face <= 2 else mid if face <= 4 else high


def raised(current: SkillDie | None) -> SkillDie | None:
    if current is None:
        return LADDER[0]
    if current == LADDER[-1]:
        return None
    return LADDER[LADDER.index(current) + 1]
