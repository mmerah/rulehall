from random import Random

import pytest
from support.table import change, game, narrowed

from rulehall.core.validation import EngineId
from rulehall.engines.pokemon.battle.models import BattleResult
from rulehall.engines.pokemon.champions.engine import ChampionsEngine
from rulehall.engines.pokemon.champions.world import ChampionsWorld

ROUNDS_MAX = 6


@pytest.fixture(autouse=True)
def _seeded_season(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ChampionsEngine, "season_seeds", Random(0))


def test_a_locals_runs_to_a_placing_and_its_cp() -> None:
    engine, state = game(EngineId("pokemon-champions"))
    draft = state.draft()
    _ = change(engine, draft, "register_team")
    world = narrowed(draft.world, ChampionsWorld)
    for _ in range(ROUNDS_MAX):
        _ = world.start_match(Random(0))
        assert world.battle is not None
        team = world.battle.setup.team
        _ = world.settle_battle(
            BattleResult(outcome="won", team=team, sent_out_foes=(), on_field_mon_ids=())
        )
        if world.player_sheet.finishes:
            break
    (finish,) = world.player_sheet.finishes
    assert (finish.placing, finish.cp, finish.record) == (1, 50, "3-0")
    assert world.player_sheet.registered is None
    assert world.player_sheet.cp() == 50
