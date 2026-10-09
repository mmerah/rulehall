from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from support.table import CHAMPIONS, change, game, narrowed, open_table, run_edit

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.champions.advice import battle_species
from rulehall.engines.pokemon.champions.args import PickEdit, TeamEdit
from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.panels import team_option
from rulehall.engines.pokemon.champions.paste import export_paste, parse_paste
from rulehall.engines.pokemon.champions.pending import SPECIES, PendingSet, PendingTeam
from rulehall.engines.pokemon.champions.season import Finish
from rulehall.engines.pokemon.champions.team_builder import team_builder_catalog, team_builder_view
from rulehall.engines.pokemon.champions.views import (
    Catalog,
    CatalogOrder,
    Choice,
    PickField,
    PointsField,
)
from rulehall.engines.pokemon.champions.world import (
    NOT_LOCKED,
    PENDING_OPEN,
    TEAM_FINAL,
    ChampionsGame,
    ChampionsWorld,
)
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import stats

FIELD_IDS = ("species", "ability", "item", "nature", "moves", "sp")


def test_a_pick_refuses_the_clauses_a_foreign_mega_stone_and_an_unowned_species() -> None:
    sets = champions_data().archetypes[0].team.sets
    team = PendingTeam.of_team(sets)
    allowed_species_ids = [each.species_id for each in sets]
    outsider = next(each for each in champions_data().presets if each not in allowed_species_ids)
    stone_id, holders = next(
        (stone_id, holders)
        for stone_id, holders in champions_data().legal.mega_formes.items()
        if sets[1].species_id not in holders and stone_id != sets[0].item_id
    )
    holder = dex().species[next(iter(holders))].name
    held = next(
        number
        for number, each in enumerate(sets, 1)
        if number > 2 and each.item_id not in champions_data().legal.mega_formes
    )
    cases = (
        ("species", sets[0].species_id, "is on slot 1"),
        ("item", sets[held - 1].item_id, f"held by slot {held}"),
        ("item", stone_id, f"only {holder}"),
        ("species", outsider, "not recruited"),
    )
    for field_id, choice_id, refusal in cases:
        with pytest.raises(Refusal, match=refusal):
            team.pick(2, field_id, (choice_id,), allowed_species_ids)


def test_save_team_refuses_an_incomplete_pending_team_and_saves_a_completed_one() -> None:
    engine, state = game(CHAMPIONS)
    draft = state.draft()
    world = narrowed(draft.world, ChampionsWorld)
    run_edit(engine, draft, "clear_slot", slot=3)
    with pytest.raises(Refusal, match="slot 3"):
        run_edit(engine, draft, "save")
    run_edit(engine, draft, "load_template", template_id="rain")
    run_edit(engine, draft, "save")
    rain = next(each for each in champions_data().archetypes if each.archetype_id == "rain")
    assert (world.player_sheet.team, world.pending_team) == (list(rain.team.sets), None)


def test_a_locked_team_copies_to_a_pending_team_that_saves_once_the_event_ends() -> None:
    engine, state = game(CHAMPIONS)
    draft = state.draft()
    world = narrowed(draft.world, ChampionsWorld)
    with pytest.raises(Refusal, match=NOT_LOCKED):
        run_edit(engine, draft, "copy_registered_team")
    _ = change(engine, draft, "register_team")
    registered = world.player_sheet.registered
    run_edit(engine, draft, "copy_registered_team")
    with pytest.raises(Refusal, match=PENDING_OPEN):
        run_edit(engine, draft, "copy_registered_team")
    assert team_builder_view(world).pending_team_open
    run_edit(engine, draft, "discard")
    run_edit(engine, draft, "copy_registered_team")
    run_edit(engine, draft, "load_template", template_id="rain")
    assert world.pending_team_dirty()
    with pytest.raises(Refusal, match="locked"):
        run_edit(engine, draft, "save")
    assert world.player_sheet.registered == registered
    world.player_sheet.registered = None
    run_edit(engine, draft, "save")
    rain = next(each for each in champions_data().archetypes if each.archetype_id == "rain")
    assert (world.player_sheet.team, world.pending_team) == (list(rain.team.sets), None)


def test_after_worlds_the_saved_team_shows_and_no_copy_opens() -> None:
    engine, state = game(CHAMPIONS)
    draft = state.draft()
    world = narrowed(draft.world, ChampionsWorld)
    _ = change(engine, draft, "register_team")
    run_edit(engine, draft, "copy_registered_team")
    run_edit(engine, draft, "load_template", template_id="rain")
    world.player_sheet.registered = None
    world.player_sheet.finishes.append(
        Finish(event_name="Worlds", tier="worlds", placing=1, record="3-0", cp=0)
    )
    assert world.shown_team() == PendingTeam.of_team(world.player_sheet.team)
    with pytest.raises(Refusal, match=TEAM_FINAL):
        run_edit(engine, draft, "copy_registered_team")


