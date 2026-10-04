from random import Random
from typing import Literal

import pytest
from pydantic import BaseModel
from support.pokemon import ENGINE, started
from support.showdown import WILD_SETUP, ScriptedSimulator
from support.showdown import started as simulator_started
from support.table import change, refused

from rulehall.core.game import Check
from rulehall.core.prompt import Prompt
from rulehall.engines.pokemon.battle.models import Battle, BattleResult, BattleSetup
from rulehall.engines.pokemon.battle.simulator import end_battle
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.sheet import Mon, Trainer
from rulehall.engines.pokemon.world import PokemonGame
from rulehall.engines.rooms.world import OFF_MAP_ID
from rulehall.engines.sheet import Gauge


async def test_a_wild_battle_gets_no_model_opponent() -> None:
    draft = started().draft()
    draft.world.battle = Battle(setup=WILD_SETUP)
    simulator = ScriptedSimulator(simulator_started(WILD_SETUP))

    run = await ENGINE.open_battle(draft, simulator, _unasked)

    assert run.opponent is None


def test_every_able_team_pokemon_gets_the_full_share() -> None:
    draft = started().draft()
    sheet = draft.world.player_sheet
    benched = Mon.new("squirtle", 12, Random(0), sheet.mon_ids())
    fainted = Mon.new("bulbasaur", 12, Random(1), [*sheet.mon_ids(), benched.mon_id])
    fainted.hp.current = 0
    sheet.team.extend((benched, fainted))
    charmander = sheet.require_mon("charmander")
    charmander.level, charmander.exp = 12, 12**3
    setup = _wild(draft)

    _ = end_battle(draft, _won(setup))

    total = 20 * setup.foes[0].level
    assert charmander.exp == 12**3 + total
    assert benched.exp == 12**3 + total
    assert fainted.exp == 12**3


def test_exp_doubles_below_the_table_level() -> None:
    draft = started().draft()
    charmander = draft.world.player_sheet.require_mon("charmander")
    setup = _wild(draft)

    _ = end_battle(draft, _won(setup))

    assert charmander.exp == 125 + 2 * 20 * setup.foes[0].level


def test_a_catch_gives_exp_but_not_to_the_caught_pokemon() -> None:
    draft = started().draft()
    sheet = draft.world.player_sheet
    charmander = sheet.require_mon("charmander")
    setup = _wild(draft)
    foe = setup.foes[0]
    result = BattleResult(
        outcome="caught",
        team=setup.team,
        sent_out_foes=(),
        on_field_mon_ids=(setup.team[0].mon_id,),
        caught=foe,
    )

    _ = end_battle(draft, result)

    caught = sheet.require_mon(foe.mon_id)
    assert charmander.exp == 125 + 2 * 20 * foe.level
    assert charmander.evs == dex().species[foe.species_id].ev_yield
    assert caught.exp == foe.level**3


def test_a_level_up_raises_max_hp_by_the_formula() -> None:
    draft = started().draft()
    charmander = draft.world.player_sheet.require_mon("charmander")
    charmander.exp = 215
    before = charmander.hp.maximum
    setup = _wild(draft)
    hurt = setup.team[0].model_copy(update={"hp": 15})

    _ = end_battle(draft, _won(setup).model_copy(update={"team": (hurt,)}))

    maximum = charmander.stats()[0]
    assert charmander.level == 6
    assert charmander.hp == Gauge(current=15 + maximum - before, maximum=maximum)
    assert charmander.friendship == 75


def test_a_trainer_win_pays_fifty_per_highest_foe_level_and_marks_the_trainer_beaten() -> None:
    draft = started().draft()

    _ = end_battle(draft, _won(_trainer_battle(draft)))

    assert draft.world.player_sheet.money == 3000 + 50 * 4
    rook = draft.world.npcs["rook"]
    assert rook.beaten
    assert rook.last_battle_visit == len(draft.world.visited_place_ids)
    assert draft.world.battle is None
    assert "already battled you on this visit" in refused(
        ENGINE, draft, "start_battle", trainer_id="rook"
    )


