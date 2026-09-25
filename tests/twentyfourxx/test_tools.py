from random import Random

import pytest
from support.table import change, refused, run_action
from support.twentyfourxx import ENGINE, KESTREL, LOCKPICKS, hired, small_world

from rulehall.core.facts import Fact
from rulehall.core.validation import Refusal
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.scenes.args import NextScene
from rulehall.engines.twentyfourxx.args import AskWorld, Helper, Job, Raise, Roll
from rulehall.engines.twentyfourxx.world import (
    SHIP_AWAY,
    STARTING_CREDITS,
    UPGRADE_COST,
    Gear,
    TwentyFourXXGame,
)


def _rolled(draft: TwentyFourXXGame, roll: Roll, *, seed: int = 0) -> list[Fact]:
    return ENGINE.roll(draft, roll, Random(seed))


def test_attempt_bands_disaster_setback_success() -> None:
    draft = small_world().draft()
    facts = _rolled(draft, Roll(what="Slip past", skill="Stealth", risk="a bruise"), seed=2)
    assert facts[1].trace.endswith("→ disaster")

    draft = small_world().draft()
    facts = _rolled(draft, Roll(what="Slip past", skill="Stealth", risk="a bruise"), seed=1)
    assert facts[1].trace.endswith("→ setback")

    draft = small_world().draft()
    facts = _rolled(draft, Roll(what="Slip past", skill="Stealth", risk="a bruise"))
    assert facts[1].trace.endswith("→ success")


def test_attempt_unskilled_rolls_the_plain_d6(draft: TwentyFourXXGame) -> None:
    facts = _rolled(draft, Roll(what="Guess", risk="a bruise"))
    assert facts[1].dice[0].faces == (6,)
    assert "Unskilled" in facts[1].trace


def test_attempt_actor_id_acts_on_the_member_and_risk_kills_them(draft: TwentyFourXXGame) -> None:
    draft = hired(draft, KESTREL, skills={"Stealth": 10}).draft()
    facts = _rolled(
        draft,
        Roll(what="Slip past", actor_id=KESTREL, skill="Stealth", risk="a long fall", deadly=True),
        seed=2,
    )
    member = draft.world.cast[KESTREL]
    assert not member.alive
    assert draft.world.player.alive
    assert any(fact.card == f"{member.name} is dead" for fact in facts)
    assert facts[1].trace.startswith("Slip past — Kestrel: ")


def test_deadly_disaster_kills() -> None:
    draft = small_world().draft()
    player = draft.world.player
    facts = _rolled(
        draft, Roll(what="Sneak past", skill="Stealth", risk="a guard's knife", deadly=True), seed=2
    )
    assert not player.alive
    assert any(fact.card == "You are dead" for fact in facts)


def test_non_deadly_disaster_neither_kills_nor_writes_the_risk_on_the_sheet() -> None:
    draft = small_world().draft()
    player = draft.world.player
    _rolled(draft, Roll(what="Sneak past", skill="Stealth", risk="a guard's knife"), seed=2)
    assert player.alive
    assert player.require_sheet().hindrances == []


def test_deadly_setback_maims_not_doubled() -> None:
    draft = small_world().draft()
    player = draft.world.player
    facts = _rolled(
        draft, Roll(what="Sneak past", skill="Stealth", risk="a guard's knife", deadly=True), seed=1
    )
    assert player.alive
    assert player.require_sheet().hindrances == ["Maimed — a guard's knife"]
    assert any(fact.card == "Hindered: Maimed — a guard's knife" for fact in facts)

    _ = _rolled(
        draft, Roll(what="Sneak past", skill="Stealth", risk="a guard's knife", deadly=True), seed=1
    )
    assert player.require_sheet().hindrances == ["Maimed — a guard's knife"]


def test_roll_refuses_naming_an_unmet_entity_in_a_free_text_field(draft: TwentyFourXXGame) -> None:
    assert "not met" in refused(
        ENGINE, draft, "roll", what="Slip past Sable", skill="Stealth", risk="a bruise"
    )

    facts = change(
        ENGINE, draft, "roll", what="Slip past Kestrel", skill="Stealth", risk="a bruise"
    )
    assert "Slip past Kestrel" in facts[1].trace


