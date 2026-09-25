import pytest
from support.twentyfourxx import ENGINE

from rulehall.core.validation import Refusal
from rulehall.engines.packs import SRD_PACK

SNEAK = {
    "specialty": "sneak",
    "origin": "human",
    "increase-1": "stealth",
    "increase-2": "stealth",
    "increase-3": "piloting",
}


@pytest.mark.parametrize(
    ("picks", "expected"),
    [
        ({}, ["specialty"]),
        ({"specialty": "sneak"}, ["specialty", "origin"]),
        ({"specialty": "muscle"}, ["specialty", "specialty-choice", "weapon", "origin"]),
        ({"specialty": "sneak", "origin": "alien"}, ["specialty", "origin", "trait-1", "trait-2"]),
        (
            {"specialty": "sneak", "origin": "android"},
            ["specialty", "origin", "body", "increase-1"],
        ),
        (
            {"specialty": "sneak", "origin": "human"},
            ["specialty", "origin", "increase-1", "increase-2", "increase-3"],
        ),
    ],
)
def test_creation_steps_grow_with_picks(picks: dict[str, str], expected: list[str]) -> None:
    assert [s.id for s in ENGINE.creation_steps(SRD_PACK, picks)] == expected


def test_create_character_builds_the_sheet() -> None:
    character = ENGINE.create_character("Rook", "A quiet operator", SRD_PACK, SNEAK)
    sheet = character.sheet.require_sheet()
    assert sheet.skills == {"Stealth": 12, "Climbing": 8, "Piloting": 8}
    assert sheet.specialty == "Sneak"
    assert sheet.origin == "Human"
    assert sheet.traits == ()


def test_pick_past_d12_is_refused() -> None:
    with pytest.raises(Refusal):
        ENGINE.create_character(
            "Rook", "A quiet operator", SRD_PACK, {**SNEAK, "increase-3": "stealth"}
        )
