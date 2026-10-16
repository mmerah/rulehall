from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

from pydantic import Field

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.battle.attack import holds_effect
from rulehall.engines.lite5e.battle.damage import (
    ANTITOXIN,
    NET,
    NO_HEALING,
    PRONE,
    DamageRoll,
    end_wild_shape,
    escape,
    follow_up,
    heal,
    lay,
    push_back,
    regain,
    resolve,
    roll_check,
    roll_parts,
    roll_save,
    save_facts,
    stabilize,
    take_damage,
)
from rulehall.engines.lite5e.battle.morale import check_morale, demand_refusal
from rulehall.engines.lite5e.battle.rows import (
    BANDS,
    area_cap,
    area_target_cap,
    band_between,
    hide_refusal,
    is_charmed_by,
    reaches,
    row_of,
    target_refusal,
)
from rulehall.engines.lite5e.battle.specs import (
    ActionSpec,
    SaveSpec,
    gear_action,
    shove_ability,
    spell_action,
    unarmed_action,
    weapon_action,
)
from rulehall.engines.lite5e.battle.spells import (
    QUICKENED,
    TRUE_STRIKE,
    VARIANT_MARK,
    cast_spell,
    lasting_action,
    spell_variant_ids,
    split_variant,
)
from rulehall.engines.lite5e.battle.state import (
    RAGE,
    SIZES,
    WILD_SHAPE,
    Combatant,
    Effect,
    Fight,
    FoeCombatant,
    MemberCombatant,
    PickedVariant,
    ended_facts,
    told,
)
from rulehall.engines.lite5e.battle.turns import (
    TURN_UNDEAD,
    after_member_action,
    hide,
    require_member_turn,
    spend_budget,
)
from rulehall.engines.lite5e.battle.variants import (
    check_passes,
    offered_variants,
    require_strike_variant,
)
from rulehall.engines.lite5e.data import (
    Ability,
    ActionBudget,
    ActionPlay,
    ActionVerb,
    Area,
    Band,
    BattleActionRow,
    CastingTime,
    CreatureType,
    DamagePart,
    DamageType,
    FeatureUse,
    Healing,
    Rider,
    TargetPool,
    srd,
)
from rulehall.engines.lite5e.rules import (
    DICE_UPGRADE_LEVEL,
    LAY_ON_HANDS_CURE,
    MADE_SLOT_COST,
    SEAR_UNDEAD,
)
from rulehall.engines.lite5e.sheet import Lite5eSheet, gear_name, is_drinkable

TARGET = "target"
SLOT = "slot"
DONE = "done"
DEMAND_DC_FLOOR = 15
SHOVE = "shove"
SHOVE_PUSH = "shove-push"
HEALERS_KIT = "healers-kit"
PRESERVE_LIFE_PER_LEVEL = 5
FLURRY_STRIKES = 2
SEAR_DIE = 8
UNDEAD: tuple[CreatureType, ...] = ("undead", "swarm of tiny undead")
SHOVE_SAVES: tuple[Ability, ...] = ("strength", "dexterity")
USE_UNITS: dict[FeatureUse, str] = {"focus": "Focus Point", "sorcery-points": "Sorcery Point"}
TURNED: tuple[Rider, ...] = tuple(
    Rider(rider_id="condition", condition=condition, effect_id=TURN_UNDEAD, ends_on=("damage",))
    for condition in ("frightened", "incapacitated")
)


class Aim(Frozen):
    row: BattleActionRow
    action_id: str
    variant_id: str | None = None
    name: str
    action: ActionSpec | None = None
    target_ids: tuple[Slug, ...] = ()
    cap: int = Field(default=0, ge=0)
    repeats: bool = False
    one_row: bool = False
    slot_levels: tuple[int, ...] = ()
    slot_caps: dict[int, int] = Field(default_factory=dict)

    @property
    def verb(self) -> ActionVerb:
        return self.row.verb

    def command(self) -> str:
        suffix = "" if self.variant_id is None else f"{VARIANT_MARK}{self.variant_id}"
        return f"{self.verb} {self.action_id}{suffix}"

    def picked_target_ids(self, picks: Sequence[str]) -> list[Slug]:
        prefix = f"{TARGET} "
        return [pick.removeprefix(prefix) for pick in picks if pick.startswith(prefix)]

    def picked_slot(self, picks: Sequence[str]) -> int | None:
        prefix = f"{SLOT} "
        picked = next((int(p.removeprefix(prefix)) for p in picks if p.startswith(prefix)), None)
        if picked is not None or len(self.slot_levels) != 1:
            return picked
        return self.slot_levels[0]

    def target_cap(self, picks: Sequence[str]) -> int:
        slot = self.picked_slot(picks)
        return self.cap if slot is None else self.slot_caps.get(slot, self.cap)

    def awaits_target(self, picks: Sequence[str]) -> bool:
        if self.slot_caps and self._slot_open(picks):
            return False
        picked = self.picked_target_ids(picks)
        left = self.repeats or any(target_id not in picked for target_id in self.target_ids)
        cap = self.target_cap(picks)
        return cap > 0 and DONE not in picks and len(picked) < cap and left

    def awaits_slot(self, picks: Sequence[str]) -> bool:
        return self._slot_open(picks) and (bool(self.slot_caps) or not self.awaits_target(picks))

    def _slot_open(self, picks: Sequence[str]) -> bool:
        return len(self.slot_levels) > 1 and self.picked_slot(picks) is None

    def is_ready(self, picks: Sequence[str]) -> bool:
        return not self.awaits_target(picks) and not self.awaits_slot(picks)