def test_defend_with_intact_item_spares_a_disaster_breaks_the_item_once() -> None:
    draft = small_world().draft()
    player = draft.world.player
    facts = _rolled(
        draft,
        Roll(
            what="Sneak past",
            skill="Stealth",
            risk="a guard's knife",
            defend_with_id=LOCKPICKS,
            hindrance="cut fingers",
        ),
        seed=2,
    )
    assert player.alive
    assert player.require_sheet().items[LOCKPICKS].broken_times == 1
    assert player.require_sheet().hindrances == ["cut fingers"]
    assert draft.pending is None
    assert any(fact.card == "Lockpick set breaks — cut fingers" for fact in facts)


def test_defend_with_harmless_gear_spares_a_disaster_and_adds_no_hindrance() -> None:
    draft = small_world().draft()
    player = draft.world.player
    facts = _rolled(
        draft,
        Roll(
            what="Weather the blast", skill="Stealth", risk="shrapnel", defend_with_id="hull-armor"
        ),
        seed=2,
    )
    assert player.alive
    assert draft.world.ship["hull-armor"].broken
    assert player.require_sheet().hindrances == []
    assert any(fact.card == "Hull armor breaks" for fact in facts)


def test_defend_with_multi_use_armor_defends_three_times_then_refuses() -> None:
    draft = small_world().draft()
    player = draft.world.player
    player.require_sheet().items["armor"] = Gear(name="Battle armor", breaks=3, harmless=True)
    for _ in range(3):
        _ = _rolled(
            draft,
            Roll(what="Take fire", skill="Stealth", risk="a bullet", defend_with_id="armor"),
            seed=2,
        )
    assert player.alive
    assert player.require_sheet().items["armor"].broken
    with pytest.raises(Refusal, match="already broken"):
        _ = _rolled(
            draft,
            Roll(what="Take fire", skill="Stealth", risk="a bullet", defend_with_id="armor"),
            seed=2,
        )


def test_both_participants_defend_with_their_own_separate_items(draft: TwentyFourXXGame) -> None:
    draft = hired(draft, KESTREL, skills={"Stealth": 10}).draft()
    draft.world.cast[KESTREL].require_sheet().items["vest"] = Gear(name="Vest")
    player = draft.world.player
    member = draft.world.cast[KESTREL]
    facts = _rolled(
        draft,
        Roll(
            what="Slip past",
            skill="Stealth",
            risk="a guard's knife",
            defend_with_id=LOCKPICKS,
            hindrance="cut fingers",
            helped_by=Helper(
                actor_id=KESTREL, risk="crossfire", defend_with_id="vest", hindrance="ringing ears"
            ),
        ),
        seed=2,
    )
    assert player.alive
    assert player.require_sheet().items[LOCKPICKS].broken_times == 1
    assert player.require_sheet().hindrances == ["cut fingers"]
    assert member.alive
    assert member.require_sheet().items["vest"].broken_times == 1
    assert member.require_sheet().hindrances == ["ringing ears"]
    assert any(fact.card == "Lockpick set breaks — cut fingers" for fact in facts)
    assert any(fact.card == "Kestrel: Vest breaks — ringing ears" for fact in facts)


def test_a_hired_helper_rolls_their_own_skill_die() -> None:
    draft = hired(small_world(), KESTREL, skills={"Stealth": 12}).draft()

    facts = _rolled(
        draft,
        Roll(
            what="Slip past", skill="Stealth", risk="a bruise", helped_by=Helper(actor_id=KESTREL)
        ),
    )

    assert "helped by Kestrel (d12)" in facts[1].trace


def test_a_hired_helper_without_the_skill_rolls_the_plain_d6() -> None:
    draft = hired(small_world(), KESTREL, skills={"Piloting": 12}).draft()

    facts = _rolled(
        draft,
        Roll(
            what="Slip past", skill="Stealth", risk="a bruise", helped_by=Helper(actor_id=KESTREL)
        ),
    )

    assert "helped by Kestrel (d6)" in facts[1].trace


