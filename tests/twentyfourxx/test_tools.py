from random import Random

import pytest
from pydantic import JsonValue, ValidationError
from support.table import change, refused, run_action
from support.twentyfourxx import ENGINE, KESTREL, LOCKPICKS, SABLE, SCENE_BASE, hired, small_world

from rulehall.core.creation import find_option
from rulehall.core.decisions import ActionOption
from rulehall.core.facts import Fact
from rulehall.core.validation import Refusal
from rulehall.engines.scenes.world import SceneProposal
from rulehall.engines.sheet import PLAYER_ID
from rulehall.engines.twentyfourxx.args import (
    Helper,
    Job,
    NextScene,
    Raise,
    Roll,
)
from rulehall.engines.twentyfourxx.engine import SCENE_LEFT, WAY_OFFERED
from rulehall.engines.twentyfourxx.sheet import STARTING_CREDITS, Crewmate, Gear
from rulehall.engines.twentyfourxx.world import SHIP_AWAY, UPGRADE_COST, TwentyFourXXGame


def _rolled(draft: TwentyFourXXGame, roll: Roll, *, seed: int = 0) -> list[Fact]:
    facts = ENGINE.roll(draft, roll.model_copy(update={"committed": True}), Random(seed))
    while draft.pending is not None and draft.pending.kind == "defence":
        take_it = find_option(draft.pending.options, "take-it")
        assert take_it is not None
        draft.pending = None
        facts.extend(ENGINE.play_option(draft, take_it, Random(seed)))
    return facts


def _decision_after(draft: TwentyFourXXGame) -> str:
    pending = ENGINE.record(draft, (), ()).pending
    assert pending is not None
    return pending.kind


def test_raise_skill_adds_a_missing_skill_at_d8_and_refuses_at_d12(
    draft: TwentyFourXXGame,
) -> None:
    draft.world.raise_owed = True
    facts = change(ENGINE, draft, "raise_skill", skill="Climbing")
    assert draft.world.player.require_sheet().skills["Climbing"] == 8
    assert any(fact.card == "Job done: Climbing d8" for fact in facts)

    draft.world.player.require_sheet().skills["Stealth"] = 12
    draft.world.raise_owed = True
    assert "already at d12" in refused(ENGINE, draft, "raise_skill", skill="Stealth")


def test_roll_asks_the_player_to_commit_and_tells_nothing(draft: TwentyFourXXGame) -> None:
    draft.world.player.require_sheet().hindrances.append("Bruised")
    facts = change(ENGINE, draft, "roll", what="Slip past", skill="Stealth", risk="a fall")

    assert facts == []
    assert draft.pending is not None
    assert draft.pending.kind == "risk"
    assert "d10" in draft.pending.prompt
    assert "Hindrances: Bruised." in draft.pending.prompt


def test_the_commit_option_rolls_once(draft: TwentyFourXXGame) -> None:
    _ = change(ENGINE, draft, "roll", what="Slip past", skill="Stealth", risk="a fall")
    assert draft.pending is not None
    (commit,) = draft.pending.options
    draft.pending = None

    facts = ENGINE.play_option(draft, commit, Random(0))

    assert len([fact for fact in facts if fact.dice]) == 1
    assert draft.pending is None


def test_a_deadly_setback_pauses_for_gear_and_a_break_spares_the_hit() -> None:
    draft = small_world().draft()
    player = draft.world.player
    roll = Roll(what="Sneak past", skill="Stealth", risk="a knife", deadly=True, committed=True)

    facts = ENGINE.roll(draft, roll, Random(1))

    assert draft.pending is not None
    assert draft.pending.kind == "defence"
    assert [fact.card for fact in facts] == [""]
    lockpicks = find_option(draft.pending.options, LOCKPICKS)
    assert lockpicks is not None
    draft.pending = None
    facts = ENGINE.play_option(draft, lockpicks, Random(0))
    assert facts[0].card.endswith("→ setback")
    assert player.require_sheet().items[LOCKPICKS].broken
    assert player.require_sheet().hindrances == ["Brief: Close call"]


