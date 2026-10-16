from collections.abc import Collection

from rulehall.core.facts import DiceEvent, Fact, roll
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.lite5e.battle.rows import (
    ally_beside,
    band_between,
    delivery_against,
    engaged_enemies,
    row_of,
)
from rulehall.engines.lite5e.battle.specs import (
    ActionSpec,
    uses_strength,
)
from rulehall.engines.lite5e.battle.state import (
    RAGE,
    REACTION,
    Combatant,
    Effect,
    Fight,
    MemberCombatant,
    OnceMark,
    told,
)
from rulehall.engines.lite5e.data import (
    Ability,
    Condition,
    DamageType,
    Dice,
    FeatureUse,
    Resistance,
    SpecialId,
    srd,
)
from rulehall.engines.lite5e.rules import (
    DICE_UPGRADE_LEVEL,
    EXHAUSTION_PENALTY,
    SHINING_SMITE,
    Edge,
)
from rulehall.engines.lite5e.sheet import (
    BARDIC_DIE_SPEND,
    Lite5eSheet,
    bardic_total,
    combined_edge,
    roll_d20,
)

NEXT_ATTACK_ADVANTAGE = "next-attack-advantage"
HELP = "help"
STEADY_AIM = "steady-aim"
SHILLELAGH: Slug = "shillelagh"
MIRROR_IMAGE: Slug = "mirror-image"
RECKLESS = "reckless"
SACRED_WEAPON = "sacred-weapon"
SACRED_WEAPON_TYPE: DamageType = "radiant"
SACRED_WEAPON_MINIMUM = 1
RAY_OF_ENFEEBLEMENT: Slug = "ray-of-enfeeblement"
SHILLELAGH_WEAPON_IDS: frozenset[Slug] = frozenset({"club", "quarterstaff"})
SHILLELAGH_DICE: Dice = "1d8"
SHILLELAGH_UPGRADED_DICE: Dice = "1d10"
HELPLESS: tuple[Condition, ...] = ("paralyzed", "unconscious")
BARDIC_DIE: Slug = "bardic-inspiration"
JEER: Slug = "jeer"
INNATE_SORCERY_EFFECT: Slug = "innate-sorcery"

type Advantage = tuple[Edge, tuple[str, ...]]


class AttackRoll(Frozen):
    face: int
    total: int
    hit: bool
    critical: bool
    dice: tuple[DiceEvent, ...]
    spends: tuple[str, ...]


class DamageReduction(Frozen):
    name: str
    die: int | None = None
    ability: Ability | None = None
    adds_level: bool = False
    feature_id: Slug | None = None
    use: FeatureUse | None = None
    effect_id: Slug | None = None
    damage_types: frozenset[DamageType] = frozenset()
    bloodying_only: bool = False
    on_hit: bool = False
    once_mark: OnceMark | None = None


DAMAGE_REDUCTIONS: tuple[DamageReduction, ...] = (
    DamageReduction(
        name="Uncanny Dodge",
        feature_id="rogue-uncanny-dodge",
        on_hit=True,
        once_mark=REACTION,
    ),
    DamageReduction(
        name="Deflect Attacks",
        die=10,
        ability="dexterity",
        adds_level=True,
        feature_id="monk-deflect-attacks",
        damage_types=frozenset({"bludgeoning", "piercing", "slashing"}),
        on_hit=True,
        once_mark=REACTION,
    ),
    DamageReduction(
        name="Stone's Endurance",
        die=12,
        ability="constitution",
        use="stones-endurance",
        bloodying_only=True,
        once_mark=REACTION,
    ),
    DamageReduction(name="Resistance", die=4, effect_id="resistance", once_mark="resistance"),
)


def has_special(fight: Fight, combatant: Combatant, special_id: SpecialId) -> bool:
    block = fight.block_or_form_of(combatant)
    return block is not None and block.find_special(special_id) is not None


