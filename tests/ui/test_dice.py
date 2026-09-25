from rulehall.core.facts import DiceEvent, Fact
from rulehall.ui.transcript import rolled_since

TWO_D6 = DiceEvent(label="2d6", faces=(6, 6), rolled=(2, 5))
DIE_KEYS = ("game-die-body", "game-die-ink", "game-die-glow")


def _fact(*, told: bool) -> Fact:
    return Fact(trace=TWO_D6.label, told=told, card=TWO_D6.label, dice=(TWO_D6,))


def test_only_told_dice_after_the_seen_facts_count_as_landed() -> None:
    facts = (_fact(told=True), _fact(told=False), _fact(told=True))

    assert rolled_since(facts, 1)
    assert rolled_since(facts, 0)
    assert not rolled_since(facts, 3)
    assert not rolled_since(facts[:2], 1)
