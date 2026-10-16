from collections.abc import Sequence

from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.specs import (
    MELEE_REACH_FEET,
    REACH_WEAPON_FEET,
    ActionSpec,
    Delivery,
)
from rulehall.engines.lite5e.battle.state import (
    Combatant,
    Fight,
    MemberCombatant,
)
from rulehall.engines.lite5e.data import Area, Band, TargetFilter, TargetRequirement
from rulehall.engines.lite5e.rules import RESTORED, FormationRow

NEAR_RANGE_FEET = 30
CLOSE_AREA_FEET = 15
NEAR_AREA_FEET = 30
SMALL_RADIUS_FEET = 5
MID_RADIUS_FEET = 10
MID_SIDE_FEET = 15
SMALL_AREA_TARGETS = 2
MID_AREA_TARGETS = 4

BANDS: tuple[Band, ...] = ("close", "near", "far")


def is_active(fight: Fight, combatant: Combatant) -> bool:
    return fight.is_standing(combatant) and not fight.battle.is_incapacitated(
        combatant.combatant_id
    )


def target_refusal(
    fight: Fight, user: Combatant, target: Combatant, target_filter: TargetFilter
) -> str:
    name = fight.name_of(target)
    if target_filter == "dead":
        if (
            not isinstance(target, MemberCombatant)
            or target.withdrawal
            or not fight.is_dead(target)
        ):
            return f"{name} did not die in this battle"
        return "" if fight.hp_of(target).maximum else f"{name} has no HP maximum left"
    if not fight.in_battle(target):
        return f"{name} is out of the battle"
    if (target.side == user.side) == (target_filter == "foe"):
        return f"{name} is {'no foe' if target_filter == 'foe' else 'no ally'}"
    sheet = fight.sheet_of(target)
    match target_filter:
        case "aid" if sheet is None or sheet.aid_hp:
            return f"{name} cannot take Aid now"
        case "restore" if not any(
            effect.condition in RESTORED for effect in fight.battle.effects_on(target.combatant_id)
        ):
            return f"{name} has no condition to restore"
        case "dying" if (
            fight.hp_of(target).current > 0
            or fight.require_member(target.combatant_id).require_vitals().stable
        ):
            return f"{name} is not dying"
        case _:
            return ""


def hide_refusal(fight: Fight, combatant: Combatant) -> str:
    if not fight.battle.cover or combatant.row != "back":
        return "Hide needs cover here and you in your back row"
    return ""


def side_of(fight: Fight, combatant: Combatant) -> list[Combatant]:
    return [c for c in fight.battle.combatants if c.side == combatant.side]


def enemies_of(fight: Fight, combatant: Combatant) -> list[Combatant]:
    return [c for c in fight.battle.combatants if c.side != combatant.side]


def row_of(fight: Fight, combatant: Combatant) -> FormationRow:
    front_held = any(c.row == "front" and is_active(fight, c) for c in side_of(fight, combatant))
    return combatant.row if front_held else "front"


def leaves_the_front(fight: Fight, combatant: Combatant) -> bool:
    return combatant.row == "front" and any(
        other is not combatant and other.row == "front" and is_active(fight, other)
        for other in side_of(fight, combatant)
    )


def band_between(fight: Fight, user: Combatant, target: Combatant) -> Band:
    user_row, target_row = row_of(fight, user), row_of(fight, target)
    if user.side == target.side:
        return "close" if user_row == target_row else "near"
    if user_row == target_row:
        return "close" if user_row == "front" else "far"
    return "near"


def engaged_enemies(fight: Fight, combatant: Combatant) -> list[Combatant]:
    return [
        enemy
        for enemy in enemies_of(fight, combatant)
        if is_active(fight, enemy) and row_of(fight, enemy) == "front"
    ]


def is_charmed_by(fight: Fight, user: Combatant, target: Combatant) -> bool:
    return any(
        effect.condition == "charmed" and effect.source_id == target.combatant_id
        for effect in fight.battle.effects_on(user.combatant_id)
    )


def meets_requirements(
    fight: Fight, user: Combatant, target: Combatant, action: ActionSpec
) -> bool:
    return not is_charmed_by(fight, user, target) and _meets_any(fight, user, target, action)


def reaches(fight: Fight, user: Combatant, target: Combatant, action: ActionSpec) -> bool:
    return meets_requirements(fight, user, target, action) and in_reach(fight, user, target, action)