def test_every_deadly_hit_in_a_scene_can_break_gear() -> None:
    draft = small_world().draft()
    sheet = draft.world.player.require_sheet()
    sheet.items["vest"] = Gear(name="Flak vest")
    knife = Roll(what="Sneak past", skill="Stealth", risk="a knife", deadly=True, committed=True)
    for item_id in (LOCKPICKS, "vest"):
        _ = ENGINE.roll(draft, knife, Random(1))
        assert draft.pending is not None
        breaking = find_option(draft.pending.options, item_id)
        assert breaking is not None
        draft.pending = None
        _ = ENGINE.play_option(draft, breaking, Random(0))
    assert sheet.hindrances == ["Brief: Close call"]
    assert sheet.items["vest"].broken


def test_a_harm_setback_writes_a_brief_wound_and_a_maim_is_named() -> None:
    draft = small_world().draft()
    player = draft.world.player
    burn = Roll(what="Pry the lid", skill="Stealth", risk="burned hands", harm=True)
    _ = _rolled(draft, burn, seed=1)
    assert player.require_sheet().hindrances == ["Brief: Minor hurt"]
    assert draft.pending is None

    knife = Roll(what="Sneak past", skill="Stealth", risk="Shot dead", deadly=True)
    _ = ENGINE.roll(draft, knife.model_copy(update={"committed": True}), Random(1))
    assert draft.pending is not None
    assert "is maimed" in draft.pending.prompt
    assert "Shot dead" not in draft.pending.prompt


def test_a_named_setback_hurt_is_written_brief_on_a_setback_and_on_softened_gear() -> None:
    draft = small_world().draft()
    sheet = draft.world.player.require_sheet()
    burn = Roll(
        what="Pry the lid", skill="Stealth", risk="Burned hands", harm=True, setback_hurt="Singed"
    )
    _ = _rolled(draft, burn, seed=1)
    assert sheet.hindrances == ["Brief: Singed"]

    _ = ENGINE.roll(draft, burn.model_copy(update={"committed": True}), Random(2))
    assert draft.pending is not None
    lockpicks = find_option(draft.pending.options, LOCKPICKS)
    assert lockpicks is not None
    draft.pending = None
    _ = ENGINE.play_option(draft, lockpicks, Random(0))
    assert sheet.hindrances == ["Brief: Singed"]
    assert sheet.items[LOCKPICKS].broken


def test_a_setback_that_is_not_deadly_opens_no_pause(draft: TwentyFourXXGame) -> None:
    roll = Roll(what="Sneak past", skill="Stealth", risk="a knife", committed=True)
    facts = ENGINE.roll(draft, roll, Random(1))
    assert draft.pending is None
    assert facts[1].card.endswith("→ setback")


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


def test_a_harm_disaster_writes_the_risk_once_and_another_disaster_writes_nothing() -> None:
    draft = small_world().draft()
    player = draft.world.player
    _ = _rolled(draft, Roll(what="Sneak past", skill="Stealth", risk="Lost the trail"), seed=2)
    assert player.require_sheet().hindrances == []

    knife = Roll(what="Sneak past", skill="Stealth", risk="Knifed arm", harm=True)
    for _ in range(2):
        _ = _rolled(draft, knife, seed=2)
    assert player.alive
    assert player.require_sheet().hindrances == ["Knifed arm"]


def test_a_deadly_setback_maims_once_and_a_wound_is_its_own_hindrance() -> None:
    draft = small_world().draft()
    player = draft.world.player
    knife = Roll(what="Sneak past", skill="Stealth", risk="The guard kills you", deadly=True)
    facts = _rolled(draft, knife, seed=1)
    assert player.alive
    assert player.require_sheet().hindrances == ["Maimed"]
    assert any(fact.card == "Hindered: Maimed" for fact in facts)

    _ = change(ENGINE, draft, "change_hindrances", gained=["Stabbed side"])
    _ = _rolled(draft, knife, seed=1)
    assert player.require_sheet().hindrances == ["Maimed", "Stabbed side"]


