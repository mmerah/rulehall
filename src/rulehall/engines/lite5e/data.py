from collections.abc import Collection, Mapping
from functools import cache
from pathlib import Path
from typing import Annotated, Literal, Self, get_args

from pydantic import AfterValidator, Field, model_validator

from rulehall.core.stores import read_model
from rulehall.core.validation import Frozen, Loose, Refusal, Slug
from rulehall.core.views import Sprite

DATA_DIR = Path(__file__).parent / "data"
PORTRAITS = "portraits"
FOES = "foes"
SILHOUETTES = "silhouettes"
SHORT_ID_LIST = 30
OVERLAY_DIR = Path(__file__).parent / "srd" / "overlay"
ART_FILE = OVERLAY_DIR / "art.json"

type Dice = Annotated[str, Field(pattern=r"^\d+d\d+$")]
type GearId = Annotated[
    Slug,
    AfterValidator(
        lambda gear_id: _known_id(
            gear_id, _gear_ids(), "gear", "use only gear ids the prompt shows"
        )
    ),
]
type StatBlockId = Annotated[
    Slug,
    AfterValidator(
        lambda block_id: _known_id(
            block_id, srd().bestiary.stat_blocks, "stat block", "use only ids from STAT BLOCKS"
        )
    ),
]
type ClassId = Annotated[
    Slug,
    AfterValidator(lambda class_id: _known_id(class_id, srd().character_options.classes, "class")),
]
type SpeciesId = Annotated[
    Slug,
    AfterValidator(
        lambda species_id: _known_id(species_id, srd().character_options.species, "species")
    ),
]
type SubspeciesId = Annotated[
    Slug, AfterValidator(lambda lineage_id: _known_id(lineage_id, _lineage_ids(), "lineage"))
]
type AbilityScores = Annotated[
    dict[Ability, int], AfterValidator(lambda scores: _every_ability(scores))
]

