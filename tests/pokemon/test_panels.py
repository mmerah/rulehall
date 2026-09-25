from pathlib import Path
from random import Random

import pytest
from pydantic import ValidationError
from support.pokemon import ENGINE, started

from rulehall.core.views import Meter, Sprite
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.panels import ICON_SHEET, item_text, mon_row
from rulehall.engines.pokemon.rules import ITEMS, TIMES
from rulehall.engines.pokemon.world import Mon, PokemonWorld, RosterSlot, Trainer


def test_people_and_pokemon_name_their_showdown_sprites() -> None:
    state = started()

    assert ENGINE.sprite(state, "player") == Sprite(path=Path("sprites/trainers/ethan.png"))
    assert ENGINE.sprite(state, "rook") == Sprite(path=Path("sprites/trainers/camper.png"))
    assert ENGINE.sprite(state, "charmander") == Sprite(
        path=ICON_SHEET, x=160, y=0, width=40, height=30
    )
    assert ENGINE.sprite(state, "poke-ball") == Sprite(path=Path("sprites/items/poke-ball.png"))
    assert ENGINE.sprite(state, "harbour-road") is None


def test_a_team_row_shows_types_hp_and_stats_as_tags_and_meters() -> None:
    mon = started().world.player.require_sheet().require_mon("charmander")
    mon.hp.current = 8
    mon.status = "brn"

    row = mon_row(mon)
    stats = mon.stats()[1:]

    assert tuple(tag.name for tag in row.tags) == ("Lv5", "Fire", "BRN", "Jolly", "♥ 70")
    assert row.tags[3].hint == "Spe ▲ · SpA ▼"
    assert [(meter.name, meter.current, meter.maximum) for meter in row.meters] == [
        ("HP", 8, 20),
        *(
            (name, value, max(stats))
            for name, value in zip(("Atk", "Def", "SpA ▼", "SpD", "Spe ▲"), stats, strict=True)
        ),
    ]
    assert row.meters[1].hint == f"base 52 · IV {mon.ivs[1]} · EV 0"
    assert row.meters[5].hint == f"base 65 · IV {mon.ivs[5]} · EV 0 · Jolly +10%"
    mon.hp.current = 0
    assert mon_row(mon).tags[2].name == "FNT"


def test_a_trainer_class_outside_the_list_is_refused() -> None:
    rook = started().world.npcs["rook"].model_dump()

    with pytest.raises(ValidationError, match="'ash' is no id from TRAINER CLASSES"):
        _ = Trainer.model_validate({**rook, "avatar_id": "ash"})


def test_a_player_in_a_trainer_class_look_is_refused() -> None:
    player = started().world.player.model_dump()

    with pytest.raises(ValidationError, match="'camper' is no player look"):
        _ = Trainer.model_validate({**player, "avatar_id": "camper"})


def test_a_player_with_an_npc_roster_is_refused() -> None:
    world = started().world
    world.player.roster = (RosterSlot(species_id="pidgey", level=3),)

    with pytest.raises(ValidationError, match="`roster` is for npc trainers"):
        _ = PokemonWorld.model_validate(world.model_dump())


def test_a_team_row_offers_its_items_moves_and_team_actions_in_groups() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    charmander = sheet.require_mon("charmander")
    charmander.level, charmander.exp = 12, 12**3
    charmander.hp.current = 8
    charmander.status = "brn"
    sheet.team.append(Mon.new("pidgey", 5, Random(0), sheet.mon_ids()))
    for item_id in ("full-heal", "tm-dig", "oran-berry", "rare-candy"):
        sheet.add(item_id, 1)
    state = ENGINE.accept(draft)

    (team,) = (panel for panel in ENGINE.player_view(state).panels if panel.title == "Team")
    charmander_row, pidgey_row = team.rows

    options = charmander_row.options
    assert [option.group for option in options] == ["Items"] * 4 + ["Learn"] * 3 + ["Team"] * 2
    assert [option.args.get("item_id") for option in options[:5]] == [
        "full-heal",
        "potion",
        "rare-candy",
        "oran-berry",
        "tm-dig",
    ]
    assert [option.action_name for option in options if option.refusal] == ["lead_mon"]
    assert all(option.refusal for option in pidgey_row.options[:2])
    assert not any(option.refusal for option in pidgey_row.options if option.group == "Team")
    assert [panel.title for panel in charmander_row.detail] == ["About", "Stats", "Moves"]


def test_the_summary_shows_the_held_item_the_nature_arrows_and_the_moves() -> None:
    mon = started().world.player.require_sheet().require_mon("charmander")
    mon.item_id = "charcoal"

    about, stats, moves = mon_row(mon).detail

    assert (about.rows[0].icon_id, about.rows[0].brief) == ("charcoal", dex().items["charcoal"])
    assert (about.rows[1].tags[0].name, about.rows[1].brief) == ("Blaze", dex().abilities["Blaze"])
    assert about.rows[2].brief == "Spe ▲ · SpA ▼"
    assert [row.name for row in stats.rows] == ["HP", "Atk", "Def", "SpA ▼", "SpD", "Spe ▲"]
    ember = moves.rows[2]
    assert [tag.name for tag in ember.tags] == ["Fire", "Special"]
    assert dex().moves["ember"].text in ember.brief
    assert ember.meters == (Meter(name="PP", current=40, maximum=40),)


def test_bag_rows_sort_by_pocket_and_carry_their_text() -> None:
    draft = started().draft()
    sheet = draft.world.player.require_sheet()
    for item_id in ("tm-dig", "oran-berry", "rare-candy", "everstone"):
        sheet.add(item_id, 1)
    state = ENGINE.accept(draft)

    (bag,) = (panel for panel in ENGINE.player_view(state).panels if panel.title == "Bag")

    assert [row.name for row in bag.rows[:-2]] == [
        "Potion",
        "Rare Candy",
        "Poké Ball",
        "Everstone",
        "Oran Berry",
        "TM Dig",
    ]
    assert [tag.name for tag in bag.rows[1].tags] == [f"{TIMES}1", "Medicine"]
    assert bag.rows[3].brief == ITEMS["everstone"].text
    assert dex().moves["dig"].text in bag.rows[5].brief
    assert all(item_text(item_id) for item_id in ITEMS)
    assert all(option.refusal for option in bag.rows[0].options)
