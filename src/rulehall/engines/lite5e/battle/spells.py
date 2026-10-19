from collections.abc import Sequence
from typing import get_args

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.battle.attack import cast_through, innate_sorcery
from rulehall.engines.lite5e.battle.damage import (
    PRONE,
    change_row,
    follow_up,
    lay,
    pay_spell_slot,
    require_targets,
    resolve,
    set_effect_end,
    stabilize,
    start_concentration,
)
from rulehall.engines.lite5e.battle.rows import reaches
from rulehall.engines.lite5e.battle.specs import (
    ActionSpec,
    SpellNumbers,
    spell_action,
    spell_numbers,
)
from rulehall.engines.lite5e.battle.state import (
    Combatant,
    Effect,
    Fight,
    MemberCombatant,
    ended_facts,
    told,
)
from rulehall.engines.lite5e.data import (
    CommandWord,
    DamagePart,
    DamageType,
    Dice,
    EffectRule,
    EndingEvent,
    MetamagicId,
    Rider,
    Spell,
    SpellBattle,
    Tier,
    srd,
)
from rulehall.engines.lite5e.rules import DICE_UPGRADE_LEVEL, duration_tier
from rulehall.engines.lite5e.sheet import Lite5eSheet

COMMAND: Slug = "command"
FEAR: Slug = "fear"
VARIANT_MARK = "+"
QUICKENED: MetamagicId = "quickened"
INNATE_SORCERY_DC = 1
TRUE_STRIKE: Slug = "true-strike"
REVIVIFY_DIAMOND: Slug = "diamond"
TRUE_STRIKE_UPGRADE_DICE: Dice = "1d6"
TRUE_STRIKE_UPGRADE_TYPE: DamageType = "radiant"
DAMAGE_TYPES: tuple[DamageType, ...] = get_args(DamageType.__value__)
COMMAND_WORDS: tuple[CommandWord, ...] = get_args(CommandWord.__value__)


class SpellCast(Frozen):
    spell: Spell
    slot_level: int
    variant_id: str | None
    numbers: SpellNumbers

    @property
    def levels_above(self) -> int:
        return self.slot_level - self.spell.level

    @property
    def lasting_tier(self) -> Tier | None:
        lasts = not self.spell.concentration and duration_tier(self.spell.duration) == "long-rest"
        return "long-rest" if lasts else None

    def require_effect(self) -> Rider:
        effect = _require_battle(self.spell).effect
        if effect is None:
            raise ValueError(f"{self.spell.name} has no spell effect")
        return effect


def cast_spell(
    fight: Fight,
    caster: MemberCombatant,
    spell_id: Slug,
    targets: Sequence[Combatant],
    slot_level: int,
    variant_id: str | None,
) -> list[Fact]:
    battle = fight.battle
    sheet = fight.require_sheet(caster)
    spell = srd().require_spell(spell_id)
    base_id, metamagic = split_variant(variant_id)
    numbers = spell_numbers(sheet, spell_id, slot_level)
    action = spell_action(sheet, spell_id, slot_level, numbers)
    pay_spell_slot(fight, caster, spell_id, slot_level)
    shown = spell.name
    if metamagic is not None:
        option = srd().character_options.metamagic[metamagic]
        sheet.spend_use("sorcery-points", option.cost)
        action = _apply_metamagic(fight, caster, action, targets, metamagic)
        shown = f"{spell.name} ({option.name})"
    cast = SpellCast(spell=spell, slot_level=slot_level, variant_id=base_id, numbers=numbers)
    battle.budget.cast_spell_ids.append(spell_id)
    action = sorcery_action(fight, caster, action)
    ends: tuple[EndingEvent, ...] = (
        ("cast", "verbal-cast") if "V" in spell.components else ("cast",)
    )
    lapsing = [
        effect
        for effect in battle.effects_on(caster.combatant_id)
        if any(end in effect.ends_on for end in ends)
    ]
    facts = [
        told(f"{fight.name_of(caster)} casts {shown}"),
        *start_concentration(fight, caster, spell_id),
        *_play_effect(fight, caster, action, targets, cast),
    ]
    battle.budget.empowered_rerolls = 0
    lapsed = battle.remove_effects(lambda held: any(held is gone for gone in lapsing))
    return [*facts, *ended_facts(fight, lapsed)]


