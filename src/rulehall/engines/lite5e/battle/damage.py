from collections.abc import Sequence
from typing import Literal

from rulehall.core.facts import DiceEvent, Fact, roll
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.battle.attack import (
    advantage_of,
    attack_facts,
    blessing,
    buffed,
    find_bardic_die,
    find_enfeeblement,
    has_special,
    holds_effect,
    is_reckless,
    jeered,
    reduce_damage,
    resisted,
    roll_attack,
    spend_bardic_die,
    spend_duplicate,
    spend_marks,
)
from rulehall.engines.lite5e.battle.foes import nearest_key
from rulehall.engines.lite5e.battle.morale import check_morale
from rulehall.engines.lite5e.battle.rows import (
    ally_beside,
    area_cap,
    area_target_cap,
    area_targets,
    band_between,
    enemies_of,
    engaged_enemies,
    is_charmed_by,
    leaves_the_front,
    reaches,
    require_reach,
    row_of,
    target_refusal,
)
from rulehall.engines.lite5e.battle.specs import (
    ActionSpec,
    SaveSpec,
    spell_part,
    stat_block_action,
    unarmed_action,
)
from rulehall.engines.lite5e.battle.state import (
    HELD_IN_PLACE,
    INCAPACITATING,
    RAGE,
    REACTION,
    SIZES,
    WILD_SHAPE,
    Combatant,
    Effect,
    Fight,
    FoeCombatant,
    MemberCombatant,
    PickedVariant,
    TurnMark,
    ended_facts,
    told,
)
from rulehall.engines.lite5e.battle.variants import variant_damage_parts, variant_fits
from rulehall.engines.lite5e.data import (
    Ability,
    ActionFollowUp,
    Condition,
    DamagePart,
    DamageType,
    Dice,
    EffectEnd,
    EffectRule,
    FeatureUse,
    Healing,
    Immunity,
    Rider,
    Size,
    Skill,
    SpecialId,
    dice_parts,
    modifier,
    srd,
)
from rulehall.engines.lite5e.rules import (
    CHECK_DISADVANTAGE_CONDITIONS,
    ELDRITCH_MIND,
    FIEND_PATRON,
    FRENZY,
    HUNTER,
    LARGE_FORM,
    POTENT_CANTRIP,
    POWERFUL_BUILD,
    RELENTLESS_ENDURANCE,
    SLEEP,
    SLEEP_FAILED,
    TRANCE,
    Edge,
)
from rulehall.engines.lite5e.sheet import (
    TestRoll,
    check_name,
    combined_edge,
    roll_healing,
    roll_test,
)

GREAT_WEAPON_FIGHTING: Slug = "great-weapon-fighting"
SAVAGE_ATTACKER: Slug = "savage-attacker"
GREAT_WEAPON_FLOOR = 3
EMPOWERED_FACE = 2
EMPOWERED_SPELL = "Empowered Spell"
FORM_ABILITIES: frozenset[Ability] = frozenset({"strength", "dexterity", "constitution"})
UNDEAD_FORTITUDE_BASE = 5
CONCENTRATION_DC_MIN = 10
NO_HEALING = "no-healing"
NO_OPPORTUNITY_ATTACK = "no-opportunity-attack"
SAVE_FAILING: tuple[Condition, ...] = ("paralyzed", "petrified", "stunned", "unconscious")
BODY_ABILITIES: frozenset[Ability] = frozenset({"strength", "dexterity"})
BEACON_OF_HOPE: Slug = "beacon-of-hope"
COLOSSUS_SLAYER_DICE: Dice = "1d8"
FRENZY_DIE = 6
ENFEEBLEMENT_DIE = 8
ATHLETICS: tuple[Ability, Skill] = ("strength", "athletics")
ACROBATICS: tuple[Ability, Skill] = ("dexterity", "acrobatics")
OIL: Slug = "oil"
NET: Slug = "net"
ANTITOXIN: Slug = "antitoxin"
RAMPAGE: Slug = "rampage"
REGENERATION_STOPPED = Rider(rider_id="effect", ends="target-next-turn-end")
PRONE = Rider(rider_id="condition", condition="prone")
FALLEN: Slug = "fallen"
HILLS_TUMBLE: Slug = "hills-tumble"
FIRE_AURA: SpecialId = "fire-aura"
HILLS_TUMBLE_SIZE: Size = "large"
STORMS_THUNDER = DamagePart(dice="1d8", bonus=0, damage_type="thunder")
STRIKING_ANCESTRY: tuple[tuple[FeatureUse, DamagePart, str], ...] = (
    ("fires-burn", DamagePart(dice="1d10", bonus=0, damage_type="fire"), "Fire's Burn"),
    ("frosts-chill", DamagePart(dice="1d6", bonus=0, damage_type="cold"), "Frost's Chill"),
)


class Dealt(Frozen):
    amount: int
    damage_type: DamageType | None


