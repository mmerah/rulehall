from typing import Literal

from pydantic import Field

from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.data import (
    Ability,
    Area,
    CreatureType,
    DamagePart,
    Healing,
    Rider,
    Size,
    StatBlockAction,
    TargetFilter,
    TargetRequirement,
    Weapon,
    dice_parts,
    raised_dice,
    srd,
)
from rulehall.engines.lite5e.rules import (
    AGONIZING_BLAST,
    CRITICAL_FACE,
    DICE_UPGRADE_LEVEL,
    ELDRITCH_BLAST,
    LIFE_DOMAIN,
    REPELLING_BLAST,
    is_monk_weapon,
)
from rulehall.engines.lite5e.sheet import Lite5eSheet

MELEE_REACH_FEET = 5
REACH_WEAPON_FEET = 10
UNARMED_DAMAGE = 1
UNARMED_STRIKE: Slug = "unarmed-strike"
REPELLING_SIZE: Size = "large"
DISCIPLE_OF_LIFE_BASE = 2
MARTIAL_ABILITIES: tuple[Ability, ...] = ("strength", "dexterity")

type ActionKind = Literal["attack", "save", "auto_hit", "heal", "buff"]
type Delivery = Literal["melee", "ranged"]
type Origin = Literal["weapon", "spell", "natural"]


class SaveSpec(Frozen):
    ability: Ability
    dc: int
    heightened_id: Slug | None = None


class ActionSpec(Frozen):
    action_id: Slug
    name: str
    kind: ActionKind
    origin: Origin = "natural"
    delivery: Delivery | None = None
    to_hit: int | None = None
    critical_face: int = CRITICAL_FACE
    finesse: bool = False
    two_handed: bool = False
    off_hand: bool = False
    pact: bool = False
    reach_feet: int | None = None
    range_feet: int | None = None
    area: Area | None = None
    damage: tuple[DamagePart, ...] = ()
    healing: Healing | None = None
    save: SaveSpec | None = None
    half_on_save: bool = False
    riders: tuple[Rider, ...] = ()
    target_count: int = Field(default=1, ge=1)
    creature_types: tuple[CreatureType, ...] = ()
    target_filter: TargetFilter = "foe"
    requires: tuple[TargetRequirement, ...] = ()
    explosions: int = Field(default=0, ge=0)
    volley: bool = False
    heals_half_dealt: bool = False
    missed_damage_parts: int = Field(default=0, ge=0)


class SpellNumbers(Frozen):
    attack_bonus: int
    save_dc: int
    modifier: int
    healing_bonus: int


def weapon_action(
    sheet: Lite5eSheet, weapon_id: Slug, *, off_hand: bool, pact: bool = False
) -> ActionSpec:
    weapon = srd().gear.weapons.get(weapon_id)
    if weapon is None:
        raise Refusal(f"{weapon_id!r} is no SRD weapon")
    if weapon_id not in sheet.equipped_ids and not pact:
        raise Refusal(f"{weapon.name} is not held")
    melee = weapon.kind == "melee"
    thrown = weapon.thrown_range
    reach = REACH_WEAPON_FEET if "reach" in weapon.properties else MELEE_REACH_FEET
    grip = None if not melee or sheet.holds_shield() else weapon.versatile_damage
    two_handed = melee and ("two-handed" in weapon.properties or grip is not None)
    rolled = _martial_arts_part(sheet, weapon, grip or weapon.damage)
    ability_modifier = sheet.weapon_modifier(weapon, pact=pact)
    damage_bonus = sheet.damage_bonus(ability_modifier, off_hand=off_hand) + weapon.magic_bonus
    to_hit = sheet.attack_bonus(weapon_id, pact=pact) + weapon.magic_bonus
    return ActionSpec(
        action_id=weapon_id,
        name=weapon.name,
        kind="attack",
        origin="weapon",
        delivery=weapon.kind,
        to_hit=to_hit,
        critical_face=sheet.crit_range(),
        finesse="finesse" in weapon.properties,
        two_handed=two_handed,
        off_hand=off_hand,
        pact=pact,
        reach_feet=reach if melee else None,
        range_feet=(None if thrown is None else thrown.normal) if melee else weapon.range.normal,
        damage=(DamagePart(dice=rolled.dice, bonus=damage_bonus, damage_type=rolled.damage_type),),
    )