def lasting_action(fight: Fight, caster: MemberCombatant, effect_id: Slug) -> ActionSpec:
    lasting = fight.battle.find_effect(caster.combatant_id, effect_id)
    if lasting is None or lasting.slot_level is None or lasting.numbers is None:
        raise ValueError(f"{caster.combatant_id} holds no lasting {effect_id} to strike with")
    sheet = fight.require_sheet(caster)
    action = spell_action(sheet, effect_id, lasting.slot_level, lasting.numbers)
    return sorcery_action(fight, caster, action)


def sorcery_action(fight: Fight, caster: Combatant, action: ActionSpec) -> ActionSpec:
    save = action.save
    if save is None or not innate_sorcery(fight, caster, action):
        return action
    raised = save.model_copy(update={"dc": save.dc + INNATE_SORCERY_DC})
    return action.model_copy(update={"save": raised})


def spell_variant_ids(sheet: Lite5eSheet, spell_id: Slug) -> tuple[str | None, ...]:
    spell = srd().require_spell(spell_id)
    bases = base_variant_ids(spell)
    points = sheet.uses_left("sorcery-points")
    options = [
        option
        for option in fitting_metamagic(sheet, spell)
        if srd().character_options.metamagic[option].cost <= points
    ]
    return (
        *bases,
        *(
            option if base is None else f"{base}{VARIANT_MARK}{option}"
            for option in options
            for base in bases
        ),
    )


def fitting_metamagic(sheet: Lite5eSheet, spell: Spell) -> tuple[MetamagicId, ...]:
    return tuple(option for option in sheet.metamagic_ids() if _fits(spell, option))


def base_variant_ids(spell: Spell) -> tuple[str | None, ...]:
    return (() if spell.battle is None else spell.battle.variants) or (None,)


def split_variant(variant_id: str | None) -> tuple[str | None, MetamagicId | None]:
    if variant_id is None:
        return None, None
    base, _, last = variant_id.rpartition(VARIANT_MARK)
    metamagic: MetamagicId | None = next(
        (option for option in srd().character_options.metamagic if option == last), None
    )
    if metamagic is None:
        return variant_id, None
    return base or None, metamagic


def require_variant[T: str](options: tuple[T, ...], variant_id: str | None) -> T:
    found = next((option for option in options if option == variant_id), None)
    if found is None:
        raise Refusal(f"{variant_id!r} is not one of: {', '.join(options)}")
    return found


def find_command(fight: Fight, combatant: Combatant) -> Effect | None:
    return next(
        (
            effect
            for effect in fight.battle.effects_on(combatant.combatant_id)
            if effect.effect_id in {f"{COMMAND}-{word}" for word in COMMAND_WORDS}
        ),
        None,
    )


def obey_command(fight: Fight, command: Effect) -> list[Fact]:
    battle = fight.battle
    holder = battle.require_combatant(command.holder_id)
    name = fight.name_of(holder)
    battle.effects.remove(command)
    word: CommandWord = require_variant(
        COMMAND_WORDS, command.effect_id.removeprefix(f"{COMMAND}-")
    )
    match word:
        case "grovel":
            source = battle.require_combatant(command.source_id)
            return [told(f"{name} grovels"), *lay(fight, source, holder, PRONE, COMMAND, None)]
        case "halt":
            return [told(f"{name} halts")]
        case "flee":
            return flee(fight, holder)


def flee(fight: Fight, holder: Combatant) -> list[Fact]:
    name = fight.name_of(holder)
    if holder.row == "back" or fight.battle.is_held(holder.combatant_id):
        return [told(f"{name} cowers")]
    return [told(f"{name} flees"), *change_row(fight, holder, provoking=True, teleport=False)]


