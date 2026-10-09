from random import Random

import pytest
from support.journey import ENGINE, started
from support.table import change

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.battle.models import BattleResult, BattleSetup
from rulehall.engines.pokemon.battle.simulator import end_battle
from rulehall.engines.pokemon.journey.rules import RosterSlot
from rulehall.engines.pokemon.journey.scheme import EvilTeam, Operation
from rulehall.engines.pokemon.journey.sheet import JourneyTrainer
from rulehall.engines.pokemon.journey.world import JourneyGame, JourneyRegionProposal
from rulehall.engines.rooms.world import OFF_MAP_ID, Place

TEAM_BEATEN = "The team is beaten. Your journey is complete."


def test_beating_the_operation_leader_foils_it_and_reveals_a_stage() -> None:
    draft = started().draft()

    resolution = end_battle(draft, _won(_battle(draft, "vesper")))

    evil_team = draft.world.evil_team
    assert (evil_team.outcomes, evil_team.operation) == (["foiled"], None)
    stage = evil_team.require_scheme().stages[0]
    assert any(fact.told and stage.foiled in fact.trace for fact in resolution.facts)
    assert draft.notes[-1] == "The team's operation at Gull Cove is foiled."


def test_a_foiled_and_a_succeeded_operation_reveal_different_texts() -> None:
    foiled_draft = started().draft()
    succeeded_draft = started().draft()

    foiled = end_battle(foiled_draft, _won(_battle(foiled_draft, "vesper")))
    succeeded = end_battle(succeeded_draft, _won(_battle(succeeded_draft, "ines")))

    stage = foiled_draft.world.evil_team.require_scheme().stages[0]
    assert stage.foiled != stage.succeeded
    assert any(stage.foiled in fact.trace for fact in foiled.facts)
    assert not any(stage.succeeded in fact.trace for fact in foiled.facts)
    assert any(stage.succeeded in fact.trace for fact in succeeded.facts)
    assert not any(stage.foiled in fact.trace for fact in succeeded.facts)


def test_a_foiled_leader_leaves_the_map_with_a_card_when_here() -> None:
    draft = started().draft()

    resolution = end_battle(draft, _won(_battle(draft, "vesper")))

    leader = draft.world.npcs["vesper"]
    assert leader.place_id == OFF_MAP_ID
    cards = [fact.card for fact in resolution.facts]
    assert cards.index(f"{leader.name} leaves") > cards.index(
        f'{leader.name}: "{leader.lose_line}"'
    )


def test_the_next_operation_is_due_by_two_badges_per_operation_at_the_latest() -> None:
    assert EvilTeam(outcomes=["foiled"] * 2, opened_at_badges=3).due(4) is None
    assert EvilTeam(outcomes=["foiled"] * 2, opened_at_badges=3).due(5) == "operation"
    assert EvilTeam(outcomes=["foiled"] * 3, opened_at_badges=7).due(8) == "operation"


def test_an_operation_is_not_due_before_two_badges_after_the_last_opening() -> None:
    draft = started().draft()
    world = draft.world
    world.evil_team.operation = None
    world.player_sheet.badges.append("Tide Badge")
    region = _reef_region(Operation(place_id="reef", leader_id="vesper", goal="Drain the reef."))

    assert world.scheme_due() is None
    with pytest.raises(Refusal, match="leave `operation` null"):
        ENGINE.check_next(draft, region)


def test_a_reused_leader_returns_at_the_new_operation() -> None:
    draft = _operation_owed()
    world = draft.world
    world.npcs["vesper"].place_id = OFF_MAP_ID
    region = _reef_region(Operation(place_id="reef", leader_id="vesper", goal="Drain the reef."))
    ENGINE.check_next(draft, region)

    _ = ENGINE.install_next(draft, region)

    assert world.npcs["vesper"].place_id == "reef"
    assert world.evil_team.opened_at_badges == 2


def test_a_badge_earned_while_the_operation_is_open_makes_it_succeed() -> None:
    draft = started().draft()

    _ = end_battle(draft, _won(_battle(draft, "ines")))

    evil_team = draft.world.evil_team
    assert (evil_team.outcomes, evil_team.operation) == (["succeeded"], None)


def test_a_region_without_the_operation_that_is_owed_is_refused() -> None:
    draft = _operation_owed()
    region = JourneyRegionProposal(
        places={"reef": Place(id="reef", name="Reef", brief="b", known=False, description="d")},
        start_id="reef",
        recap="They left the harbour behind.",
    )

    with pytest.raises(Refusal, match="write `operation`"):
        ENGINE.check_next(draft, region)


def test_a_region_installs_an_operation_led_by_one_of_its_own_new_people() -> None:
    draft = _operation_owed()
    grunt = JourneyTrainer(
        id="grunt-haddock",
        name="Grunt Haddock",
        voice="masculine",
        brief="A team grunt.",
        known=False,
        place_id="reef",
        roster=(RosterSlot(species_id="zubat", level=12),),
        style="swarms the field",
        win_line="The reef is ours.",
        lose_line="Back to the boat.",
        avatar_id="veteran",
    )
    region = JourneyRegionProposal(
        places={"reef": Place(id="reef", name="Reef", brief="b", known=False, description="d")},
        npcs={grunt.id: grunt},
        start_id="reef",
        recap="They left the harbour behind.",
        operation=Operation(place_id="reef", leader_id=grunt.id, goal="Drain the reef."),
    )
    ENGINE.check_next(draft, region)

    _ = ENGINE.install_next(draft, region)

    world = draft.world
    assert world.evil_team.operation == region.operation
    assert grunt.id in world.evil_team.leader_ids
    assert world.npcs[grunt.id].place_id == "reef"


def test_the_boss_ace_rises_with_each_success_and_the_legendary_joins_at_three() -> None:
    draft = started().draft()
    world = draft.world
    boss = _boss(draft)

    world.evil_team.outcomes = ["succeeded"]
    once = world.trainer_team(boss, Random(0))
    world.evil_team.outcomes = ["succeeded"] * 3
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

    resolution = end_battle(draft, _won(_battle(draft, "boss")))

    assert draft.world.evil_team.boss_beaten
    assert ENGINE.ending(draft) == TEAM_BEATEN
    assert (resolution.narrator_cue or "").startswith("The boss is beaten.")


def _operation_owed() -> JourneyGame:
    draft = started().draft()
    draft.world.evil_team.operation = None
    draft.world.player_sheet.badges.extend(("Tide Badge", "Gale Badge"))
    return draft


def _reef_region(operation: Operation) -> JourneyRegionProposal:
    return JourneyRegionProposal(
        places={"reef": Place(id="reef", name="Reef", brief="b", known=False, description="d")},
        start_id="reef",
        recap="They left the harbour behind.",
        operation=operation,
    )


def _boss(draft: JourneyGame) -> JourneyTrainer:
    world = draft.world
    boss = JourneyTrainer(
        id="boss",
        name="Boss Maren",
        voice="masculine",
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


def _battle(draft: JourneyGame, trainer_id: str) -> BattleSetup:
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
