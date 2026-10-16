from pathlib import Path

import pytest
from pydantic import ValidationError
from support.lite5e import ScriptedDice
from support.table import CHARACTERS

from rulehall.core.game import Character
from rulehall.core.stores import read_model
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.lite5e.data import DATA_DIR, Ability, LevelPickKind, StartingGear
from rulehall.engines.lite5e.hire import SheetProposal
from rulehall.engines.lite5e.pack import Background, Lite5ePack
from rulehall.engines.lite5e.rules import DEATH_SAVE_DC, AbilityMethod
from rulehall.engines.lite5e.sheet import (
    DEATH_SAVE,
    DamageTaken,
    Lite5ePerson,
    Lite5eSheet,
)

ARRAY: dict[Ability, int] = {
    "strength": 15,
    "dexterity": 14,
    "constitution": 13,
    "intelligence": 12,
    "wisdom": 10,
    "charisma": 8,
}
SOLDIER = Background(
    id="soldier",
    name="Soldier",
    brief="You trained for war.",
    abilities=("strength", "dexterity", "constitution"),
    feat_id="savage-attacker",
    skill_ids=("athletics", "intimidation"),
    tool_id="dice",
    gear=(StartingGear(gear_id="spear", count=1), StartingGear(gear_id="dice", count=1)),
    gp=14,
)


def build(
    class_id: str = "fighter",
    *,
    species_id: str = "human",
    level: int = 1,
    method: AbilityMethod = "array",
    scores: dict[Ability, int] = ARRAY,
    increases: dict[Ability, int] | None = None,
) -> Lite5eSheet:
    sheet = Lite5eSheet.start(
        class_id=class_id,
        species_id=species_id,
        subspecies_id=None,
        species_ability=None,
        background=SOLDIER,
        method=method,
        scores=scores,
        increases={"strength": 2, "constitution": 1} if increases is None else increases,
    )
    sheet.finish(
        level=level, background=SOLDIER, category_gear_ids={"holy-symbols": "amulet"}, picks={}
    )
    return sheet


SHIPPED_BACKGROUNDS = read_model(DATA_DIR.parent / "packs" / "srd.json", Lite5ePack).backgrounds


@pytest.mark.parametrize(
    "path", sorted(CHARACTERS.glob("*/lite5e.json")), ids=lambda path: path.parent.name
)
def test_each_shipped_sheet_is_a_legal_build(path: Path) -> None:
    sheet = read_model(path, Character[Lite5ePerson]).person.require_sheet()
    picks: dict[LevelPickKind, tuple[Slug, ...]] = {
        kind: tuple(ids) for kind, ids in sheet.picks.items() if kind != "initiate-list"
    }
    proposal = SheetProposal(
        kind="class",
        class_id=sheet.class_id,
        species_id=sheet.species_id,
        subspecies_id=sheet.subspecies_id,
        background_id=sheet.background_id,
        method="point-buy",
        scores=sheet.base_scores,
        increases=sheet.background_increases,
        picks=picks,
        species_ability=sheet.species_ability,
    )
    assert proposal.build_sheet(sheet.level, SHIPPED_BACKGROUNDS) == sheet


def test_the_builder_takes_a_point_buy_of_27_only() -> None:
    bought: dict[Ability, int] = {
        "strength": 15,
        "dexterity": 15,
        "constitution": 15,
        "intelligence": 8,
        "wisdom": 8,
        "charisma": 8,
    }
    short: dict[Ability, int] = {**bought, "constitution": 14}
    assert build(method="point-buy", scores=bought).score("dexterity") == 15
    with pytest.raises(Refusal, match="standard array"):
        build(scores=bought)
    with pytest.raises(Refusal, match="point buy"):
        build(method="point-buy", scores=short)


def test_a_build_with_an_illegal_increase_split_is_refused() -> None:
    with pytest.raises(Refusal, match="raise one ability by 2"):
        _ = build(increases={"strength": 2, "dexterity": 2})


def test_damage_takes_temporary_hp_first_then_drops_to_0() -> None:
    sheet = build()
    sheet.temp_hp = 3
    assert sheet.take_damage(5, critical=False).dealt == 5
    assert (sheet.temp_hp, sheet.vitals.hp.current) == (0, 10)
    assert sheet.take_damage(15, critical=False) == DamageTaken(dealt=10, dropped=True, died=False)


def test_damage_at_0_hp_adds_failures_two_on_a_critical() -> None:
    sheet = build()
    sheet.vitals.hp.current = 0
    assert not sheet.take_damage(1, critical=False).died
    assert sheet.vitals.death_failures == 1
    assert sheet.take_damage(1, critical=True).died
    assert sheet.vitals.death_failures == 3


def test_a_hit_that_leaves_the_hp_maximum_in_damage_kills_at_once() -> None:
    sheet = build()
    assert sheet.take_damage(2 * sheet.vitals.hp.maximum, critical=False).died
    fresh = build()
    fresh.vitals.hp.current = 0
    assert fresh.take_damage(fresh.vitals.hp.maximum, critical=False).died


def test_a_natural_20_on_a_death_save_brings_back_1_hp() -> None:
    sheet = build()
    sheet.vitals.hp.current = 0
    sheet.vitals.death_failures = 2
    test = sheet.roll_test(DEATH_SAVE, 0, DEATH_SAVE_DC, "none", ScriptedDice(20), None)
    assert sheet.vitals.record_death_save(test).outcome == "revived"
    assert (sheet.vitals.hp.current, sheet.vitals.death_failures) == (1, 0)


def test_untrained_armor_is_refused() -> None:
    wizard = build("wizard")
    wizard.add_gear("leather-armor", 1)
    with pytest.raises(Refusal, match="light armor training"):
        _ = wizard.equip("leather-armor")
    barbarian = build("barbarian")
    barbarian.add_gear("plate-armor", 1)
    with pytest.raises(Refusal, match="heavy armor training"):
        _ = barbarian.equip("plate-armor")
    assert not barbarian.wears_heavy_armor()
    assert build().wears_heavy_armor()


def test_a_lineage_cantrip_is_not_offered_again_as_a_class_cantrip() -> None:
    drow = Lite5eSheet.start(
        class_id="wizard",
        species_id="elf",
        subspecies_id="elven-lineage-drow",
        species_ability="intelligence",
        background=SOLDIER,
        method="array",
        scores=ARRAY,
        increases={"strength": 2, "constitution": 1},
    )
    assert "dancing-lights" not in drow.level_pick_options("cantrip")


def test_a_saved_sheet_with_an_unknown_pick_is_refused() -> None:
    saved = build("warlock", level=2).model_dump()
    saved["picks"]["invocation"] = ["no-such-invocation"]
    with pytest.raises(ValidationError, match="no Eldritch Invocation ids"):
        _ = Lite5eSheet.model_validate(saved)


def test_a_saved_sheet_with_an_illegal_build_is_refused() -> None:
    saved = build().model_dump()
    saved["base_scores"]["strength"] = 16
    with pytest.raises(ValidationError, match="point buy"):
        _ = Lite5eSheet.model_validate(saved)
    saved = build().model_dump()
    saved["background_increases"] = {"strength": 3}
    with pytest.raises(ValidationError, match="raise one ability by 2"):
        _ = Lite5eSheet.model_validate(saved)