def in_reach(fight: Fight, user: Combatant, target: Combatant, action: ActionSpec) -> bool:
    if action.reach_feet is None and action.range_feet is None and action.area is None:
        return target is user
    band = band_between(fight, user, target)
    if action.reach_feet is not None and _melee_reaches(fight, user, target, action, band):
        return True
    limit = _reach_band(action)
    return limit is not None and BANDS.index(band) <= BANDS.index(limit)


def require_reach(fight: Fight, user: Combatant, target: Combatant, action: ActionSpec) -> None:
    if is_charmed_by(fight, user, target):
        raise Refusal(f"{fight.name_of(user)} is charmed by {fight.name_of(target)}")
    if not _meets_any(fight, user, target, action):
        raise Refusal(f"{action.name} cannot target {fight.name_of(target)}")
    if not in_reach(fight, user, target, action):
        raise Refusal(f"{action.name} does not reach {fight.name_of(target)}")


def delivery_against(
    fight: Fight, user: Combatant, target: Combatant, action: ActionSpec
) -> Delivery | None:
    if action.delivery != "melee" or action.range_feet is None:
        return action.delivery
    band = band_between(fight, user, target)
    return "melee" if _melee_reaches(fight, user, target, action, band) else "ranged"


def ally_beside(fight: Fight, attacker: Combatant, target: Combatant) -> bool:
    return row_of(fight, target) == "front" and any(
        ally is not attacker and is_active(fight, ally) and row_of(fight, ally) == "front"
        for ally in side_of(fight, attacker)
    )


def band_of_feet(feet: int) -> Band:
    if feet <= MELEE_REACH_FEET:
        return "close"
    return "near" if feet <= NEAR_RANGE_FEET else "far"


def area_cap(area: Area) -> int | None:
    if area.shape == "line":
        return MID_AREA_TARGETS
    if area.shape in ("sphere", "emanation"):
        if area.feet <= SMALL_RADIUS_FEET:
            return SMALL_AREA_TARGETS
        return MID_AREA_TARGETS if area.feet <= MID_RADIUS_FEET else None
    return MID_AREA_TARGETS if area.feet <= MID_SIDE_FEET else None


def area_target_cap(action: ActionSpec) -> int | None:
    if action.area is None:
        raise ValueError(f"{action.name} has no area")
    chosen = None if action.target_count == 1 else action.target_count
    return area_cap(action.area) or chosen


def area_targets(
    fight: Fight, user: Combatant, picked: Sequence[Combatant], cap: int | None
) -> list[Combatant]:
    if not picked:
        raise Refusal("an area needs a target")
    if any(target.side == user.side for target in picked):
        raise Refusal("an area never hits your allies")
    rows = {row_of(fight, target) for target in picked}
    if len(rows) != 1:
        raise Refusal("an area hits one row")
    if cap is None:
        row = rows.pop()
        return [
            c for c in enemies_of(fight, user) if fight.is_standing(c) and row_of(fight, c) == row
        ]
    if len(picked) > cap:
        raise Refusal(f"this area hits up to {cap} creatures")
    return list(picked)


def _meets_any(fight: Fight, user: Combatant, target: Combatant, action: ActionSpec) -> bool:
    return not action.requires or any(
        _meets(fight, user, target, requirement) for requirement in action.requires
    )


def _meets(
    fight: Fight, user: Combatant, target: Combatant, requirement: TargetRequirement
) -> bool:
    battle = fight.battle
    held = battle.effects_on(target.combatant_id)
    if requirement == "grappled-by-self":
        return any(e.condition == "grappled" and e.source_id == user.combatant_id for e in held)
    if requirement == "incapacitated":
        down = isinstance(target, MemberCombatant) and fight.hp_of(target).current == 0
        return down or battle.is_incapacitated(target.combatant_id)
    return any(e.condition == requirement for e in held)


def _melee_reaches(
    fight: Fight, user: Combatant, target: Combatant, action: ActionSpec, band: Band
) -> bool:
    if band == "close":
        return True
    return (
        (action.reach_feet or 0) >= REACH_WEAPON_FEET
        and band == "near"
        and user.side != target.side
        and row_of(fight, user) == "back"
        and row_of(fight, target) == "front"
    )


def _reach_band(action: ActionSpec) -> Band | None:
    if action.range_feet is not None:
        return band_of_feet(action.range_feet)
    if action.area is None:
        return None
    if action.area.feet <= CLOSE_AREA_FEET:
        return "close"
    return "near" if action.area.feet <= NEAR_AREA_FEET else "far"