def gear_action(sheet: Lite5eSheet, gear_id: Slug) -> ActionSpec:
    gear = srd().gear.gear[gear_id]
    effect = gear.effect
    if effect is None or effect.save_ability is None:
        raise ValueError(f"{gear_id} is no thrown gear")
    damage = (
        ()
        if effect.dice is None
        else (DamagePart(dice=effect.dice, bonus=effect.bonus, damage_type=effect.damage_type),)
    )
    riders = (
        ()
        if effect.condition is None
        else (
            Rider(
                rider_id="condition",
                size_max=effect.size_max,
                condition=effect.condition,
                dc=effect.escape_dc,
                ends=None if effect.escape_dc is None else "escape",
            ),
        )
    )
    return ActionSpec(
        action_id=gear_id,
        name=gear.name,
        kind="save",
        range_feet=effect.range_feet,
        damage=damage,
        save=SaveSpec(ability=effect.save_ability, dc=sheet.feature_dc("dexterity")),
        riders=riders,
        creature_types=effect.creature_types,
    )


def uses_strength(sheet: Lite5eSheet, action: ActionSpec) -> bool:
    if action.origin != "weapon" or action.delivery != "melee":
        return False
    return not action.finesse or sheet.modifier("strength") >= sheet.modifier("dexterity")


def unarmed_action(sheet: Lite5eSheet) -> ActionSpec:
    die = sheet.find_martial_arts_die()
    strength = sheet.modifier("strength")
    ability = strength if die is None else max(strength, sheet.modifier("dexterity"))
    damage = (
        DamagePart(dice=None, bonus=UNARMED_DAMAGE + strength, damage_type="bludgeoning")
        if die is None
        else DamagePart(dice=f"1d{die}", bonus=ability, damage_type="bludgeoning")
    )
    return ActionSpec(
        action_id=UNARMED_STRIKE,
        name="Unarmed Strike",
        kind="attack",
        origin="weapon",
        delivery="melee",
        to_hit=ability + sheet.proficiency_bonus(),
        critical_face=sheet.crit_range(),
        reach_feet=MELEE_REACH_FEET,
        damage=(damage,),
    )


def stat_block_action(entry: StatBlockAction) -> ActionSpec:
    weapon = srd().gear.weapons.get(entry.action_id)
    save = None
    if entry.ability is not None and entry.dc is not None:
        save = SaveSpec(ability=entry.ability, dc=entry.dc)
    return ActionSpec(
        action_id=entry.action_id,
        name=entry.name,
        kind="attack" if save is None else "save",
        origin="natural" if weapon is None else "weapon",
        delivery=None if entry.kind == "save" else entry.kind,
        to_hit=entry.to_hit,
        finesse=weapon is not None and "finesse" in weapon.properties,
        reach_feet=entry.reach_feet,
        range_feet=entry.range_feet,
        area=entry.area,
        damage=entry.damage,
        save=save,
        half_on_save=entry.success == "half",
        riders=entry.riders,
        requires=entry.requires,
    )


def spell_numbers(sheet: Lite5eSheet, spell_id: Slug, slot_level: int) -> SpellNumbers:
    modifier = sheet.modifier(sheet.spell_ability(spell_id))
    life = slot_level > 0 and LIFE_DOMAIN in sheet.feature_ids()
    return SpellNumbers(
        attack_bonus=sheet.spell_attack_bonus(spell_id),
        save_dc=sheet.spell_save_dc(spell_id),
        modifier=modifier,
        healing_bonus=modifier + (DISCIPLE_OF_LIFE_BASE + slot_level if life else 0),
    )