def test_a_name_told_to_the_player_makes_them_met_unless_they_are_hidden_here(
    draft: TwentyFourXXGame,
) -> None:
    buyer = Crewmate(
        id="bray-kell", name="Bray Kell", voice="masculine", brief="The buyer on Anvil"
    )
    draft.world.cast[buyer.id] = buyer
    _ = change(ENGINE, draft, "direct", text="Ilsa says the buyer is Bray Kell, on Anvil.")
    assert buyer.known
    assert buyer.id not in draft.world.scene.here_ids
    assert "not met" in refused(ENGINE, draft, "direct", text="Sable waits in the dark.")
    assert not draft.world.cast[SABLE].known


def test_roll_refuses_naming_an_unmet_entity_in_a_free_text_field(draft: TwentyFourXXGame) -> None:
    assert "not met" in refused(
        ENGINE, draft, "roll", what="Slip past Sable", skill="Stealth", risk="a bruise"
    )

    _ = change(ENGINE, draft, "roll", what="Slip past Kestrel", skill="Stealth", risk="a bruise")
    assert draft.pending is not None
    assert "Slip past Kestrel" in draft.pending.prompt


def test_the_defence_offers_a_ship_function_while_the_ship_is_here() -> None:
    draft = small_world().draft()
    world = draft.world
    world.dock_here()
    blast = Roll(
        what="Weather the blast", skill="Stealth", risk="shrapnel", harm=True, committed=True
    )
    _ = ENGINE.roll(draft, blast, Random(2))
    assert draft.pending is not None
    hull_armor = find_option(draft.pending.options, "hull-armor")
    assert hull_armor is not None
    draft.pending = None
    facts = ENGINE.play_option(draft, hull_armor, Random(0))
    assert world.ship["hull-armor"].broken
    assert world.player.require_sheet().hindrances == []
    assert any(fact.card == "Hull armor breaks" for fact in facts)


def test_the_helper_cannot_break_the_ship_function_the_actor_broke() -> None:
    draft = hired(small_world(), KESTREL, skills={"Stealth": 8}).draft()
    draft.world.dock_here()
    blast = Roll(
        what="Weather the blast",
        skill="Stealth",
        risk="shrapnel",
        harm=True,
        helped_by=Helper(actor_id=KESTREL),
        committed=True,
    )
    _ = ENGINE.roll(draft, blast, Random(2))
    assert draft.pending is not None
    assert draft.pending.kind == "defence"
    hull_armor = find_option(draft.pending.options, "hull-armor")
    assert hull_armor is not None
    draft.pending = None
    _ = ENGINE.play_option(draft, hull_armor, Random(0))
    assert draft.pending is not None
    assert find_option(draft.pending.options, "hull-armor") is None
    assert find_option(draft.pending.options, "take-it") is not None


def test_a_helper_rolls_the_named_skill_else_the_rolled_one_and_shares_the_risk() -> None:
    draft = hired(small_world(), KESTREL, skills={"Piloting": 12, "Stealth": 8}).draft()
    slip = Roll(what="Slip past", skill="Stealth", risk="Bruised ribs", harm=True)

    for roll, helper, shown in (
        (slip, Helper(actor_id=KESTREL), "Stealth d8"),
        (slip, Helper(actor_id=KESTREL, skill="piloting"), "Piloting d12"),
        (slip.model_copy(update={"skill": "Hacking"}), Helper(actor_id=KESTREL), "Hacking d6"),
    ):
        facts = _rolled(draft, roll.model_copy(update={"helped_by": helper}))
        assert f"helped by Kestrel ({shown})" in facts[1].trace

    facts = _rolled(draft, slip.model_copy(update={"helped_by": Helper(actor_id=KESTREL)}), seed=2)
    assert "Bruised ribs" in draft.world.cast[KESTREL].require_sheet().hindrances


def test_defend_breaks_the_item_and_adds_the_hindrance_refused_when_broken() -> None:
    draft = small_world().draft()
    player = draft.world.player
    facts = change(ENGINE, draft, "defend", item_id=LOCKPICKS, hindrance="fingers cut")
    assert player.require_sheet().items[LOCKPICKS].broken_times == 1
    assert player.require_sheet().items[LOCKPICKS].broken
    assert "Brief: fingers cut" in player.require_sheet().hindrances
    assert any(fact.card == "Lockpick set breaks — Brief: fingers cut" for fact in facts)

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


