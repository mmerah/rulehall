from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from math import ceil
from random import Random
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import DiceEvent, Rolled, roll
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, parse
from rulehall.core.views import Rows, Sprite
from rulehall.engines.bases.maps.world import Dweller
from rulehall.engines.lite5e.data import (
    Ability,
    AbilityAmount,
    AbilityScores,
    Advantage,
    AdvantageRoll,
    Amount,
    Armor,
    ArmorBase,
    Bonus,
    BonusTarget,
    Boon,
    ClassId,
    ClassLevel,
    ClassOption,
    ClassOptionKind,
    Condition,
    DamageType,
    Feat,
    FeatureUse,
    GearId,
    Healing,
    Invocation,
    LevelPickKind,
    MetamagicId,
    ModifierKey,
    PerLevelAmount,
    PickVocabulary,
    Resistance,
    School,
    Skill,
    SpeciesId,
    SrdClass,
    StatBlock,
    StatBlockId,
    SubspeciesId,
    Tier,
    TimedCondition,
    Trait,
    Weapon,
    WeaponProperty,
    dice_parts,
    modifier,
    portrait_sprite,
    srd,
    stat_block_sprite,
)
from rulehall.engines.lite5e.pack import Background
from rulehall.engines.lite5e.rules import (
    ABILITIES,
    AID_HP,
    CASTING_ABILITIES,
    CRITICAL_FACE,
    DEATH_SAVES,
    DIM_PASSIVE_PENALTY,
    EXHAUSTION_PENALTY,
    FALSE_LIFE_BONUS,
    FALSE_LIFE_DICE,
    FALSE_LIFE_PER_LEVEL,
    FONT_OF_MAGIC,
    GUIDANCE_DIE,
    INCREASE_SPLITS,
    KEEP,
    LUCKY,
    MADE_SLOT_COST,
    MADE_SLOT_SORCERER_LEVEL,
    MAGE_ARMOR_BASE,
    MAGIC_INITIATE_ABILITY,
    MARTIAL_ARTS,
    MAX_EXHAUSTION,
    MAX_LEVEL,
    MAX_SCORE,
    MAX_XP,
    PACT_MAGIC,
    POINT_BUY_COST,
    POINT_BUY_TOTAL,
    RESOURCEFUL,
    SCHOLAR,
    SCHOLAR_SKILLS,
    SKILL_ABILITY,
    STANDARD_ARRAY,
    TACTICAL_MIND,
    TACTICAL_MIND_DIE,
    TOME_RITUAL_LEVEL,
    TWO_WEAPON_FIGHTING,
    AbilityMethod,
    CastingAbility,
    Difficulty,
    Edge,
    FormationRow,
    Light,
    is_monk_weapon,
    raised_light,
    reached_spell_ids,
    skill_name,
)
from rulehall.engines.sheet import Gauge, Sheeted

COMMONER: Slug = "commoner"
PASSIVE_BASE = 10
PASSIVE_EDGE = 5
DARK_PASSIVE = 0
NO_UNARMORED_BASE = 10
FINESSE_OR_LIGHT: frozenset[WeaponProperty] = frozenset({"finesse", "light"})
BARDIC_DIE_SPEND = "Bardic Inspiration"
HEROIC_INSPIRATION = "Heroic Inspiration"
LUCK = "Luck"
DEATH_SAVE = "death save"
ROUTED_NAME_SUFFIX = ", routed"

type EquipSlot = Literal["body", "shield", "weapon"]
type DeathSaveOutcome = Literal["success", "failure", "stable", "revived", "dead"]

SKILL_PICK_KINDS: tuple[LevelPickKind, ...] = (
    "class-skill",
    "species-skill",
    "skilled",
    "lore-skill",
    "primal-knowledge",
)
CLASS_OPTION_KINDS: tuple[ClassOptionKind, ...] = ("class-order", "land")


class SheetEffect(Frozen):
    effect_id: Slug
    source_id: Slug
    tier: Tier


class DamageTaken(Frozen):
    dealt: int
    dropped: bool
    died: bool


class TestRoll(Frozen):
    face: int
    total: int
    dc: int
    success: bool
    dice: tuple[DiceEvent, ...]
    spends: tuple[str, ...]

    @property
    def bardic_die_spent(self) -> bool:
        return BARDIC_DIE_SPEND in self.spends


class DeathSave(Frozen):
    outcome: DeathSaveOutcome
    dice: tuple[DiceEvent, ...]


class Vitals(Mutable):
    hp: Gauge
    death_successes: int = Field(default=0, ge=0, le=DEATH_SAVES)
    death_failures: int = Field(default=0, ge=0, le=DEATH_SAVES)
    stable: bool = False

    @property
    def is_dead(self) -> bool:
        return self.death_failures >= DEATH_SAVES

    def take_damage(self, amount: int, *, critical: bool) -> DamageTaken:
        if amount <= 0:
            return DamageTaken(dealt=0, dropped=False, died=False)
        if self.hp.current == 0:
            self.stable = False
            failures = DEATH_SAVES if amount >= self.hp.maximum else 2 if critical else 1
            self.death_failures = min(self.death_failures + failures, DEATH_SAVES)
            return DamageTaken(dealt=0, dropped=False, died=self.is_dead)
        dealt = -self.hp.adjust(-amount)
        if self.hp.current > 0:
            return DamageTaken(dealt=dealt, dropped=False, died=False)
        self.clear_death_saves()
        died = amount - dealt >= self.hp.maximum
        if died:
            self.death_failures = DEATH_SAVES
        return DamageTaken(dealt=dealt, dropped=True, died=died)

    def heal(self, amount: int) -> int:
        healed = self.hp.adjust(amount)
        if healed:
            self.clear_death_saves()
        return healed

    def record_death_save(self, test: TestRoll) -> DeathSave:
        if self.hp.current > 0 or self.stable or self.is_dead:
            raise ValueError("only a creature at 0 HP that is not stable rolls a death save")
        dice = test.dice
        if test.face == CRITICAL_FACE:
            _ = self.heal(1)
            return DeathSave(outcome="revived", dice=dice)
        if test.success:
            self.death_successes += 1
        else:
            failures = 2 if test.face == 1 else 1
            self.death_failures = min(self.death_failures + failures, DEATH_SAVES)
        if self.is_dead:
            return DeathSave(outcome="dead", dice=dice)
        if self.death_successes == DEATH_SAVES:
            self.clear_death_saves()
            self.stable = True
            return DeathSave(outcome="stable", dice=dice)
        return DeathSave(outcome="success" if test.success else "failure", dice=dice)

    def clear_death_saves(self) -> None:
        self.death_successes = 0
        self.death_failures = 0
        self.stable = False


