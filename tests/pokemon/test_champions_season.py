import pytest

from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.season import (
    STRENGTH,
    TIERS,
    Entrant,
    Event,
    Finish,
    swiss_pairings,
    total_cp,
    unlocked_tiers,
)
from rulehall.engines.sheet import PLAYER_ID


def _entrants(count: int) -> list[Entrant]:
    sets = champions_data().archetypes[0].team.sets
    return [
        Entrant(
            entrant_id=PLAYER_ID if at == 0 else f"npc-{at}",
            name=f"Player {at}",
            avatar_id="trainer",
            style="calm",
            sets=sets,
            strength=STRENGTH["archetype"],
        )
        for at in range(count)
    ]


def _finish(tier: str, cp: int) -> Finish:
    return Finish.model_validate(
        {"event_name": "E", "tier": tier, "placing": 1, "record": "3-0", "cp": cp}
    )


def _locals(seed: int, *, always_win: bool = True) -> Event:
    event = Event(name="Locals", tier="locals", venue_id="hall", battle_background="gen6-city")
    event.register(_entrants(8), seed)
    while event.stage != "done":
        event.record_player(won=always_win)
    return event


def test_round_two_pairs_within_records_without_rematch() -> None:
    event = Event(name="Locals", tier="locals", venue_id="hall", battle_background="gen6-city")
    event.register(_entrants(8), 1)
    event.record_player(won=True)
    by_id = {each.entrant_id: each for each in event.entrants}
    assert len(event.pairings) == 4
    for first, second in event.pairings:
        assert by_id[first].wins == by_id[second].wins
        assert second not in by_id[first].opponent_ids


def test_standings_rank_wins_then_opponent_win_rate() -> None:
    entrants = _entrants(4)
    entrants[0].wins, entrants[0].opponent_ids = 2, ["npc-3"]
    entrants[1].wins, entrants[1].opponent_ids = 2, ["npc-2"]
    entrants[2].wins, entrants[2].losses = 1, 1
    entrants[3].wins, entrants[3].losses = 0, 2
    event = Event(name="Locals", tier="locals", venue_id="hall", battle_background="gen6-city")
    event.entrants = entrants
    assert [each.entrant_id for each in event.standings()][:2] == ["npc-1", PLAYER_ID]
    assert swiss_pairings(entrants)[0] == ("npc-1", PLAYER_ID)


def test_winning_a_run_places_first_and_losing_in_the_cut_places_at_the_alive_count() -> None:
    won = _locals(3)
    assert (won.placing, won.winner_id) == (1, PLAYER_ID)
    assert len(won.bracket) == 1
    event = Event(name="Locals", tier="locals", venue_id="hall", battle_background="gen6-city")
    event.register(_entrants(8), 3)
    for _ in range(3):
        event.record_player(won=True)
    assert event.stage == "cut"
    assert len(event.bracket) == 4
    event.record_player(won=False)
    assert (event.stage, event.placing) == ("done", 4)
    assert event.winner_id is not None
    ranked = [each.entrant_id for each in event.standings()]
    assert ranked[0] == event.winner_id
    assert PLAYER_ID in ranked[2:4]


def test_missing_the_cut_places_at_the_standings_rank() -> None:
    event = Event(name="Locals", tier="locals", venue_id="hall", battle_background="gen6-city")
    event.register(_entrants(8), 5)
    for _ in range(3):
        event.record_player(won=False)
    assert event.stage == "done"
    assert event.placing is not None
    assert event.placing > TIERS["locals"].cut_size
    assert event.finish().cp == 0


def test_cp_table_by_placing() -> None:
    rule = TIERS["regionals"]
    assert [rule.placing_cp(placing) for placing in (1, 2, 3, 4, 5, 8, 9)] == [
        200,
        160,
        130,
        130,
        100,
        100,
        0,
    ]


def test_only_the_best_four_finishes_of_a_tier_count() -> None:
    finishes = [_finish("locals", cp) for cp in (50, 40, 25, 25, 25, 25)]
    assert total_cp(finishes) == 140


def test_unlocks_and_the_worlds_invite() -> None:
    assert unlocked_tiers([]) == ("locals",)
    assert unlocked_tiers([_finish("locals", 50)]) == ("locals", "regionals")
    rich = [_finish("regionals", 200), _finish("internationals", 500)]
    assert unlocked_tiers(rich) == ("locals", "regionals", "internationals", "worlds")
    assert "worlds" not in unlocked_tiers([*rich, _finish("worlds", 0)])
    assert "worlds" not in unlocked_tiers([_finish("regionals", 200)])


def test_a_locals_run_is_deterministic_for_a_seed() -> None:
    first, second = _locals(7, always_win=False), _locals(7, always_win=False)
    assert first.model_dump() == second.model_dump()


def test_register_rejects_a_wrong_field() -> None:
    event = Event(name="Locals", tier="locals", venue_id="hall", battle_background="gen6-city")
    with pytest.raises(ValueError, match="needs 8 entrants"):
        event.register(_entrants(6), 1)
