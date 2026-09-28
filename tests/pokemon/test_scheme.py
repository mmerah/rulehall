from random import Random

import pytest
from support.pokemon import ENGINE, started
from support.table import change, refused

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.battle.models import BattleResult, BattleSetup
from rulehall.engines.pokemon.rules import RosterSlot
from rulehall.engines.pokemon.sheet import Trainer
from rulehall.engines.pokemon.world import PokemonGame, PokemonRegionProposal
from rulehall.engines.rooms.world import Place

TEAM_BEATEN = "The team is beaten. Your journey is complete."


def test_beating_the_operation_leader_foils_it_and_reveals_a_stage() -> None:
    draft = started().draft()

    resolution = ENGINE.end_battle(draft, _won(_battle(draft, "vesper")))

    evil_team = draft.world.evil_team
    assert (evil_team.foiled, evil_team.succeeded, evil_team.operation) == (1, 0, None)
    stage = evil_team.require_scheme().stages[0]
    assert any(fact.told and stage in fact.trace for fact in resolution.facts)
    assert draft.notes[-1] == "The team's operation at Gull Cove is foiled."


def test_a_badge_earned_while_the_operation_is_open_makes_it_succeed_and_hold_its_way() -> None:
    draft = started().draft()

    _ = ENGINE.end_battle(draft, _won(_battle(draft, "ines")))

    evil_team = draft.world.evil_team
    assert (evil_team.foiled, evil_team.succeeded, evil_team.operation) == (0, 1, None)
    assert evil_team.held_ways == [("gull-cove", "harbour-road")]
    assert refused(ENGINE, draft, "unlock_way", to_id="gull-cove") == (
        "the grunts of Team Undertow hold this way"
    )


def test_a_way_that_would_cut_a_place_off_closes_a_center_instead() -> None:
    draft = started().draft()
    world = draft.world
    for start, end in (("gull-cove", "tern-harbour"), ("tern-harbour", "gull-cove")):
        world.ways[start] = [way for way in world.ways[start] if way.to_id != end]
    world.center_place_ids.append("tern-harbour")
    setup = _battle(draft, "vesper")

    _ = ENGINE.end_battle(
        draft, BattleResult(outcome="lost", team=setup.team, sent_out_foes=(), on_field_mon_ids=())
    )

    assert world.evil_team.succeeded == 1
    assert world.evil_team.held_ways == []
    assert world.center_place_ids == ["tern-harbour"]


def test_a_region_without_the_operation_that_is_owed_is_refused() -> None:
    draft = started().draft()
    draft.world.evil_team.operation = None
    region = PokemonRegionProposal(
        places={"reef": Place(id="reef", name="Reef", brief="b", known=False, description="d")},
        start_id="reef",
        recap="They left the harbour behind.",
    )

    with pytest.raises(Refusal, match="write `operation`"):
        ENGINE.check_next(draft, region)


def test_the_boss_ace_rises_with_each_success_and_the_legendary_joins_at_three() -> None:
    draft = started().draft()
    world = draft.world
    boss = _boss(draft)

    world.evil_team.succeeded = 1
    once = world.trainer_team(boss, Random(0))
    world.evil_team.succeeded = 3
    thrice = world.trainer_team(boss, Random(0))

    assert [(mon.species_id, mon.level) for mon in once] == [("zubat", 12), ("grimer", 14)]
    assert [(mon.species_id, mon.level) for mon in thrice] == [
        ("zubat", 16),
        ("grimer", 18),
        ("articuno", 18),
    ]


def test_beating_the_boss_ends_the_journey_with_an_epilogue() -> None:
    draft = started().draft()
    _ = _boss(draft)

    resolution = ENGINE.end_battle(draft, _won(_battle(draft, "boss")))

    assert draft.world.evil_team.boss_beaten
    assert ENGINE.ending(draft) == TEAM_BEATEN
    assert (resolution.narrator_cue or "").startswith("The boss is beaten.")


def _boss(draft: PokemonGame) -> Trainer:
    world = draft.world
    boss = Trainer(
        id="boss",
        name="Boss Maren",
        brief="The boss of the team.",
        known=True,
        place_id=world.current.id,
        roster=(
            RosterSlot(species_id="zubat", level=28),
            RosterSlot(species_id="grimer", level=30),
        ),
        style="floods the field",
        win_line="The sea is mine.",
        lose_line="The tide turns.",
        avatar_id="veteran",
    )
    world.npcs[boss.id] = boss
    world.evil_team.boss_id = boss.id
    return boss


def _battle(draft: PokemonGame, trainer_id: str) -> BattleSetup:
    trainer = draft.world.npcs[trainer_id]
    trainer.place_id = draft.world.current.id
    trainer.known = True
    _ = change(ENGINE, draft, "start_battle", trainer_id=trainer_id)
    assert draft.world.battle is not None
    return draft.world.battle.setup


def _won(setup: BattleSetup) -> BattleResult:
    return BattleResult(
        outcome="won",
        team=setup.team,
        sent_out_foes=tuple(foe.model_copy(update={"hp": 0}) for foe in setup.foes),
        on_field_mon_ids=(setup.team[0].mon_id,),
    )