def test_a_new_visit_lets_the_trainer_battle_again_with_the_same_team() -> None:
    draft = started().draft()
    first = _trainer_battle(draft)
    _ = end_battle(draft, _won(first))
    _ = draft.world.move("tern-harbour", ())
    _ = draft.world.move("harbour-road", ())

    again = _trainer_battle(draft)

    assert [(foe.mon_id, foe.nature, foe.moves) for foe in again.foes] == [
        (foe.mon_id, foe.nature, foe.moves) for foe in first.foes
    ]
    _ = end_battle(draft, _won(again))
    assert draft.world.player_sheet.money == 3000 + 50 * 4
    assert draft.world.npcs["rook"].beaten


def test_a_gym_leader_never_rematches() -> None:
    draft = started().draft()
    rook = draft.world.npcs["rook"]
    rook.badge = "Tide Badge"
    rook.beaten = True
    _ = draft.world.move("tern-harbour", ())
    _ = draft.world.move("harbour-road", ())

    assert "gives no rematch" in refused(ENGINE, draft, "start_battle", trainer_id="rook")


def test_a_gym_leader_battles_with_a_team_built_for_it_ace_last() -> None:
    draft = started().draft()
    ines = _ines_here(draft)

    setup = _trainer_battle(draft, "ines")

    assert setup.policy == "model"
    assert [(foe.species_id, foe.level, foe.item_id) for foe in setup.foes] == [
        ("horsea", 11, None),
        ("staryu", 12, None),
    ]
    assert all(foe.ivs == (15,) * 6 for foe in setup.foes)
    assert not ines.team


def test_the_facts_name_the_built_team_and_only_the_foes_that_were_sent_out() -> None:
    draft = started().draft()
    _ = _ines_here(draft)

    challenge = change(ENGINE, draft, "start_battle", trainer_id="ines")
    assert draft.world.battle is not None
    setup = draft.world.battle.setup
    horsea = setup.foes[0].model_copy(update={"hp": 0})
    lost = BattleResult(
        outcome="lost", team=setup.team, sent_out_foes=(horsea,), on_field_mon_ids=()
    )
    settled = end_battle(draft, lost).facts

    assert all(foe.species_name in challenge[0].trace for foe in setup.foes)
    told = " ".join(fact.trace for fact in settled if fact.told)
    assert "Horsea" in told
    assert "Staryu" not in told


def test_a_legendary_here_battles_alone_as_a_wild_pokemon_at_the_table_level() -> None:
    draft = started().draft()
    _ = _zapdos_here(draft)

    assert "battles alone" in refused(ENGINE, draft, "start_battle", trainer_id="zapdos", tag=True)
    setup = _trainer_battle(draft, "zapdos")

    assert setup.wild
    assert [(foe.species_id, foe.level) for foe in setup.foes] == [("zapdos", 12)]
    assert setup.balls


@pytest.mark.parametrize("outcome", ["won", "caught", "fled"])
def test_a_beaten_or_caught_legendary_is_gone_and_a_fled_one_stays(
    outcome: Literal["won", "caught", "fled"],
) -> None:
    draft = started().draft()
    _ = _zapdos_here(draft)
    setup = _trainer_battle(draft, "zapdos")
    foe = setup.foes[0]
    result = BattleResult(
        outcome=outcome,
        team=setup.team,
        sent_out_foes=(foe.model_copy(update={"hp": 0}),) if outcome == "won" else (),
        on_field_mon_ids=(setup.team[0].mon_id,),
        caught=foe if outcome == "caught" else None,
    )

    here = draft.world.current.id

    _ = end_battle(draft, result)

    zapdos = draft.world.npcs["zapdos"]
    gone = outcome != "fled"
    assert (zapdos.place_id == OFF_MAP_ID, zapdos.beaten) == (gone, gone)
    if not gone:
        assert zapdos.place_id == here
        assert "already battled you on this visit" in refused(
            ENGINE, draft, "start_battle", trainer_id="zapdos"
        )


