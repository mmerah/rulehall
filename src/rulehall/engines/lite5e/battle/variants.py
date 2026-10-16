from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.attack import holds_effect
from rulehall.engines.lite5e.battle.rows import row_of
from rulehall.engines.lite5e.battle.specs import (
    UNARMED_STRIKE,
    ActionSpec,
    spell_part,
    uses_strength,
)
from rulehall.engines.lite5e.battle.state import (
    RAGE,
    Combatant,
    Fight,
    MemberCombatant,
    PickedVariant,
)
from rulehall.engines.lite5e.data import (
    ActionCheck,
    DamagePart,
    StrikeNeed,
    StrikeVariant,
    raised_dice,
    srd,
)
from rulehall.engines.lite5e.rules import PACT_OF_THE_BLADE, is_monk_weapon


def offered_variants(
    fight: Fight, member: MemberCombatant, action: ActionSpec, *, techniques: bool = False
) -> tuple[PickedVariant, ...]:
    return tuple(
        picked
        for variant in srd().strike_variants
        if techniques or not variant.technique
        for slot_level in (
            variant_slot_levels(fight, member, variant) if variant.pays_slot() else (None,)
        )
        if variant_fits(
            fight, member, action, picked := PickedVariant(variant=variant, slot_level=slot_level)
        )
    )


def require_strike_variant(variant_id: str) -> PickedVariant:
    for variant in srd().strike_variants:
        if not variant.pays_slot() and variant_id == variant.variant_id:
            return PickedVariant(variant=variant, slot_level=None)
        level = variant_id.removeprefix(f"{variant.variant_id}-")
        if variant.pays_slot() and level != variant_id and level.isdigit():
            return PickedVariant(variant=variant, slot_level=int(level))
    raise Refusal(f"{variant_id!r} is no strike variant")


def variant_fits(
    fight: Fight, member: MemberCombatant, action: ActionSpec, picked: PickedVariant
) -> bool:
    variant = picked.variant
    sheet = fight.require_sheet(member)
    return (
        (variant.source_id is None or sheet.owns(variant.source_id))
        and (variant.spell_id is None or variant.spell_id in sheet.castable_spell_ids())
        and _meets_need(fight, member, action, variant.needs)
        and all(check_passes(fight, member, check) for check in variant.checks)
        and (variant.once_mark is None or not fight.battle.used_once(member, variant.once_mark))
        and (variant.spent_use is None or sheet.uses_left(variant.spent_use) > 0)
        and (
            not variant.pays_slot()
            or picked.slot_level in variant_slot_levels(fight, member, variant)
        )
    )


def check_passes(fight: Fight, member: MemberCombatant, check: ActionCheck) -> bool:
    budget = fight.battle.budget
    match check:
        case "back-row":
            return member.row == "back"
        case "front-row":
            return row_of(fight, member) == "front"
        case "can-withdraw":
            return member.row == "front"
        case "moves":
            return not fight.battle.is_held(member.combatant_id)
        case "not-surging":
            return not budget.extra_actions
        case "melee-weapon":
            return any(action.delivery == "melee" for action in fight.weapon_actions(member))
        case "still":
            return budget.move and not budget.moved
        case "no-heavy-armor":
            return not fight.require_sheet(member).wears_heavy_armor()
        case "pact-of-the-blade":
            sheet = fight.require_sheet(member)
            bound = PACT_OF_THE_BLADE in sheet.pick_ids("invocation")
            return bound and sheet.find_pick("pact-weapon") is not None
        case "not-raging":
            return not holds_effect(fight, member.combatant_id, RAGE)
        case "bonus-action":
            return budget.bonus_action
        case "first-attack":
            return not budget.attacked


def variant_slot_levels(
    fight: Fight, member: MemberCombatant, variant: StrikeVariant
) -> tuple[int, ...]:
    sheet = fight.require_sheet(member)
    spell_id = variant.spell_id
    if spell_id is not None:
        if spell_id not in sheet.castable_spell_ids():
            return ()
        return sheet.cast_slot_levels(spell_id, slot_open=not fight.battle.budget.slot_spent)
    return sheet.open_slot_levels(1) if variant.cost == "pact-slot" else ()


def variant_damage_parts(
    fight: Fight, target: Combatant, picked: PickedVariant
) -> list[DamagePart]:
    variant, slot_level = picked.variant, picked.slot_level or 0
    match variant.damage:
        case "spell":
            if variant.spell_id is None:
                raise ValueError(f"{variant.variant_id} deals spell damage with no spell")
            base = spell_part(variant.spell_id, slot_level)
        case DamagePart(dice=dice) as part:
            raised = None if dice is None else raised_dice(dice, dice, slot_level)
            base = part.model_copy(update={"dice": raised})
        case None:
            return []
    if variant.bonus_dice is None or fight.creature_type_of(target) not in variant.bonus_against:
        return [base]
    return [base, base.model_copy(update={"dice": variant.bonus_dice})]


def _meets_need(
    fight: Fight, member: MemberCombatant, action: ActionSpec, needs: StrikeNeed
) -> bool:
    weapon = action.origin == "weapon"
    match needs:
        case "any":
            return True
        case "finesse-or-ranged":
            return weapon and (action.finesse or action.delivery == "ranged")
        case "melee":
            return weapon and action.delivery == "melee"
        case "strength":
            return uses_strength(fight.require_sheet(member), action)
        case "pact-weapon":
            return action.action_id == fight.pact_weapon_id(member)
        case "monk-weapon":
            found = srd().gear.weapons.get(action.action_id)
            return action.action_id == UNARMED_STRIKE or (
                found is not None and is_monk_weapon(found)
            )
        case "unarmed":
            return action.action_id == UNARMED_STRIKE