@dataclass(frozen=True, slots=True)
class Use:
    fight: Fight
    member: MemberCombatant
    row: BattleActionRow
    action_id: str
    variant_id: str | None = None
    action: ActionSpec | None = None
    targets: tuple[Combatant, ...] = ()
    slot_level: int | None = None

    @property
    def target(self) -> Combatant:
        return self.targets[0]

    def require_sheet(self) -> Lite5eSheet:
        return self.fight.require_sheet(self.member)

    def require_action(self) -> ActionSpec:
        if self.action is None:
            raise ValueError(f"the {self.action_id} aim carries no action")
        return self.action

    def require_variant(self) -> str:
        if self.variant_id is None:
            raise ValueError(f"the {self.action_id} row names no variant")
        return self.variant_id

    def spend_use(self) -> None:
        if self.row.use is not None:
            self.require_sheet().spend_use(self.row.use)

    def told_lines(self, target: str = "") -> list[Fact]:
        sheet = self.fight.sheet_of(self.member)
        weapon_id = None if sheet is None else sheet.find_pick("pact-weapon")
        fields = {
            "name": self.fight.name_of(self.member),
            "target": target,
            "temp_hp": 0 if sheet is None else sheet.temp_hp,
            "weapon": "" if weapon_id is None else srd().gear.weapons[weapon_id].name,
        }
        return [told(line.format(**fields)) for line in self.row.lines]


class ActionHandler(ABC):
    def offers(self, use: Use) -> bool:  # noqa: ARG002
        return True

    def target_ids(self, use: Use) -> tuple[Slug, ...] | None:
        pool = use.row.targets
        return None if pool is None else pool_ids(use.fight, use.member, pool, use.row.within)

    def area(self, row: BattleActionRow) -> Area | None:
        return None if row.save is None else row.save.area

    def target_cap(self, row: BattleActionRow) -> int:
        area = self.area(row)
        return 1 if area is None else area_cap(area) or 1

    def aims(self, use: Use) -> list[Aim]:
        row = use.row
        target_ids = self.target_ids(use)
        cap = 0 if target_ids is None else self.target_cap(row)
        aim = Aim(
            row=row,
            action_id=row.action_id,
            variant_id=row.variant_id,
            name=row.name,
            target_ids=target_ids or (),
            cap=cap,
            one_row=self.area(row) is not None and cap > 1,
        )
        return [aim]

    @abstractmethod
    def play(self, use: Use) -> list[Fact]: ...


class SelfPlay(ActionHandler):
    def offers(self, use: Use) -> bool:
        held_id = use.row.held_effect_id()
        return held_id is None or not holds_effect(use.fight, use.member.combatant_id, held_id)

    def play(self, use: Use) -> list[Fact]:
        fight, member, held = use.fight, use.member, use.row.effect
        use.spend_use()
        laid = [] if held is None else lay(fight, member, member, held, use.row.action_id, None)
        return [*use.told_lines(), *laid, *_follow_up(use)]


class TargetEffect(ActionHandler):
    def target_ids(self, use: Use) -> tuple[Slug, ...]:
        held_id = use.row.held_effect_id()
        return tuple(
            target_id
            for target_id in super().target_ids(use) or ()
            if held_id is None or not holds_effect(use.fight, target_id, held_id)
        )

    def play(self, use: Use) -> list[Fact]:
        fight, member = use.fight, use.member
        use.spend_use()
        laid = lay(fight, member, use.target, use.row.require_effect(), use.row.action_id, None)
        return [*use.told_lines(target=fight.name_of(use.target)), *laid]


class SaveDamage(ActionHandler):
    def play(self, use: Use) -> list[Fact]:
        fight, member = use.fight, use.member
        action = _feature_save_action(use)
        if use.targets and all(target.side == member.side for target in use.targets):
            action = ActionSpec(
                action_id=action.action_id,
                name=action.name,
                kind="heal",
                range_feet=action.range_feet,
                healing=Healing(dice=use.row.require_save().dice, bonus=action.damage[0].bonus),
                target_filter="ally",
            )
        use.spend_use()
        resolved = resolve(fight, member, action, use.targets)
        return [*use.told_lines(), *resolved, *_follow_up(use)]


class LandsAid(SaveDamage):
    def play(self, use: Use) -> list[Fact]:
        return [*super().play(use), *_heal_weakest_ally(use)]