def test_repair_item_reaches_the_hold_only_while_the_ship_is_here() -> None:
    draft = small_world().draft()
    world = draft.world
    world.hold["vest"] = Gear(name="Vest", broken_times=1)
    assert "not among" in refused(ENGINE, draft, "repair_item", item_id="vest")

    world.dock_here()
    _ = change(ENGINE, draft, "repair_item", item_id="vest")
    assert world.hold["vest"].broken_times == 0


def test_change_hindrances_skips_a_duplicate_and_refuses_the_absent_naming_the_carried() -> None:
    draft = small_world().draft()
    player = draft.world.player
    _ = change(ENGINE, draft, "change_hindrances", gained=["Bleeding"])
    assert player.require_sheet().hindrances == ["Bleeding"]

    assert change(ENGINE, draft, "change_hindrances", gained=["bleeding"]) == []
    refusal = refused(ENGINE, draft, "change_hindrances", lost=["Scared"])
    assert "carries no hindrance 'Scared'; it carries: 'Bleeding'" in refusal

    _ = change(ENGINE, draft, "change_hindrances", gained=["Scared"], lost=["Bleeding"])
    assert player.require_sheet().hindrances == ["Scared"]


def test_finish_pays_the_player_and_asks_their_raise_once_the_turn_ends(
    draft: TwentyFourXXGame,
) -> None:
    player = draft.world.player
    before_credits = player.require_sheet().credits
    draft.world.job = "Escort the crate to dock nine"
    draft.world.work_rolled = True

    _ = change(ENGINE, draft, "job", verb="finish", terms="Escort the crate")

    assert player.require_sheet().credits == before_credits + 4
    assert draft.world.job == ""
    assert draft.pending is None
    _ = change(ENGINE, draft, "direct", text="Dock nine takes the crate.")
    state = ENGINE.record(draft, (), ())
    assert state.pending is not None
    assert state.pending.kind == "raise"
    (stealth,) = state.pending.options
    draft = state.draft()
    draft.pending = None
    facts = ENGINE.play_option(draft, stealth, Random(0))
    assert draft.world.player.require_sheet().skills["Stealth"] == 12
    assert any(fact.card == "Job done: Stealth d12" for fact in facts)


def test_raise_skill_is_refused_when_no_raise_is_owed(draft: TwentyFourXXGame) -> None:
    assert "no raise is owed" in refused(ENGINE, draft, "raise_skill", skill="Climbing")


def test_finish_job_raises_the_hired_crew_and_pays_each_a_d6(draft: TwentyFourXXGame) -> None:
    draft = hired(draft, KESTREL, skills={"Shooting": 8}).draft()
    member = draft.world.cast[KESTREL]
    before_member_credits = member.require_sheet().credits
    draft.world.job = "Escort the crate"
    draft.world.work_rolled = True

    facts = ENGINE.job(
        draft, Job(verb="finish", raises=(Raise(actor_id=KESTREL, skill="Shooting"),)), Random(0)
    )

    assert member.require_sheet().skills["Shooting"] == 10
    assert member.require_sheet().credits > before_member_credits
    assert any(fact.card == "Kestrel: Job done: Shooting d10" for fact in facts)


def test_a_dead_lead_finishes_no_job_and_the_new_lead_owes_no_raise() -> None:
    draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
    world = draft.world
    world.job = "Escort the crate"
    world.work_rolled = True
    world.player.alive = False
    world.raise_owed = True

    raises: list[JsonValue] = [{"actor_id": KESTREL, "skill": "Shooting"}]
    assert "is dead" in refused(ENGINE, draft, "job", verb="finish", raises=raises)
    _ = world.take_lead(KESTREL)
    assert not world.raise_owed


def test_take_job_opens_a_job_only_after_a_find(draft: TwentyFourXXGame) -> None:
    take = Job(verb="take", terms="Move the crates by dawn")
    with pytest.raises(Refusal, match="call `job` `find` first"):
        _ = ENGINE.job(draft, take, Random(0))

    _ = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(0))
    facts = ENGINE.job(draft, take, Random(0))
    assert draft.world.job.startswith("Move the crates by dawn")
    assert any(fact.card.startswith("Job taken\nMove the crates by dawn") for fact in facts)


