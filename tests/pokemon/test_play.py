from pathlib import Path
from random import Random

import pytest
from support.pokemon import ENGINE, started
from support.table import POKEMON, change, open_table, play_turn, refused, run_action

from rulehall.core.decisions import PlayerInput
from rulehall.core.facts import Fact
from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.battle.models import BattleResult
from rulehall.engines.pokemon.battle.simulator import end_battle
from rulehall.engines.pokemon.panels import wild_panel
from rulehall.engines.pokemon.sheet import Evolving, Learning
from rulehall.engines.pokemon.world import PokemonGame
from rulehall.engines.rooms.world import OFF_MAP_ID


def test_the_rival_blocks_every_way_but_the_way_back() -> None:
    draft = started().draft()
    world = draft.world
    rival = world.npcs["tamsin"]
    rival.place_id = OFF_MAP_ID
    _ = change(ENGINE, draft, "move", to_id="tern-harbour")
    rival.place_id = world.current.id

    refusal = refused(ENGINE, draft, "move", to_id="tern-gym")

    assert "Tamsin" in refusal
    assert world.places["harbour-road"].name in refusal
    _ = change(ENGINE, draft, "move", to_id="harbour-road")
    assert world.current.id == "harbour-road"


def test_the_rival_at_the_opening_blocks_every_way_until_the_battle() -> None:
    draft = started().draft()
    world = draft.world
    assert world.npcs["tamsin"].place_id == world.current.id

    assert "there is no way back yet" in refused(ENGINE, draft, "move", to_id="tern-harbour")

    _ = change(ENGINE, draft, "start_battle", trainer_id="tamsin")
    assert world.battle is not None
    setup = world.battle.setup
    lost = BattleResult(outcome="lost", team=setup.team, sent_out_foes=(), on_field_mon_ids=())
    _ = end_battle(draft, lost)
    _ = change(ENGINE, draft, "move", to_id="tern-harbour")
    assert world.current.id == "tern-harbour"


def test_the_wild_panel_battles_a_picked_species_or_a_rolled_one() -> None:
    draft = started().draft()
    panel = wild_panel(draft.world)
    assert panel is not None
    options = list(panel.options())
    assert [option.id for option in options] == [
        "wild-pidgey",
        "wild-rattata",
        "wild-caterpie",
        "wild-bellsprout",
        "wild-search",
    ]

    _ = ENGINE.play_option(draft, options[0], Random(0))
    assert draft.world.battle is not None
    assert draft.world.battle.setup.foes[0].species_id == "pidgey"

    rolled = started().draft()
    _ = run_action(ENGINE, rolled, "battle_wild")
    assert rolled.world.battle is not None


def test_a_nuzlocke_refuses_a_picked_species_but_rolls() -> None:
    draft = started().draft()
    draft.world.player_sheet.challenge = "nuzlocke"
    panel = wild_panel(draft.world)
    assert panel is not None
    *picks, search = panel.options()

    assert all(option.refusal for option in picks)
    with pytest.raises(Refusal):
        _ = ENGINE.play_option(draft, picks[0], Random(0))
    _ = ENGINE.play_option(draft, search, Random(0))
    assert draft.world.battle is not None


def test_no_wild_panel_in_a_place_without_a_wild_table() -> None:
    draft = started().draft()
    draft.world.npcs["tamsin"].place_id = OFF_MAP_ID
    _ = change(ENGINE, draft, "move", to_id="tern-harbour")

    assert wild_panel(draft.world) is None


async def test_a_new_move_and_a_skill_rank_resolve_with_no_role(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame)
    draft = table.state.draft()
    sheet = draft.world.player_sheet
    sheet.learning.append(Learning(mon_id="charmander", move_id="smokescreen"))
    sheet.ranks_due = 1
    table.session.save(ENGINE.accept(draft))

    await table.session.choose(PlayerInput(option_id="skip"))
    assert table.state.pending is not None
    assert table.state.pending.kind == "badge-rank"
    await table.session.choose(PlayerInput(option_id=table.state.pending.options[0].id))

    assert table.state.pending is None
    assert table.state.world.player_sheet.ranks_due == 0
    assert table.roles.prompts == []


async def test_a_silent_decision_after_an_interrupted_turn_narrates_the_held_facts(
    tmp_path: Path,
) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame)
    draft = table.state.draft()
    draft.world.player_sheet.learning.append(Learning(mon_id="charmander", move_id="smokescreen"))
    draft.unnarrated = [Fact(trace="Charmander grows to level 13.", told=True)]
    table.session.save(ENGINE.accept(draft))

    _ = await play_turn(table, PlayerInput(option_id="skip"))

    assert table.state.pending is None
    assert table.state.unnarrated == []
    assert [role for role, _ in table.roles.prompts] == ["master", "narrator"]


async def test_an_evolution_still_plays_a_turn(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=POKEMON, state_type=PokemonGame)
    draft = table.state.draft()
    sheet = draft.world.player_sheet
    sheet.evolving.append(Evolving(mon_id="charmander", species_ids=("charmeleon", "charizard")))
    table.session.save(ENGINE.accept(draft))

    _ = await play_turn(table, PlayerInput(option_id="charmeleon"))

    assert table.state.world.player_sheet.require_mon("charmander").species_id == "charmeleon"
    assert [role for role, _ in table.roles.prompts] == ["master", "narrator"]