def spell_action(
    sheet: Lite5eSheet, spell_id: Slug, slot_level: int, numbers: SpellNumbers | None = None
) -> ActionSpec:
    numbers = numbers or spell_numbers(sheet, spell_id, slot_level)
    spell = srd().require_spell(spell_id)
    battle = spell.battle
    if battle is None:
        raise Refusal(f"{spell.name} is no battle spell")
    if slot_level < spell.level:
        raise Refusal(f"{spell.name} needs a slot of level {spell.level} or higher")
    steps = slot_level - spell.level if spell.level else 0
    healing = None
    if battle.healing_dice is not None:
        healing = Healing(
            dice=raised_dice(battle.healing_dice, battle.higher_level_dice, steps),
            bonus=numbers.healing_bonus,
        )
    if spell.attack_type is not None:
        kind: ActionKind = "attack"
    elif healing is not None:
        kind = "heal"
    elif spell.save_ability is not None:
        kind = "save"
    elif battle.damage and not battle.riders:
        kind = "auto_hit"
    else:
        kind = "buff"
    damage = battle.damage
    if battle.damage_modifier:
        damage = tuple(
            part.model_copy(update={"bonus": part.bonus + numbers.modifier}) for part in damage
        )
    upgraded = sheet.level >= DICE_UPGRADE_LEVEL
    if healing is None and damage and (first := damage[0].dice) is not None:
        raised = raised_dice(first, battle.higher_level_dice, steps)
        if upgraded:
            raised = raised_dice(raised, battle.cantrip_upgrade, 1)
        damage = (damage[0].model_copy(update={"dice": raised}), *damage[1:])
    riders = battle.riders
    if spell_id == ELDRITCH_BLAST:
        if AGONIZING_BLAST in sheet.pick_ids("invocation"):
            agonized = damage[0].bonus + numbers.modifier
            damage = (damage[0].model_copy(update={"bonus": agonized}), *damage[1:])
        if REPELLING_BLAST in sheet.pick_ids("invocation"):
            riders = (*riders, Rider(rider_id="push", size_max=REPELLING_SIZE))
    return ActionSpec(
        action_id=spell_id,
        name=spell.name,
        kind=kind,
        origin="spell",
        delivery=None if battle.strike_range_feet is not None else spell.attack_type,
        to_hit=None if spell.attack_type is None else numbers.attack_bonus,
        reach_feet=(
            MELEE_REACH_FEET if spell.range == "touch" or spell.attack_type == "melee" else None
        ),
        range_feet=battle.strike_range_feet
        or (spell.range_feet if spell.range == "feet" else None),
        area=battle.area,
        damage=damage,
        healing=healing,
        save=(
            None
            if spell.save_ability is None
            else SaveSpec(ability=spell.save_ability, dc=numbers.save_dc)
        ),
        half_on_save=battle.success == "half",
        riders=riders,
        target_count=(
            battle.target_count
            + battle.targets_per_level * steps
            + (battle.upgrade_targets if upgraded else 0)
        ),
        creature_types=battle.creature_types,
        target_filter=battle.target_filter,
        explosions=max(numbers.modifier, 0) if battle.exploding_dice else 0,
        volley=battle.volley,
        heals_half_dealt=battle.heals_half_dealt,
        missed_damage_parts=battle.missed_damage_parts,
    )


def spell_part(spell_id: Slug, slot_level: int) -> DamagePart:
    spell = srd().require_spell(spell_id)
    battle = spell.battle
    first = None if battle is None or not battle.damage else battle.damage[0]
    if battle is None or first is None or first.dice is None:
        raise ValueError(f"{spell.name} has no battle dice")
    dice = raised_dice(first.dice, battle.higher_level_dice, slot_level - spell.level)
    return first.model_copy(update={"dice": dice})


def shove_ability(sheet: Lite5eSheet) -> Ability:
    if sheet.find_martial_arts_die() is None:
        return "strength"
    return max(MARTIAL_ABILITIES, key=sheet.modifier)


def _martial_arts_part(sheet: Lite5eSheet, weapon: Weapon, part: DamagePart) -> DamagePart:
    die = sheet.find_martial_arts_die()
    if die is None or not is_monk_weapon(weapon):
        return part
    if part.dice is not None:
        count, faces = dice_parts(part.dice)
        if count * (faces + 1) >= die + 1:
            return part
    return part.model_copy(update={"dice": f"1d{die}"})
