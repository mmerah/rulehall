from typing import Literal

type SkillDie = Literal[8, 10, 12]
LADDER: tuple[SkillDie, ...] = (8, 10, 12)
DEFAULT_DIE = 6
SKILL_COUNT = 17
HINDERED_DIE = 4
HELP_DIE = 6
BRIEF = "Brief: "
CLOSE_CALL = "Close call"
MINOR_HURT = "Minor hurt"
NO_WORK = "nothing"
ODD_WORK = "a job, but something seems off"
TWO_JOBS_FOUND = "a choice between two jobs"


def outcome_band(face: int, low: str, mid: str, high: str) -> str:
    return low if face <= 2 else mid if face <= 4 else high


def roll_band(face: int) -> str:
    return outcome_band(face, "disaster", "setback", "success")


def risk_text(risk: str, *, harm: bool, deadly: bool) -> str:
    return f"{risk} (deadly)" if deadly else f"{risk} (harm)" if harm else risk


def brief_hindrance(hindrance: str) -> str:
    return f"{BRIEF}{hindrance}"


def lesser_hurt(*, deadly: bool) -> str:
    return CLOSE_CALL if deadly else MINOR_HURT


def next_die(current: SkillDie | None) -> SkillDie | None:
    if current is None:
        return LADDER[0]
    if current == LADDER[-1]:
        return None
    return LADDER[LADDER.index(current) + 1]
