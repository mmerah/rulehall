from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from random import Random
from typing import Annotated, Literal

from pydantic import Field

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug
from rulehall.engines.lite5e.battle.specs import ActionSpec, SaveSpec, SpellNumbers, weapon_action
from rulehall.engines.lite5e.data import (
    Ability,
    Advantage,
    AdvantageRoll,
    Bonus,
    BonusTarget,
    Condition,
    CreatureType,
    DamageType,
    EffectRule,
    EndingEvent,
    ModifierKey,
    OnceMark,
    Size,
    StatBlock,
    StrikeVariant,
    Tier,
    srd,
)
from rulehall.engines.lite5e.rules import (
    DODGE,
    EXTRA_ATTACK_COUNT,
    LARGE_FORM,
    THIRSTING_BLADE,
    Edge,
    FormationRow,
    Light,
)
from rulehall.engines.lite5e.sheet import (
    DamageTaken,
    Lite5ePerson,
    Lite5eSheet,
    TestRoll,
    roll_test,
)
from rulehall.engines.sheet import Gauge

PACT_WEAPON: Slug = "pact-weapon"
RAGE: Slug = "rage"
WILD_SHAPE: Slug = "wild-shape"
SLOW: Slug = "slow"
MEMBER_CREATURE_TYPE: CreatureType = "humanoid"
SIZES: tuple[Size, ...] = ("tiny", "small", "medium", "large", "huge")
INCAPACITATING: frozenset[Condition] = frozenset(
    {"incapacitated", "paralyzed", "petrified", "stunned", "unconscious"}
)
HELD_IN_PLACE: tuple[Condition, ...] = ("grappled", "restrained")

type Phase = Literal["member", "foes"]
type Side = Literal["foes", "party"]
type Withdrawal = Literal["left", "fled", "surrendered"]
type MoraleMark = Literal["first-drop", "half-hp", "demand"]
type TurnEdge = Literal["start", "end"]
ROUND_MARKS: frozenset[OnceMark] = frozenset(
    {"stones-endurance", "uncanny-dodge", "deflect-attacks", "storms-thunder"}
)


class TurnMark(Frozen):
    combatant_id: Slug
    turn: int = Field(ge=1)
    edge: TurnEdge


class Effect(Mutable):
    holder_id: Slug
    source_id: Slug
    effect_id: Slug
    condition: Condition | None = None
    ends: TurnMark | None = None
    save_ends: SaveSpec | None = None
    escape_dc: int | None = None
    ends_on: tuple[EndingEvent, ...] = ()
    uses: int | None = None
    tier: Tier | None = None
    slot_level: int | None = None
    damage_type: DamageType | None = None
    stat_block_id: Slug | None = None
    numbers: SpellNumbers | None = None


class TurnBudget(Mutable):
    move: bool = True
    action: bool = True
    bonus_action: bool = True
    extra_actions: int = Field(default=0, ge=0)
    attacks_left: int = Field(default=0, ge=0)
    slot_spent: bool = False
    moved: bool = False
    disengaged: bool = False
    attacked: bool = False
    light_weapon_id: Slug | None = None
    bound_weapon_id: Slug | None = None
    cast_spell_ids: list[Slug] = Field(default_factory=list)
    quickened: bool = False
    empowered_rerolls: int = Field(default=0, ge=0)


class CombatantBase(Mutable):
    combatant_id: Slug
    row: FormationRow
    turns: int = Field(default=0, ge=0)
    recharging_ids: list[Slug] = Field(default_factory=list)
    uses_spent: dict[Slug, int] = Field(default_factory=dict)
    withdrawal: Withdrawal | None = None


class FoeCombatant(CombatantBase):
    side: Literal["foes"] = "foes"
    person_id: Slug
    name: str
    group_name: str
    stat_block_id: Slug
    hp: Gauge
    last_damager_id: Slug | None = None

    def stat_block(self) -> StatBlock:
        return srd().require_stat_block(self.stat_block_id)

    def take_damage(self, amount: int, source_id: Slug) -> DamageTaken:
        if amount <= 0:
            return DamageTaken(dealt=0, dropped=False, died=False)
        self.last_damager_id = source_id
        dealt = -self.hp.adjust(-amount)
        dropped = self.hp.current == 0
        return DamageTaken(dealt=dealt, dropped=dropped, died=dropped)

    def save_bonus(self, ability: Ability) -> int:
        return self.stat_block().save_bonus(ability)

    def roll_save(self, ability: Ability, dc: int, edge: Edge, rng: Random) -> TestRoll:
        return roll_test(f"{ability} save", self.save_bonus(ability), dc, edge, rng)