class LastingStrike(ActionHandler):
    def offers(self, use: Use) -> bool:
        spell_id = use.row.action_id
        return holds_effect(use.fight, use.member.combatant_id, spell_id) and (
            spell_id not in use.fight.battle.budget.cast_spell_ids
        )

    def aims(self, use: Use) -> list[Aim]:
        spell_id = use.row.action_id
        name = use.row.name or f"{srd().require_spell(spell_id).name}: strike"
        return [_spec_aim(use, lasting_action(use.fight, use.member, spell_id), name=name)]

    def play(self, use: Use) -> list[Fact]:
        return resolve(use.fight, use.member, use.require_action(), use.targets)


class Hide(ActionHandler):
    def offers(self, use: Use) -> bool:
        return not hide_refusal(use.fight, use.member)

    def play(self, use: Use) -> list[Fact]:
        return hide(use.fight, use.member)


class Escape(ActionHandler):
    def target_ids(self, use: Use) -> tuple[Slug, ...]:
        fight, member = use.fight, use.member
        holder_ids = _holder_ids(fight, member)
        netted_ids = [
            ally.combatant_id
            for ally in fight.battle.member_combatants()
            if ally is not member
            and ally.combatant_id not in holder_ids
            and _find_net(fight, ally) is not None
            and band_between(fight, member, ally) == "close"
        ]
        return (*holder_ids, *netted_ids)

    def play(self, use: Use) -> list[Fact]:
        fight, member, target = use.fight, use.member, use.target
        if target.combatant_id in _holder_ids(fight, member):
            return escape(fight, member, member, target.combatant_id)
        net = _find_net(fight, target)
        assert net is not None
        return escape(fight, target, member, net.source_id)


class Douse(ActionHandler):
    def offers(self, use: Use) -> bool:
        return use.fight.battle.has_condition(use.member.combatant_id, "burning")

    def play(self, use: Use) -> list[Fact]:
        fight, member = use.fight, use.member
        flames = fight.battle.remove_effects(
            lambda e: e.holder_id == member.combatant_id and e.condition == "burning"
        )
        return [told(f"{fight.name_of(member)} douses the flames"), *ended_facts(fight, flames)]


class Shove(ActionHandler):
    def target_ids(self, use: Use) -> tuple[Slug, ...]:
        fight, member = use.fight, use.member
        size = SIZES.index(fight.size_of(member))
        return tuple(
            target_id
            for target_id in pool_ids(fight, member, "foes", "close")
            if SIZES.index(fight.size_of(fight.battle.require_combatant(target_id))) <= size + 1
        )

    def play(self, use: Use) -> list[Fact]:
        fight, member, target = use.fight, use.member, use.target
        assert isinstance(target, FoeCombatant)
        ability = max(SHOVE_SAVES, key=target.save_bonus)
        sheet = use.require_sheet()
        save = SaveSpec(ability=ability, dc=sheet.feature_dc(shove_ability(sheet)))
        test = roll_save(fight, target, save, against=None, spell=False)
        name = target.name
        facts = [
            told(f"{fight.name_of(member)} shoves {name}"),
            *save_facts(fight, target, save, test),
        ]
        if test.success:
            return facts
        if use.action_id == SHOVE_PUSH:
            if target.row == "back":
                return [*facts, told(f"{name} is already in its back row")]
            return [*facts, *push_back(fight, target)]
        return [*facts, *lay(fight, member, target, PRONE, SHOVE, None)]


class Demand(ActionHandler):
    def target_ids(self, use: Use) -> tuple[Slug, ...]:
        fight = use.fight
        return tuple(
            foe.combatant_id for foe in standing_foes(fight) if not demand_refusal(fight, foe)
        )

    def play(self, use: Use) -> list[Fact]:
        fight, member, target = use.fight, use.member, use.target
        assert isinstance(target, FoeCombatant)
        group_id = target.person_id
        fight.battle.morale_marks.setdefault(group_id, []).append("demand")
        dc = max(DEMAND_DC_FLOOR, target.stat_block().scores["intelligence"])
        test = roll_check(fight, member, "charisma", "intimidation", dc, "none")
        name = fight.name_of(member)
        outcome = "success" if test.success else "failure"
        facts = [
            Fact(trace=f"{name}: demand, Intimidation {test.total} vs DC {dc}"),
            told(f"{name} demands that {target.group_name} surrender → {outcome}", test.dice),
        ]
        if test.success:
            facts.extend(check_morale(fight, group_id, "demand"))
        return facts


class WeaponAttack(ActionHandler):
    def aims(self, use: Use) -> list[Aim]:
        fight, member = use.fight, use.member
        aims: list[Aim] = []
        for action in (*fight.weapon_actions(member), unarmed_action(use.require_sheet())):
            aims.append(_spec_aim(use, action))
            aims.extend(
                _spec_aim(
                    use,
                    action,
                    name=f"{action.name}: {picked.variant.name}"
                    + ("" if picked.slot_level is None else f" (slot {picked.slot_level})"),
                    variant_id=picked.variant_id,
                )
                for picked in offered_variants(fight, member, action)
            )
        return aims

    def play(self, use: Use) -> list[Fact]:
        weapon = srd().gear.weapons.get(use.action_id)
        if weapon is not None and weapon.kind == "melee" and "light" in weapon.properties:
            use.fight.battle.budget.light_weapon_id = use.action_id
        return resolve(use.fight, use.member, use.require_action(), use.targets, _picked(use))