def test_a_species_pick_with_preset_places_its_top_preset_and_one_undo_restores(
    tmp_path: Path,
) -> None:
    table = open_table(tmp_path, engine_id=CHAMPIONS, state_type=ChampionsGame)
    before = table.state
    team = before.world.player_sheet.team
    held_ids = {each.item_id for each in team[1:]}
    species_id, presets = next(
        (species_id, presets)
        for species_id, presets in champions_data().presets.items()
        if species_id not in {each.species_id for each in team}
        and presets[0].item_id not in held_ids
    )
    pick = PickEdit(slot=1, field_id=SPECIES, choice_ids=(species_id,), preset=True)

    table.session.edit(team_option("pick", pick))

    assert table.state.world.shown_team().require_set(1) == PendingSet.of_set(presets[0])
    table.session.undo_edit()
    assert table.state == before


def test_a_paste_round_trips_every_archetype_team() -> None:
    for archetype in champions_data().archetypes:
        slots = [PendingSet.of_set(each) for each in archetype.team.sets]
        rows = parse_paste(export_paste(slots))
        assert [row.pending_set for row in rows] == slots
        assert all(not row.errors for row in rows)


def test_a_paste_with_evs_zeroes_the_stat_points_and_flags_an_unknown_move() -> None:
    (row,) = parse_paste(
        "Gardevoir @ Choice Scarf\nAbility: Trace\nEVs: 252 SpA / 4 SpD / 252 Spe\n"
        "Timid Nature\n- Moonblast\n- Not A Move\n"
    )
    assert row.pending_set is not None
    assert row.pending_set.sp == [0] * 6
    assert row.pending_set.move_ids == ["moonblast"]
    assert any("EVs" in error for error in row.errors)
    assert any("Not A Move" in error for error in row.errors)


def test_stat_points_clamp_at_the_budget_and_show_the_final_stats() -> None:
    engine, state = game(CHAMPIONS)
    draft = state.draft()
    world = narrowed(draft.world, ChampionsWorld)
    legal = champions_data().legal
    for row in range(6):
        run_edit(engine, draft, "set_points", slot=1, field_id="sp", row=row, points=99)
    pending_set = world.editing_team().require_set(1)
    assert sum(pending_set.sp) == legal.sp_total
    assert max(pending_set.sp) == legal.sp_max
    points = team_builder_view(world).slots[0].fields[-1]
    assert isinstance(points, PointsField)
    species = battle_species(pending_set)
    final = stats(
        species, 50, pending_set.nature, (31,) * 6, tuple(pending_set.sp), stat_points=True
    )
    assert tuple(row.final for row in points.rows) == final


def test_the_team_builder_view_has_six_slots_with_their_fields_and_whole_catalogs() -> None:
    _, state = game(CHAMPIONS)
    world = narrowed(state.world, ChampionsWorld)
    view = team_builder_view(world)
    assert len(view.slots) == 6
    assert all(tuple(field.field_id for field in slot.fields) == FIELD_IDS for slot in view.slots)
    natures = team_builder_catalog(world, 1, "natures")
    assert (len(natures.choices), natures.columns) == (25, 5)
    species_id = world.player_sheet.team[0].species_id
    for catalog_id in ("species", "items", "templates", f"moves-{species_id}"):
        catalog = team_builder_catalog(world, 1, catalog_id)
        assert catalog.orders
        ids = sorted(choice.choice_id for choice in catalog.choices)
        assert all(sorted(order.choice_ids) == ids for order in catalog.orders)
    moves = view.slots[0].fields[FIELD_IDS.index("moves")]
    assert isinstance(moves, PickField)
    assert moves.picks == 4


def _catalog(*orders: tuple[str, ...]) -> Catalog:
    return Catalog(
        catalog_id="natures",
        title="Natures",
        choices=(
            Choice(choice_id="adamant", name="Adamant"),
            Choice(choice_id="jolly", name="Jolly"),
        ),
        facets=(),
        orders=tuple(CatalogOrder(name="order", choice_ids=ids) for ids in orders),
    )


def test_a_catalog_orders_every_choice_once() -> None:
    assert _catalog(("jolly", "adamant")).orders

    with pytest.raises(ValidationError, match="every choice once"):
        _ = _catalog(("adamant",))
    with pytest.raises(ValidationError, match="every choice once"):
        _ = _catalog(("adamant", "adamant"))


def test_a_catalog_refuses_duplicate_choice_ids() -> None:
    twin = Choice(choice_id="jolly", name="Jolly")
    with pytest.raises(ValidationError, match="duplicate choice ids"):
        _ = Catalog(
            catalog_id="natures", title="Natures", choices=(twin, twin), facets=(), orders=()
        )


def test_the_team_edits_are_the_edits_the_engine_marks(tmp_path: Path) -> None:
    table = open_table(tmp_path, engine_id=CHAMPIONS, state_type=ChampionsGame)
    assert set(get_args(TeamEdit.__value__)) == set(table.session.engine.edits)