type RiderId = Literal[
    "condition",
    "save-condition",
    "grapple",
    "effect",
    "advantage-damage",
    "conditional-advantage",
    "bloodied-damage",
    "push",
]
type EffectEnd = Literal[
    "target-next-turn-end",
    "target-next-turn-start",
    "source-next-turn-end",
    "source-next-turn-start",
    "source-turn-end",
    "save-each-turn",
    "escape",
]
type EndingEvent = Literal["damage", "attack", "cast", "verbal-cast"]
type TargetFilter = Literal["foe", "ally", "aid", "restore", "dying", "dead"]
type MetamagicId = Literal["empowered", "heightened", "quickened", "twinned"]
type MetamagicFit = Literal["damage", "save", "action", "scaling-target"]
type ClassOptionKind = Literal["class-order", "land"]
type LevelPickKind = Literal[
    "class-skill",
    "species-skill",
    "tool",
    "origin-feat",
    "feat",
    "ability",
    "skilled",
    "initiate-list",
    "initiate-ability",
    "initiate-cantrip",
    "initiate-spell",
    "class-order",
    "land",
    "cantrip",
    "spellbook",
    "savant-spell",
    "expertise",
    "lore-skill",
    "fighting-style",
    "warrior-cantrip",
    "primal-knowledge",
    "invocation",
    "pact-weapon",
    "tome-cantrip",
    "tome-ritual",
    "replace-metamagic",
    "metamagic",
    "replace-prepared",
    "prepared",
]
type PickVocabulary = Literal[
    "proficiency",
    "feat",
    "ability",
    "spell-list",
    "spell",
    "class-option",
    "invocation",
    "weapon",
    "metamagic",
]
type FeatureUse = Literal[
    "second-wind",
    "action-surge",
    "channel-divinity",
    "arcane-recovery",
    "magic-initiate",
    "breath-weapon",
    "relentless-endurance",
    "adrenaline-rush",
    "clouds-jaunt",
    "fires-burn",
    "frosts-chill",
    "hills-tumble",
    "stones-endurance",
    "storms-thunder",
    "large-form",
    "rage",
    "lay-on-hands",
    "magical-cunning",
    "favored-enemy",
    "paladins-smite",
    "bardic-inspiration",
    "wild-shape",
    "focus",
    "uncanny-metabolism",
    "innate-sorcery",
    "sorcery-points",
    "sorcerous-restoration",
]
type UseRecovery = Literal["long-rest", "short-rest-one", "short-rest-all"]
type PreparedSwap = Literal["long-rest", "level-up"]
type FreeCasts = Literal["one", "proficiency-bonus"]
type WeaponProficiency = Literal["simple", "martial", "martial-finesse-or-light", "martial-light"]
type ArmorTraining = Literal["light", "medium", "heavy", "shields"]
type ActionVerb = Literal["act", "bonus"]
type ActionBudget = Literal["action", "attack", "magic", "bonus", "none"]
type ActionPlay = Literal["self", "target-effect", "save-damage", "lasting-strike"]
type ActionCheck = Literal[
    "back-row",
    "front-row",
    "moves",
    "not-surging",
    "melee-weapon",
    "still",
    "no-heavy-armor",
    "pact-of-the-blade",
    "not-raging",
    "bonus-action",
    "first-attack",
    "can-withdraw",
]
type TargetPool = Literal["foes", "front-foes", "other-allies", "others"]
type StrikeNeed = Literal[
    "any", "finesse-or-ranged", "melee", "strength", "pact-weapon", "monk-weapon", "unarmed"
]
type OnceMark = Literal[
    "sneak-attack",
    "savage-attacker",
    "frenzy",
    "colossus-slayer",
    "eldritch-smite",
    "stunning-strike",
    "reaction",
    "resistance",
]
type Band = Literal["close", "near", "far"]
type ActionFollowUp = Literal[
    "disengage",
    "leave",
    "extra-action",
    "lift-darkness",
    "spend-move",
    "proficiency-temp-hp",
    "teleport",
    "withdraw",
    "drop-concentration",
]
type SpecialId = Literal[
    "pack-tactics",
    "magic-resistance",
    "nimble-escape",
    "undead-fortitude",
    "bloodied-fury",
    "rampage",
    "swarm",
    "charge",
    "fire-aura",
    "regeneration",
    "life-drain",
    "agile",
    "flyby",
]
type CommandWord = Literal["grovel", "halt", "flee"]
type SpellVariant = DamageType | CommandWord
type Tier = Literal["turn", "place", "long-rest"]
type AdvantageRoll = Literal["initiative", "save", "check", "attack", "attacked"]
type BonusTarget = Literal[
    "armor-class",
    "attacks",
    "armored-armor-class",
    "check",
    "critical-range",
    "hit-points",
    "initiative",
    "light-steps",
    "minimum-armor-class",
    "ranged-attack",
    "save",
    "unskilled-check",
    "weapon",
]
type Ability = Literal[
    "strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"
]
type Skill = Literal[
    "acrobatics",
    "animal-handling",
    "arcana",
    "athletics",
    "deception",
    "history",
    "insight",
    "intimidation",
    "investigation",
    "medicine",
    "nature",
    "perception",
    "performance",
    "persuasion",
    "religion",
    "sleight-of-hand",
    "stealth",
    "survival",
]
type Size = Literal["tiny", "small", "medium", "large", "huge"]
type DamageType = Literal[
    "acid",
    "bludgeoning",
    "cold",
    "fire",
    "force",
    "lightning",
    "necrotic",
    "piercing",
    "poison",
    "psychic",
    "radiant",
    "slashing",
    "thunder",
]
type Condition = Literal[
    "blinded",
    "burning",
    "charmed",
    "deafened",
    "exhaustion",
    "frightened",
    "grappled",
    "incapacitated",
    "invisible",
    "oiled",
    "paralyzed",
    "petrified",
    "poisoned",
    "prone",
    "restrained",
    "stunned",
    "unconscious",
]
type WeaponProperty = Literal[
    "ammunition",
    "finesse",
    "heavy",
    "light",
    "loading",
    "reach",
    "thrown",
    "two-handed",
    "versatile",
]
type CoinUnit = Literal["cp", "sp", "gp"]
type AreaShape = Literal["cone", "cube", "emanation", "line", "sphere"]
type CreatureType = Literal[
    "aberration",
    "beast",
    "celestial",
    "construct",
    "dragon",
    "elemental",
    "fey",
    "fiend",
    "giant",
    "humanoid",
    "monstrosity",
    "plant",
    "swarm of tiny beasts",
    "swarm of tiny undead",
    "undead",
]
type ChallengeRating = Literal["0", "1/8", "1/4", "1/2", "1", "2", "3", "4", "5"]
type StoryBoon = Literal["guidance", "booming-voice"]
type TargetRequirement = Literal["grappled-by-self"] | Condition
type ModifierKey = Ability | Skill | Condition | CreatureType
type CastingTime = Literal["action", "bonus-action", "reaction", "1-minute", "10-minutes", "1-hour"]
type Duration = Literal[
    "instantaneous",
    "1-round",
    "1-minute",
    "10-minutes",
    "1-hour",
    "8-hours",
    "24-hours",
    "10-days",
    "until-dispelled",
]
type School = Literal[
    "abjuration",
    "conjuration",
    "divination",
    "enchantment",
    "evocation",
    "illusion",
    "necromancy",
    "transmutation",
]


COPPER_PER_UNIT: dict[CoinUnit, int] = {"cp": 1, "sp": 10, "gp": 100}
SPELL_RANGES = {"self": "Self", "touch": "Touch", "long": "Long range"}


class Source(Frozen):
    repository: str
    commit: str
    path: str
    licence: str
    licence_file: str


class Attributed(Frozen):
    attribution: Literal[
        "This work includes material from the System Reference Document 5.2.1 (“SRD 5.2.1”) by "
        "Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is "
        "licensed under the Creative Commons Attribution 4.0 International License, available at "
        "https://creativecommons.org/licenses/by/4.0/legalcode."
    ]
    changes: Literal["Cut and adapted for 5e Lite"]


class SrdFile(Attributed):
    source: Source


class HandTable[RowsT](Attributed):
    rows: RowsT