class OffHand(ActionHandler):
    def offers(self, use: Use) -> bool:
        return use.fight.battle.budget.light_weapon_id is not None

    def aims(self, use: Use) -> list[Aim]:
        sheet = use.require_sheet()
        first = use.fight.battle.budget.light_weapon_id
        return [
            _spec_aim(
                use,
                weapon_action(sheet, weapon_id, off_hand=True),
                name=f"Off-hand {srd().gear.weapons[weapon_id].name}",
            )
            for weapon_id in dict.fromkeys(sheet.equipped_ids)
            if _fits_off_hand(sheet, weapon_id, first)
        ]

    def play(self, use: Use) -> list[Fact]:
        use.fight.battle.budget.light_weapon_id = None
        return resolve(use.fight, use.member, use.require_action(), use.targets)


class Throw(ActionHandler):
    def aims(self, use: Use) -> list[Aim]:
        sheet = use.require_sheet()
        return [
            _spec_aim(use, gear_action(sheet, key), name=f"Throw {gear_name(key)}")
            for key, count in sheet.gear.items()
            if count > 0 and _is_throwable(key)
        ]

    def play(self, use: Use) -> list[Fact]:
        fight, member, action = use.fight, use.member, use.require_action()
        use.require_sheet().remove_gear(use.action_id, 1)
        return [
            told(f"{fight.name_of(member)} throws {action.name}"),
            *resolve(fight, member, action, use.targets),
        ]


class Drink(ActionHandler):
    def aims(self, use: Use) -> list[Aim]:
        return [
            self._aim(use, key)
            for key, count in use.require_sheet().gear.items()
            if count > 0 and is_drinkable(key)
        ]

    def play(self, use: Use) -> list[Fact]:
        fight, member, key = use.fight, use.member, use.action_id
        drinker = use.target if use.targets else member
        healing = use.require_sheet().spend_drink(key)
        if drinker.combatant_id == member.combatant_id:
            facts = [told(f"{fight.name_of(member)} drinks {gear_name(key)}")]
        else:
            facts = [
                told(f"{fight.name_of(member)} gives {fight.name_of(drinker)} {gear_name(key)}")
            ]
        if key == ANTITOXIN:
            facts.extend(lay(fight, member, member, Rider(rider_id="effect"), ANTITOXIN, None))
        if healing is not None:
            facts.extend(heal(fight, drinker, gear_name(key), healing))
        return facts

    def _aim(self, use: Use, key: Slug) -> Aim:
        if key not in srd().gear.magic_items:
            return Aim(row=use.row, action_id=key, name=f"Drink {gear_name(key)}")
        fight, member = use.fight, use.member
        drinker_ids = tuple(
            ally.combatant_id
            for ally in fight.battle.member_combatants()
            if fight.in_battle(ally) and band_between(fight, member, ally) == "close"
        )
        return Aim(
            row=use.row, action_id=key, name=f"Use {gear_name(key)}", target_ids=drinker_ids, cap=1
        )


class HealersKit(ActionHandler):
    def offers(self, use: Use) -> bool:
        return use.require_sheet().gear.get(HEALERS_KIT, 0) > 0

    def target_ids(self, use: Use) -> tuple[Slug, ...]:
        fight, member = use.fight, use.member
        return tuple(
            ally.combatant_id
            for ally in fight.battle.member_combatants()
            if not target_refusal(fight, member, ally, "dying")
            and band_between(fight, member, ally) == "close"
        )

    def play(self, use: Use) -> list[Fact]:
        line = told(f"{use.fight.name_of(use.member)} uses a Healer's Kit")
        return [line, stabilize(use.fight, use.target)]


class Cast(ActionHandler):
    def aims(self, use: Use) -> list[Aim]:
        fight, member = use.fight, use.member
        sheet = use.require_sheet()
        aims: list[Aim] = []
        for spell_id in sheet.castable_spell_ids():
            spell = srd().require_spell(spell_id)
            levels = sheet.cast_slot_levels(spell_id, slot_open=not fight.battle.budget.slot_spent)
            if spell.battle is None or (spell.level and not levels):
                continue
            action = spell_action(sheet, spell_id, levels[0] if levels else 0)
            scales = spell.battle.targets_per_level > 0
            for variant_id in spell_variant_ids(sheet, spell_id):
                if not _castable(fight, member, use.row.verb, spell_id, variant_id):
                    continue
                twin = int(split_variant(variant_id)[1] == "twinned")
                slot_caps = (
                    {level: _cap(spell_action(sheet, spell_id, level)) + twin for level in levels}
                    if scales
                    else {}
                )
                aims.append(
                    _spec_aim(
                        use, action, variant_id=variant_id, slot_levels=levels, slot_caps=slot_caps
                    )
                )
        return aims

    def play(self, use: Use) -> list[Fact]:
        spell = srd().require_spell(use.action_id)
        level = spell.level if use.slot_level is None else use.slot_level
        return cast_spell(use.fight, use.member, use.action_id, use.targets, level, use.variant_id)