class DamageRoll(Frozen):
    dealt: tuple[Dealt, ...]
    dice: tuple[DiceEvent, ...]
    sneak_attack: bool = False

    def halved(self) -> "DamageRoll":
        spare = sum(part.amount for part in self.dealt) // 2
        spare -= sum(part.amount // 2 for part in self.dealt)
        halves: list[Dealt] = []
        for part in self.dealt:
            rounded_up = int(spare > 0 and part.amount % 2 == 1)
            spare -= rounded_up
            halves.append(part.model_copy(update={"amount": part.amount // 2 + rounded_up}))
        return self.model_copy(update={"dealt": tuple(halves)})

    def totals(self) -> dict[DamageType | None, int]:
        totals: dict[DamageType | None, int] = {}
        for part in self.dealt:
            totals[part.damage_type] = totals.get(part.damage_type, 0) + part.amount
        return totals


def resolve(
    fight: Fight,
    user: Combatant,
    action: ActionSpec,
    targets: Sequence[Combatant],
    variant: PickedVariant | None = None,
) -> list[Fact]:
    hit = require_targets(fight, user, action, targets)
    facts: list[Fact] = []
    if variant is not None and variant.variant.effect is not None:
        assert isinstance(user, MemberCombatant)
        facts.extend(_pay_variant(fight, user, variant))
    action = buffed(fight, user, action)
    if action.area is None:
        if action.volley:
            hit = [*hit, *[hit[-1]] * (action.target_count - len(hit))]
        standing = [fight.is_standing(target) for target in hit]
        for target, stood in zip(hit, standing, strict=True):
            if action.volley and not (
                fight.is_standing(user)
                and any(fight.is_standing(enemy) for enemy in enemies_of(fight, user))
            ):
                break
            if (stood and not fight.is_standing(target)) or not reaches(
                fight, user, target, action
            ):
                continue
            carried = (
                variant
                if variant is not None
                and isinstance(user, MemberCombatant)
                and variant_fits(fight, user, action, variant)
                else None
            )
            facts.extend(_resolve_target(fight, user, action, target, carried, None))
            if action.kind == "attack":
                ended = fight.battle.end_effects_on(user.combatant_id, "attack")
                facts.extend(ended_facts(fight, ended))
    else:
        rolled = roll_damage(fight, user, hit[0], action) if action.damage else None
        facts.extend(
            fact
            for target in hit
            for fact in _resolve_target(fight, user, action, target, None, rolled)
        )
        for group_id in dict.fromkeys(t.person_id for t in hit if isinstance(t, FoeCombatant)):
            facts.extend(check_morale(fight, group_id, "harm"))
    return facts


def require_targets(
    fight: Fight, user: Combatant, action: ActionSpec, targets: Sequence[Combatant]
) -> list[Combatant]:
    if action.area is not None:
        hit = area_targets(fight, user, targets, area_target_cap(action))
    elif not 1 <= len(targets) <= action.target_count:
        raise Refusal(f"{action.name} takes 1 to {action.target_count} targets")
    else:
        hit = list(targets)
    for target in hit:
        if refusal := target_refusal(fight, user, target, action.target_filter):
            raise Refusal(refusal)
        require_reach(fight, user, target, action)
        if action.creature_types and fight.creature_type_of(target) not in action.creature_types:
            raise Refusal(f"{action.name} cannot affect {fight.name_of(target)}")
    return hit


def roll_damage(
    fight: Fight,
    user: Combatant,
    target: Combatant,
    action: ActionSpec,
    *,
    critical: bool = False,
    mode: Edge = "none",
    hit: bool = False,
    variant: PickedVariant | None = None,
) -> DamageRoll:
    parts = list(action.damage)
    for rider in action.riders:
        if rider.rider_id == "bloodied-damage" and fight.is_bloodied(user) and rider.damage:
            parts = [rider.damage]
    parts.extend(
        rider.damage
        for rider in action.riders
        if rider.rider_id == "advantage-damage" and mode == "advantage" and rider.damage
    )
    sheet = fight.sheet_of(user)
    feats = () if sheet is None or action.origin != "weapon" else sheet.feat_ids()
    great_weapon = GREAT_WEAPON_FIGHTING in feats and action.two_handed
    savage = (
        SAVAGE_ATTACKER in feats
        and isinstance(user, MemberCombatant)
        and not fight.battle.used_once(user, "savage-attacker")
    )
    if savage and isinstance(user, MemberCombatant):
        fight.battle.use_once(user, "savage-attacker")
    rolled = roll_parts(
        fight,
        parts,
        action.name,
        critical=critical,
        great_weapon=great_weapon,
        savage=savage,
        empowered=action.origin == "spell",
        explosions=action.explosions,
    )
    dealt = list(rolled.dealt)
    dice = list(rolled.dice)
    costs_a_die = variant is not None and variant.variant.cost == "sneak-attack-die"
    sneak = _sneak_attack(fight, user, target, action, mode, cost=int(costs_a_die))
    extras = [] if sneak is None else [("Sneak Attack", sneak)]
    if hit:
        extras.extend(_hit_parts(fight, user, target, action, variant))
    for label, part in extras:
        added = roll_parts(fight, [part], label, critical=critical)
        dealt.extend(added.dealt)
        dice.extend(added.dice)
    enfeebled = find_enfeeblement(fight, user)
    if enfeebled is not None and dealt:
        name = srd().require_spell(enfeebled.effect_id).name
        cut = roll((ENFEEBLEMENT_DIE,), name, fight.rng, label=name)
        dice.append(cut.event)
        dealt[0] = dealt[0].model_copy(update={"amount": max(dealt[0].amount - cut.total, 0)})
    return DamageRoll(dealt=tuple(dealt), dice=tuple(dice), sneak_attack=sneak is not None)


def take_damage(
    fight: Fight,
    source: Combatant,
    target: Combatant,
    damage: DamageRoll,
    *,
    critical: bool = False,
    hit: bool = False,
    morale: bool = True,
) -> tuple[int, list[Fact]]:
    totals, facts = _burning_oil(fight, target, damage.totals())
    amount, reduced = reduce_damage(fight, target, totals, hit=hit)
    facts.extend(reduced)
    name = fight.name_of(target)
    types = ", ".join(dict.fromkeys(p.damage_type for p in damage.dealt if p.damage_type))
    if isinstance(target, FoeCombatant):
        taken = target.take_damage(amount, source.combatant_id)
        facts.append(told(f"{name} takes {amount} {types or 'untyped'} damage", damage.dice))
        facts.extend(_stop_regeneration(fight, target, damage))
        if taken.dropped:
            facts.extend(_undead_fortitude(fight, target, amount, damage, critical=critical))
    else:
        person = fight.require_member(target.combatant_id)
        was_down = person.require_vitals().hp.current == 0
        taken = person.take_damage(amount, critical=critical)
        hp = fight.hp_of(target)
        line = f"{name}: -{taken.dealt} HP → {hp}" if not was_down else f"{name} is hit while down"
        facts.append(told(line, damage.dice))
        sheet = person.sheet
        if (
            taken.dropped
            and not taken.died
            and sheet is not None
            and RELENTLESS_ENDURANCE in sheet.trait_ids()
            and sheet.uses_left("relentless-endurance") > 0
        ):
            sheet.spend_use("relentless-endurance")
            _ = sheet.vitals.heal(1)
            facts.append(told(f"{name}: Relentless Endurance, stays up at 1 HP"))
        elif taken.died:
            facts.append(told(f"{name} dies"))
        elif taken.dropped:
            facts.append(told(f"{name} falls"))
            facts.extend(lay(fight, target, target, PRONE, FALLEN, None))
        if fight.hp_of(target).current == 0 and (taken.dropped or taken.died):
            facts.extend(ended_facts(fight, fight.battle.stop_turns(target.combatant_id)))
            facts.extend(release_incapacitated(fight, target))
    if amount > 0:
        facts.extend(ended_facts(fight, fight.battle.end_effects_on(target.combatant_id, "damage")))
    facts.extend(_concentration(fight, target, amount))
    if isinstance(target, FoeCombatant):
        if target.hp.current == 0:
            facts.append(told(f"{name} drops"))
            facts.extend(ended_facts(fight, fight.battle.stop_turns(target.combatant_id)))
            facts.extend(_move_marks(fight, target))
            facts.extend(_dark_ones_blessing(fight, source, target))
            facts.extend(_death_burst(fight, target))
        if amount > 0 and morale:
            facts.extend(check_morale(fight, target.person_id, "harm"))
    return amount, [*facts, *_storms_thunder(fight, source, target, amount)]


def roll_save(
    fight: Fight,
    target: Combatant,
    save: SaveSpec,
    *,
    against: Condition | None,
    spell: bool,
    edge: Edge = "none",
) -> TestRoll:
    battle = fight.battle
    target_id = target.combatant_id
    if save.ability in BODY_ABILITIES and (
        fight.hp_of(target).current == 0
        or any(battle.has_condition(target_id, condition) for condition in SAVE_FAILING)
    ):
        return TestRoll(face=0, total=0, dc=save.dc, success=False, dice=(), spends=())
    edges: list[Edge] = [edge]
    edges.extend(
        found.kind for found in battle.effect_edges(target_id, "save", save.ability, against)
    )
    if save.ability == "strength" and find_enfeeblement(fight, target) is not None:
        edges.append("disadvantage")
    if save.ability == "dexterity" and battle.has_condition(target_id, "restrained"):
        edges.append("disadvantage")
    if spell and has_special(fight, target, "magic-resistance"):
        edges.append("advantage")
    if save.heightened_id == target_id:
        edges.append("disadvantage")
    mode = combined_edge(*edges)
    blessed, blessing_dice = blessing(fight, target)
    jeer, jeer_dice = jeered(fight, target)
    effect_bonus = sum(battle.effect_bonuses(target_id, "save", save.ability))
    shift = blessed - jeer + effect_bonus + _form_shift(fight, target, save)
    shifted = save.dc - shift
    if isinstance(target, FoeCombatant):
        test = target.roll_save(save.ability, shifted, mode, fight.rng)
    else:
        member = fight.require_member(target.combatant_id)
        test = member.roll_save(
            save.ability,
            shifted,
            mode,
            fight.rng,
            against=against,
            bardic_die=find_bardic_die(fight, target),
        )
        if test.bardic_die_spent:
            spend_bardic_die(fight, target)
    return test.model_copy(
        update={
            "total": test.total + shift,
            "dc": save.dc,
            "dice": (*blessing_dice, *jeer_dice, *test.dice),
        }
    )


def save_facts(fight: Fight, target: Combatant, save: SaveSpec, test: TestRoll) -> list[Fact]:
    name = fight.name_of(target)
    outcome = "success" if test.success else "failure"
    spends = "".join(f", spent {spend}" for spend in test.spends)
    return [
        Fact(trace=f"{name}: {save.ability} save {test.total} vs DC {save.dc}"),
        told(f"{name}: {save.ability} save{spends} → {outcome}", test.dice),
    ]


def repeat_saves(fight: Fight, holder: Combatant) -> list[Fact]:
    battle = fight.battle
    name = fight.name_of(holder)
    held = battle.effects_on(holder.combatant_id)
    saves: dict[tuple[Slug, Slug], Effect] = {}
    for effect in held:
        if effect.save_ends is not None:
            _ = saves.setdefault((effect.source_id, effect.effect_id), effect)
    facts: list[Fact] = []
    for (source_id, effect_id), effect in saves.items():
        save = effect.save_ends
        assert save is not None
        spell = effect_id in srd().spells.spells
        test = roll_save(fight, holder, save, against=effect.condition, spell=spell)
        facts.extend(save_facts(fight, holder, save, test))
        pair = [e for e in held if (e.source_id, e.effect_id) == (source_id, effect_id)]
        if test.success:
            for ended in pair:
                battle.effects.remove(ended)
            facts.extend(ended_facts(fight, pair))
            continue
        if effect_id == SLEEP:
            for held_effect in pair:
                held_effect.condition = SLEEP_FAILED
                held_effect.save_ends = None
            facts.append(told(f"{name} is {SLEEP_FAILED}"))
    return facts


def escape(fight: Fight, holder: Combatant, freer: Combatant, source_id: str) -> list[Fact]:
    battle = fight.battle
    name = fight.name_of(holder)
    holds = battle.escape_holds(holder.combatant_id)
    if not holds:
        raise Refusal(f"{name} has nothing to escape")
    held = next((effect for effect in holds if effect.source_id == source_id), None)
    if held is None or held.escape_dc is None:
        raise Refusal(f"{name} is not held by {source_id}")
    if freer is not holder and (
        held.effect_id != NET
        or freer.side != holder.side
        or band_between(fight, freer, holder) != "close"
    ):
        raise Refusal(f"only {name}, or an ally in its row out of a Net, can make this escape")
    options = (ATHLETICS, ACROBATICS) if held.condition == "grappled" else (ATHLETICS,)
    ability, skill = max(options, key=lambda option: check_bonus(fight, freer, *option))
    sheet = fight.sheet_of(freer)
    powerful = (
        held.condition == "grappled" and sheet is not None and POWERFUL_BUILD in sheet.trait_ids()
    )
    test = roll_check(
        fight, freer, ability, skill, held.escape_dc, "advantage" if powerful else "none"
    )
    outcome = "success" if test.success else "failure"
    facts = [
        Fact(trace=f"{name}: escape, {skill} {test.total} vs DC {held.escape_dc}"),
        told(f"{name}: escape → {outcome}", test.dice),
    ]
    if not test.success:
        return facts
    freed = battle.remove_effects(
        lambda effect: (
            (effect.holder_id, effect.source_id, effect.effect_id)
            == (holder.combatant_id, held.source_id, held.effect_id)
        )
    )
    return [*facts, *ended_facts(fight, freed)]


def lose_concentration(fight: Fight, target: Combatant) -> list[Fact]:
    sheet = fight.sheet_of(target)
    assert sheet is not None and sheet.concentration_spell_id is not None
    spell = srd().require_spell(sheet.concentration_spell_id)
    ended = fight.battle.drop_concentration(target.combatant_id, sheet)
    return [told(f"{fight.name_of(target)} loses {spell.name}"), *ended_facts(fight, ended)]


def opportunity_attack(fight: Fight, mover: Combatant, *, provoking: bool) -> list[Fact]:
    if (
        not provoking
        or row_of(fight, mover) != "front"
        or has_special(fight, mover, "agile")
        or has_special(fight, mover, "flyby")
    ):
        return []
    candidates = [
        (enemy, action)
        for enemy in engaged_enemies(fight, mover)
        if not holds_effect(fight, enemy.combatant_id, NO_OPPORTUNITY_ATTACK)
        and not is_charmed_by(fight, enemy, mover)
        and (action := _melee_action(fight, enemy)) is not None
    ]
    if not candidates:
        return []
    enemy, action = max(candidates, key=lambda pair: pair[1].to_hit or 0)
    line = f"{fight.name_of(enemy)} strikes as {fight.name_of(mover)} falls back"
    return [told(line), *resolve(fight, enemy, action, [mover])]


def change_row(
    fight: Fight, combatant: Combatant, *, provoking: bool, teleport: bool
) -> list[Fact]:
    battle = fight.battle
    name = fight.name_of(combatant)
    freed = battle.release_holds(combatant.combatant_id, HELD_IN_PLACE) if teleport else []
    if battle.is_held(combatant.combatant_id):
        return [told(f"{name} is held in place")]
    provokes = provoking and not teleport and leaves_the_front(fight, combatant)
    facts = opportunity_attack(fight, combatant, provoking=provokes)
    if not fight.is_standing(combatant):
        return facts
    combatant.row = "back" if combatant.row == "front" else "front"
    released = battle.release_grapples(combatant.combatant_id)
    line = told(f"{name} moves to the {combatant.row} row")
    return [*facts, line, *ended_facts(fight, [*freed, *released])]


def start_of_turn_regeneration(fight: Fight, foe: FoeCombatant) -> list[Fact]:
    regeneration = foe.stat_block().find_special("regeneration")
    if regeneration is None or not fight.is_standing(foe) or foe.hp.shortfall == 0:
        return []
    return regain(fight, foe, regeneration.regained_hit_points, ())[1]


def end_of_turn_fire_aura(fight: Fight, combatant: Combatant) -> list[Fact]:
    block = fight.block_or_form_of(combatant)
    aura = None if block is None else block.find_special(FIRE_AURA)
    if (
        aura is None
        or aura.area is None
        or not fight.is_standing(combatant)
        or (
            aura.stops_while_incapacitated and fight.battle.is_incapacitated(combatant.combatant_id)
        )
    ):
        return []
    caught = [
        enemy
        for enemy in enemies_of(fight, combatant)
        if fight.is_standing(enemy) and band_between(fight, combatant, enemy) == "close"
    ][: area_cap(aura.area)]
    if not caught:
        return []
    rolled = roll_parts(fight, aura.damage, "Fire Aura")
    facts = [told(f"{fight.name_of(combatant)}'s aura burns")]
    for target in caught:
        facts.extend(take_damage(fight, combatant, target, rolled)[1])
        rolled = rolled.model_copy(update={"dice": ()})
        if fight.is_standing(target):
            facts.extend(
                fact
                for rider in aura.riders
                for fact in lay(fight, combatant, target, rider, FIRE_AURA, None)
            )
    return facts


def apply_rider(
    fight: Fight,
    user: Combatant,
    target: Combatant,
    action: ActionSpec,
    rider: Rider,
    slot_level: int | None = None,
) -> list[Fact]:
    match rider.rider_id:
        case "condition" | "effect":
            if not fits_size(fight.size_of(target), rider.size_max):
                return []
            if rider.ends == "escape" and rider.dc is None:
                rider = rider.model_copy(update={"dc": _escape_dc(action)})
            return lay(fight, user, target, rider, action.action_id, action.save, slot_level)
        case "save-condition":
            if rider.ability is None or rider.dc is None:
                raise ValueError(f"{action.action_id} lays a save rider with no save")
            if refused := _immunity(fight, target, rider, action.action_id):
                return [told(f"{fight.name_of(target)} is immune to {refused}")]
            save = SaveSpec(ability=rider.ability, dc=rider.dc)
            test = roll_save(fight, target, save, against=rider.condition, spell=False)
            facts = save_facts(fight, target, save, test)
            if test.success:
                return facts
            return [*facts, *lay(fight, user, target, rider, action.action_id, save)]
        case "grapple":
            if not fits_size(fight.size_of(target), rider.size_max):
                return []
            grip = rider.model_copy(update={"condition": "grappled", "ends": "escape"})
            return lay(fight, user, target, grip, action.action_id, action.save)
        case "advantage-damage" | "conditional-advantage" | "bloodied-damage":
            return []
        case "push":
            if not fits_size(fight.size_of(target), rider.size_max):
                return []
            return push_back(fight, target)


def lay(
    fight: Fight,
    source: Combatant,
    target: Combatant,
    rider: Rider,
    effect_id: Slug,
    save: SaveSpec | None,
    slot_level: int | None = None,
) -> list[Fact]:
    name = fight.name_of(target)
    effect_id = rider.effect_id or effect_id
    if refused := _immunity(fight, target, rider, effect_id):
        return [told(f"{name} is immune to {refused}")]
    effect = Effect(
        holder_id=target.combatant_id,
        source_id=source.combatant_id,
        effect_id=effect_id,
        condition=rider.condition,
        uses=rider.uses,
        ends_on=rider.ends_on,
        slot_level=slot_level,
    )
    escape_dc = rider.dc if rider.dc is not None else None if save is None else save.dc
    set_effect_end(fight, effect, rider.ends, save, escape_dc)
    fight.battle.replace_effect(effect)
    if rider.condition is None:
        rule = srd().battle_effects.effects.get(effect_id)
        state = None if rule is None else rule.state
        return [] if state is None else [told(f"{name} is {state}")]
    facts = [told(f"{name} is {rider.condition}")]
    if rider.condition not in INCAPACITATING:
        return facts
    return [*facts, *release_incapacitated(fight, target)]


def set_effect_end(
    fight: Fight,
    effect: Effect,
    ends: EffectEnd | None,
    save: SaveSpec | None,
    escape_dc: int | None = None,
) -> None:
    battle = fight.battle
    match ends:
        case "target-next-turn-end":
            effect.ends = battle.next_turn_mark(effect.holder_id, "end")
        case "target-next-turn-start":
            effect.ends = battle.next_turn_mark(effect.holder_id, "start")
        case "source-next-turn-end":
            effect.ends = battle.next_turn_mark(effect.source_id, "end")
        case "source-next-turn-start":
            effect.ends = battle.next_turn_mark(effect.source_id, "start")
        case "source-turn-end":
            turns = battle.require_combatant(effect.source_id).turns
            effect.ends = TurnMark(combatant_id=effect.source_id, turn=turns, edge="end")
        case "save-each-turn":
            if save is None:
                raise ValueError(f"{effect.effect_id} repeats a save it does not have")
            effect.save_ends = save
        case "escape":
            if escape_dc is None:
                raise ValueError(f"{effect.effect_id} holds with no escape DC")
            effect.escape_dc = escape_dc
        case None:
            pass


def follow_up(fight: Fight, member: MemberCombatant, then: ActionFollowUp) -> list[Fact]:
    budget = fight.battle.budget
    match then:
        case "disengage":
            budget.disengaged = True
        case "leave":
            member.withdrawal = "left"
            stopped = ended_facts(fight, fight.battle.stop_turns(member.combatant_id))
            return [told(f"{fight.name_of(member)} leaves the battle"), *stopped]
        case "extra-action":
            budget.extra_actions += 1
        case "lift-darkness":
            if fight.battle.light == "dark":
                fight.battle.light = "dim"
                return [told("The holy light lifts the darkness")]
        case "spend-move":
            budget.move = False
        case "proficiency-temp-hp":
            sheet = fight.require_sheet(member)
            _ = sheet.gain_temp_hp(sheet.proficiency_bonus())
        case "teleport":
            return change_row(fight, member, provoking=False, teleport=True)
        case "withdraw":
            return change_row(fight, member, provoking=False, teleport=False)
        case "drop-concentration":
            if fight.require_sheet(member).concentration_spell_id:
                return lose_concentration(fight, member)
    return []


def release_incapacitated(fight: Fight, target: Combatant) -> list[Fact]:
    battle = fight.battle
    facts = ended_facts(fight, battle.release_grapples(target.combatant_id))
    sheet = fight.sheet_of(target)
    if sheet is not None and sheet.concentration_spell_id:
        facts.extend(lose_concentration(fight, target))
    rage = battle.find_effect(target.combatant_id, RAGE)
    if rage is not None:
        battle.effects.remove(rage)
        facts.append(told(f"{fight.name_of(target)}'s rage ends"))
    return [*facts, *end_wild_shape(fight, target)]


def end_wild_shape(fight: Fight, combatant: Combatant) -> list[Fact]:
    shape = fight.battle.find_effect(combatant.combatant_id, WILD_SHAPE)
    if shape is None:
        return []
    fight.battle.effects.remove(shape)
    return [told(f"{fight.name_of(combatant)}'s Wild Shape ends")]


def push_back(fight: Fight, target: Combatant) -> list[Fact]:
    if target.row == "back":
        return []
    target.row = "back"
    battle = fight.battle
    released = [
        *battle.release_grapples(target.combatant_id),
        *battle.release_holds(target.combatant_id, ("grappled",)),
    ]
    line = told(f"{fight.name_of(target)} is pushed to the back row")
    return [line, *ended_facts(fight, released)]


def deal_extra(
    fight: Fight,
    source: Combatant,
    target: Combatant,
    parts: Sequence[DamagePart],
    label: str,
    line: str,
) -> list[Fact]:
    rolled = roll_parts(fight, parts, label)
    return [told(line), *take_damage(fight, source, target, rolled)[1]]


def pay_spell_slot(fight: Fight, caster: MemberCombatant, spell_id: Slug, slot_level: int) -> None:
    budget = fight.battle.budget
    if fight.require_sheet(caster).pay_cast(spell_id, slot_level, slot_open=not budget.slot_spent):
        budget.slot_spent = True


def start_concentration(fight: Fight, caster: MemberCombatant, spell_id: Slug) -> list[Fact]:
    sheet = fight.require_sheet(caster)
    if not srd().require_spell(spell_id).concentration:
        return []
    facts = [] if sheet.concentration_spell_id is None else lose_concentration(fight, caster)
    sheet.concentration_spell_id = spell_id
    return facts


def fits_size(size: Size, size_max: Size | None) -> bool:
    return size_max is None or SIZES.index(size) <= SIZES.index(size_max)


def roll_parts(
    fight: Fight,
    parts: Sequence[DamagePart],
    label: str,
    *,
    critical: bool = False,
    great_weapon: bool = False,
    savage: bool = False,
    empowered: bool = False,
    explosions: int = 0,
) -> DamageRoll:
    budget = fight.battle.budget
    dealt: list[Dealt] = []
    events: list[DiceEvent] = []
    floor = GREAT_WEAPON_FLOOR if great_weapon else 1
    for index, part in enumerate(parts):
        best = 0
        if part.dice is not None:
            count, faces = dice_parts(part.dice)
            pool = (faces,) * (count * 2 if critical else count)
            for _ in range(2 if savage and index == 0 else 1):
                rolled = roll(pool, label, fight.rng, label=label)
                events.append(rolled.event)
                kept = list(rolled.event.rolled)
                rerolls = budget.empowered_rerolls if empowered else 0
                low = [at for at, face in enumerate(kept) if face <= EMPOWERED_FACE][:rerolls]
                if low:
                    budget.empowered_rerolls -= len(low)
                    again = roll(
                        (faces,) * len(low), EMPOWERED_SPELL, fight.rng, label=EMPOWERED_SPELL
                    )
                    events.append(again.event)
                    for at, face in zip(low, again.event.rolled, strict=True):
                        kept[at] = face
                bursts = kept.count(faces)
                while bursts and explosions:
                    burst = roll((faces,), label, fight.rng, label=label)
                    events.append(burst.event)
                    kept.append(burst.total)
                    explosions -= 1
                    bursts += int(burst.total == faces) - 1
                best = max(best, sum(max(face, floor) for face in kept))
        dealt.append(Dealt(amount=max(best + part.bonus, 0), damage_type=part.damage_type))
    return DamageRoll(dealt=tuple(dealt), dice=tuple(events))


def check_bonus(fight: Fight, combatant: Combatant, ability: Ability, skill: Skill) -> int:
    sheet = fight.sheet_of(combatant)
    if sheet is not None:
        return sheet.check_bonus(ability, skill, None)
    block = fight.stat_block_of(combatant)
    assert block is not None
    return block.check_bonus(ability, skill)


def roll_check(
    fight: Fight, combatant: Combatant, ability: Ability, skill: Skill, dc: int, edge: Edge
) -> TestRoll:
    held = fight.battle.effects_on(combatant.combatant_id)
    mighty = ability == "strength" and any(e.effect_id in (LARGE_FORM, RAGE) for e in held)
    hindered = any(effect.condition in CHECK_DISADVANTAGE_CONDITIONS for effect in held)
    edge = combined_edge(
        edge,
        "advantage" if mighty else "none",
        "disadvantage" if hindered else "none",
    )
    if isinstance(combatant, MemberCombatant):
        member = fight.require_member(combatant.combatant_id)
        test = member.roll_check(
            ability,
            skill,
            None,
            dc,
            edge,
            fight.rng,
            guided=False,
            bardic_die=find_bardic_die(fight, combatant),
            in_battle=True,
        )
        if test.bardic_die_spent:
            spend_bardic_die(fight, combatant)
        return test
    bonus = check_bonus(fight, combatant, ability, skill)
    return roll_test(check_name(ability, skill, None), bonus, dc, edge, fight.rng)


def heal(fight: Fight, target: Combatant, label: str, healing: Healing) -> list[Fact]:
    count, faces = dice_parts(healing.dice)
    if holds_effect(fight, target.combatant_id, BEACON_OF_HOPE):
        return regain(fight, target, max(count * faces + healing.bonus, 0), ())[1]
    amount, event = roll_healing(healing, label, fight.rng)
    return regain(fight, target, amount, (event,))[1]


def stabilize(fight: Fight, target: Combatant) -> Fact:
    fight.require_member(target.combatant_id).require_vitals().stable = True
    return told(f"{fight.name_of(target)} is stable")


def regain(
    fight: Fight, target: Combatant, amount: int, dice: tuple[DiceEvent, ...]
) -> tuple[int, list[Fact]]:
    name = fight.name_of(target)
    if holds_effect(fight, target.combatant_id, NO_HEALING):
        return 0, [told(f"{name} cannot regain HP")]
    if isinstance(target, FoeCombatant):
        return target.hp.adjust(amount), [told(f"{name} regains HP", dice)]
    healed = fight.require_member(target.combatant_id).require_vitals().heal(amount)
    return healed, [told(f"{name}: +{healed} HP → {fight.hp_of(target)}", dice)]


def _resolve_target(
    fight: Fight,
    user: Combatant,
    action: ActionSpec,
    target: Combatant,
    variant: PickedVariant | None,
    area_damage: DamageRoll | None,
) -> list[Fact]:
    morale = area_damage is None
    if action.kind == "attack":
        mode, reasons = advantage_of(fight, user, target, action)
        rolled = roll_attack(fight, user, target, action, mode)
        spend_marks(fight, user, target)
        facts = attack_facts(fight, user, target, action, rolled, reasons)
        if not rolled.hit and (missed := _missed_action(fight, user, action)) is not None:
            damage = roll_damage(fight, user, target, missed, mode=mode).halved()
            return [*facts, *take_damage(fight, user, target, damage)[1]]
        if not rolled.hit:
            return facts
        if spend_duplicate(fight, user, target):
            line = f"{fight.name_of(user)} strikes a mirror image of {fight.name_of(target)}"
            return [*facts, told(line)]
        damage = roll_damage(
            fight,
            user,
            target,
            action,
            critical=rolled.critical,
            mode=mode,
            hit=True,
            variant=variant,
        )
        bloodied = fight.is_bloodied(target)
        dealt, harmed = take_damage(
            fight, user, target, damage, critical=rolled.critical, hit=True, morale=morale
        )
        facts.extend(harmed)
        if action.heals_half_dealt and dealt // 2 > 0:
            facts.extend(regain(fight, user, dealt // 2, ())[1])
        facts.extend(_life_drain(fight, user, target, action, damage))
        facts.extend(_riders(fight, user, target, action))
        if (
            variant is not None
            and isinstance(user, MemberCombatant)
            and variant.variant.effect is None
            and (damage.sneak_attack or variant.variant.cost != "sneak-attack-die")
        ):
            facts.extend(_pay_variant(fight, user, variant))
            facts.extend(_play_variant(fight, user, target, action, variant))
        facts.extend(_giant_ancestry(fight, user, target, dealt))
        if bloodied and dealt > 0:
            facts.extend(_rampage(fight, user, target))
        return facts
    if action.kind == "save":
        if action.save is None:
            raise ValueError(f"{action.action_id} asks a save with no DC")
        against = _first_condition(action.riders)
        test = roll_save(
            fight, target, action.save, against=against, spell=action.origin == "spell"
        )
        facts = save_facts(fight, target, action.save, test)
        halves = action.half_on_save or _potent_cantrip(fight, user, action)
        if action.damage and (not test.success or halves):
            damage = area_damage or roll_damage(fight, user, target, action)
            damage = damage.halved() if test.success else damage
            _, harmed = take_damage(fight, user, target, damage, morale=morale)
            facts.extend(harmed)
            facts.extend(_life_drain(fight, user, target, action, damage))
        return [*facts, *_riders(fight, user, target, action, saved=test.success)]
    if action.kind == "heal":
        if action.healing is None:
            raise ValueError(f"{action.action_id} heals with no dice")
        return heal(fight, target, action.name, action.healing)
    if action.kind == "auto_hit":
        damage = area_damage or roll_damage(fight, user, target, action)
        _, dealt = take_damage(fight, user, target, damage, morale=morale)
        return [*dealt, *_riders(fight, user, target, action)]
    return _riders(fight, user, target, action)


def _life_drain(
    fight: Fight, user: Combatant, target: Combatant, action: ActionSpec, damage: DamageRoll
) -> list[Fact]:
    block = fight.stat_block_of(user)
    drain = None if block is None else block.find_special("life-drain")
    if drain is None or drain.action_id != action.action_id:
        return []
    drained = resisted(fight, target, damage.totals().get("necrotic", 0), "necrotic")
    if drained <= 0:
        return []
    hp = fight.hp_of(target)
    dies = drained >= hp.maximum
    # A member dies at a maximum of 0; the maximum stops at 1 so its HP still renders.
    cut = min(drained, hp.maximum - 1)
    sheet = fight.sheet_of(target)
    if sheet is not None:
        sheet.cut_hp_maximum(cut)
    else:
        hp.current = min(hp.current, hp.maximum - cut)
        hp.maximum -= cut
    name = fight.name_of(target)
    if isinstance(target, FoeCombatant):
        facts = [told(f"{name}'s life is drained")]
    elif dies:
        fight.require_member(target.combatant_id).require_vitals().die()
        facts = [told(f"{name}: HP maximum drained to 0"), told(f"{name} dies")]
        facts.extend(ended_facts(fight, fight.battle.stop_turns(target.combatant_id)))
        facts.extend(release_incapacitated(fight, target))
    else:
        facts = [told(f"{name}: HP maximum -{cut} → {fight.hp_of(target)}")]
    if drain.heals_self:
        facts.extend(regain(fight, user, cut, ())[1])
    return facts


def _missed_action(fight: Fight, user: Combatant, action: ActionSpec) -> ActionSpec | None:
    if action.missed_damage_parts:
        return action.model_copy(update={"damage": action.damage[: action.missed_damage_parts]})
    return action if _potent_cantrip(fight, user, action) else None


def _potent_cantrip(fight: Fight, user: Combatant, action: ActionSpec) -> bool:
    sheet = fight.sheet_of(user)
    return (
        action.origin == "spell"
        and sheet is not None
        and POTENT_CANTRIP in sheet.feature_ids()
        and srd().require_spell(action.action_id).level == 0
    )


def _riders(
    fight: Fight,
    user: Combatant,
    target: Combatant,
    action: ActionSpec,
    *,
    saved: bool = False,
    slot_level: int | None = None,
) -> list[Fact]:
    if not fight.is_standing(target):
        return []
    return [
        fact
        for rider in action.riders
        if rider.on_success == saved
        for fact in apply_rider(fight, user, target, action, rider, slot_level)
    ]


def _first_condition(riders: Sequence[Rider]) -> Condition | None:
    return next((rider.condition for rider in riders if rider.condition is not None), None)


def _pay_variant(fight: Fight, member: MemberCombatant, picked: PickedVariant) -> list[Fact]:
    variant = picked.variant
    sheet = fight.require_sheet(member)
    facts = [told(line.format(name=fight.name_of(member))) for line in variant.lines]
    if variant.spell_id is not None:
        assert picked.slot_level is not None
        pay_spell_slot(fight, member, variant.spell_id, picked.slot_level)
        facts.extend(start_concentration(fight, member, variant.spell_id))
    elif variant.cost == "pact-slot":
        assert picked.slot_level is not None
        sheet.spend_slot(picked.slot_level)
    elif variant.spent_use is not None:
        sheet.spend_use(variant.spent_use)
    if "bonus-action" in variant.checks:
        fight.battle.budget.bonus_action = False
    if variant.once_mark is not None:
        fight.battle.use_once(member, variant.once_mark)
    if variant.effect is not None:
        facts.extend(lay(fight, member, member, variant.effect, variant.variant_id, None))
    return facts


def _play_variant(
    fight: Fight,
    member: MemberCombatant,
    target: Combatant,
    action: ActionSpec,
    picked: PickedVariant,
) -> list[Fact]:
    variant = picked.variant
    facts: list[Fact] = []
    if fight.is_standing(target) and fits_size(fight.size_of(target), variant.size_max):
        varied = action.model_copy(update={"riders": variant.riders})
        saved = False
        if variant.save_ability is not None and variant.dc_ability is not None:
            dc = fight.require_sheet(member).feature_dc(variant.dc_ability)
            save = SaveSpec(ability=variant.save_ability, dc=dc)
            against = _first_condition(variant.riders)
            test = roll_save(fight, target, save, against=against, spell=False)
            facts.extend(save_facts(fight, target, save, test))
            saved = test.success
        facts.extend(
            _riders(fight, member, target, varied, saved=saved, slot_level=picked.slot_level)
        )
    if fight.is_standing(member):
        facts.extend(fact for then in variant.then for fact in follow_up(fight, member, then))
    return facts


def _escape_dc(action: ActionSpec) -> int:
    grip = next((r.dc for r in action.riders if r.rider_id == "grapple"), None)
    if grip is not None:
        return grip
    if action.save is None:
        raise ValueError(f"{action.action_id} restrains with no escape DC")
    return action.save.dc


def _immunity(fight: Fight, target: Combatant, rider: Rider, effect_id: Slug) -> str:
    block = fight.stat_block_of(target)
    immunities = {
        *(() if block is None else block.condition_immunities),
        *(
            condition
            for found in fight.battle.effect_modifiers(target.combatant_id, Immunity)
            for condition in found.conditions
        ),
    }
    if rider.condition in immunities:
        return rider.condition or ""
    sheet = fight.sheet_of(target)
    if (
        rider.immune_condition in immunities
        or (effect_id == SLEEP and sheet is not None and TRANCE in sheet.trait_ids())
        or fight.creature_type_of(target) in rider.spared_types
        or (sheet is not None and sheet.species_id in rider.spared_species_ids)
    ):
        return rider.condition or rider.effect_id or ""
    return ""


def _hit_parts(
    fight: Fight,
    user: Combatant,
    target: Combatant,
    action: ActionSpec,
    variant: PickedVariant | None,
) -> list[tuple[str, DamagePart]]:
    parts = (
        []
        if variant is None
        else [(variant.variant.name, part) for part in variant_damage_parts(fight, target, variant)]
    )
    weapon = action.action_id in srd().gear.weapons
    battle = fight.battle
    lasting = [
        *(e for e in battle.effects_on(target.combatant_id) if e.source_id == user.combatant_id),
        *(battle.effects_on(user.combatant_id) if weapon else ()),
    ]
    parts.extend(
        (srd().require_spell(effect.effect_id).name, _rule_part(effect, rule.hit_damage))
        for effect in lasting
        if (rule := _rule_of(effect)) is not None and rule.hit_damage is not None
    )
    sheet = fight.sheet_of(user)
    if sheet is None or not isinstance(user, MemberCombatant):
        return parts
    damage_type = action.damage[0].damage_type if action.damage else None
    features = sheet.feature_ids()
    if (
        weapon
        and HUNTER in features
        and not battle.used_once(user, "colossus-slayer")
        and fight.hp_of(target).shortfall > 0
    ):
        battle.use_once(user, "colossus-slayer")
        slayer = DamagePart(dice=COLOSSUS_SLAYER_DICE, bonus=0, damage_type=damage_type)
        parts.append(("Colossus Slayer", slayer))
    rage = sheet.class_level().class_specific.rage_damage_bonus
    if (
        FRENZY in features
        and rage is not None
        and not battle.used_once(user, "frenzy")
        and holds_effect(fight, user.combatant_id, RAGE)
        and is_reckless(fight, user, action)
    ):
        battle.use_once(user, "frenzy")
        parts.append(
            ("Frenzy", DamagePart(dice=f"{rage}d{FRENZY_DIE}", bonus=0, damage_type=damage_type))
        )
    return parts


def _rule_of(effect: Effect) -> EffectRule | None:
    return srd().battle_effects.effects.get(effect.effect_id)


def _rule_part(effect: Effect, damage: DamagePart | Literal["spell"]) -> DamagePart:
    if damage != "spell":
        return damage
    level = effect.slot_level or srd().require_spell(effect.effect_id).level
    return spell_part(effect.effect_id, level)


def _move_marks(fight: Fight, foe: FoeCombatant) -> list[Fact]:
    battle = fight.battle
    facts: list[Fact] = []
    for mark in battle.effects_on(foe.combatant_id):
        rule = _rule_of(mark)
        if rule is None or not rule.moves_on_drop:
            continue
        caster = battle.require_combatant(mark.source_id)
        found = min(
            (other for other in battle.foes() if fight.is_standing(other)),
            key=lambda other: nearest_key(fight, caster, other),
            default=None,
        )
        if found is None:
            continue
        mark.holder_id = found.combatant_id
        name = srd().require_spell(mark.effect_id).name
        facts.append(told(f"{fight.name_of(caster)}'s {name} moves to {found.name}"))
    return facts


def _dark_ones_blessing(fight: Fight, source: Combatant, foe: FoeCombatant) -> list[Fact]:
    facts: list[Fact] = []
    for member in fight.battle.member_combatants():
        sheet = fight.sheet_of(member)
        if (
            sheet is None
            or FIEND_PATRON not in sheet.feature_ids()
            or not fight.is_standing(member)
            or (member is not source and band_between(fight, member, foe) != "close")
        ):
            continue
        gain = max(sheet.modifier("charisma") + sheet.level, 1)
        if sheet.gain_temp_hp(gain):
            line = f"{fight.name_of(member)}: Dark One's Blessing, temporary HP {gain}"
            facts.append(told(line))
    return facts


def _sneak_attack(
    fight: Fight,
    user: Combatant,
    target: Combatant,
    action: ActionSpec,
    mode: Edge,
    *,
    cost: int,
) -> DamagePart | None:
    sheet = fight.sheet_of(user)
    if sheet is None or not isinstance(user, MemberCombatant) or action.origin != "weapon":
        return None
    sneak = sheet.class_level().class_specific.sneak_attack
    if (
        sneak is None
        or fight.battle.used_once(user, "sneak-attack")
        or not (action.finesse or action.delivery == "ranged")
        or mode == "disadvantage"
        or (mode != "advantage" and not ally_beside(fight, user, target))
    ):
        return None
    fight.battle.use_once(user, "sneak-attack")
    damage_type = action.damage[0].damage_type if action.damage else None
    count = sneak.dice_count - cost
    dice = f"{count}d{sneak.dice_value}"
    return DamagePart(dice=dice, bonus=0, damage_type=damage_type)


def _stop_regeneration(fight: Fight, foe: FoeCombatant, damage: DamageRoll) -> list[Fact]:
    regeneration = foe.stat_block().find_special("regeneration")
    if (
        regeneration is None
        or not fight.is_standing(foe)
        or not any(
            damage_type in regeneration.stopping_damage_types
            and resisted(fight, foe, amount, damage_type) > 0
            for damage_type, amount in damage.totals().items()
        )
    ):
        return []
    return lay(fight, foe, foe, REGENERATION_STOPPED, NO_HEALING, None)


def _undead_fortitude(
    fight: Fight, foe: FoeCombatant, amount: int, damage: DamageRoll, *, critical: bool
) -> list[Fact]:
    radiant = any(part.damage_type == "radiant" for part in damage.dealt)
    if critical or radiant or not has_special(fight, foe, "undead-fortitude"):
        return []
    save = SaveSpec(ability="constitution", dc=UNDEAD_FORTITUDE_BASE + amount)
    test = foe.roll_save(save.ability, save.dc, "none", fight.rng)
    facts = save_facts(fight, foe, save, test)
    if test.success:
        _ = foe.hp.adjust(1)
        facts.append(told(f"{foe.name} refuses to fall"))
    return facts


def _form_shift(fight: Fight, target: Combatant, save: SaveSpec) -> int:
    form = fight.form_of(target)
    if form is None or save.ability not in FORM_ABILITIES:
        return 0
    sheet = fight.require_sheet(target)
    return modifier(form.scores[save.ability]) - sheet.modifier(save.ability)


def _concentration(fight: Fight, target: Combatant, amount: int) -> list[Fact]:
    sheet = fight.sheet_of(target)
    if sheet is None or sheet.concentration_spell_id is None:
        return []
    if fight.hp_of(target).current == 0:
        return lose_concentration(fight, target)
    if amount <= 0:
        return []
    save = SaveSpec(ability="constitution", dc=max(CONCENTRATION_DC_MIN, amount // 2))
    edge: Edge = "advantage" if ELDRITCH_MIND in sheet.pick_ids("invocation") else "none"
    test = roll_save(fight, target, save, against=None, spell=False, edge=edge)
    facts = save_facts(fight, target, save, test)
    if test.success:
        return facts
    return [*facts, *lose_concentration(fight, target)]


def _death_burst(fight: Fight, foe: FoeCombatant) -> list[Fact]:
    burst = foe.stat_block().death_burst
    if burst is None:
        return []
    action = stat_block_action(burst)
    caught = [
        member
        for member in fight.battle.member_combatants()
        if fight.is_standing(member) and band_between(fight, foe, member) == "close"
    ][: area_target_cap(action)]
    facts = [told(f"{foe.name} bursts as it dies")]
    return [*facts, *resolve(fight, foe, action, caught)] if caught else facts


def _melee_action(fight: Fight, combatant: Combatant) -> ActionSpec | None:
    block = fight.block_or_form_of(combatant)
    if block is None:
        held = [action for action in fight.weapon_actions(combatant) if action.delivery == "melee"]
        default = unarmed_action(fight.require_sheet(combatant))
        return max(held, key=lambda action: action.to_hit or 0, default=default)
    melee = [stat_block_action(entry) for entry in block.actions if entry.kind == "melee"]
    return max(melee, key=lambda action: action.to_hit or 0, default=None)


def _burning_oil(
    fight: Fight, target: Combatant, totals: dict[DamageType | None, int]
) -> tuple[dict[DamageType | None, int], list[Fact]]:
    battle = fight.battle
    oiled = next(
        (e for e in battle.effects_on(target.combatant_id) if e.condition == "oiled"), None
    )
    burned = totals.get("fire", 0)
    if oiled is None or resisted(fight, target, burned, "fire") <= 0:
        return totals, []
    oil = srd().gear.gear[OIL].effect
    assert oil is not None
    battle.effects.remove(oiled)
    line = told(f"The oil on {fight.name_of(target)} burns: +{oil.bonus} fire damage")
    return {**totals, "fire": burned + oil.bonus}, [line]


def _storms_thunder(fight: Fight, source: Combatant, target: Combatant, amount: int) -> list[Fact]:
    sheet = fight.sheet_of(target)
    if (
        amount <= 0
        or sheet is None
        or not isinstance(target, MemberCombatant)
        or source is target
        or fight.battle.used_once(target, REACTION)
        or sheet.uses_left("storms-thunder") <= 0
        or fight.hp_of(target).current == 0
        or not fight.is_standing(source)
    ):
        return []
    sheet.spend_use("storms-thunder")
    fight.battle.use_once(target, REACTION)
    line = f"{fight.name_of(target)}: Storm's Thunder strikes {fight.name_of(source)}"
    return deal_extra(fight, target, source, [STORMS_THUNDER], "Storm's Thunder", line)


def _giant_ancestry(fight: Fight, user: Combatant, target: Combatant, dealt: int) -> list[Fact]:
    sheet = fight.sheet_of(user)
    if sheet is None or dealt <= 0 or not fight.is_standing(target):
        return []
    name = fight.name_of(user)
    for use, part, label in STRIKING_ANCESTRY:
        if sheet.uses_left(use) > 0:
            sheet.spend_use(use)
            return deal_extra(fight, user, target, [part], label, f"{name}: {label}")
    if sheet.uses_left("hills-tumble") <= 0 or not fits_size(
        fight.size_of(target), HILLS_TUMBLE_SIZE
    ):
        return []
    if _immunity(fight, target, PRONE, HILLS_TUMBLE):
        return []
    sheet.spend_use("hills-tumble")
    return [told(f"{name}: Hill's Tumble"), *lay(fight, user, target, PRONE, HILLS_TUMBLE, None)]


def _rampage(fight: Fight, user: Combatant, target: Combatant) -> list[Fact]:
    block = fight.stat_block_of(user)
    if block is None:
        return []
    special = block.find_special("rampage")
    if special is None or special.action_id is None:
        return []
    limit = special.usage.uses_per_day
    if limit is not None and user.uses_spent.get(RAMPAGE, 0) >= limit:
        return []
    action = stat_block_action(block.require_action(special.action_id))
    targets = [target, *(c for c in fight.battle.combatants if c.side != user.side)]
    struck = next(
        (c for c in targets if fight.is_standing(c) and reaches(fight, user, c, action)), None
    )
    if struck is None:
        return []
    user.uses_spent[RAMPAGE] = user.uses_spent.get(RAMPAGE, 0) + 1
    line = told(f"{fight.name_of(user)} rampages")
    return [line, *resolve(fight, user, action, [struck])]