def is_helpless(fight: Fight, combatant: Combatant) -> bool:
    return fight.hp_of(combatant).current == 0 or any(
        fight.battle.has_condition(combatant.combatant_id, condition) for condition in HELPLESS
    )


def holds_effect(fight: Fight, holder_id: str, effect_id: str) -> bool:
    return fight.battle.find_effect(holder_id, effect_id) is not None


def armor_class(fight: Fight, combatant: Combatant) -> int:
    battle = fight.battle
    shift = sum(battle.effect_bonuses(combatant.combatant_id, "armor-class"))
    floor = max(battle.effect_bonuses(combatant.combatant_id, "minimum-armor-class"), default=0)
    block = fight.block_or_form_of(combatant)
    if block is None:
        held = [effect.effect_id for effect in battle.effects_on(combatant.combatant_id)]
        return max(fight.require_sheet(combatant).armor_class(held) + shift, floor)
    return max(block.armor_class + shift, floor)


def cast_through(sheet: Lite5eSheet, action: ActionSpec, spell_id: Slug) -> ActionSpec:
    weapon = srd().gear.weapons[action.action_id]
    weapon_modifier = sheet.weapon_modifier(weapon, pact=action.pact)
    spell_modifier = sheet.modifier(sheet.spell_ability(spell_id))
    damage_shift = sheet.damage_bonus(
        spell_modifier, off_hand=action.off_hand
    ) - sheet.damage_bonus(weapon_modifier, off_hand=action.off_hand)
    return _raised(action, to_hit=spell_modifier - weapon_modifier, damage=damage_shift)


def buffed(fight: Fight, user: Combatant, action: ActionSpec) -> ActionSpec:
    sheet = fight.sheet_of(user)
    if sheet is None or action.origin != "weapon":
        return action
    held = {effect.effect_id: effect for effect in fight.battle.effects_on(user.combatant_id)}
    found = srd().gear.weapons.get(action.action_id)
    weapon = found is not None
    base_weapon_id = None if found is None else found.base_weapon_id or action.action_id
    if base_weapon_id in SHILLELAGH_WEAPON_IDS and SHILLELAGH in held:
        action = cast_through(sheet, action, SHILLELAGH)
        first = action.damage[0]
        upgraded = sheet.level >= DICE_UPGRADE_LEVEL
        update = {"dice": SHILLELAGH_UPGRADED_DICE if upgraded else SHILLELAGH_DICE}
        action = action.model_copy(
            update={"damage": (first.model_copy(update=update), *action.damage[1:])}
        )
    raise_by = sum(fight.battle.effect_bonuses(user.combatant_id, "weapon"))
    if weapon and raise_by:
        action = _raised(action, to_hit=raise_by, damage=raise_by)
    if weapon and action.delivery == "melee" and SACRED_WEAPON in held:
        sharpened = max(sheet.modifier("charisma"), SACRED_WEAPON_MINIMUM)
        action = _raised(action, to_hit=sharpened, damage=0)
        first = action.damage[0].model_copy(update={"damage_type": SACRED_WEAPON_TYPE})
        action = action.model_copy(update={"damage": (first, *action.damage[1:])})
    rage = sheet.class_level().class_specific.rage_damage_bonus
    if rage is not None and RAGE in held and uses_strength(sheet, action):
        action = _raised(action, to_hit=0, damage=rage)
    return action


def is_reckless(fight: Fight, attacker: Combatant, action: ActionSpec) -> bool:
    sheet = fight.sheet_of(attacker)
    return (
        sheet is not None
        and holds_effect(fight, attacker.combatant_id, RECKLESS)
        and uses_strength(sheet, action)
    )


def blessing(fight: Fight, holder: Combatant) -> tuple[int, tuple[DiceEvent, ...]]:
    total = 0
    events: list[DiceEvent] = []
    for effect, rule in fight.battle.effect_rules_on(holder.combatant_id):
        if rule.roll_die is not None:
            name = srd().require_spell(effect.effect_id).name
            rolled = roll((abs(rule.roll_die),), name, fight.rng, label=name)
            total += rolled.total if rule.roll_die > 0 else -rolled.total
            events.append(rolled.event)
    return total, tuple(events)


