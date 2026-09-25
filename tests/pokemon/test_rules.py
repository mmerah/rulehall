from random import Random

import pytest
from support.pokemon import ENGINE, started
from support.table import change, refused

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.dex import Stats, dex
from rulehall.engines.pokemon.rules import stats, succeeds
from rulehall.engines.pokemon.world import Mon

TWO_NATURE_RANKS = {
    "rank-1": "nature",
    "rank-2": "nature",
    "rank-4": "athletics",
    "starter": "charmander",
}


@pytest.mark.parametrize(
    ("species_id", "level", "nature", "ivs", "evs", "shown"),
    [
        ("pidgey", 5, "Quirky", (31,) * 6, (0,) * 6, (20, 11, 10, 10, 10, 12)),
        (
            "pikachu",
            50,
            "Adamant",
            (0, 31, 15, 7, 20, 31),
            (252, 4, 0, 0, 0, 252),
            (126, 83, 52, 52, 65, 142),
        ),
        (
            "charizard",
            36,
            "Modest",
            (12, 3, 30, 31, 0, 17),
            (85,) * 6,
            (114, 66, 79, 112, 73, 90),
        ),
        (
            "snorlax",
            64,
            "Relaxed",
            (31, 0, 31, 0, 31, 0),
            (252, 0, 252, 0, 4, 0),
            (338, 145, 162, 88, 166, 38),
        ),
    ],
)
def test_stats_match_showdown(
    species_id: str, level: int, nature: str, ivs: Stats, evs: Stats, shown: Stats
) -> None:
    assert stats(dex().species[species_id], level, nature, ivs, evs) == shown


def test_a_check_succeeds_on_the_total_and_on_a_natural_twenty() -> None:
    assert succeeds(20, 20, 30)
    assert not succeeds(1, 30, 10)
    assert succeeds(8, 10, 10)
    assert not succeeds(8, 9, 10)


def test_a_new_pokemon_knows_its_last_four_level_up_moves() -> None:
    mon = Mon.new("bulbasaur", 9, Random(0), ())

    assert [slot.move_id for slot in mon.moves] == ["tackle", "vinewhip", "growth", "leechseed"]
    assert all(slot.pp == slot.move.pp for slot in mon.moves)


def test_creation_refuses_a_third_rank_in_one_skill() -> None:
    picks = TWO_NATURE_RANKS | {"rank-3": "nature"}

    with pytest.raises(Refusal, match="'rank-3' offers no 'nature'"):
        _ = ENGINE.create_character("Kael", "A trainer.", "srd", picks)


def test_a_revive_needs_a_fainted_pokemon() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    sheet.add("revive", 1)

    assert refused(ENGINE, draft, "use_item", item_id="revive", mon_id="charmander") == (
        "Charmander has not fainted"
    )
    sheet.require_mon("charmander").hp.current = 0
    _ = change(ENGINE, draft, "use_item", item_id="revive", mon_id="charmander")
    assert sheet.require_mon("charmander").hp.current == 10
    assert "revive" not in sheet.bag
