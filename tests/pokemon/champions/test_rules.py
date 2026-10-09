from random import Random

import pytest
from pydantic import JsonValue
from support.table import CHAMPIONS, change, game, narrowed, run_edit

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.engine import ChampionsEngine
from rulehall.engines.pokemon.champions.rules import (
    battler_of_set,
    build_key_team,
    build_rival,
    check_team,
    draw_field,
    field_id,
)
from rulehall.engines.pokemon.champions.sheet import ChampionsSheet
from rulehall.engines.pokemon.champions.world import ChampionsWorld
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import stats


@pytest.mark.parametrize("roster", ["open", "story"])
def test_every_archetype_starts_a_valid_character(roster: str) -> None:
    engine, _ = game(CHAMPIONS)
    for archetype in champions_data().archetypes:
        picks = {"roster": roster, "team": archetype.archetype_id, "avatar": "ethan"}
        _ = narrowed(engine, ChampionsEngine).create_character(
            "Kael", "", "masculine", "srd", picks
        )


def test_team_actions_refuse_while_registered() -> None:
    engine, state = game(CHAMPIONS)
    draft = state.draft()
    _ = change(engine, draft, "register_team")
    team = narrowed(draft.world, ChampionsWorld).player_sheet.team
    cases: dict[str, dict[str, JsonValue]] = {
        "pick": {"slot": 1, "field_id": "nature", "choice_ids": ["jolly"]},
        "set_points": {"slot": 1, "field_id": "sp", "row": 0, "points": 1},
        "apply_quick": {"slot": 1, "field_id": "sp", "choice_id": "clear"},
        "apply_preset": {"slot": 1, "preset_id": f"{team[0].species_id}-a"},
        "move_slot": {"slot": 1, "to_slot": 2},
        "clear_slot": {"slot": 1},
        "import_text": {"text": "Garchomp @ Life Orb"},
        "load_template": {"template_id": "rain"},
        "fill_empty_slots": {},
        "save": {},
        "discard": {},
    }
    assert set(cases) == set(engine.edits) - {"copy_registered_team"}
    for name, args in cases.items():
        with pytest.raises(Refusal, match="locked"):
            run_edit(engine, draft, name, **args)
    run_edit(engine, draft, "copy_registered_team")
    with pytest.raises(Refusal, match="locked"):
        run_edit(engine, draft, "save")


def test_a_story_roster_refuses_an_unowned_species() -> None:
    sets = champions_data().archetypes[0].team.sets
    sheet = ChampionsSheet(
        roster="story",
        team=list(sets),
        owned_species_ids=[each.species_id for each in sets],
        recruits_left=1,
    )
    rain = next(each for each in champions_data().archetypes if each.archetype_id == "rain")
    with pytest.raises(Refusal, match="not recruited"):
        sheet.replace_team(rain.team.sets)
    check_team(rain.team.sets, None)


def test_a_set_battles_at_level_50_with_full_ivs_and_its_stat_points() -> None:
    competitive_set = champions_data().presets["incineroar"][0]
    battler = battler_of_set(competitive_set, "incineroar")
    species = dex().species["incineroar"]
    assert (battler.level, battler.ivs, battler.evs) == (50, (31,) * 6, competitive_set.sp)
    assert (
        battler.hp
        == stats(
            species, 50, competitive_set.nature, (31,) * 6, competitive_set.sp, stat_points=True
        )[0]
    )
    assert battler.ability == "Intimidate"


def test_a_key_team_gets_its_ace() -> None:
    real_team, sets = build_key_team("tailwind", "garchomp", (), (), Random(1))
    assert real_team is None
    assert "garchomp" in {each.species_id for each in sets}
    assert "salamence" in {each.species_id for each in sets}
    check_team(sets, None)


def test_the_rival_is_legal_and_shares_no_species_with_the_player() -> None:
    player = champions_data().archetypes[0].team.sets
    rival = build_rival([each.species_id for each in player], Random(3))
    check_team(rival, None)
    legal = champions_data().legal
    bases = {legal.species[each.species_id].base_species_id for each in player}
    assert bases.isdisjoint(legal.species[each.species_id].base_species_id for each in rival)


def test_a_field_draw_repeats_no_team_and_leaves_out_the_key_teams() -> None:
    key_team_id = field_id(draw_field("internationals", 30, (), (), Random(5))[0])
    drawn = draw_field("internationals", 30, (), (key_team_id,), Random(5))
    assert len({field_id(each) for each in drawn}) == len(drawn) == 30
    assert key_team_id not in {field_id(each) for each in drawn}
