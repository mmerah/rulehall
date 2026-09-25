import pytest
from support.table import ENGINES_BUILT, TWENTYFOURXX

from rulehall.core.creation import CreationStep, check_picks, drop_stale
from rulehall.core.play import DecisionOption
from rulehall.core.validation import Refusal, Slug

ANDROID: dict[Slug, str] = {
    "specialty": "muscle",
    "specialty-choice": "hand-to-hand",
    "weapon": "sword",
    "origin": "android",
    "body": "case",
}
STEP = CreationStep(
    id="supplements",
    name="Table sets beyond the SRD",
    options=(DecisionOption(id="one", name="One"), DecisionOption(id="two", name="Two")),
)


def test_a_step_takes_exactly_one_offered_answer() -> None:
    check_picks((STEP,), {"supplements": "one"})
    with pytest.raises(Refusal, match="'supplements' is unanswered"):
        check_picks((STEP,), {"supplements": ""})
    with pytest.raises(Refusal, match="'supplements' offers no 'three'"):
        check_picks((STEP,), {"supplements": "three"})


def test_a_constrained_step_still_loses_an_answer_it_no_longer_offers() -> None:
    engine = ENGINES_BUILT[TWENTYFOURXX]
    picks = dict(ANDROID) | {"body": "not-on-offer"}

    drop_stale(engine.creation_steps("srd", picks), picks)

    assert "body" not in picks
