from collections.abc import Mapping, Sequence

from rulehall.core.play import DecisionOption
from rulehall.core.validation import Frozen, Refusal, Slug

type Picks = Mapping[Slug, str]
ANSWER_MAX = 100


class CreationStep(Frozen):
    """No options means the player writes the answer."""

    id: Slug
    name: str
    options: tuple[DecisionOption, ...] = ()
    hint: str = ""
    allows_text: bool = False

    @property
    def constrains(self) -> bool:
        return bool(self.options) and not self.allows_text

    def offers(self, answer: str) -> bool:
        return not self.constrains or any(option.id == answer for option in self.options)


def picked(picks: Picks, step_id: Slug) -> str:
    return picks.get(step_id, "")


def check_picks(steps: Sequence[CreationStep], picks: Picks) -> None:
    """One legality rule for the page and for `create`, so neither can drift."""
    known = {step.id for step in steps}
    if unknown := sorted(set(picks) - known):
        raise Refusal(f"no creation step is called {unknown}")
    for step in steps:
        answer = picked(picks, step.id)
        if not answer.strip():
            raise Refusal(f"{step.id!r} is unanswered")
        if len(answer) > ANSWER_MAX:
            raise Refusal(f"{step.id!r} takes at most {ANSWER_MAX} characters")
        if not step.offers(answer):
            raise Refusal(f"{step.id!r} offers no {answer!r}")


def drop_stale(steps: Sequence[CreationStep], picks: dict[Slug, str]) -> None:
    """A new pack, or a skill moved onto its twin, can leave an answer its step no longer offers."""
    for step in steps:
        if not step.offers(picked(picks, step.id)):
            picks.pop(step.id, None)


def other_than(options: Sequence[DecisionOption], taken: str) -> tuple[DecisionOption, ...]:
    return tuple(option for option in options if option.id != taken)


def option_of[T: DecisionOption](options: Sequence[T], chosen: str) -> T | None:
    return next((option for option in options if option.id == chosen), None)


def chosen_option[T: DecisionOption](options: Sequence[T], chosen: str) -> T:
    found = option_of(options, chosen)
    if found is None:
        raise Refusal(f"no option {chosen!r}")
    return found
