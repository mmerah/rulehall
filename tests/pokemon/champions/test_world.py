from random import Random

import pytest
from support.table import CHAMPIONS, change, game, narrowed, run_action

from rulehall.core.game import AnyGame
from rulehall.core.prompt import sections
from rulehall.core.validation import Refusal
from rulehall.engines.engine import AnyEngine
from rulehall.engines.pokemon.battle.models import BattleResult
from rulehall.engines.pokemon.champions.engine import ChampionsEngine
from rulehall.engines.pokemon.champions.rules import PRIZE_CHOICES, RECRUIT_CAP
from rulehall.engines.pokemon.champions.world import ChampionsWorld
from rulehall.engines.pokemon.dex import species_name

ROUNDS_MAX = 6


@pytest.fixture(autouse=True)
def _seeded_season(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ChampionsEngine, "season_seeds", Random(0))


def test_a_locals_runs_to_a_placing_and_its_cp() -> None:
    engine, state = game(CHAMPIONS)
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


def _registered() -> tuple[AnyEngine, AnyGame, ChampionsWorld]:
    engine, state = game(CHAMPIONS)
    draft = state.draft()
    _ = change(engine, draft, "register_team")
    return engine, draft, narrowed(draft.world, ChampionsWorld)


def _play_event(world: ChampionsWorld, *, won: bool) -> None:
    while not world.player_sheet.finishes:
        _ = world.start_match(Random(0))
        assert world.battle is not None
        team = world.battle.setup.team
        _ = world.settle_battle(
            BattleResult(
                outcome="won" if won else "lost", team=team, sent_out_foes=(), on_field_mon_ids=()
            )
        )


def _scout_seed(*, success: bool, dc: int) -> int:
    return next(seed for seed in range(100) if (Random(seed).randint(1, 20) >= dc) == success)


def _foe_names(world: ChampionsWorld) -> set[str]:
    own = {each.species_id for each in world.player_sheet.team}
    foe = world.require_event().require_player_opponent()
    return {species_name(each.species_id) for each in foe.sets if each.species_id not in own}


def test_a_closed_tier_scouting_success_tells_the_team_and_opens_the_foe_sheet() -> None:
    engine, draft, world = _registered()
    names = _foe_names(world)
    before = sections(engine.master_sections(draft))
    assert names
    assert not any(name in before for name in names)
    facts = world.scout("Watch the next table", Random(_scout_seed(success=True, dc=10)))
    card = " ".join(fact.card for fact in facts)
    assert all(name in card for name in names)
    (line,) = (each for each in world.event_lines().splitlines() if each.startswith("scouted"))
    assert all(name in line for name in names)
    assert "SP" not in line
    _ = world.start_match(Random(0))
    assert world.battle is not None
    assert world.battle.setup.foe_sheet_open
    assert not world.battle.setup.player_sheet_open


def test_a_failed_scouting_tells_nothing_and_a_second_try_refuses() -> None:
    _, _, world = _registered()
    _ = world.scout("Watch the next table", Random(_scout_seed(success=False, dc=10)))
    assert "scouted" not in world.event_lines()
    with pytest.raises(Refusal, match="already scouted"):
        _ = world.scout("Watch again", Random(0))
    _ = world.start_match(Random(0))
    assert world.battle is not None
    assert not world.battle.setup.foe_sheet_open


def test_scouting_refuses_with_no_match_to_play_and_during_a_match() -> None:
    _, state = game(CHAMPIONS)
    world = narrowed(state.draft().world, ChampionsWorld)
    with pytest.raises(Refusal, match="no match to play"):
        _ = world.scout("Watch", Random(0))
    _, _, world = _registered()
    _ = world.start_match(Random(0))
    with pytest.raises(Refusal, match="match is on"):
        _ = world.scout("Watch", Random(0))


def test_an_open_tier_opens_both_sheets_and_scouting_tells_the_likely_leads() -> None:
    _, _, world = _registered()
    world.require_event().tier = "regionals"
    foe = world.require_event().require_player_opponent()
    names = {species_name(each.species_id) for each in foe.sets}
    _ = world.scout("Watch the next table", Random(_scout_seed(success=True, dc=12)))
    (line,) = (each for each in world.event_lines().splitlines() if each.startswith("scouted"))
    first, second = line.removeprefix("scouted: likely leads ").split(" and ")
    assert {first, second} <= names
    _ = world.start_match(Random(0))
    assert world.battle is not None
    assert world.battle.setup.foe_sheet_open
    assert world.battle.setup.player_sheet_open


def test_a_story_top_cut_offers_beaten_species_and_a_claim_adds_one() -> None:
    engine, draft, world = _registered()
    sheet = world.player_sheet
    sheet.roster = "story"
    _play_event(world, won=True)
    offered = list(sheet.prize_species_ids)
    assert 1 <= len(offered) <= PRIZE_CHOICES
    assert not set(offered) & set(sheet.owned_species_ids)
    accepted = engine.accept(draft)
    assert accepted.pending is not None
    assert [option.id for option in accepted.pending.options] == offered
    _ = run_action(engine, draft, "claim_prize", species_id=offered[0])
    assert offered[0] in sheet.owned_species_ids
    assert sheet.prize_species_ids == []


def test_missing_the_cut_or_an_open_roster_offers_no_prize() -> None:
    _, _, world = _registered()
    world.player_sheet.roster = "story"
    _play_event(world, won=False)
    assert world.player_sheet.prize_species_ids == []
    _, _, world = _registered()
    _play_event(world, won=True)
    assert world.player_sheet.prize_species_ids == []


def test_recruits_add_up_to_the_cap() -> None:
    _, _, world = _registered()
    _play_event(world, won=True)
    assert world.player_sheet.recruits_left == 2
    _, _, world = _registered()
    world.player_sheet.recruits_left = RECRUIT_CAP
    _play_event(world, won=True)
    assert world.player_sheet.recruits_left == RECRUIT_CAP