class Cost(Frozen):
    quantity: int = Field(ge=0)
    unit: CoinUnit

    def copper(self) -> int:
        return self.quantity * COPPER_PER_UNIT[self.unit]


class DamagePart(Frozen):
    dice: Dice | None = None
    bonus: int
    damage_type: DamageType | None = None

    def text(self) -> str:
        if self.dice is None:
            amount = str(self.bonus)
        else:
            amount = f"{self.dice}{self.bonus:+d}" if self.bonus else self.dice
        return f"{amount} {self.damage_type}" if self.damage_type else amount


class Range(Frozen):
    normal: int
    long: int | None = None


class Area(Frozen):
    feet: int
    shape: AreaShape

    def text(self) -> str:
        return f"{self.feet}-ft {self.shape}"


class Weapon(Frozen):
    name: str
    category: Literal["simple", "martial"]
    kind: Literal["melee", "ranged"]
    cost: Cost
    damage: DamagePart
    versatile_damage: DamagePart | None = None
    properties: tuple[WeaponProperty, ...] = ()
    range: Range
    thrown_range: Range | None = None
    magic_bonus: int = 0
    base_weapon_id: Slug | None = None


class Armor(Frozen):
    name: str
    category: Literal["light", "medium", "heavy", "shield"]
    cost: Cost
    base_ac: int
    dex_cap: int | None = None
    stealth_disadvantage: bool = False

    def worn_armor_class(self, dexterity_modifier: int) -> int:
        if self.dex_cap == 0:
            return self.base_ac
        if self.dex_cap is None:
            return self.base_ac + dexterity_modifier
        return self.base_ac + min(dexterity_modifier, self.dex_cap)


class GearEffect(Frozen):
    use: Literal["drink", "throw", "utilize"]
    dice: Dice | None = None
    bonus: int
    damage_type: DamageType | None = None
    condition: Condition | None = None
    save_ability: Ability | None = None
    escape_dc: int | None = None
    range_feet: int | None = None
    size_max: Size | None = None
    creature_types: tuple[CreatureType, ...] = ()
    uses: int | None = None


class Gear(Frozen):
    name: str
    group: Literal["adventuring-gear", "ammunition", "tool"]
    cost: Cost
    bundle: int
    effect: GearEffect | None = None
    ability: Ability | None = None
    contents: dict[Slug, int] = Field(default_factory=dict)
    light_source: bool = False
    description: str = ""


class Healing(Frozen):
    dice: Dice
    bonus: int


class MagicItem(Frozen):
    name: str
    kind: Literal["armor", "potion", "shield", "weapon"]
    cost: Cost
    bonus: int | None = None
    healing: Healing | None = None
    base_armor_id: Slug | None = None
    description: str


class GearFile(SrdFile):
    weapons: dict[Slug, Weapon]
    armor: dict[Slug, Armor]
    gear: dict[Slug, Gear]
    magic_items: dict[Slug, MagicItem]
    categories: dict[Slug, tuple[Slug, ...]]

    def tables(self) -> tuple[Mapping[Slug, Weapon | Armor | Gear | MagicItem], ...]:
        return (self.weapons, self.armor, self.gear, self.magic_items)


class SneakAttack(Frozen):
    dice_count: int
    dice_value: int


class ClassSpecific(Frozen):
    bardic_inspiration_die: int | None = None
    martial_arts_die: int | None = None
    rage_damage_bonus: int | None = None
    sneak_attack: SneakAttack | None = None


class ClassLevel(Frozen):
    level: int
    proficiency_bonus: int
    feature_ids: tuple[Slug, ...] = ()
    class_specific: ClassSpecific = ClassSpecific()
    slots: tuple[int, ...] | None = None
    grants: dict[LevelPickKind, int] = Field(default_factory=dict)
    use_counts: dict[FeatureUse, int] = Field(default_factory=dict)


class StartingGear(Frozen):
    gear_id: GearId
    count: int = Field(ge=1)


class StartingGearCategory(Frozen):
    category_id: Slug
    count: int


class GearOption(Frozen):
    gear: tuple[StartingGear, ...] = ()
    gear_categories: tuple[StartingGearCategory, ...] = ()
    gp: int