class TurnUndead(ActionHandler):
    def play(self, use: Use) -> list[Fact]:
        fight, member = use.fight, use.member
        sheet = use.require_sheet()
        use.spend_use()
        save = SaveSpec(ability="wisdom", dc=sheet.feature_dc("wisdom"))
        sear_dice = f"{max(sheet.modifier('wisdom'), 1)}d{SEAR_DIE}"
        sear_part = DamagePart(dice=sear_dice, bonus=0, damage_type="radiant")
        sears = SEAR_UNDEAD in sheet.feature_ids()
        sear: DamageRoll | None = None
        facts = [told(f"{fight.name_of(member)} turns the undead")]
        for foe in fight.battle.foes():
            if (
                not fight.is_standing(foe)
                or foe.stat_block().creature_type not in UNDEAD
                or band_between(fight, member, foe) == "far"
            ):
                continue
            test = roll_save(fight, foe, save, against=None, spell=False)
            facts.extend(save_facts(fight, foe, save, test))
            if test.success:
                continue
            if sears:
                damage = sear or roll_parts(fight, [sear_part], "Sear Undead")
                sear = damage.model_copy(update={"dice": ()})
                facts.extend(take_damage(fight, member, foe, damage)[1])
                if not fight.is_standing(foe):
                    continue
            foe.row = "back"
            facts.append(told(f"{foe.name} is turned and flees to its back row"))
            for rider in TURNED:
                facts.extend(lay(fight, member, foe, rider, TURN_UNDEAD, None))
        return facts