class MemberCombatant(CombatantBase):
    side: Literal["party"] = "party"
    auto: bool = False
    once_marks: dict[OnceMark, int] = Field(default_factory=dict)


type Combatant = FoeCombatant | MemberCombatant


class Battle(Mutable):
    round: int = Field(default=1, ge=1)
    order: list[Slug]
    turn_index: int = Field(default=0, ge=0)
    combatants: list[Annotated[FoeCombatant | MemberCombatant, Field(discriminator="side")]]
    effects: list[Effect] = Field(default_factory=list)
    phase: Phase
    pending_plans: dict[Slug, str] = Field(default_factory=dict)
    budget: TurnBudget = Field(default_factory=TurnBudget)
    morale_marks: dict[Slug, list[MoraleMark]] = Field(default_factory=dict)
    facts: list[Fact] = Field(default_factory=list)
    light: Light
    cover: bool

    def log(self) -> list[str]:
        return [fact.card for fact in self.facts if fact.card]

    def turn_number(self) -> int:
        return (self.round - 1) * len(self.order) + self.turn_index + 1

    def used_once(self, member: MemberCombatant, mark: OnceMark) -> bool:
        return member.once_marks.get(mark) == self._once_stamp(mark)

    def use_once(self, member: MemberCombatant, mark: OnceMark) -> None:
        member.once_marks[mark] = self._once_stamp(mark)

    def require_combatant(self, combatant_id: str) -> Combatant:
        found = next((c for c in self.combatants if c.combatant_id == combatant_id), None)
        if found is None:
            raise Refusal(f"{combatant_id!r} is no combatant of this battle")
        return found

    def foes(self) -> list[FoeCombatant]:
        return [c for c in self.combatants if isinstance(c, FoeCombatant)]

    def member_combatants(self) -> list[MemberCombatant]:
        return [c for c in self.combatants if isinstance(c, MemberCombatant)]

    def require_group_foes(self, group_id: str) -> list[FoeCombatant]:
        found = [foe for foe in self.foes() if foe.person_id == group_id]
        if not found:
            raise Refusal(f"{group_id!r} is no foe group of this battle")
        return found

    def effects_on(self, holder_id: str) -> list[Effect]:
        return [effect for effect in self.effects if effect.holder_id == holder_id]

    def find_effect(self, holder_id: str, effect_id: str) -> Effect | None:
        return next((e for e in self.effects_on(holder_id) if e.effect_id == effect_id), None)

    def effect_rules_on(self, holder_id: str) -> list[tuple[Effect, EffectRule]]:
        rules = srd().battle_effects.effects
        incapacitated = self.is_incapacitated(holder_id)
        found: dict[str, tuple[Effect, EffectRule]] = {}
        for effect in self.effects_on(holder_id):
            for key in (effect.effect_id, effect.condition):
                rule = None if key is None else rules.get(key)
                if key is None or rule is None or key in found:
                    continue
                if not (key == DODGE and incapacitated):
                    found[key] = (effect, rule)
        return list(found.values())

    def effect_modifiers[ModifierT: Frozen](
        self, holder_id: str, kind: type[ModifierT]
    ) -> list[ModifierT]:
        rules = [rule for _, rule in self.effect_rules_on(holder_id)]
        return [found for rule in rules for found in rule.modifiers if isinstance(found, kind)]

    def effect_bonuses(
        self, holder_id: str, to: BonusTarget, key: ModifierKey | None = None
    ) -> list[int]:
        bonuses = self.effect_modifiers(holder_id, Bonus)
        return [found.fixed_amount() for found in bonuses if found.matches(to, key)]

    def effect_edges(
        self, holder_id: str, on: AdvantageRoll, *keys: ModifierKey | None
    ) -> list[Advantage]:
        edges = self.effect_modifiers(holder_id, Advantage)
        return [found for found in edges if any(found.matches(on, key) for key in keys or (None,))]

    def conditions_on(self, holder_id: str) -> list[Condition]:
        return list(
            dict.fromkeys(
                effect.condition
                for effect in self.effects_on(holder_id)
                if effect.condition is not None
            )
        )

    def has_condition(self, holder_id: str, condition: Condition) -> bool:
        return any(effect.condition == condition for effect in self.effects_on(holder_id))

    def is_incapacitated(self, holder_id: str) -> bool:
        return any(effect.condition in INCAPACITATING for effect in self.effects_on(holder_id))

    def is_held(self, holder_id: str) -> bool:
        return any(effect.condition in HELD_IN_PLACE for effect in self.effects_on(holder_id))

    def escape_holds(self, holder_id: str) -> list[Effect]:
        holds: dict[str, Effect] = {}
        for effect in self.effects_on(holder_id):
            if effect.escape_dc is not None:
                holds.setdefault(effect.source_id, effect)
        return list(holds.values())

    def next_turn_mark(self, combatant_id: str, edge: TurnEdge) -> TurnMark:
        turns = self.require_combatant(combatant_id).turns
        return TurnMark(combatant_id=combatant_id, turn=turns + 1, edge=edge)

    def expire_effects(self, combatant_id: str, edge: TurnEdge) -> list[Effect]:
        turns = self.require_combatant(combatant_id).turns
        return self.remove_effects(
            lambda effect: (
                effect.ends is not None
                and effect.ends.combatant_id == combatant_id
                and effect.ends.edge == edge
                and effect.ends.turn <= turns
            )
        )

    def end_effects_on(self, holder_id: str, reason: EndingEvent) -> list[Effect]:
        return self.remove_effects(
            lambda effect: effect.holder_id == holder_id and reason in effect.ends_on
        )

    def release_grapples(self, grappler_id: str) -> list[Effect]:
        grips = {
            (effect.holder_id, effect.effect_id)
            for effect in self.effects
            if effect.source_id == grappler_id and effect.condition == "grappled"
        }
        return self.remove_effects(
            lambda effect: (
                effect.source_id == grappler_id and (effect.holder_id, effect.effect_id) in grips
            )
        )

    def release_holds(self, holder_id: str, conditions: tuple[Condition, ...]) -> list[Effect]:
        holds = {
            (effect.source_id, effect.effect_id)
            for effect in self.effects_on(holder_id)
            if effect.condition in conditions
        }
        return self.remove_effects(
            lambda effect: (
                effect.holder_id == holder_id and (effect.source_id, effect.effect_id) in holds
            )
        )

    def drop_concentration(self, caster_id: str, sheet: Lite5eSheet) -> list[Effect]:
        spell_id = sheet.concentration_spell_id
        sheet.concentration_spell_id = None
        return self.remove_effects(
            lambda effect: effect.source_id == caster_id and effect.effect_id == spell_id
        )

    def stop_turns(self, combatant_id: str) -> list[Effect]:
        released = self.release_grapples(combatant_id)
        return [
            *released,
            *self.remove_effects(
                lambda effect: effect.ends is not None and effect.ends.combatant_id == combatant_id
            ),
        ]

    def remove_effects(self, ends: Callable[[Effect], bool]) -> list[Effect]:
        gone = [effect for effect in self.effects if ends(effect)]
        self.effects[:] = [effect for effect in self.effects if not ends(effect)]
        return gone

    def replace_effect(self, effect: Effect) -> None:
        key = (effect.holder_id, effect.source_id, effect.effect_id, effect.condition)
        _ = self.remove_effects(
            lambda held: (held.holder_id, held.source_id, held.effect_id, held.condition) == key
        )
        self.effects.append(effect)

    def _once_stamp(self, mark: OnceMark) -> int:
        return self.round if mark in ROUND_MARKS else self.turn_number()