def test_a_find_is_refused_while_a_job_is_open_even_with_its_work_rolled() -> None:
    draft = small_world().draft()
    world = draft.world
    world.job = "Escort the crate"
    for rolled in (False, True):
        world.work_rolled = rolled
        with pytest.raises(Refusal, match="a job is open"):
            _ = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(0))


def test_a_find_stands_across_a_scene_change_until_a_job_is_taken() -> None:
    draft = small_world().draft()
    world = draft.world
    _ = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(0))
    world.apply_scene(SceneProposal[Crewmate].model_validate(SCENE_BASE))

    assert _look_again(draft)
    _ = ENGINE.job(draft, Job(verb="take", terms="Fly the crate"), Random(0))
    assert world.job == "Fly the crate"
    world.close_job()
    assert _look_again(draft) == []
    with pytest.raises(Refusal, match="call `job` `find` first"):
        _ = ENGINE.job(draft, Job(verb="take", terms="Fly it again"), Random(0))


def test_the_way_on_and_the_leaving_are_notes_for_the_master_not_story() -> None:
    draft = small_world().draft()
    title = draft.world.scene.title

    assert not any(fact.told for fact in change(ENGINE, draft, "next_scene"))
    assert draft.notes == [WAY_OFFERED]
    draft.notes.clear()
    facts = change(ENGINE, draft, "next_scene", pursuit="To the docks")
    assert [fact.trace for fact in facts if fact.told] == [f"the player leaves {title}"]
    assert draft.notes == [SCENE_LEFT]


def test_harmless_repeats_are_no_ops() -> None:
    draft = small_world().draft()
    _ = change(ENGINE, draft, "drop_item", item_id=LOCKPICKS)
    assert change(ENGINE, draft, "drop_item", item_id=LOCKPICKS) == []


def test_a_take_while_a_job_is_open_amends_its_terms_and_closes_nothing() -> None:
    draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
    world = draft.world
    world.job = "Fly the crate to Kesh"
    world.work_rolled = True
    credits = world.player.require_sheet().credits

    facts = ENGINE.job(draft, Job(verb="take", terms="Fly the crate to Anvil"), Random(0))

    assert world.job == "Fly the crate to Anvil"
    assert [fact.card for fact in facts] == ["New job terms\nFly the crate to Anvil"]
    assert world.work_rolled
    assert not world.raise_owed
    assert world.player.require_sheet().credits == credits
    assert world.cast[KESTREL].require_sheet().skills == {"Shooting": 8}


def _look_again(draft: TwentyFourXXGame) -> list[ActionOption]:
    return [move for move in ENGINE.player_view(draft).moves if move.action_name == "find_again"]


def test_every_find_can_be_looked_again_for_1_credit_until_a_job_is_taken() -> None:
    draft = small_world().draft()
    for seed in (1, 0, 5):
        _ = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(seed))
        (look_again,) = _look_again(draft)
    facts = ENGINE.play_option(draft, look_again, Random(0))
    assert draft.world.player.require_sheet().credits == STARTING_CREDITS - 1
    assert any(fact.trace.endswith("a job, but something seems off") for fact in facts)

    draft.world.player.require_sheet().credits = 0
    assert _look_again(draft) == []
    draft.world.player.require_sheet().credits = 1
    _ = ENGINE.job(draft, Job(verb="take", terms="Fly the crate"), Random(0))
    assert _look_again(draft) == []


def test_find_job_reads_the_three_bands_by_seed() -> None:
    draft = small_world().draft()
    facts = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(1))
    assert facts[1].trace.endswith("nothing")
    assert draft.pending is None

    draft = small_world().draft()
    facts = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(0))
    assert facts[1].trace.endswith("a job, but something seems off")

    draft = small_world().draft()
    facts = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(5))
    assert facts[1].trace.endswith("a choice between two jobs")


