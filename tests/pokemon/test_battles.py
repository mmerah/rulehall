from random import Random

from pydantic import BaseModel
from support.pokemon import ENGINE, started
from support.showdown import WILD_SETUP, ScriptedSimulator
from support.showdown import started as simulator_started
from support.table import change, refused

from rulehall.core.model import Check
from rulehall.core.prompt import Prompt
from rulehall.engines.entities import Gauge
from rulehall.engines.pokemon.battle.models import Battle, BattleResult, BattleSetup
from rulehall.engines.pokemon.world import Mon, PokemonGame


async def test_a_wild_battle_gets_no_model_opponent() -> None:
    draft = started().draft()
    draft.world.battle = Battle(setup=WILD_SETUP)
    simulator = ScriptedSimulator(simulator_started(WILD_SETUP))

    run = await ENGINE.open_battle(draft, simulator, _unasked)

    assert run.opponent is None


def test_exp_goes_whole_to_the_field_and_half_to_the_bench() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    sheet.team.append(Mon.new("squirtle", 5, Random(0), sheet.mon_ids()))
    setup = _wild(draft)

    _ = ENGINE.end_battle(draft, _won(setup))

    total = 20 * setup.foes[0].level
    assert sheet.require_mon("charmander").exp == 125 + total
    assert sheet.require_mon("squirtle").exp == 125 + total // 2


def test_a_level_up_raises_max_hp_by_the_formula() -> None:
    draft = started().draft()
    charmander = draft.world.player.require_sheet().require_mon("charmander")
    charmander.exp = 215
    before = charmander.hp.maximum
    setup = _wild(draft)
    hurt = setup.team[0].model_copy(update={"hp": 15})

    _ = ENGINE.end_battle(draft, _won(setup).model_copy(update={"team": (hurt,)}))

    maximum = charmander.stats()[0]
    assert charmander.level == 6
    assert charmander.hp == Gauge(current=15 + maximum - before, maximum=maximum)
    assert charmander.friendship == 75


def test_a_trainer_win_pays_fifty_per_highest_foe_level_and_marks_the_trainer_beaten() -> None:
    draft = started().draft()

    _ = ENGINE.end_battle(draft, _won(_trainer_battle(draft)))

    assert draft.world.player.require_sheet().money == 3000 + 50 * 4
    rook = draft.world.npcs["rook"]
    assert rook.beaten
    assert rook.last_battle_visit == len(draft.world.visits)
    assert draft.world.battle is None
    assert "already battled you on this visit" in refused(
        ENGINE, draft, "start_battle", trainer_id="rook"
    )


def test_a_new_visit_lets_the_trainer_battle_again_with_the_same_team() -> None:
    draft = started().draft()
    first = _trainer_battle(draft)
    _ = ENGINE.end_battle(draft, _won(first))
    _ = draft.world.move("tern-harbour", ())
    _ = draft.world.move("harbour-road", ())

    again = _trainer_battle(draft)

    assert [(foe.mon_id, foe.nature, foe.moves) for foe in again.foes] == [
        (foe.mon_id, foe.nature, foe.moves) for foe in first.foes
    ]
    _ = ENGINE.end_battle(draft, _won(again))
    assert draft.world.player.require_sheet().money == 3000 + 50 * 4
    assert draft.world.npcs["rook"].beaten


def test_a_gym_leader_never_rematches() -> None:
    draft = started().draft()
    rook = draft.world.npcs["rook"]
    rook.badge = "Tide Badge"
    rook.beaten = True
    _ = draft.world.move("tern-harbour", ())
    _ = draft.world.move("harbour-road", ())

    assert "gives no rematch" in refused(ENGINE, draft, "start_battle", trainer_id="rook")


def test_a_blackout_halves_the_money_and_heals_the_team() -> None:
    draft = started().draft()
    setup = _wild(draft)
    fainted = setup.team[0].model_copy(update={"hp": 0})

    _ = ENGINE.end_battle(
        draft, BattleResult(outcome="lost", team=(fainted,), fainted_foes=(), on_field=())
    )

    sheet = draft.world.player.require_sheet()
    charmander = sheet.require_mon("charmander")
    assert sheet.money == 1500
    assert charmander.hp.current == charmander.hp.maximum


def _wild(draft: PokemonGame) -> BattleSetup:
    _ = change(ENGINE, draft, "start_wild_battle", species_id="pidgey")
    assert draft.world.battle is not None
    return draft.world.battle.setup


def _trainer_battle(draft: PokemonGame) -> BattleSetup:
    _ = change(ENGINE, draft, "start_battle", trainer_id="rook")
    assert draft.world.battle is not None
    return draft.world.battle.setup


def _won(setup: BattleSetup) -> BattleResult:
    return BattleResult(
        outcome="won",
        team=setup.team,
        fainted_foes=setup.foes,
        on_field=(setup.team[0].mon_id,),
    )


async def _unasked[M: BaseModel](_prompt: Prompt, _model: type[M], _check: Check[M], /) -> M:
    raise AssertionError("a wild Pokemon asked the model")