@dataclass(frozen=True, slots=True)
class Fight:
    battle: Battle
    members: Mapping[Slug, Lite5ePerson]
    rng: Random

    def require_member(self, member_id: str) -> Lite5ePerson:
        found = self.members.get(member_id)
        if found is None:
            raise Refusal(f"{member_id!r} is no member in this battle")
        return found

    def name_of(self, combatant: Combatant) -> str:
        if isinstance(combatant, FoeCombatant):
            return combatant.name
        return self.require_member(combatant.combatant_id).name

    def hp_of(self, combatant: Combatant) -> Gauge:
        if isinstance(combatant, FoeCombatant):
            return combatant.hp
        return self.require_member(combatant.combatant_id).require_vitals().hp

    def sheet_of(self, combatant: Combatant) -> Lite5eSheet | None:
        if isinstance(combatant, FoeCombatant):
            return None
        return self.require_member(combatant.combatant_id).sheet

    def require_sheet(self, combatant: Combatant) -> Lite5eSheet:
        sheet = self.sheet_of(combatant)
        if sheet is None:
            raise ValueError(f"{combatant.combatant_id} plays a sheet rule with no sheet")
        return sheet

    def stat_block_of(self, combatant: Combatant) -> StatBlock | None:
        if isinstance(combatant, FoeCombatant):
            return combatant.stat_block()
        member = self.require_member(combatant.combatant_id)
        return member.stat_block() if member.sheet is None else None

    def find_form_id(self, combatant: Combatant) -> Slug | None:
        shape = self.battle.find_effect(combatant.combatant_id, WILD_SHAPE)
        return None if shape is None else shape.stat_block_id

    def form_of(self, combatant: Combatant) -> StatBlock | None:
        form_id = self.find_form_id(combatant)
        return None if form_id is None else srd().require_stat_block(form_id)

    def block_or_form_of(self, combatant: Combatant) -> StatBlock | None:
        return self.stat_block_of(combatant) or self.form_of(combatant)

    def size_of(self, combatant: Combatant) -> Size:
        block = self.block_or_form_of(combatant)
        if block is not None:
            return block.size
        if self.battle.find_effect(combatant.combatant_id, LARGE_FORM) is not None:
            return "large"
        sheet = self.sheet_of(combatant)
        assert sheet is not None
        sizes = srd().character_options.species[sheet.species_id].sizes
        return max(sizes, key=SIZES.index)

    def creature_type_of(self, combatant: Combatant) -> CreatureType:
        block = self.stat_block_of(combatant)
        return MEMBER_CREATURE_TYPE if block is None else block.creature_type

    def sees_in_dark(self, combatant: Combatant) -> bool:
        block = self.stat_block_of(combatant)
        if block is not None:
            return block.darkvision
        sheet = self.sheet_of(combatant)
        return sheet is not None and sheet.sees_in_dark()

    def pact_weapon_id(self, combatant: Combatant) -> Slug | None:
        sheet = self.sheet_of(combatant)
        if sheet is None or self.battle.find_effect(combatant.combatant_id, PACT_WEAPON) is None:
            return None
        return sheet.find_pick("pact-weapon")

    def thirsts(self, member: MemberCombatant, weapon_id: str) -> bool:
        sheet = self.sheet_of(member)
        return (
            sheet is not None
            and sheet.attack_count() < EXTRA_ATTACK_COUNT
            and THIRSTING_BLADE in sheet.pick_ids("invocation")
            and weapon_id == self.pact_weapon_id(member)
        )

    def attack_count(self, member: MemberCombatant, weapon_id: str) -> int:
        sheet = self.sheet_of(member)
        if sheet is None or self.battle.find_effect(member.combatant_id, SLOW) is not None:
            return 1
        return EXTRA_ATTACK_COUNT if self.thirsts(member, weapon_id) else sheet.attack_count()

    def weapon_actions(self, combatant: Combatant) -> list[ActionSpec]:
        sheet = self.sheet_of(combatant)
        if sheet is None:
            return []
        pact_weapon_id = self.pact_weapon_id(combatant)
        weapons = srd().gear.weapons
        held = [weapon_id for weapon_id in sheet.equipped_ids if weapon_id in weapons]
        return [
            weapon_action(sheet, weapon_id, off_hand=False, pact=weapon_id == pact_weapon_id)
            for weapon_id in dict.fromkeys(
                (*held, *(() if pact_weapon_id is None else (pact_weapon_id,)))
            )
        ]

    def is_dead(self, combatant: Combatant) -> bool:
        if isinstance(combatant, FoeCombatant):
            return combatant.hp.current == 0
        return self.require_member(combatant.combatant_id).require_vitals().is_dead

    def is_standing(self, combatant: Combatant) -> bool:
        return combatant.withdrawal is None and self.hp_of(combatant).current > 0

    def in_battle(self, combatant: Combatant) -> bool:
        return combatant.withdrawal is None and not self.is_dead(combatant)

    def is_bloodied(self, combatant: Combatant) -> bool:
        hp = self.hp_of(combatant)
        return 0 < hp.current * 2 <= hp.maximum


class PickedVariant(Frozen):
    variant: StrikeVariant
    slot_level: int | None

    @property
    def variant_id(self) -> str:
        family = self.variant.variant_id
        return family if self.slot_level is None else f"{family}-{self.slot_level}"


def told(line: str, dice: tuple[DiceEvent, ...] = ()) -> Fact:
    return Fact(trace=line, told=True, card=line, dice=dice)


def ended_facts(fight: Fight, effects: Sequence[Effect]) -> list[Fact]:
    facts: list[Fact] = []
    for effect in effects:
        rule = srd().battle_effects.effects.get(effect.effect_id)
        state = rule.state if rule is not None and rule.state is not None else effect.condition
        if state is not None:
            name = fight.name_of(fight.battle.require_combatant(effect.holder_id))
            facts.append(told(f"{name}: no longer {state}"))
    return facts


def foe_ids(person_id: Slug, count: int, taken: Collection[str]) -> list[Slug]:
    if count == 1:
        return [person_id]
    made: list[Slug] = []
    number = 0
    while len(made) < count:
        number += 1
        if f"{person_id}-{number}" not in taken:
            made.append(f"{person_id}-{number}")
    return made