def find_bardic_die(fight: Fight, holder: Combatant) -> int | None:
    held = fight.battle.find_effect(holder.combatant_id, BARDIC_DIE)
    return None if held is None else inspiration_die(fight, held.source_id)


def spend_bardic_die(fight: Fight, holder: Combatant) -> None:
    held = fight.battle.find_effect(holder.combatant_id, BARDIC_DIE)
    if held is None:
        raise ValueError(f"{holder.combatant_id} spends a Bardic Inspiration die it does not hold")
    fight.battle.effects.remove(held)


def inspiration_die(fight: Fight, bard_id: str) -> int:
    sheet = fight.require_sheet(fight.battle.require_combatant(bard_id))
    die = sheet.class_level().class_specific.bardic_inspiration_die
    if die is None:
        raise ValueError(f"{bard_id} inspires with no Bardic Inspiration die")
    return die


def jeered(fight: Fight, holder: Combatant) -> tuple[int, tuple[DiceEvent, ...]]:
    jeer = fight.battle.find_effect(holder.combatant_id, JEER)
    if jeer is None:
        return 0, ()
    fight.battle.effects.remove(jeer)
    rolled = roll((inspiration_die(fight, jeer.source_id),), "Jeer", fight.rng, label="Jeer")
    return rolled.total, (rolled.event,)


def innate_sorcery(fight: Fight, caster: Combatant, action: ActionSpec) -> bool:
    sheet = fight.sheet_of(caster)
    return (
        sheet is not None
        and action.origin == "spell"
        and holds_effect(fight, caster.combatant_id, INNATE_SORCERY_EFFECT)
        and action.action_id in sheet.class_spell_ids()
    )


def find_enfeeblement(fight: Fight, holder: Combatant) -> Effect | None:
    return fight.battle.find_effect(holder.combatant_id, RAY_OF_ENFEEBLEMENT)


def spend_duplicate(fight: Fight, attacker: Combatant, target: Combatant) -> bool:
    battle = fight.battle
    image = battle.find_effect(target.combatant_id, MIRROR_IMAGE)
    if image is None or battle.has_condition(attacker.combatant_id, "blinded"):
        return False
    image.uses = (image.uses or 1) - 1
    if not image.uses:
        battle.effects.remove(image)
    return True