def test_finish_is_refused_until_a_roll_has_played_the_work(draft: TwentyFourXXGame) -> None:
    _ = ENGINE.job(draft, Job(verb="find", where="Docks"), Random(0))
    _ = ENGINE.job(draft, Job(verb="take", terms="Move the crates by dawn"), Random(0))
    with pytest.raises(Refusal, match="no roll has played the job's work"):
        _ = ENGINE.job(draft, Job(verb="finish"), Random(0))

    _ = _rolled(draft, Roll(what="Haul the crates", skill="Stealth", risk="a strained back"))
    _ = ENGINE.job(draft, Job(verb="finish"), Random(0))
    assert draft.world.job == ""


def test_a_hindrance_is_sent_only_inside_the_defence_that_causes_it() -> None:
    with pytest.raises(ValidationError, match="hindrance"):
        _ = Roll.model_validate({"what": "Short the lock", "risk": "a burn", "hindrance": "Burned"})


def test_job_validator_needs_the_field_of_its_verb_and_ignores_the_others() -> None:
    with pytest.raises(ValueError, match="find needs where"):
        _ = Job(verb="find", terms="extra")
    with pytest.raises(ValueError, match="take needs terms"):
        _ = Job(verb="take", where="Docks")
    _ = Job(verb="finish", raises=(Raise(actor_id=KESTREL, skill="Stealth"),), terms="agreed")


def test_kill_on_the_player_flips_player_over(draft: TwentyFourXXGame) -> None:
    facts = change(ENGINE, draft, "kill", target_id=PLAYER_ID)
    assert not draft.world.player.alive
    assert draft.pending is None
    assert _decision_after(draft) == "newcomer"
    assert any(fact.card == "You are dead" for fact in facts)


def test_risk_disaster_with_hired_member_sets_succession_and_over_stays_none() -> None:
    draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
    facts = _rolled(
        draft, Roll(what="Slip past", skill="Stealth", risk="a long fall", deadly=True), seed=2
    )
    assert not draft.world.player.alive
    state = ENGINE.record(draft, (), ())
    assert state.pending is not None
    assert state.pending.kind == "succession"
    assert [option.id for option in state.pending.options] == [KESTREL]
    assert ENGINE.ending(state) is None
    assert any(fact.card == "You are dead" for fact in facts)


def test_a_death_with_no_hired_crew_asks_who_joins(draft: TwentyFourXXGame) -> None:
    _ = _rolled(
        draft, Roll(what="Slip past", skill="Stealth", risk="a long fall", deadly=True), seed=2
    )
    assert not draft.world.player.alive
    assert _decision_after(draft) == "newcomer"
    assert ENGINE.ending(draft) is None


def test_a_hired_member_let_go_by_the_master_or_the_player_is_crew_no_more() -> None:
    for let_go in (change, run_action):
        draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
        facts = let_go(ENGINE, draft, "leave_party", target_id=KESTREL)
        assert [(fact.trace, fact.told) for fact in facts] == [
            ("Kestrel[kestrel] is no longer with the crew", True)
        ]
        assert "not the player or a hired party member" in refused(
            ENGINE, draft, "roll", what="Slip past", actor_id=KESTREL, risk="a fall"
        )
        _ = _rolled(draft, Roll(what="Slip past", risk="a long fall", deadly=True), seed=2)
        assert _decision_after(draft) == "newcomer"


def test_a_let_go_member_is_named_so_and_repeat_leaves_do_nothing() -> None:
    draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
    world = draft.world
    _ = change(ENGINE, draft, "leave_party", target_id=KESTREL)
    assert "let go from the crew" in world.here_lines()
    assert "let go from the crew; last seen in" in world.cast_lines()
    assert change(ENGINE, draft, "leave_party", target_id=KESTREL) == []

    _ = change(ENGINE, draft, "kill", target_id=KESTREL)
    assert "let go" not in world.cast_lines()
    assert change(ENGINE, draft, "leave", target_id=KESTREL) == []


def test_enter_files_a_stranger_the_player_names_who_can_then_be_hired(
    draft: TwentyFourXXGame,
) -> None:
    facts = change(ENGINE, draft, "enter", target_id="juno-pell", voice="feminine")
    assert draft.world.cast["juno-pell"].name == "Juno Pell"
    assert draft.world.cast["juno-pell"].voice == "feminine"
    assert any(fact.card == "Juno Pell arrives" for fact in facts)

    _ = change(ENGINE, draft, "join_party", target_id="juno", terms="Watch my back")
    assert draft.request is not None
    assert draft.request.target_id == "juno-pell"


