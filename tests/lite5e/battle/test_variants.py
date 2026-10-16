import pytest
from support.lite5e_battle import SteadyDice, fight, foe, member, play, play_first_pick

from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.actions import member_aims
from rulehall.engines.lite5e.battle.state import Effect, Fight, MemberCombatant
from rulehall.engines.lite5e.data import StrikeVariant, srd

VARIANT_CAST: dict[str, tuple[str, int, str]] = {
    "trip": ("rogue", 5, "shortsword"),
    "withdraw": ("rogue", 5, "shortsword"),
    "divine-smite": ("paladin", 2, "longsword"),
    "searing-smite": ("paladin", 2, "longsword"),
    "shining-smite": ("paladin", 5, "longsword"),
    "reckless": ("barbarian", 2, "greataxe"),
    "eldritch-smite": ("warlock", 5, "longsword"),
    "stunning-strike": ("monk", 5, "shortsword"),
    "addle": ("monk", 3, "shortsword"),
    "push": ("monk", 3, "shortsword"),
    "topple": ("monk", 3, "shortsword"),
}


def _paladin(face: int) -> Fight:
    paladin = member("player", "paladin", level=2, weapon_ids=("longsword",))
    paladin.require_sheet().inspiration = False
    paladin.require_sheet().uses_spent["paladins-smite"] = 1
    return fight([(paladin, "front")], [foe("ogre", "ogre")], SteadyDice(face))


@pytest.mark.parametrize(("face", "paid"), [(2, False), (15, True)])
def test_a_smite_spends_its_slot_and_the_bonus_action_only_on_a_hit(
    face: int, *, paid: bool
) -> None:
    f = _paladin(face)
    _ = play(f, "act longsword+divine-smite-1", "ogre")
    sheet = f.require_member("player").require_sheet()
    assert sheet.slots_left(1) == (1 if paid else 2)
    assert f.battle.budget.bonus_action is not paid


@pytest.mark.parametrize("variant", srd().strike_variants, ids=lambda v: v.variant_id)
def test_every_strike_variant_plays(variant: StrikeVariant) -> None:
    class_id, level, weapon_id = VARIANT_CAST[variant.variant_id]
    hero = member("player", class_id, level=level, weapon_ids=(weapon_id,))
    sheet = hero.require_sheet()
    sheet.inspiration = False
    if variant.spell_id is not None:
        sheet.picks.setdefault("prepared", []).append(variant.spell_id)
    invoked = variant.source_id in srd().character_options.invocations
    if invoked:
        sheet.picks["invocation"] = ["pact-of-the-blade", variant.source_id or ""]
        sheet.picks["pact-weapon"] = [weapon_id]
    f = fight([(hero, "front"), (member("bo"), "front")], [foe("ogre", "ogre")], SteadyDice(15))
    if invoked:
        f.battle.effects.append(
            Effect(holder_id="player", source_id="player", effect_id="pact-weapon")
        )
    player = f.battle.require_combatant("player")
    assert isinstance(player, MemberCombatant)
    aim = next(
        aim
        for aim in member_aims(f, player)
        if (aim.variant_id or "").startswith(variant.variant_id)
    )
    _ = play_first_pick(f, aim)
    assert f.battle.foes()[0].hp.shortfall > 0


def test_flurry_with_stunning_strike_needs_two_points_and_spends_one_per_part() -> None:
    monk = member("player", "monk", level=5)
    f = fight([(monk, "front")], [foe("ogre", "ogre")], SteadyDice(15))
    sheet = monk.require_sheet()
    sheet.spend_use("focus", sheet.uses_left("focus") - 1)
    with pytest.raises(Refusal, match="no pick"):
        _ = play(f, "bonus flurry-of-blows+stunning-strike", "ogre")
    sheet.uses_spent["focus"] -= 1
    _ = play(f, "bonus flurry-of-blows+stunning-strike", "ogre")
    assert sheet.uses_left("focus") == 0