def advantage_of(
    fight: Fight, attacker: Combatant, target: Combatant, action: ActionSpec
) -> Advantage:
    battle = fight.battle
    attacker_id, target_id = attacker.combatant_id, target.combatant_id
    close = band_between(fight, attacker, target) == "close"
    down = fight.hp_of(target).current == 0
    reasons: dict[str, Edge] = {}

    def held(holder_id: str, condition: Condition) -> bool:
        return battle.has_condition(holder_id, condition)

    for condition in ("blinded", "frightened", "poisoned", "prone", "restrained"):
        if held(attacker_id, condition):
            reasons[condition] = "disadvantage"
    if any(
        effect.condition == "grappled" and effect.source_id != target_id
        for effect in battle.effects_on(attacker_id)
    ):
        reasons["grappled by another"] = "disadvantage"
    if _is_unseen(fight, attacker_id):
        reasons["unseen"] = "advantage"
    if _is_unseen(fight, target_id):
        reasons["target unseen"] = "disadvantage"
    if is_reckless(fight, attacker, action):
        reasons["reckless"] = "advantage"
    if any(held(target_id, condition) for condition in ("prone", "unconscious")) or down:
        reasons["target prone"] = "advantage" if close else "disadvantage"
    for condition in ("blinded", "restrained", "paralyzed", "stunned", "unconscious", "petrified"):
        if held(target_id, condition):
            reasons[f"target {condition}"] = "advantage"
    if down:
        reasons["target down"] = "advantage"
    if (
        delivery_against(fight, attacker, target, action) == "ranged"
        and row_of(fight, attacker) == "front"
        and engaged_enemies(fight, attacker)
    ):
        reasons["ranged while engaged"] = "disadvantage"
    if battle.light == "dark":
        if not fight.sees_in_dark(attacker):
            reasons["darkness"] = "disadvantage"
        if not fight.sees_in_dark(target):
            reasons["target in darkness"] = "advantage"
    if has_special(fight, attacker, "pack-tactics") and ally_beside(fight, attacker, target):
        reasons["pack tactics"] = "advantage"
    if fight.is_bloodied(attacker) and has_special(fight, attacker, "bloodied-fury"):
        reasons["bloodied fury"] = "advantage"
    for rider in action.riders:
        if rider.rider_id != "conditional-advantage":
            continue
        if rider.condition is None and fight.hp_of(target).shortfall > 0:
            reasons["target wounded"] = "advantage"
        if rider.condition is not None and any(
            effect.condition == rider.condition and effect.source_id == attacker_id
            for effect in battle.effects_on(target_id)
        ):
            reasons[f"target {rider.condition}"] = "advantage"
    if _marks(fight, attacker, target):
        reasons["marked"] = "advantage"
    if action.to_hit is not None and innate_sorcery(fight, attacker, action):
        reasons["innate sorcery"] = "advantage"
    if (
        find_enfeeblement(fight, attacker) is not None
        and action.delivery == "melee"
        and not action.finesse
    ):
        reasons["enfeebled"] = "disadvantage"
    reasons.update(_effect_edges(fight, attacker, target))
    mode = combined_edge(*reasons.values())
    shown = tuple(f"{edge}: {reason}" for reason, edge in reasons.items())
    return mode, shown


def spend_marks(fight: Fight, attacker: Combatant, target: Combatant) -> None:
    for mark in _marks(fight, attacker, target):
        uses = (mark.uses or 1) - 1
        if uses:
            mark.uses = uses
        else:
            fight.battle.effects.remove(mark)


def roll_attack(
    fight: Fight, attacker: Combatant, target: Combatant, action: ActionSpec, mode: Edge
) -> AttackRoll:
    if action.to_hit is None:
        raise ValueError(f"{action.action_id} makes no attack roll")
    armor = armor_class(fight, target)
    sheet = fight.sheet_of(attacker)
    blessed, blessing_dice = blessing(fight, attacker)
    jeer, jeer_dice = jeered(fight, attacker)
    bonus = action.to_hit + blessed - jeer
    lucky = False
    if sheet is not None:
        bonus -= EXHAUSTION_PENALTY * sheet.exhaustion
        lucky = sheet.rerolls_ones()
    face, events, luck_used = roll_d20(action.name, mode, fight.rng, lucky=lucky)
    events[:0] = (*blessing_dice, *jeer_dice)
    spends = ["Luck"] if luck_used else []
    total = face + bonus
    die = find_bardic_die(fight, attacker)
    if die is not None and not _hits(face, total, armor, action) and face != 1:
        raised = bardic_total(total, armor, die, fight.rng, events)
        if raised is not None:
            total = raised
            spends.append(BARDIC_DIE_SPEND)
            spend_bardic_die(fight, attacker)
    if sheet is not None and not _hits(face, total, armor, action) and sheet.inspiration:
        sheet.inspiration = False
        spends.append("Heroic Inspiration")
        face, again, luck_used = roll_d20(action.name, mode, fight.rng, lucky=lucky)
        events.extend(again)
        if luck_used:
            spends.append("Luck")
        total = face + bonus
    hit = _hits(face, total, armor, action)
    point_blank = band_between(fight, attacker, target) == "close"
    critical = hit and (
        face >= action.critical_face or (point_blank and is_helpless(fight, target))
    )
    return AttackRoll(
        face=face,
        total=total,
        hit=hit,
        critical=critical,
        dice=tuple(events),
        spends=tuple(spends),
    )