class ClassDefaults(Frozen):
    ability_order: tuple[Ability, Ability, Ability, Ability, Ability, Ability]
    picks: dict[LevelPickKind, tuple[Slug, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _orders_each_ability_once(self) -> Self:
        if len(set(self.ability_order)) != len(self.ability_order):
            raise ValueError("the ability order names each ability once")
        return self

    def pick_ids(self, kind: LevelPickKind) -> tuple[Slug, ...]:
        return self.ability_order if kind == "ability" else self.picks.get(kind, ())


class SrdClass(Frozen):
    name: str
    hit_die: int
    saving_throws: tuple[Ability, ...] = ()
    skill_options: tuple[Skill, ...] = ()
    tool_options: tuple[Slug, ...] = ()
    tool_ids: tuple[Slug, ...] = ()
    armor_training: tuple[ArmorTraining, ...] = ()
    weapon_proficiencies: tuple[WeaponProficiency, ...] = ()
    gear_option_a: GearOption
    levels: tuple[ClassLevel, ...] = ()
    defaults: ClassDefaults
    spell_ability: Ability | None = None
    prepared_swap: PreparedSwap | None = None
    spellbook: bool = False

    @model_validator(mode="after")
    def _has_a_spell_ability_exactly_when_it_casts(self) -> Self:
        casts = any(level.slots is not None for level in self.levels)
        if casts != (self.spell_ability is not None):
            raise ValueError(f"{self.name}: a spell ability goes exactly with spellcasting")
        return self


class LevelSpells(Frozen):
    level: int
    spell_ids: tuple[Slug, ...] = ()


class AbilityAmount(Frozen):
    ability: Ability


class PerLevelAmount(Frozen):
    per_level: int = Field(ge=1)


type Amount = (
    int | Literal["proficiency-bonus", "half-proficiency-bonus"] | AbilityAmount | PerLevelAmount
)


class Advantage(Frozen):
    kind: Literal["advantage", "disadvantage"]
    on: AdvantageRoll
    keys: tuple[ModifierKey, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def _keys_and_reason_fit_the_roll(self) -> Self:
        if self.keys and self.on not in ("save", "check", "attacked"):
            raise ValueError(f"an edge on {self.on} takes no keys")
        if (self.reason is None) == (self.on in ("attack", "attacked")):
            raise ValueError("an edge on an attack roll gives a reason, and only there")
        return self

    def matches(self, on: AdvantageRoll, key: ModifierKey | None) -> bool:
        return self.on == on and (not self.keys or key in self.keys)


class Bonus(Frozen):
    kind: Literal["bonus"]
    to: BonusTarget
    amount: Amount = 1
    keys: tuple[ModifierKey, ...] = ()

    @model_validator(mode="after")
    def _keys_only_on_checks_and_saves(self) -> Self:
        if self.keys and self.to not in ("check", "save"):
            raise ValueError(f"a bonus to {self.to} takes no keys")
        return self

    def matches(self, to: BonusTarget, key: ModifierKey | None) -> bool:
        return self.to == to and (not self.keys or key in self.keys)

    def fixed_amount(self) -> int:
        if not isinstance(self.amount, int):
            raise ValueError(f"a bonus to {self.to} needs a fixed amount here")
        return self.amount


class Resistance(Frozen):
    kind: Literal["resistance"]
    damage_types: tuple[DamageType, ...]


class ArmorBase(Frozen):
    kind: Literal["armor-base"]
    base: int
    ability: Ability | None = None
    shieldless: bool = False


class Immunity(Frozen):
    kind: Literal["immunity"]
    conditions: tuple[Condition, ...]


type Modifier = Annotated[
    Advantage | Bonus | Resistance | Immunity | ArmorBase, Field(discriminator="kind")
]


class Boon(Frozen):
    name: str
    description: str
    tag: str | None = None
    grants: dict[LevelPickKind, int] = Field(default_factory=dict)
    always_prepared: tuple[LevelSpells, ...] = ()
    modifiers: tuple[Modifier, ...] = ()
    weapon_proficiencies: tuple[WeaponProficiency, ...] = ()
    armor_training: tuple[ArmorTraining, ...] = ()


class ClassOption(Boon):
    class_id: Slug
    pick_kind: ClassOptionKind


class Trait(Boon):
    trait_id: Slug
    replaces: Slug | None = None
    level: int | None = None
    skill_options: tuple[Skill, ...] = ()
    spell_ids: tuple[Slug, ...] = ()
    free_casts: FreeCasts = "one"


class Subspecies(Frozen):
    name: str
    damage_type: DamageType | None = None
    traits: tuple[Trait, ...] = ()


class Species(Frozen):
    name: str
    sizes: tuple[Size, ...] = ()
    speed: int
    traits: tuple[Trait, ...] = ()
    subspecies: dict[Slug, Subspecies] = Field(default_factory=dict)

    def lineage_traits(self, subspecies_id: str | None) -> tuple[Trait, ...]:
        lineage = self.subspecies.get(subspecies_id or "")
        if lineage is None:
            return self.traits
        replaced = {trait.replaces for trait in lineage.traits}
        kept = (trait for trait in self.traits if trait.trait_id not in replaced)
        return (*kept, *lineage.traits)


class Feat(Boon):
    type: Literal["origin", "fighting-style", "general"]
    repeatable: bool = False
    minimum_level: int | None = None
    class_id: Slug | None = None
    cantrip_list: Slug | None = None


class FeatureUseRule(Frozen):
    source_id: Slug | None = None
    amount: Amount | Literal["class-level"] = 1
    recovery: UseRecovery = "long-rest"
    short_rest_with: Slug | None = None
    free_cast_spell_id: Slug | None = None

    @model_validator(mode="after")
    def _has_a_source_unless_the_class_level_counts_it(self) -> Self:
        if self.source_id is None and self.amount != "class-level":
            raise ValueError("a use names its source when the class level does not count it")
        return self


class Invocation(Boon):
    minimum_level: int
    prerequisite_id: Slug | None = None
    spell_id: Slug | None = None


class MetamagicOption(Frozen):
    name: str
    cost: int
    fits: MetamagicFit
    description: str


class Described(Frozen):
    name: str
    description: str


class Rider(Frozen):
    rider_id: RiderId
    ability: Ability | None = None
    size_max: Size | None = None
    condition: Condition | None = None
    damage: DamagePart | None = None
    dc: int | None = None
    effect_id: Slug | None = None
    ends: EffectEnd | None = None
    uses: int | None = None
    ends_on: tuple[EndingEvent, ...] = ()
    immune_condition: Condition | None = None
    spared_types: tuple[CreatureType, ...] = ()
    spared_species_ids: tuple[Slug, ...] = ()
    on_success: bool = False

    def require_effect_id(self) -> Slug:
        if self.effect_id is None:
            raise ValueError(f"a {self.rider_id} rider names no effect")
        return self.effect_id

    def summary(self) -> str:
        if self.condition is not None:
            return self.condition.title()
        rule = None if self.effect_id is None else srd().battle_effects.effects.get(self.effect_id)
        return "" if rule is None else rule.summary()


class SpellBattle(Frozen):
    damage: tuple[DamagePart, ...] = ()
    higher_level_dice: Dice | None = None
    healing_dice: Dice | None = None
    area: Area | None = None
    success: Literal["half", "none"] | None = None
    effect: Rider | None = None
    cantrip_upgrade: Dice | None = None
    upgrade_targets: int = Field(default=0, ge=0)
    exploding_dice: bool = False
    target_count: int = Field(ge=1)
    targets_per_level: int = Field(ge=0)
    volley: bool = False
    variants: tuple[SpellVariant, ...] = ()
    missed_damage_parts: int = Field(default=0, ge=0)
    creature_types: tuple[CreatureType, ...] = ()
    target_filter: TargetFilter = "foe"
    damage_modifier: bool = False
    strike_range_feet: int | None = None
    heals_half_dealt: bool = False
    then: tuple[ActionFollowUp, ...] = ()
    riders: tuple[Rider, ...] = ()

    def holds_lasting_effect(self) -> bool:
        # An effect aimed at foes stays with its caster, who strikes with it again.
        return self.effect is not None and self.target_filter == "foe"


class TimedCondition(Frozen):
    condition: Condition
    tier: Tier


class StoryTargets(Frozen):
    target_count: int = Field(default=1, ge=1)
    targets_per_level: int = Field(default=0, ge=0)
    creature_types: tuple[CreatureType, ...] = ()
    every_creature: bool = False


class Spell(Frozen):
    name: str
    level: int = Field(ge=0)
    school: School
    class_ids: tuple[Slug, ...] = ()
    casting_time: CastingTime
    components: tuple[Literal["V", "S", "M"], ...] = ()
    concentration: bool = False
    ritual: bool = False
    duration: Duration
    range: Literal["feet", "self", "touch", "long"]
    range_feet: int | None = None
    attack_type: Literal["melee", "ranged"] | None = None
    save_ability: Ability | None = None
    description: str
    group: Literal["battle", "story"]
    story_condition: TimedCondition | None = None
    story_boon: StoryBoon | None = None
    story_targets: StoryTargets = StoryTargets()
    battle: SpellBattle | None = None

    def brief(self) -> str:
        level = (
            f"{self.school.title()} cantrip"
            if self.level == 0
            else f"Level {self.level} {self.school}"
        )
        reach = f"{self.range_feet} ft" if self.range == "feet" else SPELL_RANGES[self.range]
        parts = (level, self.casting_time.replace("-", " "), reach, self.summary())
        return " · ".join(part for part in parts if part)

    def summary(self) -> str:
        battle = self.battle
        parts = [
            *(() if self.attack_type is None else (f"{self.attack_type} spell attack",)),
            *(() if self.save_ability is None else (f"{self.save_ability.title()} save",)),
        ]
        if self.story_condition is not None:
            parts.append(self.story_condition.condition.title())
        if battle is None:
            return ", ".join(parts)
        if battle.success == "half":
            parts.append("half on a success")
        if battle.area is not None:
            parts.append(battle.area.text())
        elif battle.volley:
            parts.append(f"{battle.target_count} strikes")
        elif battle.target_count > 1:
            parts.append(f"up to {battle.target_count} targets")
        if battle.damage:
            damage = " + ".join(part.text() for part in battle.damage)
            parts.append(f"{damage} + modifier" if battle.damage_modifier else damage)
        if battle.healing_dice is not None:
            parts.append(f"heals {battle.healing_dice} + modifier")
        riders = (*battle.riders, *(() if battle.effect is None else (battle.effect,)))
        parts.extend(found for rider in riders if (found := rider.summary()))
        return ", ".join(parts)

    def targeting(self) -> SpellBattle | StoryTargets:
        return self.story_targets if self.battle is None else self.battle

    def target_limit(self, cast_level: int) -> int | None:
        targeting = self.targeting()
        if isinstance(targeting, StoryTargets) and targeting.every_creature:
            return None
        return targeting.target_count + targeting.targets_per_level * (cast_level - self.level)


class SpellsFile(SrdFile):
    spells: dict[Slug, Spell]


class Usage(Frozen):
    recharge_min: int | None = None
    uses_per_day: int | None = None


class StatBlockAction(Frozen):
    action_id: Slug
    name: str
    kind: Literal["melee", "ranged", "save"]
    to_hit: int | None = None
    ability: Ability | None = None
    dc: int | None = None
    success: Literal["half", "none"] | None = None
    area: Area | None = None
    damage: tuple[DamagePart, ...] = ()
    reach_feet: int | None = None
    range_feet: int | None = None
    requires: tuple[TargetRequirement, ...] = ()
    usage: Usage = Usage()
    riders: tuple[Rider, ...] = ()

    @model_validator(mode="after")
    def _save_fields_go_with_the_save_kind(self) -> Self:
        save = self.kind == "save"
        save_fields = (self.ability, self.dc, self.success)
        if (self.to_hit is None) != save or any((field is None) == save for field in save_fields):
            raise ValueError(f"{self.name}: a save has ability, dc and success; an attack to_hit")
        return self


class Special(Frozen):
    special_id: SpecialId
    action_id: Slug | None = None
    follow_up_action_id: Slug | None = None
    damage: tuple[DamagePart, ...] = ()
    usage: Usage = Usage()
    regained_hit_points: int = 0
    stopping_damage_types: tuple[DamageType, ...] = ()
    heals_self: bool = False
    stops_while_incapacitated: bool = False
    riders: tuple[Rider, ...] = ()
    area: Area | None = None


class MultiattackPart(Frozen):
    action_id: Slug
    count: int


class Multiattack(Frozen):
    total: int
    fixed: tuple[MultiattackPart, ...] = ()
    choose: int
    options: tuple[Slug, ...] = ()


class StatBlock(Frozen):
    name: str
    size: Size
    creature_type: CreatureType
    challenge_rating: ChallengeRating
    xp: int
    armor_class: int
    hit_points: int
    speed: str
    scores: dict[Ability, int] = Field(default_factory=dict)
    save_bonuses: dict[Ability, int] = Field(default_factory=dict)
    skill_bonuses: dict[Skill, int] = Field(default_factory=dict)
    passive_perception: int
    darkvision: bool = False
    damage_vulnerabilities: tuple[DamageType, ...] = ()
    damage_resistances: tuple[DamageType, ...] = ()
    damage_immunities: tuple[DamageType, ...] = ()
    condition_immunities: tuple[Condition, ...] = ()
    tags: tuple[Slug, ...] = ()
    actions: tuple[StatBlockAction, ...] = ()
    specials: tuple[Special, ...] = ()
    death_burst: StatBlockAction | None = None
    bonus_actions: tuple[StatBlockAction, ...] = ()
    multiattack: Multiattack | None = None
    gear_drops: tuple[Slug, ...] = ()

    def find_special(self, special_id: SpecialId) -> Special | None:
        return next((found for found in self.specials if found.special_id == special_id), None)

    def require_action(self, action_id: Slug) -> StatBlockAction:
        found = next((action for action in self.actions if action.action_id == action_id), None)
        if found is None:
            raise ValueError(f"{self.name} has no action {action_id!r}")
        return found

    def require_usage(self, usage_id: Slug) -> Usage:
        charge = self.find_special("charge")
        if usage_id == "charge" and charge is not None:
            return charge.usage
        return self.require_action(usage_id).usage

    def save_bonus(self, ability: Ability) -> int:
        return self.save_bonuses.get(ability, modifier(self.scores[ability]))

    def check_bonus(self, ability: Ability, skill: Skill | None) -> int:
        plain = modifier(self.scores[ability])
        return plain if skill is None else self.skill_bonuses.get(skill, plain)

    def resisted(self, amount: int, damage_type: DamageType, *, warded: bool) -> int:
        if damage_type in self.damage_immunities:
            return 0
        if warded or damage_type in self.damage_resistances:
            amount //= 2
        return amount * 2 if damage_type in self.damage_vulnerabilities else amount


class BestiaryFile(SrdFile):
    stat_blocks: dict[Slug, StatBlock]


class FoeArt(Loose):
    stat_blocks: dict[Slug, tuple[str, ...] | None]


class FeatureSave(Frozen):
    save_ability: Ability
    dc_ability: Ability
    dice: Dice
    upgraded_dice: Dice | None = None
    damage_type: DamageType | None = None
    bonus_ability: Ability | None = None
    range_feet: int | None = None
    area: Area | None = None


class BattleActionRow(Frozen):
    action_id: Slug
    variant_id: str | None = None
    name: str = ""
    budget: ActionBudget
    play: ActionPlay | None = None
    feature_id: Slug | None = None
    minimum_level: int = 0
    use: FeatureUse | None = None
    checks: tuple[ActionCheck, ...] = ()
    effect: Rider | None = None
    then: tuple[ActionFollowUp, ...] = ()
    lines: tuple[str, ...] = ()
    save: FeatureSave | None = None
    healing_dice: Dice | None = None
    targets: TargetPool | None = None
    within: Band = "far"
    in_form: bool = False
    companion: bool = False

    @property
    def verb(self) -> ActionVerb:
        return "bonus" if self.budget == "bonus" else "act"

    def require_save(self) -> FeatureSave:
        if self.save is None:
            raise ValueError(f"{self.action_id} has no save template")
        return self.save

    def require_effect(self) -> Rider:
        if self.effect is None:
            raise ValueError(f"{self.action_id} lays no effect")
        return self.effect

    def held_effect_id(self) -> Slug | None:
        return None if self.effect is None else self.effect.effect_id or self.action_id


class StrikeVariant(Frozen):
    variant_id: Slug
    name: str
    technique: bool = False
    source_id: Slug | None = None
    spell_id: Slug | None = None
    cost: Literal["pact-slot", "sneak-attack-die"] | FeatureUse | None = None
    needs: StrikeNeed = "any"
    checks: tuple[ActionCheck, ...] = ()
    once_mark: OnceMark | None = None
    lines: tuple[str, ...] = ()
    damage: DamagePart | Literal["spell"] | None = None
    bonus_dice: Dice | None = None
    bonus_against: tuple[CreatureType, ...] = ()
    effect: Rider | None = None
    size_max: Size | None = None
    save_ability: Ability | None = None
    dc_ability: Ability | None = None
    riders: tuple[Rider, ...] = ()
    then: tuple[ActionFollowUp, ...] = ()

    def pays_slot(self) -> bool:
        return self.spell_id is not None or self.cost == "pact-slot"

    @property
    def spent_use(self) -> FeatureUse | None:
        match self.cost:
            case "pact-slot" | "sneak-attack-die":
                return None
            case spent:
                return spent


class EffectRule(Frozen):
    tag: str | None = None
    state: str | None = None
    modifiers: tuple[Modifier, ...] = ()
    ends_conditions: tuple[Condition, ...] = ()
    roll_die: int | None = None
    turn_damage: DamagePart | Literal["spell"] | None = None
    turn_save: Ability | None = None
    turn_temp_hp: bool = False
    hit_damage: DamagePart | Literal["spell"] | None = None
    moves_on_drop: bool = False
    stabilizes: bool = False
    ends_one: bool = False

    def summary(self) -> str:
        parts = [
            f"{modifier.fixed_amount():+d} AC"
            if modifier.to == "armor-class"
            else f"AC at least {modifier.fixed_amount()}"
            for modifier in self.modifiers
            if isinstance(modifier, Bonus) and modifier.to in ("armor-class", "minimum-armor-class")
        ]
        parts.extend(
            f"AC {modifier.base} + Dexterity"
            for modifier in self.modifiers
            if isinstance(modifier, ArmorBase) and modifier.ability is None
        )
        if self.roll_die is not None:
            sign = "+" if self.roll_die > 0 else "-"
            parts.append(f"{sign}1d{abs(self.roll_die)} to attack rolls and saves")
        return ", ".join(parts)

    def is_instant(self) -> bool:
        return self == EffectRule(
            ends_conditions=self.ends_conditions, stabilizes=self.stabilizes, ends_one=self.ends_one
        )

    @model_validator(mode="after")
    def _bonuses_are_fixed(self) -> Self:
        for found in self.modifiers:
            if isinstance(found, Bonus):
                _ = found.fixed_amount()
        return self


class BattleEffects(Frozen):
    effects: dict[Slug, EffectRule] = Field(default_factory=dict)


class CharacterOptionsFile(SrdFile):
    classes: dict[Slug, SrdClass]
    species: dict[Slug, Species]
    feats: dict[Slug, Feat]
    features: dict[Slug, Boon]
    class_options: dict[Slug, ClassOption]
    default_picks: dict[LevelPickKind, tuple[Slug, ...]]
    feature_uses: dict[FeatureUse, FeatureUseRule]
    invocations: dict[Slug, Invocation]
    metamagic: dict[MetamagicId, MetamagicOption]
    conditions: dict[Condition, Described]
    skills: dict[Skill, Described]

    @model_validator(mode="after")
    def _describes_every_condition_and_skill(self) -> Self:
        named = {*get_args(Condition.__value__), *get_args(Skill.__value__)}
        if missing := sorted(named.difference(self.conditions, self.skills)):
            raise ValueError(f"no description for {missing}")
        return self


class Srd(Frozen):
    gear: GearFile
    character_options: CharacterOptionsFile
    spells: SpellsFile
    bestiary: BestiaryFile
    battle_actions: tuple[BattleActionRow, ...]
    battle_effects: BattleEffects
    strike_variants: tuple[StrikeVariant, ...]

    def require_stat_block(self, stat_block_id: str) -> StatBlock:
        found = self.bestiary.stat_blocks.get(stat_block_id)
        if found is None:
            raise Refusal(f"{stat_block_id!r} is no stat block id of the SRD")
        return found

    def require_spell(self, spell_id: str) -> Spell:
        found = self.spells.spells.get(spell_id)
        if found is None:
            raise Refusal(f"{spell_id!r} is no spell id of the SRD")
        return found

    def find_gear(self, gear_id: str) -> Weapon | Armor | Gear | MagicItem | None:
        return next((table[gear_id] for table in self.gear.tables() if gear_id in table), None)

    def require_gear(self, gear_id: str) -> Weapon | Armor | Gear | MagicItem:
        found = self.find_gear(gear_id)
        if found is None:
            raise Refusal(f"{gear_id!r} is no gear id of the SRD")
        return found

    def is_magic_gear(self, gear_id: str) -> bool:
        weapon = self.gear.weapons.get(gear_id)
        return gear_id in self.gear.magic_items or (weapon is not None and weapon.magic_bonus > 0)

    def spell_ids(self, list_id: str, max_level: int) -> list[Slug]:
        return [
            spell_id
            for spell_id, spell in self.spells.spells.items()
            if list_id in spell.class_ids and spell.level <= max_level
        ]

    def require_class(self, class_id: str) -> SrdClass:
        found = self.character_options.classes.get(class_id)
        if found is None:
            raise Refusal(f"{class_id!r} is no class id of the SRD")
        return found


@cache
def srd() -> Srd:
    return Srd(
        gear=_concrete_gear(),
        character_options=read_model(DATA_DIR / "character_options.json", CharacterOptionsFile),
        spells=read_model(DATA_DIR / "spells.json", SpellsFile),
        bestiary=read_model(DATA_DIR / "bestiary.json", BestiaryFile),
        battle_actions=_hand_rows("battle_actions.json", HandTable[tuple[BattleActionRow, ...]]),
        battle_effects=_hand_rows("battle_effects.json", HandTable[BattleEffects]),
        strike_variants=_hand_rows("strike_variants.json", HandTable[tuple[StrikeVariant, ...]]),
    )


def modifier(score: int) -> int:
    return (score - 10) // 2


def dice_parts(dice: Dice) -> tuple[int, int]:
    count, faces = dice.split("d")
    return int(count), int(faces)


def raised_dice(dice: Dice, per_step: Dice | None, steps: int) -> Dice:
    if per_step is None or steps == 0:
        return dice
    count, faces = dice_parts(dice)
    more, more_faces = dice_parts(per_step)
    if more_faces != faces:
        raise ValueError(f"{per_step} does not add to {dice}")
    return f"{count + more * steps}d{faces}"


def portrait_sprite(look_id: Slug) -> Sprite:
    return Sprite(path=Path(PORTRAITS) / f"{look_id}.png")


def stat_block_sprite(stat_block_id: Slug) -> Sprite:
    if stat_block_id in _foe_art_ids():
        return Sprite(path=Path(FOES) / f"{stat_block_id}.png")
    creature_type = srd().require_stat_block(stat_block_id).creature_type
    return Sprite(path=Path(SILHOUETTES) / f"{creature_type}.png")


def _with_concrete_magic_gear(gear: GearFile) -> GearFile:
    magic_items = dict(gear.magic_items)
    weapons = dict(gear.weapons)
    for item_id, item in gear.magic_items.items():
        bonus = item.bonus or 0
        if item.kind == "armor":
            del magic_items[item_id]
            magic_items.update(
                {
                    f"{item_id}-{armor_id}": item.model_copy(
                        update={"name": f"{armor.name} +{bonus}", "base_armor_id": armor_id}
                    )
                    for armor_id, armor in gear.armor.items()
                    if armor.category != "shield"
                }
            )
        elif item.kind == "weapon":
            del magic_items[item_id]
            weapons.update(
                {
                    f"{item_id}-{weapon_id}": weapon.model_copy(
                        update={
                            "name": f"{weapon.name} +{bonus}",
                            "cost": item.cost,
                            "magic_bonus": bonus,
                            "base_weapon_id": weapon_id,
                        }
                    )
                    for weapon_id, weapon in gear.weapons.items()
                }
            )
    return gear.model_copy(update={"weapons": weapons, "magic_items": magic_items})


@cache
def _concrete_gear() -> GearFile:
    return _with_concrete_magic_gear(read_model(DATA_DIR / "gear.json", GearFile))


@cache
def _gear_ids() -> frozenset[Slug]:
    return frozenset(gear_id for table in _concrete_gear().tables() for gear_id in table)


def _known_id(found_id: Slug, known: Collection[str], noun: str, hint: str = "") -> Slug:
    if found_id not in known:
        listed = f"use one of {sorted(known)}" if len(known) <= SHORT_ID_LIST else hint
        raise ValueError(f"{found_id!r} is no {noun} id of the SRD; {listed}")
    return found_id


@cache
def _lineage_ids() -> frozenset[Slug]:
    return frozenset(
        lineage_id
        for species in srd().character_options.species.values()
        for lineage_id in species.subspecies
    )


def _every_ability(scores: dict[Ability, int]) -> dict[Ability, int]:
    if missing := [ability for ability in get_args(Ability.__value__) if ability not in scores]:
        raise ValueError(f"no score for {missing}")
    return scores


def _hand_rows[RowsT](file: str, table: type[HandTable[RowsT]]) -> RowsT:
    return read_model(OVERLAY_DIR / file, table).rows


@cache
def _foe_art_ids() -> frozenset[Slug]:
    art = read_model(ART_FILE, FoeArt)
    return frozenset(block_id for block_id, layers in art.stat_blocks.items() if layers)
