from functools import partial

import pytest
from support.table import ENGINES_BUILT, TWENTYFOURXX

from rulehall.core.creation import CreationStep, check_picks, drop_stale
from rulehall.core.decisions import Option
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
    options=(Option(id="one", name="One"), Option(id="two", name="Two")),
)


def test_a_step_takes_exactly_one_offered_answer() -> None:
    check_picks((STEP,), {"supplements": "one"})
    with pytest.raises(Refusal, match="Table sets beyond the SRD is unanswered"):
        check_picks((STEP,), {"supplements": ""})
    with pytest.raises(Refusal, match="Table sets beyond the SRD offers no 'three'"):
        check_picks((STEP,), {"supplements": "three"})


def test_an_optional_step_accepts_a_blank_answer() -> None:
    check_picks((CreationStep(id="goal", name="What do you want?", optional=True),), {"goal": ""})


def test_a_constrained_step_still_loses_an_answer_it_no_longer_offers() -> None:
    engine = ENGINES_BUILT[TWENTYFOURXX]
    picks = dict(ANDROID) | {"body": "not-on-offer"}

    drop_stale(partial(engine.creation_steps, "srd"), picks)

    assert "body" not in picks


def test_a_pick_whose_step_is_gone_drops() -> None:
    engine = ENGINES_BUILT[TWENTYFOURXX]
    picks = dict(ANDROID) | {"specialty": "face", "increase-1": "climbing"}

    drop_stale(partial(engine.creation_steps, "srd"), picks)

    assert picks.keys() == {"specialty", "origin", "body", "increase-1"}
    check_picks(engine.creation_steps("srd", picks), picks)
