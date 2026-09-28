from collections.abc import Mapping, Sequence

from rulehall.core.decisions import DecisionOption
from rulehall.core.validation import Frozen, Refusal, Slug

type Picks = Mapping[Slug, str]
ANSWER_MAX = 100


class CreationStep(Frozen):
    id: Slug
    name: str
    options: tuple[DecisionOption, ...] = ()
    hint: str = ""
    help: str = ""
    allows_text: bool = False
    optional: bool = False

    @property
    def constrains(self) -> bool:
        return bool(self.options) and not self.allows_text

    def offers(self, answer: str) -> bool:
        return not self.constrains or any(option.id == answer for option in self.options)


def check_picks(steps: Sequence[CreationStep], picks: Picks) -> None:
    known = {step.id for step in steps}
    if unknown := sorted(set(picks) - known):
        raise Refusal(f"no creation step is called {unknown}")
    for step in steps:
        answer = picks.get(step.id, "")
        if not answer.strip():
            if step.optional:
                continue
            raise Refusal(f"{step.id!r} is unanswered")
        if len(answer) > ANSWER_MAX:
            raise Refusal(f"{step.id!r} takes at most {ANSWER_MAX} characters")
        if not step.offers(answer):
            raise Refusal(f"{step.id!r} offers no {answer!r}")


def drop_stale(steps: Sequence[CreationStep], picks: dict[Slug, str]) -> None:
    for step in steps:
        if not step.offers(picks.get(step.id, "")):
            picks.pop(step.id, None)


def other_than(options: Sequence[DecisionOption], taken: str) -> tuple[DecisionOption, ...]:
    return tuple(option for option in options if taken not in (option.id, option.name))


def find_option[T: DecisionOption](options: Sequence[T], chosen: str) -> T | None:
    return next((option for option in options if option.id == chosen), None)
