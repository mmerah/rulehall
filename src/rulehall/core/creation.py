from collections.abc import Callable, Mapping, Sequence

from rulehall.core.decisions import Option
from rulehall.core.validation import Frozen, Refusal, Slug

type Picks = Mapping[Slug, str]
type StepBuilder = Callable[[Picks], Sequence[CreationStep]]
ANSWER_MAX = 100


class CreationStep(Frozen):
    id: Slug
    name: str
    options: tuple[Option, ...] = ()
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
            raise Refusal(f"{step.name} is unanswered")
        if len(answer) > ANSWER_MAX:
            raise Refusal(f"{step.name} takes at most {ANSWER_MAX} characters")
        if not step.offers(answer):
            raise Refusal(f"{step.name} offers no {answer!r}")


def drop_stale(build_steps: StepBuilder, picks: dict[Slug, str]) -> None:
    while stale := _stale_keys(build_steps(picks), picks):
        for key in stale:
            del picks[key]


def numbered_picks(picks: Picks, prefix: str) -> tuple[str, ...]:
    numbered = (f"{prefix}-{number}" for number in range(1, len(picks) + 1))
    return tuple(picks[key] for key in numbered if key in picks)


def _stale_keys(steps: Sequence[CreationStep], picks: Picks) -> list[Slug]:
    by_id = {step.id: step for step in steps}
    return [
        key
        for key, answer in picks.items()
        if (step := by_id.get(key)) is None or not step.offers(answer)
    ]
