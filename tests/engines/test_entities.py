import pytest
from pydantic import ValidationError
from support.game import initialized

from rulehall.engines.entities import (
    Gauge,
    Thing,
    named_by_word,
    named_unmet,
)
from rulehall.engines.loner4e.sheet import Loner4eEntity
from rulehall.engines.loner4e.world import Loner4eGame

KAEL = Loner4eEntity(id="kael", name="Kael", brief="", known=True)


def _state() -> Loner4eGame:
    """A counter card drops the name for the played character alone, so it needs the state."""
    _, state = initialized()
    return state


def test_counter_rejects_current_outside_its_bounds() -> None:
    with pytest.raises(ValidationError, match="below zero"):
        Gauge(current=-1, maximum=10)
    with pytest.raises(ValidationError, match="above maximum"):
        Gauge(current=11, maximum=10)


def test_adjust_clamps_to_the_counters_bounds_and_reports_only_a_real_move() -> None:
    state = _state()
    KAEL.luck.current = 0
    (changed,) = KAEL.change(KAEL.luck, 99, "Luck", "the strain")
    assert (changed.card, KAEL.luck.current) == ("Kael: Luck +6 → 6/6", 6)
    assert KAEL.change(KAEL.luck, 99, "Luck", "the strain") == []
    assert KAEL.luck.adjust(-2) == -2

    player = state.world.player
    player.luck.current = 0
    (own,) = player.change(player.luck, 1, "Luck", "the strain")
    assert own.card == "Luck +1 → 1/6"


def test_a_dead_persons_subject_and_headline_show_it_but_a_living_ones_do_not() -> None:
    living = Loner4eEntity(id="kael", name="Kael", brief="", known=True)
    dead = Loner4eEntity(id="mara", name="Mara", brief="", known=True, alive=False)

    assert living.subject().alive is True
    assert not living.headline.endswith(" (dead)")

    assert dead.subject().alive is False
    assert dead.headline.endswith(" (dead)")


def test_named_unmet_finds_whole_words_and_phrases_case_folded() -> None:
    text = "The Bell Tower looms over the square; a bell rings, and old-tom watches."
    entities = [
        Thing(id="bell-tower", name="Bell Tower", brief=""),
        Thing(id="the-bell", name="Bell", brief=""),
        Thing(id="town-square", name="town square", brief=""),
        Thing(id="old-tom", name="Tom", brief=""),
    ]
    assert named_unmet(text, entities) == ["Bell Tower", "Bell", "Tom"]


def test_a_name_word_names_its_person_unless_shared_short_or_of_a_description() -> None:
    orlov = Loner4eEntity(id="collector-orlov", name="Collector Orlov", brief="")
    listener = Loner4eEntity(id="tithe-listener", name="Tithe Listener", brief="")
    hand = Loner4eEntity(id="second-hand", name="The Second Hand", brief="")
    vek = Loner4eEntity(id="dara-vek", name="Dara Vek", brief="")
    met = [Loner4eEntity(id="tithe-runner", name="Tithe Runner", brief="", known=True)]
    unmet = [orlov, listener, hand, vek]

    def named(text: str) -> list[str]:
        return named_by_word(text, unmet, met)

    assert named("An officer of Orlov's rank is not here.") == ["Collector Orlov"]
    assert named("The Tithe office sends its Second courier; the vek is cold.") == []
    assert named("A collector waits; Listener is a word he likes.") == ["Tithe Listener"]