def attack_facts(
    fight: Fight,
    attacker: Combatant,
    target: Combatant,
    action: ActionSpec,
    rolled: AttackRoll,
    reasons: tuple[str, ...],
) -> list[Fact]:
    outcome = "critical hit" if rolled.critical else "hit" if rolled.hit else "miss"
    notes = "; ".join((*reasons, *(f"spent {spend}" for spend in rolled.spends)))
    who = f"{fight.name_of(attacker)} → {fight.name_of(target)}, {action.name}"
    line = f"{who}: {rolled.total}: {outcome}" + (f" ({notes})" if notes else "")
    return [
        Fact(trace=f"{who}: {rolled.total} vs AC {armor_class(fight, target)}"),
        told(line, rolled.dice),
    ]


def resisted(fight: Fight, target: Combatant, amount: int, damage_type: DamageType | None) -> int:
    if damage_type is None:
        return amount
    warded = any(
        damage_type in (found.damage_types or (effect.damage_type,))
        for effect, rule in fight.battle.effect_rules_on(target.combatant_id)
        for found in rule.modifiers
        if isinstance(found, Resistance)
    )
    sheet = fight.sheet_of(target)
    if sheet is not None:
        warded = warded or damage_type in sheet.resistances()
    block = fight.block_or_form_of(target)
    if block is None:
        return amount // 2 if warded else amount
    return block.resisted(amount, damage_type, warded=warded)


def reduce_damage(
    fight: Fight,
    target: Combatant,
    totals: dict[DamageType | None, int],
    *,
    hit: bool,
) -> tuple[int, list[Fact]]:
    facts: list[Fact] = []
    for reduction in DAMAGE_REDUCTIONS:
        held = (
            None
            if reduction.effect_id is None
            else fight.battle.find_effect(target.combatant_id, reduction.effect_id)
        )
        taken = _resisted_totals(fight, target, totals)
        amount = sum(taken.values())
        taken_types: list[DamageType | None] = [
            damage_type for damage_type, part in taken.items() if part > 0
        ]
        if amount > 0 and _reduces(fight, target, reduction, held, amount, taken_types, hit=hit):
            cut, dice = _reduction_cut(fight, target, reduction, sum(totals.values()))
            totals = _cut_totals(totals, cut, _cut_order(held, totals, taken))
            dropped = amount - sum(_resisted_totals(fight, target, totals).values())
            facts.append(
                told(f"{fight.name_of(target)}: {reduction.name}, -{dropped} damage", dice)
            )
    return sum(_resisted_totals(fight, target, totals).values()), facts


def _raised(action: ActionSpec, *, to_hit: int, damage: int) -> ActionSpec:
    if action.to_hit is None:
        raise ValueError(f"{action.action_id} makes no attack roll")
    first = action.damage[0]
    return action.model_copy(
        update={
            "to_hit": action.to_hit + to_hit,
            "damage": (
                first.model_copy(update={"bonus": first.bonus + damage}),
                *action.damage[1:],
            ),
        }
    )


def _reduces(
    fight: Fight,
    target: Combatant,
    reduction: DamageReduction,
    held: Effect | None,
    amount: int,
    damage_types: Collection[DamageType | None],
    *,
    hit: bool,
) -> bool:
    if not isinstance(target, MemberCombatant):
        return False
    if reduction.effect_id is not None:
        return (
            held is not None
            and held.damage_type in damage_types
            and _claim_once(fight, target, reduction.once_mark)
        )
    sheet = fight.sheet_of(target)
    if (reduction.on_hit and not hit) or sheet is None:
        return False
    hp = sheet.vitals.hp
    return (
        (reduction.feature_id is None or reduction.feature_id in sheet.feature_ids())
        and (reduction.use is None or sheet.uses_left(reduction.use) > 0)
        and (not reduction.damage_types or not reduction.damage_types.isdisjoint(damage_types))
        and (
            not reduction.bloodying_only or 2 * (hp.current + sheet.temp_hp - amount) <= hp.maximum
        )
        and not fight.battle.is_incapacitated(target.combatant_id)
        and fight.hp_of(target).current > 0
        and _claim_once(fight, target, reduction.once_mark)
    )