def _play_effect(
    fight: Fight,
    caster: MemberCombatant,
    action: ActionSpec,
    targets: Sequence[Combatant],
    cast: SpellCast,
) -> list[Fact]:
    battle = _require_battle(cast.spell)
    effect = battle.effect
    if battle.then:
        return [fact for then in battle.then for fact in follow_up(fight, caster, then)]
    if effect is None:
        return resolve(fight, caster, _varied(action, cast.variant_id), targets)
    match effect.effect_id:
        case "aid":
            return _aid(fight, caster, action, targets, cast)
        case "false-life":
            sheet = fight.require_sheet(caster)
            event = sheet.gain_false_life(cast.levels_above, fight.rng)
            return [told(f"{fight.name_of(caster)}: temporary HP {sheet.temp_hp}", (event,))]
        case "revivify":
            return _revivify(fight, caster, action, targets)
        case "true-strike":
            return _true_strike(fight, caster, action, targets)
        case _ if battle.holds_lasting_effect():
            return _hold_lasting(fight, caster, action, targets, cast)
        case _:
            return _bestow(fight, caster, action, targets, cast)


def _require_battle(spell: Spell) -> SpellBattle:
    if spell.battle is None:
        raise Refusal(f"{spell.name} is no battle spell")
    return spell.battle


def _fits(spell: Spell, metamagic: MetamagicId) -> bool:
    battle = spell.battle
    if battle is None:
        return False
    match srd().character_options.metamagic[metamagic].fits:
        case "damage":
            return bool(battle.damage)
        case "save":
            return spell.save_ability is not None
        case "action":
            return spell.casting_time == "action"
        case "scaling-target":
            return spell.level > 0 and battle.targets_per_level > 0 and not battle.volley


def _apply_metamagic(
    fight: Fight,
    caster: MemberCombatant,
    action: ActionSpec,
    targets: Sequence[Combatant],
    metamagic: MetamagicId,
) -> ActionSpec:
    budget = fight.battle.budget
    match metamagic:
        case "empowered":
            budget.empowered_rerolls = max(fight.require_sheet(caster).modifier("charisma"), 1)
        case "heightened":
            if action.save is None:
                raise ValueError(f"{action.action_id} heightens a spell with no save")
            if not targets:
                raise Refusal(f"Heightened Spell names a target of {action.name}")
            save = action.save.model_copy(update={"heightened_id": targets[0].combatant_id})
            return action.model_copy(update={"save": save})
        case "quickened":
            budget.quickened = True
        case "twinned":
            return action.model_copy(update={"target_count": action.target_count + 1})
    return action


def _varied(action: ActionSpec, variant_id: str | None) -> ActionSpec:
    if variant_id is None:
        return action
    if variant_id in COMMAND_WORDS:
        riders = tuple(
            rider.model_copy(update={"effect_id": f"{rider.effect_id}-{variant_id}"})
            for rider in action.riders
        )
        return action.model_copy(update={"riders": riders})
    damage_type = _damage_type(variant_id)
    parts = tuple(part.model_copy(update={"damage_type": damage_type}) for part in action.damage)
    return action.model_copy(update={"damage": parts})


def _damage_type(variant_id: str) -> DamageType:
    return require_variant(DAMAGE_TYPES, variant_id)


