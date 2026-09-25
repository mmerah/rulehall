from random import Random

from rulehall.core.facts import roll


def test_roll_traces_every_die() -> None:
    rolled = roll((6, 6), "a forced door", Random(0))

    assert len(rolled.event.rolled) == 2
    assert (
        rolled.fact.trace
        == f"a forced door: 2d6 [{rolled.event.rolled[0]}, {rolled.event.rolled[1]}]"
    )


def test_roll_highlights_the_kept_die_only_when_keeping_highest_in_a_pool() -> None:
    rolled = roll((6, 6, 6), "a forced door", Random(0), label="Pool", highlight_kept=True)

    assert rolled.kept == 4
    assert rolled.event.rolled == (4, 4, 1)
    assert rolled.event.highlight == (0,)

    single = roll((6,), "a forced door", Random(0), label="d6", highlight_kept=True)

    assert single.event.highlight == ()
