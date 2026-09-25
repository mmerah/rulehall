from random import Random

import pytest
from support.pokemon import ENGINE, started
from support.table import change, refused, run_action

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.rules import START_BAG
from rulehall.engines.pokemon.world import Mon


def test_a_tm_teaches_its_move_and_stays_in_the_bag() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    charmander = sheet.require_mon("charmander")
    assert len(charmander.moves) == 3
    _ = change(ENGINE, draft, "gain_item", item_id="tm-flamethrower")
    _ = change(ENGINE, draft, "gain_item", item_id="tm-surf")

    _ = run_action(ENGINE, draft, "teach_move", mon_id="charmander", item_id="tm-flamethrower")

    assert charmander.moves[-1].move_id == "flamethrower"
    assert sheet.bag["tm-flamethrower"] == 1
    with pytest.raises(Refusal, match="Charmander cannot learn Surf from a TM now"):
        _ = run_action(ENGINE, draft, "teach_move", mon_id="charmander", item_id="tm-surf")


def test_a_stone_or_the_linking_cord_evolves_the_pokemon_it_fits() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    pikachu = Mon.new("pikachu", 20, Random(0), sheet.mon_ids())
    kadabra = Mon.new("kadabra", 20, Random(0), [*sheet.mon_ids(), pikachu.mon_id])
    _ = sheet.receive(pikachu)
    _ = sheet.receive(kadabra)
    for item_id in ("fire-stone", "thunder-stone", "linking-cord"):
        _ = change(ENGINE, draft, "gain_item", item_id=item_id)

    assert (
        refused(ENGINE, draft, "use_item", item_id="fire-stone", mon_id=pikachu.mon_id)
        == "Fire Stone does not evolve Pikachu"
    )
    _ = change(ENGINE, draft, "use_item", item_id="thunder-stone", mon_id=pikachu.mon_id)
    _ = change(ENGINE, draft, "use_item", item_id="linking-cord", mon_id=kadabra.mon_id)

    assert pikachu.species_id == "raichu"
    assert kadabra.species_id == "alakazam"
    assert sheet.bag == {**START_BAG, "fire-stone": 1}


def test_a_box_row_swaps_with_any_team_pokemon() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    pidgey = Mon.new("pidgey", 5, Random(0), sheet.mon_ids())
    pidgey.hp.current = 0
    sheet.box.append(pidgey)
    sheet.require_mon("charmander").hp.current = 1
    state = ENGINE.accept(draft)
    (box,) = (panel for panel in ENGINE.player_view(state).panels if panel.title == "Box")
    added, option = box.rows[0].options
    assert (added.name, added.refusal) == ("Add Pidgey to the team", "")
    assert option.name == "Swap with Charmander"

    draft = state.draft()
    sheet = draft.world.player.require_sheet()
    _ = ENGINE.play_option(draft, option, Random(0))
    assert sheet.mon_ids() == [pidgey.mon_id, "charmander"]

    _ = change(ENGINE, draft, "heal_team")
    assert all(mon.hp.current == mon.hp.maximum for mon in (*sheet.team, *sheet.box))


def test_the_team_sends_to_the_box_withdraws_and_sets_the_lead() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    with pytest.raises(Refusal, match="No other team Pokemon can fight"):
        _ = run_action(ENGINE, draft, "store_mon", mon_id="charmander")
    pidgey = Mon.new("pidgey", 5, Random(0), sheet.mon_ids())
    pidgey.hp.current = 0
    sheet.team.append(pidgey)
    with pytest.raises(Refusal, match="No other team Pokemon can fight"):
        _ = run_action(ENGINE, draft, "store_mon", mon_id="charmander")
    with pytest.raises(Refusal, match="Charmander leads the team already"):
        _ = run_action(ENGINE, draft, "lead_mon", mon_id="charmander")

    _ = run_action(ENGINE, draft, "store_mon", mon_id=pidgey.mon_id)
    assert ([mon.mon_id for mon in sheet.box], len(sheet.team)) == ([pidgey.mon_id], 1)
    _ = run_action(ENGINE, draft, "withdraw_mon", mon_id=pidgey.mon_id)
    _ = run_action(ENGINE, draft, "lead_mon", mon_id=pidgey.mon_id)
    assert [mon.mon_id for mon in sheet.team] == [pidgey.mon_id, "charmander"]

    rattata = Mon.new("rattata", 5, Random(0), sheet.mon_ids())
    sheet.box.append(rattata)
    for number in range(4):
        sheet.team.append(Mon.new("weedle", 5, Random(number), sheet.mon_ids()))
    with pytest.raises(Refusal, match="The team is full; swap Rattata in"):
        _ = run_action(ENGINE, draft, "withdraw_mon", mon_id=rattata.mon_id)


def test_a_rare_candy_raises_one_level_and_grows_the_pokemon() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    charmander = sheet.require_mon("charmander")
    charmander.level, charmander.exp = 15, 15**3
    _ = change(ENGINE, draft, "gain_item", item_id="rare-candy")
    charmander.hp.current = 0
    assert (
        refused(ENGINE, draft, "use_item", item_id="rare-candy", mon_id="charmander")
        == "Charmander has fainted; only a revive helps it"
    )
    charmander.hp.current = 1

    _ = change(ENGINE, draft, "use_item", item_id="rare-candy", mon_id="charmander")

    assert (charmander.level, charmander.exp, charmander.species_id) == (16, 16**3, "charmeleon")
    assert "rare-candy" not in sheet.bag
    assert refused(ENGINE, draft, "buy", item_id="rare-candy") == (
        "Rare Candy is not sold; it is found or given"
    )