def _bestow(
    fight: Fight,
    caster: MemberCombatant,
    action: ActionSpec,
    targets: Sequence[Combatant],
    cast: SpellCast,
) -> list[Fact]:
    battle = fight.battle
    effect = cast.require_effect()
    effect_id = effect.require_effect_id()
    rule = srd().battle_effects.effects.get(effect_id)
    damage_type = None if cast.variant_id is None else _damage_type(cast.variant_id)
    bestowed = require_targets(fight, caster, action, targets or [caster])
    facts: list[Fact] = []
    for target in bestowed:
        if rule is None or not rule.is_instant():
            given = Effect(
                holder_id=target.combatant_id,
                source_id=caster.combatant_id,
                effect_id=effect_id,
                uses=effect.uses,
                tier=cast.lasting_tier,
                damage_type=damage_type,
                numbers=cast.numbers,
            )
            set_effect_end(fight, given, effect.ends, action.save)
            battle.replace_effect(given)
            facts.append(told(f"{fight.name_of(target)}: {action.name}"))
        if rule is not None and rule.stabilizes:
            facts.append(stabilize(fight, target))
    ended = [held for target in bestowed for held in _ended_by(fight, target, rule)]
    for held in ended:
        battle.effects.remove(held)
    return [*facts, *ended_facts(fight, ended)]


def _ended_by(fight: Fight, target: Combatant, rule: EffectRule | None) -> list[Effect]:
    if rule is None:
        return []
    ended = [
        held
        for held in fight.battle.effects_on(target.combatant_id)
        if held.condition in rule.ends_conditions
    ]
    return ended[:1] if rule.ends_one else ended


def _hold_lasting(
    fight: Fight,
    caster: MemberCombatant,
    action: ActionSpec,
    targets: Sequence[Combatant],
    cast: SpellCast,
) -> list[Fact]:
    fight.battle.effects.append(
        Effect(
            holder_id=caster.combatant_id,
            source_id=caster.combatant_id,
            effect_id=cast.require_effect().require_effect_id(),
            tier=cast.lasting_tier,
            slot_level=cast.slot_level,
            numbers=cast.numbers,
        )
    )
    return resolve(fight, caster, action, targets)


def _aid(
    fight: Fight,
    caster: MemberCombatant,
    action: ActionSpec,
    targets: Sequence[Combatant],
    cast: SpellCast,
) -> list[Fact]:
    aided = require_targets(fight, caster, action, targets or [caster])
    facts = _bestow(fight, caster, action, aided, cast)
    for target in aided:
        sheet = fight.require_sheet(target)
        gain = sheet.take_aid(cast.levels_above)
        facts.append(told(f"{fight.name_of(target)}: +{gain} HP → {sheet.vitals.hp}"))
    return facts


def _true_strike(
    fight: Fight, caster: MemberCombatant, action: ActionSpec, targets: Sequence[Combatant]
) -> list[Fact]:
    if len(targets) != 1:
        raise Refusal(f"{action.name} takes 1 target")
    target = targets[0]
    strike = next(
        (w for w in fight.weapon_actions(caster) if reaches(fight, caster, target, w)), None
    )
    if strike is None:
        raise Refusal(f"no held weapon reaches {fight.name_of(target)}")
    sheet = fight.require_sheet(caster)
    guided = cast_through(sheet, strike, action.action_id)
    damage = guided.damage
    if sheet.level >= DICE_UPGRADE_LEVEL:
        radiant = DamagePart(
            dice=TRUE_STRIKE_UPGRADE_DICE, bonus=0, damage_type=TRUE_STRIKE_UPGRADE_TYPE
        )
        damage = (*damage, radiant)
    named = guided.model_copy(update={"name": f"{action.name} ({strike.name})", "damage": damage})
    return resolve(fight, caster, named, targets)


def _revivify(
    fight: Fight, caster: MemberCombatant, action: ActionSpec, targets: Sequence[Combatant]
) -> list[Fact]:
    sheet = fight.require_sheet(caster)
    if sheet.gear.get(REVIVIFY_DIAMOND, 0) < 1:
        raise Refusal(f"{action.name} needs a diamond worth 300 GP")
    facts: list[Fact] = []
    for target in require_targets(fight, caster, action, targets):
        sheet.remove_gear(REVIVIFY_DIAMOND, 1)
        _ = fight.require_member(target.combatant_id).require_vitals().heal(1)
        facts.append(told(f"{fight.name_of(target)} returns to life at 1 HP"))
    return facts