def test_the_master_hires_a_stranger_the_story_just_brought_in(draft: TwentyFourXXGame) -> None:
    facts = change(ENGINE, draft, "join_party", target_id="tug-driver", terms="Drive the tanker")
    driver = draft.world.cast["tug-driver"]
    assert driver.name == "Tug Driver"
    assert driver.known
    assert any(fact.card == "Tug Driver arrives" for fact in facts)
    assert draft.request is not None
    assert draft.request.target_id == "tug-driver"


def test_answering_the_succession_decision_makes_the_member_the_player() -> None:
    draft = hired(small_world(), KESTREL, skills={"Shooting": 8}).draft()
    _ = _rolled(
        draft, Roll(what="Slip past", skill="Stealth", risk="a long fall", deadly=True), seed=2
    )
    state = ENGINE.record(draft, (), ())
    assert state.pending is not None
    option = state.pending.options[0]
    draft = state.draft()
    draft.pending = None
    facts = ENGINE.play_option(draft, option, Random(0))
    assert draft.world.player.name == "Kestrel"
    assert any(fact.card == "Kestrel leads now" for fact in facts)


def test_a_ship_function_takes_several_named_upgrades_at_10_each(draft: TwentyFourXXGame) -> None:
    draft.world.dock_here()
    player = draft.world.player
    player.require_sheet().credits = UPGRADE_COST * 2 + 1
    facts = change(ENGINE, draft, "ship_upgrade", function_id="sensors", upgrade="Deep scanner")
    assert any(fact.card == "Sensors upgraded: Deep scanner — ₡10" for fact in facts)
    _ = change(ENGINE, draft, "ship_upgrade", function_id="sensors", upgrade="Cloak sniffer")

    assert player.require_sheet().credits == 1
    assert draft.world.ship["sensors"].upgrades == ["Deep scanner", "Cloak sniffer"]
    ship = dict(ENGINE.master_sections(draft))["THE SHIP"]
    assert "upgraded: Deep scanner, upgraded: Cloak sniffer" in ship
    refusal = refused(ENGINE, draft, "ship_upgrade", function_id="sensors", upgrade="Ion sail")
    assert "only ₡1" in refusal


def test_next_scene_with_a_pursuit_requests_the_crossing(draft: TwentyFourXXGame) -> None:
    _ = ENGINE.next_scene(draft, NextScene(pursuit="Down the stair."), Random(0))

    assert draft.request is not None
    assert draft.request.detail == "Down the stair."


@pytest.mark.parametrize(
    ("seed", "band"), [(2, "trouble"), (7, "signs of trouble"), (5, "no trouble")]
)
def test_a_complication_is_a_bad_luck_test_and_only_trouble_asks_the_worldsmith(
    draft: TwentyFourXXGame, seed: int, band: str
) -> None:
    raid = NextScene(complication="A customs raid, tipped off by Sable.")

    facts = ENGINE.next_scene(draft, raid, Random(seed))

    assert [fact.card for fact in facts if fact.told] == [f"Bad luck — d6 → {band}"]
    assert (draft.request is not None) == (band == "trouble")


def test_only_what_is_hidden_here_can_be_revealed(draft: TwentyFourXXGame) -> None:
    assert "not hidden here" in refused(ENGINE, draft, "reveal", target_id=KESTREL)


def test_the_hold_passes_an_item_from_the_player_to_a_hired_member() -> None:
    draft = hired(small_world(), KESTREL, skills={}).draft()
    world = draft.world
    world.dock_here()
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
        if option.action_name in {"stow_item", "retrieve_item"}
    ]
    assert {option.action_name for option in options} == {"stow_item", "retrieve_item"}
    assert all(option.refusal == SHIP_AWAY for option in options)


def test_lose_hold_item_tells_the_loss_and_empties_the_slot(draft: TwentyFourXXGame) -> None:
    draft.world.hold["crate"] = Gear(name="Crate")
    facts = change(ENGINE, draft, "lose_hold_item", item_id="crate", why="a dock raid")
    assert [fact.told for fact in facts] == [True]
    assert "crate" not in draft.world.hold