def test_a_nuzlocke_legendary_is_always_catchable_and_keeps_the_first_encounter() -> None:
    draft = started().draft()
    draft.world.player_sheet.challenge = "nuzlocke"
    here = draft.world.current.id
    _ = _zapdos_here(draft)

    assert _fled(draft, _trainer_battle(draft, "zapdos")).balls
    assert _fled(draft, _rolled_wild(draft)).balls
    _ = change(ENGINE, draft, "move", to_id="tern-harbour")
    _ = change(ENGINE, draft, "move", to_id=here)
    assert _trainer_battle(draft, "zapdos").balls


def test_the_rival_leaves_the_map_after_a_battle_until_the_next_badge() -> None:
    draft = started().draft()
    rival = draft.world.npcs["tamsin"]
    rival.place_id = draft.world.current.id
    rival.known = True

    resolution = end_battle(draft, _won(_trainer_battle(draft, "tamsin")))

    assert rival.place_id == OFF_MAP_ID
    assert f"{rival.name} leaves" in [fact.card for fact in resolution.facts]
    _ = _ines_here(draft)
    _ = end_battle(draft, _won(_trainer_battle(draft, "ines")))
    _ = change(ENGINE, draft, "move", to_id="tern-harbour")
    assert rival.place_id == "tern-harbour"


def test_after_a_badge_the_next_move_places_the_rival_and_notes_it() -> None:
    draft = started().draft()
    _ = _ines_here(draft)
    _ = end_battle(draft, _won(_trainer_battle(draft, "ines")))

    _ = change(ENGINE, draft, "move", to_id="tern-harbour")

    assert draft.world.npcs["tamsin"].place_id == "tern-harbour"
    assert draft.notes[-1].startswith("Your rival Tamsin waits here to battle.")
    assert not draft.world.rival_record.due


def test_a_blackout_halves_the_money_and_heals_the_team() -> None:
    draft = started().draft()
    setup = _wild(draft)
    fainted = setup.team[0].model_copy(update={"hp": 0})

    _ = end_battle(
        draft, BattleResult(outcome="lost", team=(fainted,), sent_out_foes=(), on_field_mon_ids=())
    )

    sheet = draft.world.player_sheet
    charmander = sheet.require_mon("charmander")
    assert sheet.money == 1500
    assert charmander.hp.current == charmander.hp.maximum


def test_a_won_battle_does_not_black_out_when_the_players_team_has_fainted() -> None:
    draft = started().draft()
    setup = _wild(draft)
    fainted = setup.team[0].model_copy(update={"hp": 0})
    won = _won(setup).model_copy(update={"team": (fainted,)})

    _ = end_battle(draft, won)

    assert draft.world.player_sheet.money == 3000


def test_exp_stops_at_the_level_cap_and_a_rare_candy_is_refused_there() -> None:
    draft = started().draft()
    sheet = draft.world.player_sheet
    sheet.challenge = "hard"
    charmander = sheet.require_mon("charmander")
    charmander.level, charmander.exp = 11, 11**3
    setup = _wild(draft)
    strong = setup.foes[0].model_copy(update={"level": 50, "hp": 0})

    _ = end_battle(draft, _won(setup).model_copy(update={"sent_out_foes": (strong,)}))

    assert (charmander.level, charmander.exp) == (12, 12**3)
    _ = change(ENGINE, draft, "gain_item", item_id="rare-candy")
    assert refused(ENGINE, draft, "use_item", item_id="rare-candy", mon_id="charmander") == (
        "Charmander is at the level cap (L12)"
    )


def test_a_nuzlocke_buries_a_fainted_pokemon_and_a_wipe_ends_the_journey() -> None:
    draft = started().draft()
    sheet = draft.world.player_sheet
    sheet.challenge = "nuzlocke"
    squirtle = Mon.new("squirtle", 5, Random(0), sheet.mon_ids())
    squirtle.nickname = "Shelly"
    sheet.team.append(squirtle)
    setup = _trainer_battle(draft)
    fallen = setup.team[1].model_copy(update={"hp": 0})

    _ = end_battle(draft, _won(setup).model_copy(update={"team": (setup.team[0], fallen)}))

    assert sheet.mon_ids() == ["charmander"]
    assert sheet.memorial == ["Shelly the Squirtle, fell to Rook"]
    assert ENGINE.ending(draft) is None
    wild = _rolled_wild(draft)
    wiped = wild.team[0].model_copy(update={"hp": 0})
    _ = end_battle(
        draft, BattleResult(outcome="lost", team=(wiped,), sent_out_foes=(), on_field_mon_ids=())
    )
    assert sheet.mon_ids() == ["charmander"]
    assert ENGINE.ending(draft) == "Your whole team has fallen. The journey ends."