def test_a_hired_helper_rolls_a_skill_a_job_invented() -> None:
    draft = hired(small_world(), KESTREL, skills={"Relic lore": 10}).draft()
    draft.world.player.require_sheet().skills["Relic lore"] = 8

    facts = _rolled(
        draft,
        Roll(
            what="Read the seal",
            skill="Relic lore",
            risk="a bruise",
            helped_by=Helper(actor_id=KESTREL),
        ),
    )

    assert "helped by Kestrel (d10)" in facts[1].trace


def test_helper_with_risk_takes_their_own_consequence_on_a_bad_roll() -> None:
    draft = hired(small_world(), KESTREL, skills={"Stealth": 10}).draft()
    facts = _rolled(
        draft,
        Roll(
            what="Slip past",
            skill="Stealth",
            risk="a bruise",
            helped_by=Helper(actor_id=KESTREL, risk="a guard's knife", deadly=True),
        ),
        seed=2,
    )
    member = draft.world.cast[KESTREL]
    assert draft.world.player.alive
    assert not member.alive
    assert any(fact.card == f"{member.name} is dead" for fact in facts)


def test_ask_world_facts_are_untold(draft: TwentyFourXXGame) -> None:
    dice_fact, luck_fact = ENGINE.ask_world(draft, AskWorld(question="Is anyone home?"), Random(0))
    assert not dice_fact.told
    assert not luck_fact.told
    assert luck_fact.card == ""


def test_defend_breaks_the_item_and_adds_the_hindrance_refused_when_broken() -> None:
    draft = small_world().draft()
    player = draft.world.player
    facts = change(ENGINE, draft, "defend", item_id=LOCKPICKS, hindrance="fingers cut")
    assert player.require_sheet().items[LOCKPICKS].broken_times == 1
    assert player.require_sheet().items[LOCKPICKS].broken
    assert "fingers cut" in player.require_sheet().hindrances
    assert any(fact.card == "Lockpick set breaks — fingers cut" for fact in facts)

    assert "already broken" in refused(
        ENGINE, draft, "defend", item_id=LOCKPICKS, hindrance="fingers cut again"
    )


def test_gain_item_spends_and_refuses_short_credits(draft: TwentyFourXXGame) -> None:
    player = draft.world.player
    assert player.require_sheet().credits == STARTING_CREDITS
    _ = change(ENGINE, draft, "gain_item", name="Rope", cost=1)
    assert player.require_sheet().credits == STARTING_CREDITS - 1
    assert player.require_sheet().items["rope"].name == "Rope"

    assert "only" in refused(ENGINE, draft, "gain_item", name="Grenade", cost=99)


def test_gain_item_slugs_against_the_ships_functions_too(draft: TwentyFourXXGame) -> None:
    player = draft.world.player
    _ = change(ENGINE, draft, "gain_item", name="Sensors")
    assert "sensors" not in player.require_sheet().items
    assert player.require_sheet().items["sensors-2"].name == "Sensors"
    assert draft.world.ship["sensors"].name == "Sensors"


def test_spend_refuses_short_credits(draft: TwentyFourXXGame) -> None:
    player = draft.world.player
    _ = change(ENGINE, draft, "spend", amount=1, why="a bribe")
    assert player.require_sheet().credits == STARTING_CREDITS - 1
    assert "only" in refused(ENGINE, draft, "spend", amount=99, why="a bigger bribe")


def test_repair_item_zeroes_broken_times_and_refuses_an_unbroken_item() -> None:
    draft = small_world().draft()
    player = draft.world.player
    assert "not broken" in refused(ENGINE, draft, "repair_item", item_id=LOCKPICKS)

    player.require_sheet().items[LOCKPICKS].broken_times = 1
    _ = change(ENGINE, draft, "repair_item", item_id=LOCKPICKS)
    assert player.require_sheet().items[LOCKPICKS].broken_times == 0


def test_change_hindrances_gains_and_loses_refuses_duplicate_and_absent() -> None:
    draft = small_world().draft()
    player = draft.world.player
    _ = change(ENGINE, draft, "change_hindrances", gained=["Bleeding"])
    assert player.require_sheet().hindrances == ["Bleeding"]

    assert "already" in refused(ENGINE, draft, "change_hindrances", gained=["Bleeding"])
    assert "carries no" in refused(ENGINE, draft, "change_hindrances", lost=["Scared"])

    _ = change(ENGINE, draft, "change_hindrances", gained=["Scared"], lost=["Bleeding"])
    assert player.require_sheet().hindrances == ["Scared"]


