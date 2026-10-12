from rulehall.core.answer_repair import parse_with_repairs
from rulehall.core.validation import Slug
from rulehall.engines.pokemon.champions.advice import ABILITY_IMMUNITIES, team_advice
from rulehall.engines.pokemon.champions.args import PickEdit
from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.unsaved import UnsavedSet, UnsavedTeam
from rulehall.engines.pokemon.champions.views import Advice
from rulehall.engines.pokemon.dex import dex

GROUND_WEAK_IDS = ("incineroar", "kingambit", "sneasler")


def test_the_speed_control_fix_clears_its_warning() -> None:
    data = champions_data()
    speed_control = data.roles["speed-control"]
    team = next(
        team
        for team in data.real_teams
        if not any(set(speed_control.move_ids) & set(each.move_ids) for each in team.sets)
    )
    unsaved = UnsavedTeam.of_team(team.sets)

    fix = _advice(unsaved.slots)["no-speed-control"].fix
    assert fix is not None
    edit = parse_with_repairs(PickEdit, fix.args)
    unsaved.pick(edit.slot, edit.field_id, edit.choice_ids)

    assert "no-speed-control" not in _advice(unsaved.slots)
    assert "speed-control" in _advice(unsaved.slots)


def test_a_levitate_holder_cancels_a_shared_ground_weakness() -> None:
    weak: list[UnsavedSet | None] = [UnsavedSet(species_id=each) for each in GROUND_WEAK_IDS]
    grounded = UnsavedSet(species_id="rotomheat")
    floating = UnsavedSet(species_id="rotomheat", ability_id="levitate")

    assert "weak-to-ground" in _advice([*weak, grounded, None, None])
    assert "weak-to-ground" not in _advice([*weak, floating, None, None])


def test_ability_immunities_name_dex_abilities() -> None:
    assert set(ABILITY_IMMUNITIES) <= set(dex().ability_names)


def _advice(slots: list[UnsavedSet | None]) -> dict[Slug, Advice]:
    return {each.advice_id: each for each in team_advice(UnsavedTeam(slots=slots))}