class PreserveLife(ActionHandler):
    def play(self, use: Use) -> list[Fact]:
        fight, member = use.fight, use.member
        sheet = use.require_sheet()
        use.spend_use()
        pool = PRESERVE_LIFE_PER_LEVEL * sheet.level
        allies = sorted(
            (
                ally
                for ally in fight.battle.member_combatants()
                if fight.in_battle(ally)
                and band_between(fight, member, ally) != "far"
                and 2 * fight.hp_of(ally).current <= fight.hp_of(ally).maximum
                and not holds_effect(fight, ally.combatant_id, NO_HEALING)
            ),
            key=lambda ally: fight.hp_of(ally).current,
        )
        facts = [told(f"{fight.name_of(member)} preserves life")]
        for ally in allies:
            hp = fight.hp_of(ally)
            gain = min(pool, hp.maximum // 2 - hp.current)
            if gain <= 0:
                continue
            healed, regained = regain(fight, ally, gain, ())
            pool -= healed
            facts.extend(regained)
        return facts


class LayOnHands(ActionHandler):
    def offers(self, use: Use) -> bool:
        pool = use.require_sheet().uses_left("lay-on-hands")
        return use.variant_id is None or pool >= LAY_ON_HANDS_CURE

    def target_ids(self, use: Use) -> tuple[Slug, ...]:
        fight = use.fight
        allies = [
            ally
            for ally in fight.battle.member_combatants()
            if fight.in_battle(ally) and band_between(fight, use.member, ally) == "close"
        ]
        if use.variant_id is not None:
            return tuple(
                ally.combatant_id
                for ally in allies
                if fight.battle.has_condition(ally.combatant_id, "poisoned")
            )
        return tuple(
            ally.combatant_id
            for ally in allies
            if fight.hp_of(ally).shortfall > 0
            and not holds_effect(fight, ally.combatant_id, NO_HEALING)
        )

    def play(self, use: Use) -> list[Fact]:
        fight, target = use.fight, use.target
        sheet = use.require_sheet()
        facts = [told(f"{fight.name_of(use.member)} lays on hands")]
        if use.variant_id is not None:
            sheet.spend_use("lay-on-hands", LAY_ON_HANDS_CURE)
            poison = fight.battle.remove_effects(
                lambda e: e.holder_id == target.combatant_id and e.condition == "poisoned"
            )
            return [*facts, *ended_facts(fight, poison)]
        missing = fight.hp_of(target).shortfall
        healed, regained = regain(fight, target, min(sheet.uses_left("lay-on-hands"), missing), ())
        if healed:
            sheet.spend_use("lay-on-hands", healed)
        return [*facts, *regained]


class WildShape(ActionHandler):
    def offers(self, use: Use) -> bool:
        return use.fight.form_of(use.member) is None

    def play(self, use: Use) -> list[Fact]:
        fight, member = use.fight, use.member
        sheet = use.require_sheet()
        form_id = use.require_variant()
        use.spend_use()
        fight.battle.effects.append(
            Effect(
                holder_id=member.combatant_id,
                source_id=member.combatant_id,
                effect_id=WILD_SHAPE,
                stat_block_id=form_id,
            )
        )
        _ = sheet.gain_temp_hp(sheet.level)
        form = srd().require_stat_block(form_id)
        name = fight.name_of(member)
        return [told(f"{name} takes the form of a {form.name}, temporary HP {sheet.temp_hp}")]


class EndWildShape(ActionHandler):
    def offers(self, use: Use) -> bool:
        return use.fight.form_of(use.member) is not None

    def play(self, use: Use) -> list[Fact]:
        return end_wild_shape(use.fight, use.member)


class MartialArts(ActionHandler):
    techniques = False

    def offers(self, use: Use) -> bool:
        return use.require_sheet().find_martial_arts_die() is not None

    def strike(self, sheet: Lite5eSheet) -> ActionSpec:
        return unarmed_action(sheet)

    def aims(self, use: Use) -> list[Aim]:
        sheet, row = use.require_sheet(), use.row
        strike = self.strike(sheet)
        named = _priced(row.name, _use_costs(row, None))
        aims = [_spec_aim(use, strike, name=named, action_id=row.action_id)]
        for picked in offered_variants(use.fight, use.member, strike, techniques=self.techniques):
            costs = _use_costs(row, picked)
            if all(sheet.uses_left(spent) >= count for spent, count in costs.items()):
                named = _priced(f"{row.name}: {picked.variant.name}", costs)
                aims.append(
                    _spec_aim(
                        use,
                        strike,
                        name=named,
                        action_id=row.action_id,
                        variant_id=picked.variant_id,
                    )
                )
        return aims

    def play(self, use: Use) -> list[Fact]:
        return resolve(use.fight, use.member, use.require_action(), use.targets, _picked(use))


class Flurry(MartialArts):
    techniques = True

    def strike(self, sheet: Lite5eSheet) -> ActionSpec:
        update = {"volley": True, "target_count": FLURRY_STRIKES}
        return unarmed_action(sheet).model_copy(update=update)

    def play(self, use: Use) -> list[Fact]:
        struck = super().play(use)
        use.spend_use()
        return [told(f"{use.fight.name_of(use.member)} unleashes a Flurry of Blows"), *struck]


class FontOfMagic(ActionHandler):
    def aims(self, use: Use) -> list[Aim]:
        sheet, row = use.require_sheet(), use.row
        return [
            Aim(
                row=row,
                action_id=row.action_id,
                variant_id=str(level),
                name=_priced(
                    f"{row.name}: a level {level} slot", Counter({"sorcery-points": cost})
                ),
            )
            for level, cost in MADE_SLOT_COST.items()
            if not sheet.font_of_magic_refusal(level)
        ]

    def play(self, use: Use) -> list[Fact]:
        made = use.require_sheet().make_slot(int(use.require_variant()))
        return [told(f"{use.fight.name_of(use.member)}: {made}")]


PLAYS: dict[ActionPlay, ActionHandler] = {
    "self": SelfPlay(),
    "target-effect": TargetEffect(),
    "save-damage": SaveDamage(),
    "lasting-strike": LastingStrike(),
}
HANDLERS: dict[Slug, ActionHandler] = {
    "hide": Hide(),
    "escape": Escape(),
    "douse": Douse(),
    "shove-prone": Shove(),
    "shove-push": Shove(),
    "demand": Demand(),
    "weapons": WeaponAttack(),
    "off-hand": OffHand(),
    "thrown": Throw(),
    "potions": Drink(),
    "healers-kit": HealersKit(),
    "spells": Cast(),
    "turn-undead": TurnUndead(),
    "preserve-life": PreserveLife(),
    "lands-aid": LandsAid(),
    "lay-on-hands": LayOnHands(),
    "wild-shape": WildShape(),
    "wild-shape-end": EndWildShape(),
    "martial-arts": MartialArts(),
    "flurry-of-blows": Flurry(),
    "font-of-magic": FontOfMagic(),
}


def handler_of(row: BattleActionRow) -> ActionHandler:
    if row.play is None:
        return HANDLERS[row.action_id]
    return PLAYS[row.play]


@cache
def member_actions(verb: ActionVerb) -> tuple[BattleActionRow, ...]:
    return tuple(row for row in srd().battle_actions if row.verb == verb)


def offered_rows(fight: Fight, member: MemberCombatant, verb: ActionVerb) -> list[BattleActionRow]:
    rows = member_actions(verb)
    if fight.block_or_form_of(member) is None:
        return list(rows)
    formed = fight.form_of(member) is not None
    return [row for row in rows if row.companion or (formed and row.in_form)]


def budget_open(fight: Fight, budget: ActionBudget) -> bool:
    spent = fight.battle.budget
    if budget == "bonus":
        return spent.bonus_action
    if budget == "magic":
        return spent.action
    if budget == "attack" and spent.attacks_left:
        return True
    return budget == "none" or spent.action or spent.extra_actions > 0


def row_offered(use: Use) -> bool:
    fight, member, row = use.fight, use.member, use.row
    sheet = fight.sheet_of(member)
    return (
        (row.feature_id is None or (sheet is not None and row.feature_id in sheet.feature_ids()))
        and (not row.minimum_level or (sheet is not None and sheet.level >= row.minimum_level))
        and all(check_passes(fight, member, check) for check in row.checks)
        and (row.use is None or (sheet is not None and sheet.uses_left(row.use) > 0))
        and handler_of(row).offers(use)
    )


def member_aims(fight: Fight, member: MemberCombatant) -> list[Aim]:
    aims = [
        aim
        for verb in ("act", "bonus")
        for row in offered_rows(fight, member, verb)
        if budget_open(fight, row.budget)
        and row_offered(use := Use(fight, member, row, row.action_id, row.variant_id))
        for aim in handler_of(row).aims(use)
    ]
    return [aim for aim in aims if (aim.cap == 0 or aim.target_ids) and _keeps_bound(fight, aim)]


def take_action(fight: Fight, aim: Aim, picks: Sequence[str]) -> list[Fact]:
    member = require_member_turn(fight)
    target_ids = aim.picked_target_ids(picks)
    slot_level = aim.picked_slot(picks)
    counted = 0 < len(target_ids) <= aim.target_cap(picks) if aim.cap else not target_ids
    if not counted or any(target_id not in aim.target_ids for target_id in target_ids):
        offered = ", ".join(aim.target_ids) or "no target"
        raise Refusal(f"{aim.name} takes up to {aim.target_cap(picks)} of: {offered}")
    if not aim.repeats and len(set(target_ids)) < len(target_ids):
        raise Refusal(f"{aim.name} takes each target once")
    if aim.slot_levels and slot_level not in aim.slot_levels:
        raise Refusal(f"{aim.name} takes a slot of level {', '.join(map(str, aim.slot_levels))}")
    targets = tuple(fight.battle.require_combatant(target_id) for target_id in target_ids)
    spend_budget(fight, member, aim.row.budget, aim.action_id)
    use = Use(
        fight, member, aim.row, aim.action_id, aim.variant_id, aim.action, targets, slot_level
    )
    facts = handler_of(aim.row).play(use)
    if aim.row.budget == "attack":
        fight.battle.budget.attacked = True
    return after_member_action(fight, member, facts)


def standing_foes(fight: Fight) -> list[FoeCombatant]:
    return [foe for foe in fight.battle.foes() if fight.is_standing(foe)]


def pool_ids(
    fight: Fight, member: MemberCombatant, pool: TargetPool, band: Band
) -> tuple[Slug, ...]:
    match pool:
        case "foes":
            found: Sequence[Combatant] = standing_foes(fight)
        case "front-foes":
            found = [foe for foe in standing_foes(fight) if row_of(fight, foe) == "front"]
        case "other-allies":
            found = [
                ally
                for ally in fight.battle.member_combatants()
                if ally is not member and fight.is_standing(ally)
            ]
        case "others":
            found = [c for c in fight.battle.combatants if c is not member and fight.in_battle(c)]
    return tuple(
        c.combatant_id
        for c in found
        if BANDS.index(band_between(fight, member, c)) <= BANDS.index(band)
        and not is_charmed_by(fight, member, c)
    )


def _keeps_bound(fight: Fight, aim: Aim) -> bool:
    budget = fight.battle.budget
    bound = budget.bound_weapon_id
    return aim.row.budget != "attack" or not budget.attacks_left or bound in (None, aim.action_id)


def _follow_up(use: Use) -> list[Fact]:
    fight, member, row = use.fight, use.member, use.row
    facts: list[Fact] = []
    if row.healing_dice is not None:
        healing = Healing(dice=row.healing_dice, bonus=use.require_sheet().level)
        facts.extend(heal(fight, member, row.name, healing))
    facts.extend(fact for then in row.then for fact in follow_up(fight, member, then))
    return facts


def _heal_weakest_ally(use: Use) -> list[Fact]:
    fight, member = use.fight, use.member
    tended = min(
        (
            ally
            for ally in fight.battle.member_combatants()
            if fight.in_battle(ally) and band_between(fight, member, ally) != "far"
        ),
        key=lambda ally: fight.hp_of(ally).current,
        default=None,
    )
    if tended is None:
        return []
    return heal(fight, tended, use.row.name, Healing(dice=use.row.require_save().dice, bonus=0))


def _picked(use: Use) -> PickedVariant | None:
    return None if use.variant_id is None else require_strike_variant(use.variant_id)


def _use_costs(row: BattleActionRow, picked: PickedVariant | None) -> Counter[FeatureUse]:
    costs: Counter[FeatureUse] = Counter()
    if row.use is not None:
        costs[row.use] += 1
    spent = None if picked is None else picked.variant.spent_use
    if spent is not None:
        costs[spent] += 1
    return costs


def _priced(name: str, costs: Counter[FeatureUse]) -> str:
    prices = [
        f"{count} {unit}{'s' if count > 1 else ''}"
        for spent, count in costs.items()
        if (unit := USE_UNITS.get(spent)) is not None
    ]
    return f"{name} ({', '.join(prices)})" if prices else name


def _fits_off_hand(sheet: Lite5eSheet, weapon_id: Slug, first: Slug | None) -> bool:
    weapon = srd().gear.weapons.get(weapon_id)
    return (
        weapon is not None
        and weapon.kind == "melee"
        and "light" in weapon.properties
        and (first != weapon_id or sheet.gear.get(weapon_id, 0) >= 2)
    )


def _is_throwable(key: Slug) -> bool:
    gear = srd().gear.gear.get(key)
    return gear is not None and gear.effect is not None and gear.effect.use == "throw"


def _castable(
    fight: Fight, member: MemberCombatant, verb: ActionVerb, spell_id: Slug, variant_id: str | None
) -> bool:
    budget = fight.battle.budget
    casting: CastingTime = "action" if verb == "act" else "bonus-action"
    if split_variant(variant_id)[1] == QUICKENED:
        leveled = any(srd().require_spell(cast_id).level for cast_id in budget.cast_spell_ids)
        if casting == "action" or leveled:
            return False
        casting = "action"
    spell = srd().require_spell(spell_id)
    effect = None if spell.battle is None else spell.battle.effect
    lasting = spell.battle is not None and spell.battle.holds_lasting_effect()
    return (
        spell.battle is not None
        and spell.casting_time == casting
        and not holds_effect(fight, member.combatant_id, RAGE)
        and not any(variant.spell_id == spell_id for variant in srd().strike_variants)
        and not (
            lasting
            and effect is not None
            and holds_effect(fight, member.combatant_id, effect.require_effect_id())
        )
        and not (spell.level and budget.quickened)
    )


def _holder_ids(fight: Fight, member: MemberCombatant) -> tuple[Slug, ...]:
    return tuple(hold.source_id for hold in fight.battle.escape_holds(member.combatant_id))


def _find_net(fight: Fight, holder: Combatant) -> Effect | None:
    holds = fight.battle.escape_holds(holder.combatant_id)
    return next((hold for hold in holds if hold.effect_id == NET), None)


def _feature_save_action(use: Use) -> ActionSpec:
    fight, member, row = use.fight, use.member, use.row
    sheet = use.require_sheet()
    template = row.require_save()
    damage_type = template.damage_type or _breath_damage_type(fight, member, sheet)
    upgraded = template.upgraded_dice is not None and sheet.level >= DICE_UPGRADE_LEVEL
    dice = template.upgraded_dice if upgraded else template.dice
    ability = template.bonus_ability
    part = DamagePart(
        dice=dice,
        bonus=0 if ability is None else sheet.modifier(ability),
        damage_type=damage_type,
    )
    return ActionSpec(
        action_id=row.action_id,
        name=row.name,
        kind="save",
        range_feet=template.range_feet,
        area=template.area,
        damage=(part,),
        save=SaveSpec(ability=template.save_ability, dc=sheet.feature_dc(template.dc_ability)),
        half_on_save=True,
    )


def _breath_damage_type(fight: Fight, member: MemberCombatant, sheet: Lite5eSheet) -> DamageType:
    species = srd().character_options.species[sheet.species_id]
    lineage = species.subspecies.get(sheet.subspecies_id or "")
    if lineage is None or lineage.damage_type is None:
        raise Refusal(f"{fight.name_of(member)} has no Breath Weapon")
    return lineage.damage_type


def _spec_aim(
    use: Use,
    action: ActionSpec,
    *,
    name: str = "",
    action_id: str = "",
    variant_id: str | None = None,
    slot_levels: tuple[int, ...] = (),
    slot_caps: dict[int, int] | None = None,
) -> Aim:
    fight, member = use.fight, use.member
    if action.action_id == TRUE_STRIKE:
        weapons = fight.weapon_actions(member)
        target_ids = tuple(
            foe.combatant_id
            for foe in standing_foes(fight)
            if any(reaches(fight, member, foe, weapon) for weapon in weapons)
        )
        cap = 1
    else:
        target_ids = tuple(
            target.combatant_id
            for target in fight.battle.combatants
            if not target_refusal(fight, member, target, action.target_filter)
            and reaches(fight, member, target, action)
            and (
                not action.creature_types or fight.creature_type_of(target) in action.creature_types
            )
        )
        cap = _cap(action)
    if name or variant_id is None:
        shown = name or action.name
    else:
        shown = f"{action.name}: {variant_id.replace(VARIANT_MARK, ', ')}"
    return Aim(
        row=use.row,
        action_id=action_id or action.action_id,
        variant_id=variant_id,
        name=shown,
        action=action,
        target_ids=target_ids,
        cap=cap,
        repeats=action.volley,
        one_row=action.area is not None and cap > 1,
        slot_levels=slot_levels,
        slot_caps=slot_caps or {},
    )


def _cap(action: ActionSpec) -> int:
    if action.area is not None:
        return area_target_cap(action) or 1
    personal = action.reach_feet is None and action.range_feet is None
    return 0 if personal else action.target_count