def test_finish_job_raises_a_skill_enters_a_new_one_refuses_at_d12_adds_credits() -> None:
    draft = small_world().draft()
    player = draft.world.player
    before_credits = player.require_sheet().credits

    draft.world.job = "Escort the crate to dock nine"
    facts = ENGINE.job(draft, Job(verb="finish", raises=(Raise(skill="Stealth"),)), Random(0))
    assert player.require_sheet().skills["Stealth"] == 12
    assert player.require_sheet().credits == before_credits + 4
    assert any(fact.card == "Job done: Stealth d12" for fact in facts)
    assert draft.world.job == ""

    draft.world.job = "Shadow the courier"
    _ = ENGINE.job(draft, Job(verb="finish", raises=(Raise(skill="Climbing"),)), Random(1))
    assert player.require_sheet().skills["Climbing"] == 8

    draft.world.job = "One skill too far"
    with pytest.raises(Refusal, match="Rook's Stealth is already at d12"):
        _ = ENGINE.job(draft, Job(verb="finish", raises=(Raise(skill="Stealth"),)), Random(0))


def test_finish_job_raises_the_whole_crew_and_pays_each_a_d6(draft: TwentyFourXXGame) -> None:
    draft = hired(draft, KESTREL, skills={"Shooting": 8}).draft()
    player = draft.world.player
    member = draft.world.cast[KESTREL]
    before_member_credits = member.require_sheet().credits
    draft.world.job = "Escort the crate"

    facts = ENGINE.job(
        draft,
        Job(
            verb="finish",
            raises=(Raise(skill="Stealth"), Raise(actor_id=KESTREL, skill="Shooting")),
        ),
        Random(0),
    )

    assert player.require_sheet().skills["Stealth"] == 12
    assert member.require_sheet().skills["Shooting"] == 10
    assert member.require_sheet().credits > before_member_credits
    assert any(fact.card == "Kestrel: Job done: Shooting d10" for fact in facts)


def test_take_job_opens_a_job_and_refuses_a_second_while_open(draft: TwentyFourXXGame) -> None:
    facts = ENGINE.job(draft, Job(verb="take", terms="Move the crates by dawn"), Random(0))
    assert draft.world.job == "Move the crates by dawn"
    assert any(fact.card == "Job taken\nMove the crates by dawn" for fact in facts)

    with pytest.raises(Refusal, match="a job is open"):
        _ = ENGINE.job(draft, Job(verb="take", terms="A second job"), Random(0))


def test_find_job_reads_the_three_bands_by_seed() -> None:
    draft = small_world().draft()
    facts = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(1))
    assert facts[1].trace.endswith("nothing; the player owes somebody to get in on a job")

    draft = small_world().draft()
    facts = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(0))
    assert facts[1].trace.endswith("a job, but something seems off")

    draft = small_world().draft()
    facts = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(5))
    assert facts[1].trace.endswith("a choice between two jobs")


def test_job_validator_refuses_fields_that_do_not_match_the_verb() -> None:
    with pytest.raises(ValueError, match="find takes where only"):
        _ = Job(verb="find")
    with pytest.raises(ValueError, match="find takes where only"):
        _ = Job(verb="find", where="Docks", terms="extra")
    with pytest.raises(ValueError, match="take takes terms only"):
        _ = Job(verb="take")
    with pytest.raises(ValueError, match="take takes terms only"):
        _ = Job(verb="take", terms="agreed", where="Docks")
    with pytest.raises(ValueError, match="finish takes raises only"):
        _ = Job(verb="finish")
    with pytest.raises(ValueError, match="finish takes raises only"):
        _ = Job(verb="finish", raises=(Raise(skill="Stealth"),), terms="agreed")


def test_kill_on_the_player_flips_player_over(draft: TwentyFourXXGame) -> None:
    facts = change(ENGINE, draft, "kill", target_id=PLAYER_ID)
    assert not draft.world.player.alive
    assert ENGINE.ending(draft) == "You died."
    assert any(fact.card == "You are dead" for fact in facts)