def test_a_nuzlocke_offers_balls_only_at_the_first_wild_battle_of_a_place() -> None:
    draft = started().draft()
    draft.world.player_sheet.challenge = "nuzlocke"
    first = _rolled_wild(draft)
    assert first.balls
    _ = end_battle(
        draft, BattleResult(outcome="fled", team=first.team, sent_out_foes=(), on_field_mon_ids=())
    )

    assert _rolled_wild(draft).balls == ()


def test_an_edge_won_in_a_check_reaches_the_next_battle_here_and_a_move_clears_it() -> None:
    draft = started().draft()
    ambush = {"what": "Sneak up", "skill": "stealth", "difficulty": "easy", "edge": "foe-asleep"}
    _ = change(ENGINE, draft, "check", **ambush)

    _ = change(ENGINE, draft, "start_wild_battle", species_id="pidgey", weather="rain")

    assert draft.world.battle is not None
    setup = draft.world.battle.setup
    assert (setup.edge, setup.weather, setup.terrain) == ("foe-asleep", "rain", None)
    assert draft.world.pending_edge is None
    draft.world.battle = None
    _ = change(ENGINE, draft, "check", **ambush)
    _ = change(ENGINE, draft, "move", to_id="tern-harbour")
    assert draft.world.pending_edge is None
    bait = {**ambush, "edge": "bait"}
    assert "no wild Pokemon to bait" in refused(ENGINE, draft, "check", **bait)


def _wild(draft: PokemonGame) -> BattleSetup:
    _ = change(ENGINE, draft, "start_wild_battle", species_id="pidgey")
    assert draft.world.battle is not None
    return draft.world.battle.setup


def _rolled_wild(draft: PokemonGame) -> BattleSetup:
    _ = change(ENGINE, draft, "start_wild_battle")
    assert draft.world.battle is not None
    return draft.world.battle.setup


def _trainer_battle(draft: PokemonGame, trainer_id: str = "rook") -> BattleSetup:
    _ = change(ENGINE, draft, "start_battle", trainer_id=trainer_id)
    assert draft.world.battle is not None
    return draft.world.battle.setup


def _ines_here(draft: PokemonGame) -> Trainer:
    ines = draft.world.npcs["ines"]
    ines.place_id = draft.world.current.id
    ines.known = True
    return ines


def _zapdos_here(draft: PokemonGame) -> Trainer:
    mira = draft.world.npcs["mira"]
    zapdos = Trainer(
        id="zapdos",
        name="Zapdos",
        brief="A storm bird over the cliffs.",
        voice=mira.voice,
        known=True,
        place_id=draft.world.current.id,
        avatar_id=mira.avatar_id,
        legendary_id="zapdos",
    )
    draft.world.npcs[zapdos.id] = zapdos
    return zapdos


def _fled(draft: PokemonGame, setup: BattleSetup) -> BattleSetup:
    _ = end_battle(
        draft, BattleResult(outcome="fled", team=setup.team, sent_out_foes=(), on_field_mon_ids=())
    )
    return setup


def _won(setup: BattleSetup) -> BattleResult:
    return BattleResult(
        outcome="won",
        team=setup.team,
        sent_out_foes=tuple(foe.model_copy(update={"hp": 0}) for foe in setup.foes),
        on_field_mon_ids=(setup.team[0].mon_id,),
    )


async def _unasked[M: BaseModel](_prompt: Prompt, _model: type[M], _check: Check[M], /) -> M:
    raise AssertionError("a wild Pokemon asked the model")
