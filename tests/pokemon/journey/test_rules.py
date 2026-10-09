from random import Random

import pytest
from support.journey import ENGINE, started
from support.table import change, refused

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.dex import SIGNATURE_EXCLUDED, Stats, dex
from rulehall.engines.pokemon.journey.rules import (
    RIVAL_IV,
    STARTER_LEVEL,
    built_ev,
    built_iv,
    counter_pick,
    help_bonus,
    rival_ev,
    signature_moves,
)
from rulehall.engines.pokemon.journey.sheet import Mon
from rulehall.engines.pokemon.journey.world import RivalTeam, WildSlot
from rulehall.engines.pokemon.rules import stats, succeeds

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


@pytest.mark.parametrize(
    ("friendship", "bonus"), [(0, 2), (119, 2), (120, 3), (199, 3), (200, 4), (255, 4)]
)
def test_the_help_bonus_rises_with_friendship(friendship: int, bonus: int) -> None:
    assert help_bonus(friendship) == bonus


def test_a_helper_grows_closer_up_to_the_max_and_the_check_shows_its_bonus() -> None:
    draft = started().draft()
    charmander = draft.world.player_sheet.require_mon("charmander")
    charmander.friendship = 254

    facts = change(
        ENGINE,
        draft,
        "check",
        what="Climb",
        skill="athletics",
        difficulty="hard",
        helper_mon_id="charmander",
        reason="Charmander lights the way",
    )

    assert charmander.friendship == 255
    assert "helped by Charmander +4" in facts[-1].trace


def test_a_new_pokemon_knows_its_last_four_level_up_moves() -> None:
    mon = Mon.new("bulbasaur", 9, Random(0), ())

    assert [slot.move_id for slot in mon.moves] == ["tackle", "vinewhip", "growth", "leechseed"]
    assert all(slot.pp == slot.move.pp for slot in mon.moves)


def test_signature_moves_lead_with_a_same_type_move_then_coverage_and_skip_the_excluded() -> None:
    charizard = dex().species["charizard"]

    picked = signature_moves(charizard, 36)

    first, second = (dex().moves[move_id] for move_id in picked[:2])
    assert first.type in charizard.types and first.power > 0
    assert second.type not in charizard.types and second.power > 0
    assert not SIGNATURE_EXCLUDED.intersection(picked)


def test_signature_moves_take_only_tm_moves_up_to_three_times_the_level_in_power() -> None:
    tentacool = dex().species["tentacool"]
    levelup = {move_id for _, move_id in tentacool.levelup}

    picked = signature_moves(tentacool, 14)

    machines = [dex().moves[move_id] for move_id in picked if move_id not in levelup]
    assert all(move.power <= 42 for move in machines)


def test_a_species_with_only_excluded_moves_is_built_with_its_latest_level_up_move() -> None:
    unown = Mon.built("unown", 20, "unown", ace=True, badges=0, iv=15, ev=0)

    assert [slot.move_id for slot in unown.moves] == ["hiddenpower"]


def test_a_built_pokemon_grows_its_spread_and_gets_items_with_badges() -> None:
    fresh = Mon.built("machop", 12, "machop", ace=True, badges=0, iv=built_iv(0), ev=built_ev(0))
    first_badge = Mon.built(
        "machop", 14, "machop", ace=False, badges=1, iv=built_iv(1), ev=built_ev(1)
    )
    seasoned = Mon.built("machop", 30, "machop", ace=True, badges=3, iv=built_iv(3), ev=built_ev(3))
    champion = Mon.built("machop", 54, "machop", ace=True, badges=8, iv=built_iv(8), ev=built_ev(8))

    assert (fresh.ivs, fresh.evs, fresh.item_id) == ((15,) * 6, (0,) * 6, None)
    assert (seasoned.ivs, seasoned.evs) == ((21,) * 6, (0, 96, 0, 0, 0, 96))
    assert first_badge.item_id is None
    assert seasoned.item_id is not None
    assert (champion.ivs, champion.evs) == ((31,) * 6, (0, 252, 0, 0, 0, 252))


def test_a_wild_table_refuses_a_legendary() -> None:
    with pytest.raises(ValueError, match="legendary_id"):
        _ = WildSlot(species_id="mewtwo", lowest=50, highest=50, weight=1)


def test_the_rival_counter_picks_squirtle_against_charmander() -> None:
    charmander = dex().species["charmander"]

    assert counter_pick(("bulbasaur", "squirtle"), charmander.types, STARTER_LEVEL) == "squirtle"
    assert started().world.rival_team.starter_id == "squirtle"


def test_creation_refuses_a_third_rank_in_one_skill() -> None:
    picks = TWO_NATURE_RANKS | {"rank-3": "nature"}

    with pytest.raises(Refusal, match="'rank-3' offers no 'nature'"):
        _ = ENGINE.create_character("Kael", "A trainer.", "masculine", "srd", picks)


def test_a_revive_needs_a_fainted_pokemon() -> None:
    draft = started().draft()
    sheet = draft.world.player_sheet
    sheet.add("revive", 1)

    assert refused(ENGINE, draft, "use_item", item_id="revive", mon_id="charmander") == (
        "Charmander has not fainted"
    )
    sheet.require_mon("charmander").hp.current = 0
    _ = change(ENGINE, draft, "use_item", item_id="revive", mon_id="charmander")
    assert sheet.require_mon("charmander").hp.current == 10
    assert "revive" not in sheet.bag


def _species_ids(*, water: bool) -> list[str]:
    line = {"squirtle", "wartortle", "blastoise"}
    return [
        sid
        for sid, sp in dex().species.items()
        if sid not in line and not sp.evolution_species_ids and (("Water" in sp.types) == water)
    ]


def test_the_rival_picks_extras_that_share_no_type_with_the_ace_or_each_other() -> None:
    species = dex().species
    pool = [*_species_ids(water=True)[:6], *_species_ids(water=False)[:12]]
    rival_team = RivalTeam(starter_id="squirtle")

    roster = rival_team.roster(3, 30, pool, tuple(species))

    types = [t for slot in roster for t in species[slot.species_id].types]
    assert len(roster) == 4
    assert roster[-1].species_id == "wartortle"
    assert len(types) == len(set(types))


def test_the_rival_fills_remaining_slots_when_the_pool_lacks_distinct_types() -> None:
    species = dex().species
    water = _species_ids(water=True)[:5]
    rival_team = RivalTeam(starter_id="squirtle")

    roster = rival_team.roster(3, 30, water, tuple(species))

    assert len(roster) == 4
    assert all(roster_slot.species_id in water for roster_slot in roster[:-1])


def test_rival_mons_carry_flat_ivs_and_half_the_built_evs() -> None:
    mon = Mon.built("machop", 30, "machop", ace=True, badges=8, iv=RIVAL_IV, ev=rival_ev(8))

    assert (mon.ivs, mon.evs) == ((15,) * 6, (0, 126, 0, 0, 0, 126))


def test_the_rival_never_fields_the_ace_line_and_ranks_by_evolved_strength() -> None:
    species = dex().species
    rival_team = RivalTeam(starter_id="squirtle")

    roster = rival_team.roster(1, 50, ["squirtle", "caterpie"], tuple(species))

    assert [slot.species_id for slot in roster] == ["butterfree", "blastoise"]