def test_risk_disaster_with_hired_member_sets_succession_and_over_stays_none() -> None:
    draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
    facts = _rolled(
        draft, Roll(what="Slip past", skill="Stealth", risk="a long fall", deadly=True), seed=2
    )
    assert not draft.world.player.alive
    assert draft.pending is not None
    assert draft.pending.kind == "succession"
    assert [option.id for option in draft.pending.options] == [KESTREL]
    assert ENGINE.ending(draft) is None
    assert any(fact.card == "You are dead" for fact in facts)


def test_risk_disaster_with_none_hired_ends_the_game(draft: TwentyFourXXGame) -> None:
    _ = _rolled(
        draft, Roll(what="Slip past", skill="Stealth", risk="a long fall", deadly=True), seed=2
    )
    assert not draft.world.player.alive
    assert draft.pending is None
    assert ENGINE.ending(draft) == "You died."


def test_answering_the_succession_decision_makes_the_member_the_player() -> None:
    draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
    _ = _rolled(
        draft, Roll(what="Slip past", skill="Stealth", risk="a long fall", deadly=True), seed=2
    )
    assert draft.pending is not None
    option = draft.pending.options[0]
    facts = ENGINE.play_option(draft, option, Random(0))
    assert draft.world.player.id == KESTREL
    assert any(fact.card == "Kestrel leads now" for fact in facts)


def test_ship_upgrade_pays_credits_once_and_refuses_a_second(draft: TwentyFourXXGame) -> None:
    draft.world.ship_here = True
    player = draft.world.player
    player.require_sheet().credits = UPGRADE_COST * 2
    before = player.require_sheet().credits
    facts = change(ENGINE, draft, "ship_upgrade", function_id="hull-armor")
    assert player.require_sheet().credits == before - UPGRADE_COST
    assert draft.world.ship["hull-armor"].upgraded
    assert any(fact.card == "Hull armor upgraded — ₡10" for fact in facts)

    assert "already" in refused(ENGINE, draft, "ship_upgrade", function_id="hull-armor")


def test_next_scene_offers_the_way_on_and_refuses_a_second_offer(draft: TwentyFourXXGame) -> None:
    _ = ENGINE.next_scene(draft, NextScene(), Random(0))
    assert draft.world.scene.way_offered
    with pytest.raises(Refusal, match="already offers"):
        _ = ENGINE.next_scene(draft, NextScene(), Random(0))


def test_the_hold_passes_an_item_from_the_player_to_a_hired_member() -> None:
    draft = hired(small_world(), KESTREL, skills={}).draft()
    world = draft.world
    world.ship_here = True
    _ = run_action(ENGINE, draft, "stow_item", item_id=LOCKPICKS, actor_id=PLAYER_ID)
    (held,) = world.hold
    _ = run_action(ENGINE, draft, "retrieve_item", item_id=held, actor_id=KESTREL)
    assert world.player.require_sheet().items == {}
    assert [item.name for item in world.cast[KESTREL].require_sheet().items.values()] == [
        "Lockpick set"
    ]
    assert world.hold == {}


def test_every_hold_option_is_refused_while_the_ship_is_away() -> None:
    draft = hired(small_world(), KESTREL, skills={}).draft()
    draft.world.hold["crate"] = Gear(name="Crate")
    options = [
        option
        for panel in ENGINE.player_view(draft).panels
        for row in panel.rows
        for option in row.options
        if option.action_name in {"stow_item", "retrieve_item", "ship_upgrade"}
    ]
    assert {option.action_name for option in options} == {
        "stow_item",
        "retrieve_item",
        "ship_upgrade",
    }
    assert all(option.refusal == SHIP_AWAY for option in options)


def test_lose_hold_item_tells_the_loss_and_empties_the_slot(draft: TwentyFourXXGame) -> None:
    draft.world.hold["crate"] = Gear(name="Crate")
    facts = change(ENGINE, draft, "lose_hold_item", item_id="crate", why="a dock raid")
    assert [fact.told for fact in facts] == [True]
    assert "crate" not in draft.world.hold
