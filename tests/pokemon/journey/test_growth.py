from random import Random

import pytest
from support.journey import ENGINE, started
from support.table import change, run_action

from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.battle.models import BattleResult
from rulehall.engines.pokemon.battle.simulator import end_battle
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.journey.panels import pending_decision
from rulehall.engines.pokemon.journey.sheet import Mon
from rulehall.engines.pokemon.journey.world import JourneyGame


def test_a_new_move_is_learned_at_once_below_four_moves() -> None:
    draft = started().draft()
    charmander = _charmander(draft, level=7)

    _win_wild(draft)

    assert charmander.level == 8
    assert [slot.move_id for slot in charmander.moves][-1] == "smokescreen"
    assert charmander.moves[-1].pp == dex().moves["smokescreen"].pp
    assert pending_decision(draft.world.player_sheet) is None


def test_a_fifth_move_waits_on_a_decision_and_the_answer_replaces_a_move() -> None:
    draft = started().draft()
    charmander = _charmander(draft, level=11)
    charmander.learn("smokescreen")

    _win_wild(draft)

    decision = pending_decision(draft.world.player_sheet)
    assert decision is not None
    assert decision.kind == "new-move"
    assert [option.id for option in decision.options] == [
        *(slot.move_id for slot in charmander.moves),
        "skip",
    ]
    _ = ENGINE.play_option(draft, _option(draft, "smokescreen"), Random(0))
    assert [slot.move_id for slot in charmander.moves] == [
        "growl",
        "scratch",
        "ember",
        "dragonbreath",
    ]
    assert draft.world.player_sheet.learning == []
    assert pending_decision(draft.world.player_sheet) is None


def test_a_pokemon_at_its_evolution_level_evolves_after_the_battle() -> None:
    draft = started().draft()
    charmander = _charmander(draft, level=15)

    _win_wild(draft)

    assert charmander.level == 16
    assert charmander.species_id == "charmeleon"
    assert charmander.hp.maximum == charmander.stats()[0]


def test_an_everstone_stops_evolution_by_level_until_it_is_taken() -> None:
    draft = started().draft()
    charmander = _charmander(draft, level=15)
    _ = change(ENGINE, draft, "gain_item", item_id="everstone")
    _ = run_action(ENGINE, draft, "hold_item", mon_id="charmander", item_id="everstone")

    _win_wild(draft)

    assert charmander.level == 16
    assert charmander.species_id == "charmander"
    _ = run_action(ENGINE, draft, "hold_item", mon_id="charmander", item_id=None)
    assert charmander.item_id is None
    assert draft.world.player_sheet.bag["everstone"] == 1


def test_evs_grow_from_each_fainted_foe_up_to_the_caps() -> None:
    draft = started().draft()
    charmander = draft.world.player_sheet.require_mon("charmander")

    _win_wild(draft)

    assert charmander.evs == dex().species["pidgey"].ev_yield
    charmander.evs = (250, 0, 0, 0, 252, 4)
    charmander.train(
        Mon.new(species_id, 50, Random(0), ()).battler() for species_id in ("snorlax", "mewtwo")
    )
    assert charmander.evs == (252, 0, 0, 2, 252, 4)


def test_a_new_badge_opens_a_skill_rank_decision() -> None:
    draft = started().draft()
    draft.world.npcs["rook"].badge = "Tide Badge"
    _ = change(ENGINE, draft, "start_battle", trainer_id="rook")
    assert draft.world.battle is not None
    sheet = draft.world.player_sheet
    lore = sheet.skills.get("lore", 0)

    _ = end_battle(draft, _won(draft))

    assert sheet.badges == ["Tide Badge"]
    decision = pending_decision(draft.world.player_sheet)
    assert decision is not None
    assert decision.kind == "badge-rank"
    _ = ENGINE.play_option(draft, _option(draft, "lore"), Random(0))
    assert sheet.skills["lore"] == lore + 1
    assert draft.world.player_sheet.ranks_due == 0
    assert pending_decision(draft.world.player_sheet) is None


def test_a_tool_that_decides_nothing_keeps_an_open_badge_rank_decision() -> None:
    draft = started().draft()
    draft.world.player_sheet.ranks_due = 1
    opened = ENGINE.accept(draft)
    assert opened.pending is not None
    assert opened.pending.kind == "badge-rank"

    draft = opened.draft()
    _ = change(ENGINE, draft, "gain_money", amount=1)

    assert ENGINE.accept(draft).pending == opened.pending


def test_a_remembered_move_learns_at_once_or_opens_the_decision() -> None:
    draft = started().draft()
    charmander = _charmander(draft, level=12)
    assert charmander.relearnable() == ("smokescreen", "dragonbreath")

    _ = run_action(ENGINE, draft, "relearn_move", mon_id="charmander", move_id="smokescreen")
    assert [slot.move_id for slot in charmander.moves][-1] == "smokescreen"
    assert pending_decision(draft.world.player_sheet) is None

    _ = run_action(ENGINE, draft, "relearn_move", mon_id="charmander", move_id="dragonbreath")
    decision = pending_decision(draft.world.player_sheet)
    assert decision is not None and decision.kind == "new-move"
    with pytest.raises(Refusal, match="Charmander cannot remember 'flamethrower'"):
        _ = run_action(ENGINE, draft, "relearn_move", mon_id="charmander", move_id="flamethrower")


def _charmander(draft: JourneyGame, *, level: int) -> Mon:
    charmander = draft.world.player_sheet.require_mon("charmander")
    charmander.level = level
    charmander.exp = (level + 1) ** 3 - 1
    return charmander


def _win_wild(draft: JourneyGame) -> None:
    _ = change(ENGINE, draft, "start_wild_battle", species_id="pidgey")
    _ = end_battle(draft, _won(draft))


def _won(draft: JourneyGame) -> BattleResult:
    assert draft.world.battle is not None
    setup = draft.world.battle.setup
    return BattleResult(
        outcome="won",
        team=setup.team,
        sent_out_foes=tuple(foe.model_copy(update={"hp": 0}) for foe in setup.foes),
        on_field_mon_ids=(setup.team[0].mon_id,),
    )


def _option(draft: JourneyGame, option_id: str) -> ActionOption:
    decision = pending_decision(draft.world.player_sheet)
    assert decision is not None
    return next(option for option in decision.options if option.id == option_id)