def _reduction_cut(
    fight: Fight, target: Combatant, reduction: DamageReduction, amount: int
) -> tuple[int, tuple[DiceEvent, ...]]:
    if reduction.use is not None:
        fight.require_sheet(target).spend_use(reduction.use)
    if reduction.die is None:
        return amount - amount // 2, ()
    rolled = roll((reduction.die,), reduction.name, fight.rng, label=reduction.name)
    return max(rolled.total + _reduction_bonus(fight, target, reduction), 0), (rolled.event,)


def _resisted_totals(
    fight: Fight, target: Combatant, totals: dict[DamageType | None, int]
) -> dict[DamageType | None, int]:
    return {
        damage_type: resisted(fight, target, part, damage_type)
        for damage_type, part in totals.items()
    }


def _cut_order(
    held: Effect | None,
    totals: dict[DamageType | None, int],
    taken: dict[DamageType | None, int],
) -> list[DamageType | None]:
    return sorted(
        totals,
        key=lambda damage_type: (
            held is None or damage_type != held.damage_type,
            taken[damage_type] < totals[damage_type],
        ),
    )


def _cut_totals(
    totals: dict[DamageType | None, int], cut: int, order: list[DamageType | None]
) -> dict[DamageType | None, int]:
    left = dict(totals)
    for damage_type in order:
        taken = min(left[damage_type], cut)
        cut -= taken
        left[damage_type] -= taken
    return left


def _reduction_bonus(fight: Fight, target: Combatant, reduction: DamageReduction) -> int:
    if reduction.ability is None:
        return 0
    sheet = fight.require_sheet(target)
    return sheet.modifier(reduction.ability) + (sheet.level if reduction.adds_level else 0)


def _claim_once(fight: Fight, member: MemberCombatant, mark: OnceMark | None) -> bool:
    battle = fight.battle
    if mark is None:
        return True
    if battle.used_once(member, mark):
        return False
    battle.use_once(member, mark)
    return True


def _is_unseen(fight: Fight, combatant_id: str) -> bool:
    battle = fight.battle
    return battle.has_condition(combatant_id, "invisible") and not holds_effect(
        fight, combatant_id, SHINING_SMITE
    )


def _effect_edges(fight: Fight, attacker: Combatant, target: Combatant) -> dict[str, Edge]:
    battle = fight.battle
    block = fight.stat_block_of(attacker)
    edges = [
        *battle.effect_edges(attacker.combatant_id, "attack"),
        *battle.effect_edges(
            target.combatant_id, "attacked", None if block is None else block.creature_type
        ),
    ]
    return {edge.reason or "": edge.kind for edge in edges}


def _hits(face: int, total: int, armor: int, action: ActionSpec) -> bool:
    if face == 1:
        return False
    return face >= action.critical_face or total >= armor


def _marks(fight: Fight, attacker: Combatant, target: Combatant) -> list[Effect]:
    battle = fight.battle
    marks = [
        effect
        for effect in battle.effects_on(target.combatant_id)
        if effect.effect_id == NEXT_ATTACK_ADVANTAGE
        or (
            effect.effect_id == HELP
            and effect.source_id != attacker.combatant_id
            and battle.require_combatant(effect.source_id).side == attacker.side
        )
    ]
    marks.extend(
        effect
        for effect in battle.effects_on(attacker.combatant_id)
        if effect.effect_id == STEADY_AIM
    )
    return marks