class Lite5eSheet(Mutable):
    class_id: ClassId
    level: int = Field(ge=1, le=MAX_LEVEL)
    species_id: SpeciesId
    subspecies_id: SubspeciesId | None
    species_ability: CastingAbility | None
    background_id: Slug
    base_scores: AbilityScores
    background_increases: dict[Ability, int]
    background_skills: tuple[Skill, ...]
    background_tool_id: Slug
    background_feat_id: Slug
    picks: dict[LevelPickKind, list[Slug]]
    replacements_due: list[LevelPickKind]
    vitals: Vitals
    temp_hp: int = Field(default=0, ge=0)
    hit_dice_spent: int = Field(default=0, ge=0)
    slots_spent: dict[int, int] = Field(default_factory=dict)
    made_slots: dict[int, int]
    uses_spent: dict[FeatureUse, int] = Field(default_factory=dict)
    lineage_casts_spent: dict[Slug, int]
    concentration_spell_id: Slug | None = None
    gear: dict[GearId, int]
    equipped_ids: list[GearId]
    exhaustion: int = Field(default=0, ge=0, le=MAX_EXHAUSTION)
    inspiration: bool = False
    inspired_since_long_rest: bool = False
    coins_cp: int = Field(ge=0)
    xp: int = Field(default=0, ge=0)
    aid_hp: int = Field(default=0, ge=0)
    hp_max_cut: int = Field(default=0, ge=0)
    effects: list[SheetEffect] = Field(default_factory=list)

    @model_validator(mode="after")
    def _knows_every_pick(self) -> Self:
        rules = level_pick_rules()
        for kind, pick_ids in self.picks.items():
            if unknown := sorted(set(pick_ids).difference(pick_catalog(rules[kind].vocabulary))):
                raise ValueError(f"{unknown} are no {rules[kind].noun} ids")
        return self

    @model_validator(mode="after")
    def _is_a_legal_build(self) -> Self:
        _check_scores("point-buy", self.base_scores)
        _check_increase_split(self.background_increases)
        return self

    @model_validator(mode="after")
    def _holds_its_hp_maximum(self) -> Self:
        if self.vitals.hp.maximum != self.hp_maximum():
            raise ValueError(f"the HP maximum is {self.hp_maximum()}, not {self.vitals.hp.maximum}")
        return self

    @classmethod
    def start(
        cls,
        *,
        class_id: Slug,
        species_id: Slug,
        subspecies_id: Slug | None,
        species_ability: CastingAbility | None,
        background: Background,
        method: AbilityMethod,
        scores: Mapping[Ability, int],
        increases: Mapping[Ability, int],
    ) -> Self:
        _check_scores(method, scores)
        if strays := sorted(set(increases) - set(background.abilities)):
            raise Refusal(f"{background.name} cannot raise {strays}")
        srd_class = srd().require_class(class_id)
        initiate_list = background.magic_initiate_list
        sheet = cls.model_construct(
            class_id=class_id,
            level=1,
            species_id=species_id,
            subspecies_id=subspecies_id,
            species_ability=species_ability,
            background_id=background.id,
            base_scores=dict(scores),
            background_increases=dict(increases),
            background_skills=background.skill_ids,
            background_tool_id=background.tool_id,
            background_feat_id=background.feat_id,
            picks={} if initiate_list is None else {"initiate-list": [initiate_list]},
            replacements_due=[],
            vitals=Vitals(hp=Gauge(current=0, maximum=0)),
            made_slots={},
            lineage_casts_spent={},
            gear={},
            equipped_ids=[],
            coins_cp=(srd_class.gear_option_a.gp + background.gp) * 100,
        )
        hp = sheet.hp_maximum()
        sheet.vitals.hp = Gauge(current=hp, maximum=hp)
        return parse(cls, sheet.model_dump())

    def finish(
        self,
        *,
        level: int,
        background: Background,
        category_gear_ids: Mapping[Slug, Slug],
        picks: Mapping[LevelPickKind, Sequence[Slug]],
    ) -> None:
        self.level_to(level)
        self.take_level_picks(picks)
        self._add_starting_gear(self.srd_class(), background, category_gear_ids)

    def srd_class(self) -> SrdClass:
        return srd().require_class(self.class_id)

    def class_level(self) -> ClassLevel:
        return self.srd_class().levels[self.level - 1]

    def feature_ids(self) -> frozenset[Slug]:
        levels = self.srd_class().levels[: self.level]
        return frozenset(feature for level in levels for feature in level.feature_ids)

    def features(self) -> tuple[Boon, ...]:
        owned = self.feature_ids()
        features = srd().character_options.features
        return tuple(feature for feature_id, feature in features.items() if feature_id in owned)

    def traits(self) -> tuple[Trait, ...]:
        species = srd().character_options.species[self.species_id]
        traits = species.lineage_traits(self.subspecies_id)
        return tuple(trait for trait in traits if (trait.level or 1) <= self.level)

    def trait_ids(self) -> frozenset[Slug]:
        return frozenset(trait.trait_id for trait in self.traits())

    def invocations(self) -> tuple[Invocation, ...]:
        invocations = srd().character_options.invocations
        return tuple(invocations[found] for found in self.pick_ids("invocation"))

    def class_options(self) -> tuple[ClassOption, ...]:
        options = srd().character_options.class_options
        return tuple(options[found] for kind in CLASS_OPTION_KINDS for found in self.pick_ids(kind))

    def boons(self) -> tuple[Boon, ...]:
        return (
            *self.features(),
            *self.traits(),
            *self.feats(),
            *self.invocations(),
            *self.class_options(),
        )

    def tags(self) -> tuple[str, ...]:
        return tuple(boon.tag for boon in self.boons() if boon.tag is not None)

    def skills(self) -> tuple[Skill, ...]:
        picked = (pick_id for kind in SKILL_PICK_KINDS for pick_id in self.pick_ids(kind))
        return (
            *self.background_skills,
            *(
                _require_member(SKILL_ABILITY, pick_id)
                for pick_id in picked
                if pick_id in SKILL_ABILITY
            ),
        )

    def tool_ids(self) -> tuple[Slug, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.srd_class().tool_ids,
                    self.background_tool_id,
                    *self.pick_ids("tool"),
                    *(
                        pick_id
                        for pick_id in self.pick_ids("skilled")
                        if pick_id not in SKILL_ABILITY
                    ),
                )
            )
        )

    def feat_ids(self) -> tuple[Slug, ...]:
        return (
            self.background_feat_id,
            *self.pick_ids("origin-feat"),
            *self.pick_ids("feat"),
            *self.pick_ids("fighting-style"),
        )

    def feats(self) -> tuple[Feat, ...]:
        feats = srd().character_options.feats
        return tuple(feats[feat_id] for feat_id in self.feat_ids())

    def has_short_rest_slots(self) -> bool:
        return PACT_MAGIC in self.feature_ids()

    def modifiers_of[ModifierT: Frozen](self, kind: type[ModifierT]) -> list[ModifierT]:
        rules = srd().battle_effects.effects
        held = (rules[effect.effect_id] for effect in self.effects if effect.effect_id in rules)
        sources = (*self.boons(), *held)
        return [found for kept in sources for found in kept.modifiers if isinstance(found, kind)]

    def has_advantage(self, on: AdvantageRoll, key: ModifierKey | None = None) -> bool:
        return any(
            found.kind == "advantage" and found.matches(on, key)
            for found in self.modifiers_of(Advantage)
        )

    def bonus_to(self, target: BonusTarget, key: ModifierKey | None = None) -> int:
        return sum(
            self.amount_of(found.amount)
            for found in self.modifiers_of(Bonus)
            if found.matches(target, key)
        )

    def amount_of(self, amount: Amount) -> int:
        match amount:
            case int():
                return amount
            case "proficiency-bonus":
                return self.proficiency_bonus()
            case "half-proficiency-bonus":
                return self.proficiency_bonus() // 2
            case AbilityAmount(ability=ability):
                return max(self.modifier(ability), 1)
            case PerLevelAmount(per_level=per_level):
                return per_level * self.level

    def pick_limit(self, kind: LevelPickKind) -> int:
        levels = self.srd_class().levels[: self.level]
        grants = (*(level.grants for level in levels), *(boon.grants for boon in self.boons()))
        return sum(granted.get(kind, 0) for granted in grants)

    def proficiency_bonus(self) -> int:
        return self.class_level().proficiency_bonus

    def score(self, ability: Ability) -> int:
        raised = self.base_scores[ability] + self.background_increases.get(ability, 0)
        return min(raised + self.pick_ids("ability").count(ability), MAX_SCORE)

    def modifier(self, ability: Ability) -> int:
        return modifier(self.score(ability))

    def armor_class(self, effect_ids: Collection[str] = ()) -> int:
        worn = self.worn_pieces()
        body = next(((armor, bonus) for armor, bonus in worn if armor.category != "shield"), None)
        dexterity = self.modifier("dexterity")
        if body is None:
            mage_armor = "mage-armor" in effect_ids or self.has_effect("mage-armor")
            shield = self.holds_shield()
            bases = [
                MAGE_ARMOR_BASE if mage_armor else NO_UNARMORED_BASE,
                *(
                    base.base + (0 if base.ability is None else self.modifier(base.ability))
                    for base in self.modifiers_of(ArmorBase)
                    if not (base.shieldless and shield)
                ),
            ]
            armor_class = max(bases) + dexterity
        else:
            armor, bonus = body
            armor_class = armor.worn_armor_class(dexterity) + bonus
            armor_class += self.bonus_to("armored-armor-class")
        return armor_class + sum(
            armor.base_ac + bonus for armor, bonus in worn if armor.category == "shield"
        )

    def attack_bonus(self, weapon_id: Slug, *, pact: bool) -> int:
        weapon = _require_weapon(weapon_id)
        bonus = self.weapon_modifier(weapon, pact=pact)
        if pact or self._proficient_with(weapon):
            bonus += self.proficiency_bonus()
        if weapon.kind == "ranged":
            bonus += self.bonus_to("ranged-attack")
        return bonus

    def damage_bonus(self, ability_modifier: int, *, off_hand: bool) -> int:
        if off_hand and TWO_WEAPON_FIGHTING not in self.feat_ids():
            return min(ability_modifier, 0)
        return ability_modifier

    def is_trained_for(self, armor: Armor) -> bool:
        training = "shields" if armor.category == "shield" else armor.category
        trained = (
            *self.srd_class().armor_training,
            *(found for boon in self.boons() for found in boon.armor_training),
        )
        return training in trained

    def is_trained_to_wear(self, gear_id: Slug) -> bool:
        worn = _worn(gear_id)
        return worn is None or self.is_trained_for(worn[0])

    def worn_pieces(self) -> list[tuple[Armor, int]]:
        return [piece for gear_id in self.equipped_ids if (piece := _worn(gear_id)) is not None]

    def wears_heavy_armor(self) -> bool:
        return any(armor.category == "heavy" for armor, _ in self.worn_pieces())

    def holds_shield(self) -> bool:
        return any(armor.category == "shield" for armor, _ in self.worn_pieces())

    def find_martial_arts_die(self) -> int | None:
        if MARTIAL_ARTS not in self.feature_ids():
            return None
        weapons = srd().gear.weapons
        for gear_id in self.equipped_ids:
            weapon = weapons.get(gear_id)
            if weapon is None or not is_monk_weapon(weapon):
                return None
        return self.class_level().class_specific.martial_arts_die

    def crit_range(self) -> int:
        return CRITICAL_FACE - self.bonus_to("critical-range")

    def initiative_bonus(self) -> int:
        penalty = EXHAUSTION_PENALTY * self.exhaustion
        return self.modifier("dexterity") - penalty + self.bonus_to("initiative")

    def has_effect(self, effect_id: Slug) -> bool:
        return any(held.effect_id == effect_id for held in self.effects)

    def end_effects(self, tier: Tier) -> None:
        self.effects[:] = [held for held in self.effects if held.tier != tier]

    def save_bonus(self, ability: Ability) -> int:
        proficient = ability in self.srd_class().saving_throws
        return self.modifier(ability) + (self.proficiency_bonus() if proficient else 0)

    def check_bonus(self, ability: Ability, skill: Skill | None, tool_id: Slug | None) -> int:
        bonus = self.modifier(ability) + self.bonus_to("check", skill)
        if skill in self.pick_ids("expertise"):
            bonus += 2 * self.proficiency_bonus()
        elif skill in self.skills() or tool_id in self.tool_ids():
            bonus += self.proficiency_bonus()
        elif skill is not None:
            bonus += self.bonus_to("unskilled-check")
        return bonus

    def sees_in_dark(self) -> bool:
        return self.bonus_to("light-steps") > 0

    def rerolls_ones(self) -> bool:
        return LUCKY in self.trait_ids()

    def carries_light(self) -> bool:
        gear = srd().gear.gear
        return any(key in gear and gear[key].light_source for key in self.gear)

    def light_seen(self, place_light: Light, *, party_lit: bool) -> Light:
        return raised_light(place_light, self.bonus_to("light-steps") + int(party_lit))

    def passive_perception(self, light: Light) -> int:
        if light == "dark":
            return DARK_PASSIVE
        score = PASSIVE_BASE + self.check_bonus("wisdom", "perception", None)
        edge = self._check_edge("perception")
        score += {"advantage": PASSIVE_EDGE, "disadvantage": -PASSIVE_EDGE, "none": 0}[edge]
        return score - (DIM_PASSIVE_PENALTY if light == "dim" else 0)

    def lineage_spell_ids(self) -> tuple[Slug, ...]:
        return tuple(spell_id for trait in self.traits() for spell_id in trait.spell_ids)

    def always_prepared_ids(self) -> tuple[Slug, ...]:
        return (
            *(
                spell_id
                for boon in self.boons()
                for spell_id in reached_spell_ids(boon.always_prepared, self.level)
            ),
            *self.pick_ids("tome-ritual"),
        )

    def all_prepared_ids(self) -> tuple[Slug, ...]:
        return (*self.pick_ids("prepared"), *self.always_prepared_ids())

    def class_cantrip_ids(self) -> tuple[Slug, ...]:
        return (
            *self.pick_ids("cantrip"),
            *self.pick_ids("warrior-cantrip"),
            *self.pick_ids("tome-cantrip"),
        )

    def class_spell_ids(self) -> tuple[Slug, ...]:
        return (
            *self.class_cantrip_ids(),
            *self.pick_ids("prepared"),
            *self.spellbook_ids(),
            *self.always_prepared_ids(),
        )

    def spellbook_ids(self) -> tuple[Slug, ...]:
        return (*self.pick_ids("spellbook"), *self.pick_ids("savant-spell"))

    def initiate_spell_ids(self) -> tuple[Slug, ...]:
        return (*self.pick_ids("initiate-cantrip"), *self.pick_ids("initiate-spell"))

    def castable_spell_ids(self) -> tuple[Slug, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.class_cantrip_ids(),
                    *self.pick_ids("prepared"),
                    *self.always_prepared_ids(),
                    *self.lineage_spell_ids(),
                    *self.initiate_spell_ids(),
                    *self.invocation_spell_ids(),
                )
            )
        )

    def invocation_spell_ids(self) -> tuple[Slug, ...]:
        return tuple(
            invocation.spell_id
            for invocation in self.invocations()
            if invocation.spell_id is not None
        )

    def pick_ids(self, kind: LevelPickKind) -> list[Slug]:
        return self.picks.get(kind, [])

    def find_pick(self, kind: LevelPickKind) -> Slug | None:
        return next(iter(self.pick_ids(kind)), None)

    def metamagic_ids(self) -> tuple[MetamagicId, ...]:
        metamagic = srd().character_options.metamagic
        return tuple(_require_member(metamagic, pick_id) for pick_id in self.pick_ids("metamagic"))

    def class_list_ids(self) -> list[Slug]:
        slot_totals = self.class_level().slots
        if slot_totals is None:
            return []
        data = srd()
        top = _top_slot_level(slot_totals)
        return [
            spell_id
            for spell_id in data.spell_ids(self.class_id, top)
            if data.require_spell(spell_id).level > 0
        ]

    def attack_count(self) -> int:
        return 1 + self.bonus_to("attacks")

    def prepared_pool(self) -> list[Slug]:
        initiate = self.initiate_spell_ids()
        if self.srd_class().spellbook:
            return [spell_id for spell_id in self.spellbook_ids() if spell_id not in initiate]
        taken = (*self.always_prepared_ids(), *initiate)
        return [spell_id for spell_id in self.class_list_ids() if spell_id not in taken]

    def changes_all_prepared(self) -> bool:
        return self.pick_limit("prepared") > 0 and self.srd_class().prepared_swap is None

    def level_pick_options(self, kind: LevelPickKind) -> list[Slug]:
        rule = level_pick_rules()[kind]
        if rule.replaces is not None:
            due = rule.replaces in self.replacements_due
            return [KEEP, *self.pick_ids(rule.replaces)] if due else []
        held = self.pick_ids(kind)
        if len(held) >= self.pick_limit(kind):
            return []
        return [pick_id for pick_id in rule.pool(self) if rule.repeats or pick_id not in held]

    def level_pick_name(self, kind: LevelPickKind, pick_id: Slug) -> str:
        rule = level_pick_rules()[kind]
        if rule.replaces is not None:
            return (
                "Keep all"
                if pick_id == KEEP
                else f"Replace {self.level_pick_name(rule.replaces, pick_id)}"
            )
        name = pick_catalog(rule.vocabulary)[pick_id]
        if kind == "ability":
            return f"{name} {self.score(_require_member(ABILITIES, pick_id))}"
        return name

    def find_level_pick_kind(self) -> LevelPickKind | None:
        return next((kind for kind in level_pick_rules() if self.level_pick_options(kind)), None)

    def level_pick(self, kind: LevelPickKind, pick_id: Slug) -> str:
        rule = level_pick_rules()[kind]
        if pick_id not in self.level_pick_options(kind):
            raise Refusal(f"{pick_id!r} is no {rule.noun} pick now")
        if rule.replaces is not None:
            self.replacements_due.remove(rule.replaces)
            if pick_id != KEEP:
                self.picks[rule.replaces].remove(pick_id)
        else:
            self.picks.setdefault(kind, []).append(pick_id)
            if rule.take is not None:
                rule.take(self, pick_id)
        self._refresh_hp()
        return f"{rule.noun}: {self.level_pick_name(kind, pick_id)}"

    def default_pick_ids(self, kind: LevelPickKind) -> tuple[Slug, ...]:
        return (
            *self.srd_class().defaults.pick_ids(kind),
            *srd().character_options.default_picks.get(kind, ()),
        )

    def take_level_picks(self, picks: Mapping[LevelPickKind, Sequence[Slug]]) -> None:
        queued = {kind: list(pick_ids) for kind, pick_ids in picks.items()}
        while (kind := self.find_level_pick_kind()) is not None:
            options = self.level_pick_options(kind)
            own = queued.get(kind, [])
            if own:
                pick_id = next((found for found in own if found in options), own[0])
                own.remove(pick_id)
            else:
                asked = {found for pick_ids in queued.values() for found in pick_ids}
                free = [found for found in options if found not in asked] or options
                wanted = self.default_pick_ids(kind)
                pick_id = next((found for found in wanted if found in free), free[0])
            _ = self.level_pick(kind, pick_id)
        if strays := [pick_id for pick_ids in queued.values() for pick_id in pick_ids]:
            raise Refusal(f"no pick is open for {strays}")

    def unprepare(self, spell_id: Slug) -> str:
        prepared = self.pick_ids("prepared")
        if spell_id not in prepared:
            raise Refusal(f"{spell_id!r} is not prepared")
        prepared.remove(spell_id)
        return f"unprepares {srd().require_spell(spell_id).name}"

    def spell_ability(self, spell_id: Slug) -> Ability:
        class_spell_ids = (*self.class_spell_ids(), *self.invocation_spell_ids())
        if spell_id in class_spell_ids and self.srd_class().spell_ability is not None:
            return self.class_spell_ability()
        initiate_ability = self.find_pick("initiate-ability")
        if initiate_ability is not None and spell_id in self.initiate_spell_ids():
            return _require_member(ABILITIES, initiate_ability)
        if spell_id in self.lineage_spell_ids() and self.species_ability is not None:
            return self.species_ability
        raise Refusal(f"{spell_id!r} is not among this member's spells")

    def class_spell_ability(self) -> Ability:
        ability = self.srd_class().spell_ability
        if ability is None:
            raise ValueError(f"the {self.srd_class().name} class casts no spells")
        return ability

    def feature_dc(self, ability: Ability) -> int:
        return 8 + self.modifier(ability) + self.proficiency_bonus()

    def spell_save_dc(self, spell_id: Slug) -> int:
        return 8 + self.spell_attack_bonus(spell_id)

    def spell_attack_bonus(self, spell_id: Slug) -> int:
        return self.modifier(self.spell_ability(spell_id)) + self.proficiency_bonus()

    def slots_left(self, slot_level: int) -> int:
        slot_totals = self.class_level().slots
        total = 0 if slot_totals is None else slot_totals[slot_level - 1]
        made = self.made_slots.get(slot_level, 0)
        return total + made - self.slots_spent.get(slot_level, 0)

    def spend_slot(self, slot_level: int) -> None:
        if self.slots_left(slot_level) <= 0:
            raise Refusal(f"no level {slot_level} spell slot is left")
        self.slots_spent[slot_level] = self.slots_spent.get(slot_level, 0) + 1

    def font_of_magic_refusal(self, slot_level: int) -> str:
        if FONT_OF_MAGIC not in self.feature_ids():
            return f"a level {self.level} {self.srd_class().name} has no Font of Magic"
        cost = MADE_SLOT_COST.get(slot_level)
        if cost is None:
            return "Font of Magic makes a slot of level 1 to 3 only"
        least = MADE_SLOT_SORCERER_LEVEL[slot_level]
        if self.level < least:
            return f"a level {slot_level} slot needs Sorcerer level {least}"
        if self.uses_left("sorcery-points") < cost:
            return f"a level {slot_level} slot costs {cost} Sorcery Points"
        return ""

    def make_slot(self, slot_level: int) -> str:
        if refusal := self.font_of_magic_refusal(slot_level):
            raise Refusal(refusal)
        cost = MADE_SLOT_COST[slot_level]
        self.spend_use("sorcery-points", cost)
        self.made_slots[slot_level] = self.made_slots.get(slot_level, 0) + 1
        return f"Font of Magic: a level {slot_level} slot for {cost} Sorcery Points"

    def open_slot_levels(self, lowest: int) -> tuple[int, ...]:
        slot_totals = self.class_level().slots
        if slot_totals is None:
            return ()
        return tuple(
            level for level in range(lowest, len(slot_totals) + 1) if self.slots_left(level) > 0
        )

    def has_free_cast(self, spell_id: Slug) -> bool:
        return (
            spell_id in self.invocation_spell_ids()
            or self.lineage_casts_left(spell_id) > 0
            or self._free_cast_use(spell_id) is not None
        )

    def cast_slot_levels(self, spell_id: Slug, *, slot_open: bool) -> tuple[int, ...]:
        spell = srd().require_spell(spell_id)
        if spell.level == 0:
            return ()
        slotted = self.open_slot_levels(spell.level) if slot_open else ()
        free = [spell.level] if self.has_free_cast(spell_id) else []
        return tuple(sorted({*slotted, *free}))

    def pay_cast(self, spell_id: Slug, slot_level: int, *, slot_open: bool) -> bool:
        spell = srd().require_spell(spell_id)
        known = spell_id in self.castable_spell_ids()
        if spell.level == 0:
            if slot_level:
                raise Refusal(f"{spell.name} is a cantrip: it takes no slot")
            if not known:
                raise Refusal(f"{spell.name} is not among this caster's cantrips")
            return False
        if not known:
            raise Refusal(f"{spell.name} is not prepared")
        if slot_level < spell.level:
            raise Refusal(f"{spell.name} needs a slot of level {spell.level} at least")
        if slot_level == spell.level and self._spend_free_cast(spell_id):
            return False
        if not slot_open:
            raise Refusal("one spell slot per turn")
        self.spend_slot(slot_level)
        return True

    def recover_pact_slots(self) -> int:
        slot_totals = self.class_level().slots
        if self.uses_left("magical-cunning") <= 0 or slot_totals is None:
            return 0
        pact_level = _top_slot_level(slot_totals)
        half = ceil(slot_totals[pact_level - 1] / 2)
        back = min(half, self.slots_spent.get(pact_level, 0))
        if back == 0:
            return 0
        self.slots_spent[pact_level] -= back
        self.spend_use("magical-cunning")
        return back

    def owns(self, source_id: Slug) -> bool:
        return (
            source_id in self.feature_ids()
            or source_id in self.trait_ids()
            or source_id in self.feat_ids()
            or source_id in self.pick_ids("invocation")
            or source_id in (self.species_id, self.subspecies_id)
        )

    def use_limit(self, use: FeatureUse) -> int:
        rule = srd().character_options.feature_uses[use]
        if rule.source_id is not None and not self.owns(rule.source_id):
            return 0
        if rule.amount == "class-level":
            return self.class_level().use_counts.get(use, 0)
        return self.amount_of(rule.amount)

    def uses_left(self, use: FeatureUse) -> int:
        return self.use_limit(use) - self.uses_spent.get(use, 0)

    def spend_use(self, use: FeatureUse, amount: int = 1) -> None:
        left = self.uses_left(use)
        if left <= 0:
            raise Refusal(f"no {use} use is left")
        if left < amount:
            raise Refusal(f"only {left} {use} is left, not {amount}")
        self.uses_spent[use] = self.uses_spent.get(use, 0) + amount

    def lineage_casts_left(self, spell_id: Slug) -> int:
        if spell_id not in self.lineage_spell_ids() or srd().require_spell(spell_id).level == 0:
            return 0
        proficient = any(
            trait.free_casts == "proficiency-bonus" and spell_id in trait.spell_ids
            for trait in self.traits()
        )
        limit = self.proficiency_bonus() if proficient else 1
        return limit - self.lineage_casts_spent.get(spell_id, 0)

    def gain_xp(self, amount: int) -> None:
        self.xp = min(self.xp + amount, MAX_XP)

    def resistances(self) -> frozenset[DamageType]:
        return frozenset(
            found for kept in self.modifiers_of(Resistance) for found in kept.damage_types
        )

    def add_gear(self, gear_id: Slug, count: int) -> None:
        pack = srd().gear.gear.get(gear_id)
        if pack is not None and pack.contents:
            for part_id, part_count in pack.contents.items():
                self.add_gear(part_id, part_count * count)
            return
        self.gear[gear_id] = self.gear.get(gear_id, 0) + count

    def remove_gear(self, gear_id: Slug, count: int) -> None:
        held = self.gear.get(gear_id, 0)
        if held < count:
            raise Refusal(f"holds {held} {gear_name(gear_id)}, not {count}")
        if held > count:
            self.gear[gear_id] = held - count
            return
        del self.gear[gear_id]
        if gear_id in self.equipped_ids:
            self.equipped_ids.remove(gear_id)

    def equip(self, gear_id: Slug) -> str:
        name = gear_name(gear_id)
        if not self.gear.get(gear_id):
            raise Refusal(f"{name} is not carried")
        slot = equip_slot(gear_id)
        if slot is None:
            raise Refusal(f"{name} is not a weapon, armor or a shield")
        if gear_id in self.equipped_ids:
            raise Refusal(f"{name} is already equipped")
        worn = _worn(gear_id)
        if worn is not None and not self.is_trained_for(worn[0]):
            raise Refusal(f"{name} needs {worn[0].category} armor training")
        if slot != "weapon":
            self.equipped_ids[:] = [held for held in self.equipped_ids if equip_slot(held) != slot]
        self.equipped_ids.append(gear_id)
        return f"equips {name}"

    def unequip(self, gear_id: Slug) -> str:
        if gear_id not in self.equipped_ids:
            raise Refusal(f"{gear_name(gear_id)} is not equipped")
        self.equipped_ids.remove(gear_id)
        return f"unequips {gear_name(gear_id)}"

    def spend_drink(self, gear_id: Slug) -> Healing | None:
        if not is_drinkable(gear_id):
            raise Refusal(f"{gear_name(gear_id)} is not a drink")
        self.remove_gear(gear_id, 1)
        potion = srd().gear.magic_items.get(gear_id)
        return None if potion is None else potion.healing

    def roll_check(
        self,
        ability: Ability,
        skill: Skill | None,
        tool_id: Slug | None,
        dc: int,
        edge: Edge,
        rng: Random,
        *,
        guided: bool,
        bardic_die: int | None,
        in_battle: bool,
    ) -> TestRoll:
        label = check_name(ability, skill, tool_id)
        bonus = self.check_bonus(ability, skill, tool_id)
        edge = combined_edge(edge, self._check_edge(skill))
        dice: list[DiceEvent] = []
        if guided:
            bonus += _roll_guidance(rng, dice)
        test = self.roll_test(label, bonus, dc, edge, rng, bardic_die, dice)
        if test.success or in_battle or TACTICAL_MIND not in self.feature_ids():
            return test
        if self.uses_left("second-wind") <= 0:
            return test
        tactical = roll((TACTICAL_MIND_DIE,), "Tactical Mind", rng, label="Tactical Mind")
        total = test.total + tactical.total
        spends = test.spends
        if total >= dc:
            self.spend_use("second-wind")
            spends = (*spends, "Tactical Mind")
        return TestRoll(
            face=test.face,
            total=total,
            dc=dc,
            success=total >= dc,
            dice=(*test.dice, tactical.event),
            spends=spends,
        )

    def roll_save(
        self,
        ability: Ability,
        dc: int,
        edge: Edge,
        rng: Random,
        *,
        against: Condition | None,
        bardic_die: int | None,
    ) -> TestRoll:
        advantage = self.has_advantage("save", ability) or self.has_advantage("save", against)
        own: Edge = "advantage" if advantage else "none"
        label = f"{ability} save"
        return self.roll_test(
            label, self.save_bonus(ability), dc, combined_edge(edge, own), rng, bardic_die
        )

    def take_harm(self, amount: int, damage_type: DamageType) -> int:
        if damage_type in self.resistances():
            amount //= 2
        spared = max(min(amount, self.temp_hp + self.vitals.hp.current - 1), 0)
        return self.take_damage(spared, critical=False).dealt

    def take_damage(self, amount: int, *, critical: bool) -> DamageTaken:
        absorbed = min(self.temp_hp, amount)
        self.temp_hp -= absorbed
        taken = self.vitals.take_damage(amount - absorbed, critical=critical)
        return DamageTaken(dealt=absorbed + taken.dealt, dropped=taken.dropped, died=taken.died)

    def take_aid(self, steps: int) -> int:
        self.aid_hp = AID_HP * (steps + 1)
        self._refresh_hp()
        return self.aid_hp

    def gain_false_life(self, steps: int, rng: Random) -> DiceEvent:
        rolled = roll(FALSE_LIFE_DICE, "False Life", rng, label="False Life")
        _ = self.gain_temp_hp(rolled.total + FALSE_LIFE_BONUS + FALSE_LIFE_PER_LEVEL * steps)
        return rolled.event

    def gain_temp_hp(self, amount: int) -> bool:
        if amount <= self.temp_hp:
            return False
        self.temp_hp = amount
        return True

    def hp_maximum(self) -> int:
        hit_die = self.srd_class().hit_die
        constitution = self.modifier("constitution")
        first = max(hit_die + constitution, 1)
        later = max(hit_die // 2 + 1 + constitution, 1) * (self.level - 1)
        boons = self.bonus_to("hit-points")
        return max(first + later + boons + self.aid_hp - self.hp_max_cut, 0)

    def cut_hp_maximum(self, amount: int) -> None:
        self.hp_max_cut += min(amount, self.vitals.hp.maximum)
        self._refresh_hp()

    def hit_dice_left(self) -> int:
        return self.level - self.hit_dice_spent

    def spend_hit_die(self, rng: Random) -> Rolled:
        if self.hit_dice_left() <= 0:
            raise Refusal("no Hit Die is left")
        self.hit_dice_spent += 1
        rolled = roll((self.srd_class().hit_die,), "Hit Die", rng)
        _ = self.vitals.heal(max(rolled.total + self.modifier("constitution"), 0))
        return rolled

    def short_rest(self) -> list[str]:
        back: list[str] = []
        features = self.feature_ids()
        for use, rule in srd().character_options.feature_uses.items():
            recovery = "short-rest-all" if rule.short_rest_with in features else rule.recovery
            if recovery == "short-rest-one" and self.uses_spent.get(use, 0) > 0:
                self.uses_spent[use] -= 1
                back.append(f"{use}: 1 use")
            elif recovery == "short-rest-all" and self.uses_spent.pop(use, 0):
                back.append(f"{use}: all uses")
        if restored := self._sorcerous_restoration():
            back.append(f"Sorcerous Restoration: {restored} Sorcery Points")
        if restored := self._arcane_recovery():
            back.append(f"Arcane Recovery: {restored}")
        if self.has_short_rest_slots() and any(self.slots_spent.values()):
            self.slots_spent.clear()
            back.append("Pact Magic: all slots")
        return back

    def long_rest(self) -> None:
        self._restore()
        if self.srd_class().prepared_swap == "long-rest":
            self._mark_replacement("prepared", due=bool(self.pick_ids("prepared")))
        self.exhaustion = max(self.exhaustion - 1, 0)
        self.inspired_since_long_rest = False
        if RESOURCEFUL in self.trait_ids():
            self.inspiration = True

    def rows(self) -> Rows:
        slot_totals = self.class_level().slots
        gear = ", ".join(
            f"{gear_name(gear_id)} x{count}"
            + (" (equipped)" if gear_id in self.equipped_ids else "")
            for gear_id, count in self.gear.items()
        )
        spells: Rows = (
            ()
            if slot_totals is None
            else (
                (
                    "slots",
                    ", ".join(
                        f"L{level} {self.slots_left(level)}/{total}"
                        for level, total in enumerate(slot_totals, 1)
                        if total
                    ),
                ),
                ("cantrips", _spell_names(self.class_cantrip_ids())),
                ("prepared", _spell_names(self.all_prepared_ids())),
            )
        )
        effects = ", ".join(f"{held.effect_id} (until {held.tier})" for held in self.effects)
        return (
            ("class", f"{self.srd_class().name} {self.level}"),
            ("HP", f"{self.vitals.hp}, temporary {self.temp_hp}"),
            ("exhaustion", str(self.exhaustion)),
            *((("effects", effects),) if effects else ()),
            ("Hit Dice", f"{self.hit_dice_left()}/{self.level}"),
            *spells,
            ("concentration", self.concentration_spell_id or "none"),
            ("inspiration", "yes" if self.inspiration else "no"),
            *((("sight", "sees in the dark"),) if self.sees_in_dark() else ()),
            *(("trait", tag) for tag in self.tags()),
            ("skills", ", ".join(self.skills())),
            ("tools", ", ".join(self.tool_ids()) or "none"),
            ("gear", gear or "none"),
        )

    def written_back(self) -> Self:
        grown = self.model_copy(deep=True)
        grown._restore()
        grown.exhaustion = 0
        return grown

    def level_to(self, level: int) -> None:
        if not self.level <= level <= MAX_LEVEL:
            raise Refusal(f"level {level} is not between {self.level} and {MAX_LEVEL}")
        if (
            level > self.level
            and self.srd_class().prepared_swap == "level-up"
            and self.pick_ids("prepared")
        ):
            self._mark_replacement("prepared", due=True)
        if level > self.level and self.pick_ids("metamagic"):
            self._mark_replacement("metamagic", due=True)
        pact_spent = sum(self.slots_spent.values()) if self.has_short_rest_slots() else 0
        self.level = level
        self._refresh_hp()
        slot_totals = self.class_level().slots
        if pact_spent and slot_totals is not None:
            self.slots_spent = {_top_slot_level(slot_totals): pact_spent}
        self.drop_always_prepared()

    def drop_always_prepared(self) -> None:
        always = self.always_prepared_ids()
        kinds: tuple[LevelPickKind, ...] = (
            "cantrip",
            "prepared",
            "initiate-cantrip",
            "initiate-spell",
        )
        for kind in kinds:
            if kind in self.picks:
                self.picks[kind][:] = [found for found in self.picks[kind] if found not in always]

    def _mark_replacement(self, kind: LevelPickKind, *, due: bool) -> None:
        if kind in self.replacements_due:
            self.replacements_due.remove(kind)
        if due:
            self.replacements_due.append(kind)

    def _restore(self) -> None:
        self.aid_hp = 0
        self.hp_max_cut = 0
        self._refresh_hp()
        self.vitals.hp.current = self.vitals.hp.maximum
        self.vitals.clear_death_saves()
        self.effects.clear()
        self.temp_hp = 0
        self.hit_dice_spent = 0
        self.slots_spent.clear()
        self.made_slots.clear()
        self.uses_spent.clear()
        self.lineage_casts_spent.clear()
        self.concentration_spell_id = None

    def _refresh_hp(self) -> None:
        hp = self.vitals.hp
        gain = self.hp_maximum() - hp.maximum
        hp.maximum += gain
        if gain > 0:
            _ = self.vitals.heal(gain)
        hp.current = min(hp.current, hp.maximum)

    def _sorcerous_restoration(self) -> int:
        spent = self.uses_spent.get("sorcery-points", 0)
        back = min(self.level // 2, spent)
        if self.uses_left("sorcerous-restoration") <= 0 or back == 0:
            return 0
        self.uses_spent["sorcery-points"] = spent - back
        self.spend_use("sorcerous-restoration")
        return back

    def _free_cast_use(self, spell_id: Slug) -> FeatureUse | None:
        initiate = spell_id in self.initiate_spell_ids()
        uses: list[FeatureUse] = ["magic-initiate"] if initiate else []
        uses.extend(
            use
            for use, rule in srd().character_options.feature_uses.items()
            if rule.free_cast_spell_id == spell_id
        )
        return next((use for use in uses if self.uses_left(use) > 0), None)

    def _spend_free_cast(self, spell_id: Slug) -> bool:
        if spell_id in self.invocation_spell_ids():
            return True
        if self.lineage_casts_left(spell_id) > 0:
            self.lineage_casts_spent[spell_id] = self.lineage_casts_spent.get(spell_id, 0) + 1
            return True
        use = self._free_cast_use(spell_id)
        if use is None:
            return False
        self.spend_use(use)
        return True

    def _add_starting_gear(
        self,
        srd_class: SrdClass,
        background: Background,
        category_gear_ids: Mapping[Slug, Slug],
    ) -> None:
        for part in (*srd_class.gear_option_a.gear, *background.gear):
            self.add_gear(part.gear_id, part.count)
        gear = srd().gear
        for category in srd_class.gear_option_a.gear_categories:
            offered = gear.categories[category.category_id]
            picked = next(
                (tool_id for tool_id in self.pick_ids("tool") if tool_id in offered),
                category_gear_ids.get(category.category_id, offered[0]),
            )
            if picked not in offered:
                raise Refusal(f"pick one of {offered}")
            self.add_gear(picked, category.count)
        self.equipped_ids = [
            gear_id
            for gear_id in self.gear
            if gear_id in gear.armor and self.is_trained_for(gear.armor[gear_id])
        ]
        self.equipped_ids.extend(
            [part.gear_id for part in srd_class.gear_option_a.gear if part.gear_id in gear.weapons][
                :1
            ]
        )

    def weapon_modifier(self, weapon: Weapon, *, pact: bool) -> int:
        strength, dexterity = self.modifier("strength"), self.modifier("dexterity")
        martial_arts = is_monk_weapon(weapon) and self.find_martial_arts_die() is not None
        nimble = martial_arts or "finesse" in weapon.properties
        chosen = max(strength, dexterity) if nimble else strength
        chosen = dexterity if weapon.kind == "ranged" else chosen
        return max(chosen, self.modifier("charisma")) if pact else chosen

    def _proficient_with(self, weapon: Weapon) -> bool:
        proficiencies = (
            *self.srd_class().weapon_proficiencies,
            *(found for boon in self.boons() for found in boon.weapon_proficiencies),
        )
        if weapon.category == "simple":
            return "simple" in proficiencies
        return (
            "martial" in proficiencies
            or (
                "martial-finesse-or-light" in proficiencies
                and not FINESSE_OR_LIGHT.isdisjoint(weapon.properties)
            )
            or ("martial-light" in proficiencies and "light" in weapon.properties)
        )

    def _check_edge(self, skill: Skill | None) -> Edge:
        advantage = skill is not None and self.has_advantage("check", skill)
        disadvantage = skill == "stealth" and any(
            armor.stealth_disadvantage for armor, _ in self.worn_pieces()
        )
        return combined_edge(
            "advantage" if advantage else "none", "disadvantage" if disadvantage else "none"
        )

    def roll_test(
        self,
        label: str,
        bonus: int,
        dc: int,
        edge: Edge,
        rng: Random,
        bardic_die: int | None,
        dice: Sequence[DiceEvent] = (),
        *,
        natural_one_fails: bool = False,
    ) -> TestRoll:
        test = roll_test(
            label,
            bonus - EXHAUSTION_PENALTY * self.exhaustion,
            dc,
            edge,
            rng,
            bardic_die,
            lucky=self.rerolls_ones(),
            inspired=self.inspiration,
            natural_one_fails=natural_one_fails,
            dice=dice,
        )
        if HEROIC_INSPIRATION in test.spends:
            self.inspiration = False
        return test

    def _arcane_recovery(self) -> str:
        if self.uses_left("arcane-recovery") <= 0 or not any(self.slots_spent.values()):
            return ""
        budget = ceil(self.level / 2)
        restored: Counter[int] = Counter()
        for slot_level in sorted(self.slots_spent, reverse=True):
            while self.slots_spent[slot_level] > 0 and slot_level <= budget:
                self.slots_spent[slot_level] -= 1
                budget -= slot_level
                restored[slot_level] += 1
        if not restored:
            return ""
        self.spend_use("arcane-recovery")
        return ", ".join(f"{count} level {level} slot" for level, count in restored.items())


class Lite5ePerson(Sheeted[Lite5eSheet], Dweller):
    stat_block_id: StatBlockId = Field(
        default=COMMONER,
        description="The id of the SRD stat block that gives this person or group its numbers, "
        "such as 'bandit-captain' or 'wolf'. Commoner when none fits better.",
    )
    count: int = Field(
        default=1,
        ge=1,
        le=8,
        description="How many stand in this group, from 1 to 8. A named enemy is 1.",
    )
    hostile: bool = Field(default=False, description="True when it attacks the party on sight.")
    captive: bool = Field(default=False, description="True when it is held as a captive.")
    find: Difficulty | None = Field(
        default=None,
        description="How hard this hidden person is to notice. The party notices it on arrival "
        "when its best passive Perception is at least the word's DC. Null: it hides by its "
        "Stealth when the party arrives or it walks in.",
    )
    conditions: SkipJsonSchema[list[TimedCondition]] = Field(default_factory=list)
    stat_block_vitals: SkipJsonSchema[Vitals | None] = None
    portrait_id: SkipJsonSchema[Slug | None] = None
    formation_row: SkipJsonSchema[FormationRow] = "front"
    routed: SkipJsonSchema[bool] = False
    xp_paid: SkipJsonSchema[bool] = False
    stealth_total: SkipJsonSchema[int | None] = None
    missed: SkipJsonSchema[bool] = False

    @property
    def has_sheet(self) -> bool:
        return self.sheet is not None or self.stat_block_vitals is not None

    @property
    def vitals(self) -> Vitals | None:
        return self.stat_block_vitals if self.sheet is None else self.sheet.vitals

    def stat_block(self) -> StatBlock:
        return srd().require_stat_block(self.stat_block_id)

    def regroup(self) -> None:
        self.routed = False
        self.name = self.name.removesuffix(ROUTED_NAME_SUFFIX)

    def fill_stat_block_hp(self) -> None:
        hit_points = self.stat_block().hit_points
        self.stat_block_vitals = Vitals(hp=Gauge(current=hit_points, maximum=hit_points))

    def sprite(self) -> Sprite:
        if self.portrait_id is not None:
            return portrait_sprite(self.portrait_id)
        return stat_block_sprite(self.stat_block_id)

    def master_rows(self) -> Rows:
        hidden: Rows = (
            ()
            if self.known
            else (
                *((("find", self.find),) if self.find is not None else ()),
                *(
                    (("unseen arrival, find DC", str(self.stealth_total)),)
                    if self.stealth_total is not None
                    else ()
                ),
                *((("arrival check", "missed it"),) if self.missed else ()),
            )
        )
        if self.sheet is not None:
            own = self.sheet.rows()
        else:
            block = self.stat_block()
            own = (
                ("stat block", f"{block.name}, CR {block.challenge_rating}"),
                *((("HP", str(self.stat_block_vitals.hp)),) if self.stat_block_vitals else ()),
                *((("count", str(self.count)),) if self.count > 1 else ()),
            )
        conditions = ", ".join(f"{held.condition} (until {held.tier})" for held in self.conditions)
        flags = [
            flag
            for flag, on in (
                ("hostile", self.hostile),
                ("routed", self.routed),
                ("captive", self.captive),
            )
            if on
        ]
        return (
            *hidden,
            *own,
            *((("conditions", conditions),) if conditions else ()),
            *((("state", ", ".join(flags)),) if flags else ()),
        )

    def require_vitals(self) -> Vitals:
        if self.vitals is None:
            raise ValueError(f"{self.id} has no HP of its own")
        return self.vitals

    def light_seen(self, place_light: Light, *, party_lit: bool) -> Light:
        if self.sheet is not None:
            return self.sheet.light_seen(place_light, party_lit=party_lit)
        return raised_light(place_light, int(self.stat_block().darkvision) + int(party_lit))

    def passive_perception(self, light: Light) -> int:
        if self.sheet is not None:
            return self.sheet.passive_perception(light)
        if light == "dark":
            return DARK_PASSIVE
        penalty = DIM_PASSIVE_PENALTY if light == "dim" else 0
        return self.stat_block().passive_perception - penalty

    def roll_check(
        self,
        ability: Ability,
        skill: Skill | None,
        tool_id: Slug | None,
        dc: int,
        edge: Edge,
        rng: Random,
        *,
        guided: bool,
        bardic_die: int | None,
        in_battle: bool,
    ) -> TestRoll:
        poisoned: Edge = "disadvantage" if self.has_condition("poisoned") else "none"
        edge = combined_edge(edge, poisoned)
        if self.sheet is not None:
            return self.sheet.roll_check(
                ability,
                skill,
                tool_id,
                dc,
                edge,
                rng,
                guided=guided,
                bardic_die=bardic_die,
                in_battle=in_battle,
            )
        bonus = self.stat_block().check_bonus(ability, skill)
        dice: list[DiceEvent] = []
        if guided:
            bonus += _roll_guidance(rng, dice)
        return roll_test(
            check_name(ability, skill, tool_id), bonus, dc, edge, rng, bardic_die, dice=dice
        )

    def has_condition(self, condition: Condition) -> bool:
        return any(held.condition == condition for held in self.conditions)

    def roll_save(
        self,
        ability: Ability,
        dc: int,
        edge: Edge,
        rng: Random,
        *,
        against: Condition | None,
        bardic_die: int | None,
    ) -> TestRoll:
        if self.sheet is not None:
            return self.sheet.roll_save(
                ability, dc, edge, rng, against=against, bardic_die=bardic_die
            )
        bonus = self.stat_block().save_bonus(ability)
        return roll_test(f"{ability} save", bonus, dc, edge, rng, bardic_die)

    def take_harm(self, amount: int, damage_type: DamageType) -> int:
        if self.sheet is not None:
            return self.sheet.take_harm(amount, damage_type)
        if self.stat_block_vitals is None:
            raise Refusal(f"{self.name} has no HP to lose outside a battle")
        hp = self.stat_block_vitals.hp
        amount = self.stat_block().resisted(amount, damage_type, warded=False)
        lost = max(min(amount, hp.current - 1), 0)
        hp.adjust(-lost)
        return lost

    def take_damage(self, amount: int, *, critical: bool) -> DamageTaken:
        if self.sheet is not None:
            return self.sheet.take_damage(amount, critical=critical)
        return self.require_vitals().take_damage(amount, critical=critical)

    def roll_death_save(
        self, edge: Edge, rng: Random, *, dc: int, bardic_die: int | None
    ) -> tuple[DeathSave, TestRoll]:
        roller = roll_test if self.sheet is None else self.sheet.roll_test
        test = roller(DEATH_SAVE, 0, dc, edge, rng, bardic_die, natural_one_fails=True)
        return self.require_vitals().record_death_save(test), test


@dataclass(frozen=True, slots=True, kw_only=True)
class LevelPickRule:
    noun: str
    vocabulary: PickVocabulary
    pool: Callable[[Lite5eSheet], Iterable[Slug]] = lambda _sheet: ()
    take: Callable[[Lite5eSheet, Slug], None] | None = None
    repeats: bool = False
    replaces: LevelPickKind | None = None


@cache
def level_pick_rules() -> Mapping[LevelPickKind, LevelPickRule]:
    return {
        "class-skill": LevelPickRule(
            noun="class skill",
            vocabulary="proficiency",
            pool=lambda sheet: _unlearned(sheet, sheet.srd_class().skill_options),
        ),
        "species-skill": LevelPickRule(
            noun="species skill",
            vocabulary="proficiency",
            pool=lambda sheet: _unlearned(
                sheet, [skill for trait in sheet.traits() for skill in trait.skill_options]
            ),
        ),
        "tool": LevelPickRule(
            noun="tool",
            vocabulary="proficiency",
            pool=lambda sheet: [
                tool_id
                for tool_id in sheet.srd_class().tool_options
                if tool_id not in sheet.tool_ids()
            ],
        ),
        "origin-feat": LevelPickRule(
            noun="origin feat",
            vocabulary="feat",
            pool=lambda sheet: _typed_feats(sheet, "origin"),
        ),
        "feat": LevelPickRule(noun="feat", vocabulary="feat", pool=_feat_pool, repeats=True),
        "ability": LevelPickRule(
            noun="ability increase",
            vocabulary="ability",
            pool=lambda sheet: [a for a in ABILITIES if sheet.score(a) < MAX_SCORE],
            repeats=True,
        ),
        "skilled": LevelPickRule(
            noun="Skilled",
            vocabulary="proficiency",
            pool=lambda sheet: [
                pick_id
                for pick_id in pick_catalog("proficiency")
                if pick_id not in sheet.skills() and pick_id not in sheet.tool_ids()
            ],
        ),
        "initiate-list": LevelPickRule(
            noun="Magic Initiate list",
            vocabulary="spell-list",
            pool=lambda _sheet: MAGIC_INITIATE_ABILITY,
        ),
        "initiate-ability": LevelPickRule(
            noun="Magic Initiate spellcasting",
            vocabulary="ability",
            pool=_initiate_abilities,
        ),
        "initiate-cantrip": LevelPickRule(
            noun="Magic Initiate cantrip",
            vocabulary="spell",
            pool=lambda sheet: _initiate_pool(sheet, 0),
        ),
        "initiate-spell": LevelPickRule(
            noun="Magic Initiate spell",
            vocabulary="spell",
            pool=lambda sheet: _initiate_pool(sheet, 1),
        ),
        "class-order": LevelPickRule(
            noun="class order",
            vocabulary="class-option",
            pool=lambda sheet: _class_option_pool(sheet, "class-order"),
        ),
        "land": LevelPickRule(
            noun="land",
            vocabulary="class-option",
            pool=lambda sheet: _class_option_pool(sheet, "land"),
            take=lambda sheet, _pick_id: sheet.drop_always_prepared(),
        ),
        "cantrip": LevelPickRule(noun="cantrip", vocabulary="spell", pool=_cantrip_pool),
        "spellbook": LevelPickRule(
            noun="spellbook",
            vocabulary="spell",
            pool=lambda sheet: _spellbook_pool(sheet, schools=None),
        ),
        "savant-spell": LevelPickRule(
            noun="Evocation Savant spell",
            vocabulary="spell",
            pool=lambda sheet: _spellbook_pool(sheet, schools=("evocation",)),
        ),
        "expertise": LevelPickRule(
            noun="Expertise", vocabulary="proficiency", pool=_expertise_pool
        ),
        "lore-skill": LevelPickRule(
            noun="Bonus Proficiencies skill",
            vocabulary="proficiency",
            pool=lambda sheet: _unlearned(sheet, SKILL_ABILITY),
        ),
        "fighting-style": LevelPickRule(
            noun="Fighting Style",
            vocabulary="feat",
            pool=lambda sheet: _typed_feats(sheet, "fighting-style"),
        ),
        "warrior-cantrip": LevelPickRule(
            noun="warrior cantrip", vocabulary="spell", pool=_warrior_cantrip_pool
        ),
        "primal-knowledge": LevelPickRule(
            noun="Primal Knowledge skill",
            vocabulary="proficiency",
            pool=lambda sheet: _unlearned(sheet, sheet.srd_class().skill_options),
        ),
        "invocation": LevelPickRule(
            noun="Eldritch Invocation", vocabulary="invocation", pool=_invocation_pool
        ),
        "pact-weapon": LevelPickRule(
            noun="pact weapon",
            vocabulary="weapon",
            pool=lambda _sheet: [
                weapon_id
                for weapon_id, weapon in srd().gear.weapons.items()
                if weapon.kind == "melee" and not weapon.magic_bonus
            ],
        ),
        "tome-cantrip": LevelPickRule(
            noun="Book of Shadows cantrip",
            vocabulary="spell",
            pool=lambda sheet: _tome_cantrip_choices(sheet.castable_spell_ids()),
        ),
        "tome-ritual": LevelPickRule(
            noun="Book of Shadows ritual",
            vocabulary="spell",
            pool=lambda sheet: _tome_ritual_choices(sheet.castable_spell_ids()),
        ),
        "replace-metamagic": LevelPickRule(
            noun="Metamagic option to replace", vocabulary="metamagic", replaces="metamagic"
        ),
        "metamagic": LevelPickRule(
            noun="Metamagic option",
            vocabulary="metamagic",
            pool=lambda _sheet: srd().character_options.metamagic,
        ),
        "replace-prepared": LevelPickRule(
            noun="prepared spell to replace", vocabulary="spell", replaces="prepared"
        ),
        "prepared": LevelPickRule(
            noun="prepared spell", vocabulary="spell", pool=lambda sheet: sheet.prepared_pool()
        ),
    }


@cache
def pick_catalog(vocabulary: PickVocabulary) -> Mapping[Slug, str]:
    data = srd()
    options = data.character_options
    match vocabulary:
        case "proficiency":
            tools = {
                gear_id: gear.name
                for gear_id, gear in data.gear.gear.items()
                if gear.group == "tool"
            }
            return {**{skill: skill_name(skill) for skill in SKILL_ABILITY}, **tools}
        case "feat":
            return {feat_id: feat.name for feat_id, feat in options.feats.items()}
        case "ability":
            return {ability: ability.title() for ability in ABILITIES}
        case "spell-list":
            return {spell_list: spell_list.title() for spell_list in MAGIC_INITIATE_ABILITY}
        case "spell":
            return {spell_id: spell.name for spell_id, spell in data.spells.spells.items()}
        case "class-option":
            return {option_id: option.name for option_id, option in options.class_options.items()}
        case "invocation":
            return {found_id: found.name for found_id, found in options.invocations.items()}
        case "weapon":
            return {weapon_id: weapon.name for weapon_id, weapon in data.gear.weapons.items()}
        case "metamagic":
            return {found_id: found.name for found_id, found in options.metamagic.items()}


def gear_name(gear_id: Slug) -> str:
    return srd().require_gear(gear_id).name


def check_name(ability: Ability, skill: Skill | None, tool_id: Slug | None) -> str:
    if skill is not None:
        return skill_name(skill)
    if tool_id is not None:
        return gear_name(tool_id)
    return ability.title()


def equip_slot(gear_id: Slug) -> EquipSlot | None:
    worn = _worn(gear_id)
    if worn is not None:
        return "shield" if worn[0].category == "shield" else "body"
    return "weapon" if gear_id in srd().gear.weapons else None


def is_drinkable(gear_id: Slug) -> bool:
    gear = srd().gear
    magic = gear.magic_items.get(gear_id)
    plain = gear.gear.get(gear_id)
    return (magic is not None and magic.kind == "potion") or (
        plain is not None and plain.effect is not None and plain.effect.use == "drink"
    )


def roll_healing(healing: Healing, label: str, rng: Random) -> tuple[int, DiceEvent]:
    count, faces = dice_parts(healing.dice)
    rolled = roll((faces,) * count, label, rng, label=label)
    return max(rolled.total + healing.bonus, 0), rolled.event


def combined_edge(*edges: Edge) -> Edge:
    advantage = "advantage" in edges
    disadvantage = "disadvantage" in edges
    if advantage == disadvantage:
        return "none"
    return "advantage" if advantage else "disadvantage"


def roll_test(
    label: str,
    bonus: int,
    dc: int,
    edge: Edge,
    rng: Random,
    bardic_die: int | None = None,
    *,
    lucky: bool = False,
    inspired: bool = False,
    natural_one_fails: bool = False,
    dice: Sequence[DiceEvent] = (),
) -> TestRoll:
    events = list(dice)
    spends: list[str] = []
    face, rolled, luck_used = roll_d20(label, edge, rng, lucky=lucky)
    events.extend(rolled)
    spends.extend([LUCK] if luck_used else [])
    total = face + bonus
    fumbled = natural_one_fails and face == 1
    if bardic_die is not None and not fumbled:
        raised = bardic_total(total, dc, bardic_die, rng, events)
        if raised is not None:
            total = raised
            spends.append(BARDIC_DIE_SPEND)
    if (fumbled or total < dc) and inspired:
        spends.append(HEROIC_INSPIRATION)
        face, rolled, luck_used = roll_d20(label, edge, rng, lucky=lucky)
        events.extend(rolled)
        spends.extend([LUCK] if luck_used else [])
        total = face + bonus
        fumbled = natural_one_fails and face == 1
    return TestRoll(
        face=face,
        total=total,
        dc=dc,
        success=total >= dc and not fumbled,
        dice=tuple(events),
        spends=tuple(spends),
    )


def bardic_total(
    total: int, threshold: int, bardic_die: int, rng: Random, dice: list[DiceEvent]
) -> int | None:
    if total >= threshold or total + bardic_die < threshold:
        return None
    rolled = roll((bardic_die,), BARDIC_DIE_SPEND, rng, label=BARDIC_DIE_SPEND)
    dice.append(rolled.event)
    raised = total + rolled.total
    return raised if raised >= threshold else None


def roll_d20(
    label: str, edge: Edge, rng: Random, *, lucky: bool
) -> tuple[int, list[DiceEvent], bool]:
    count = 1 if edge == "none" else 2
    drawn = roll((20,) * count, label, rng, label=label)
    faces = list(drawn.event.rolled)
    events = [drawn.event]
    ones = [index for index, face in enumerate(faces) if face == 1]
    if lucky and ones:
        again = roll((20,) * len(ones), "Luck", rng, label="Luck")
        events.append(again.event)
        for index, face in zip(ones, again.event.rolled, strict=True):
            faces[index] = face
    face = min(faces) if edge == "disadvantage" else max(faces)
    return face, events, lucky and bool(ones)


def _unlearned(sheet: Lite5eSheet, skills: Iterable[Skill]) -> list[Skill]:
    return [skill for skill in skills if skill not in sheet.skills()]


def _typed_feats(sheet: Lite5eSheet, feat_type: str) -> list[Slug]:
    return [
        feat_id
        for feat_id, feat in srd().character_options.feats.items()
        if feat.type == feat_type and _is_feat_open(sheet, feat_id, feat)
    ]


def _feat_pool(sheet: Lite5eSheet) -> list[Slug]:
    styled = sheet.pick_limit("fighting-style") > 0
    return [
        feat_id
        for feat_id, feat in srd().character_options.feats.items()
        if (feat.minimum_level or 1) <= sheet.level
        and _is_feat_open(sheet, feat_id, feat)
        and (feat.type != "fighting-style" or styled)
    ]


def _initiate_abilities(sheet: Lite5eSheet) -> list[Slug]:
    spell_list = sheet.find_pick("initiate-list")
    if spell_list is None:
        return []
    fitting = MAGIC_INITIATE_ABILITY[_require_member(MAGIC_INITIATE_ABILITY, spell_list)]
    return [fitting, *(ability for ability in CASTING_ABILITIES if ability != fitting)]


def _initiate_pool(sheet: Lite5eSheet, spell_level: int) -> list[Slug]:
    spell_list = sheet.find_pick("initiate-list")
    if spell_list is None:
        return []
    data = srd()
    taken = (*sheet.pick_ids("cantrip"), *sheet.always_prepared_ids())
    return [
        spell_id
        for spell_id in data.spell_ids(spell_list, spell_level)
        if data.require_spell(spell_id).level == spell_level and spell_id not in taken
    ]


def _class_option_pool(sheet: Lite5eSheet, kind: ClassOptionKind) -> list[Slug]:
    return [
        option_id
        for option_id, option in srd().character_options.class_options.items()
        if option.pick_kind == kind and option.class_id == sheet.class_id
    ]


def _cantrip_pool(sheet: Lite5eSheet) -> list[Slug]:
    known = sheet.castable_spell_ids()
    return [spell_id for spell_id in srd().spell_ids(sheet.class_id, 0) if spell_id not in known]


def _spellbook_pool(sheet: Lite5eSheet, *, schools: Collection[School] | None) -> list[Slug]:
    spells = srd().spells.spells
    book = sheet.spellbook_ids()
    return [
        spell_id
        for spell_id in sheet.class_list_ids()
        if spell_id not in book and (schools is None or spells[spell_id].school in schools)
    ]


def _expertise_pool(sheet: Lite5eSheet) -> list[Slug]:
    narrowed = SCHOLAR_SKILLS if SCHOLAR in sheet.feature_ids() else ()
    return [skill for skill in sheet.skills() if not narrowed or skill in narrowed]


def _warrior_cantrip_pool(sheet: Lite5eSheet) -> list[Slug]:
    known = sheet.castable_spell_ids()
    return [
        spell_id
        for feat in sheet.feats()
        if feat.cantrip_list is not None
        for spell_id in srd().spell_ids(feat.cantrip_list, 0)
        if spell_id not in known
    ]


def _spell_names(spell_ids: Iterable[Slug]) -> str:
    return ", ".join(srd().require_spell(spell_id).name for spell_id in spell_ids) or "none"


def _require_member[Member: str](members: Iterable[Member], pick_id: Slug) -> Member:
    for member in members:
        if member == pick_id:
            return member
    raise Refusal(f"{pick_id!r} is no pick of this kind")


def _require_weapon(weapon_id: Slug) -> Weapon:
    weapon = srd().gear.weapons.get(weapon_id)
    if weapon is None:
        raise Refusal(f"{weapon_id!r} is no SRD weapon")
    return weapon


def _check_scores(method: AbilityMethod, scores: Mapping[Ability, int]) -> None:
    if len(scores) != len(STANDARD_ARRAY):
        raise Refusal("give a score for each of the six abilities")
    values = sorted(scores.values(), reverse=True)
    if method == "array" and tuple(values) != STANDARD_ARRAY:
        raise Refusal(f"the standard array uses each of {STANDARD_ARRAY} once")
    if method == "point-buy" and (
        any(value not in POINT_BUY_COST for value in values)
        or sum(POINT_BUY_COST[value] for value in values) != POINT_BUY_TOTAL
    ):
        raise Refusal(f"a point buy spends exactly {POINT_BUY_TOTAL} points on scores 8 to 15")


def _check_increase_split(increases: Mapping[Ability, int]) -> None:
    if tuple(sorted(increases.values(), reverse=True)) not in INCREASE_SPLITS:
        raise Refusal("raise one ability by 2 and another by 1, or three abilities by 1")


def _top_slot_level(slots: Sequence[int]) -> int:
    return max(level for level, total in enumerate(slots, 1) if total)


def _worn(gear_id: Slug) -> tuple[Armor, int] | None:
    gear = srd().gear
    if gear_id in gear.armor:
        return gear.armor[gear_id], 0
    magic = gear.magic_items.get(gear_id)
    if magic is None or magic.base_armor_id is None:
        return None
    return gear.armor[magic.base_armor_id], magic.bonus or 0


def _roll_guidance(rng: Random, dice: list[DiceEvent]) -> int:
    guidance = roll((GUIDANCE_DIE,), "Guidance", rng, label="Guidance")
    dice.append(guidance.event)
    return guidance.total


def _is_feat_open(sheet: Lite5eSheet, feat_id: Slug, feat: Feat) -> bool:
    held = feat_id in sheet.feat_ids() and not feat.repeatable
    return not held and feat.class_id in (None, sheet.class_id)


def _invocation_pool(sheet: Lite5eSheet) -> list[Slug]:
    met = (*sheet.pick_ids("invocation"), *sheet.castable_spell_ids())
    return [
        invocation_id
        for invocation_id, invocation in srd().character_options.invocations.items()
        if invocation.minimum_level <= sheet.level
        and (invocation.prerequisite_id is None or invocation.prerequisite_id in met)
    ]


def _tome_cantrip_choices(known_spell_ids: Collection[Slug]) -> list[Slug]:
    return [
        spell_id
        for spell_id, spell in srd().spells.spells.items()
        if spell.level == 0 and spell_id not in known_spell_ids
    ]


def _tome_ritual_choices(known_spell_ids: Collection[Slug]) -> list[Slug]:
    return [
        spell_id
        for spell_id, spell in srd().spells.spells.items()
        if spell.level == TOME_RITUAL_LEVEL and spell.ritual and spell_id not in known_spell_ids
    ]
