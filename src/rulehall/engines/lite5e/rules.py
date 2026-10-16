from collections.abc import Collection
from typing import Literal

from rulehall.core.validation import Slug
from rulehall.engines.lite5e.data import (
    Ability,
    ChallengeRating,
    Condition,
    Duration,
    LevelSpells,
    Skill,
    Tier,
    Weapon,
)

type Difficulty = Literal["easy", "medium", "hard"]
type DamageSize = Literal["light", "moderate", "heavy"]
type GoalSize = Literal["low", "moderate", "high"]
type Light = Literal["dark", "dim", "bright"]
type Edge = Literal["none", "advantage", "disadvantage"]
type AbilityMethod = Literal["array", "point-buy"]
type CastingAbility = Literal["intelligence", "wisdom", "charisma"]
type MagicInitiateList = Literal["cleric", "druid", "wizard"]
type FormationRow = Literal["front", "back"]

MAX_LEVEL = 5
MAX_SCORE = 20
XP_FOR_LEVEL: dict[int, int] = {1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500}
MAX_XP = XP_FOR_LEVEL[MAX_LEVEL]
DIFFICULTY_DC: dict[Difficulty, int] = {"easy": 10, "medium": 15, "hard": 20}
DIFFICULTY_MEANING: dict[Difficulty, str] = {
    "easy": "A capable person does it most of the time.",
    "medium": "It needs training or luck.",
    "hard": "A trained person often fails.",
}
DAMAGE_D6S: dict[DamageSize, tuple[int, int]] = {
    "light": (1, 2),
    "moderate": (2, 3),
    "heavy": (3, 5),
}
ENCOUNTER_BUDGET: dict[int, dict[GoalSize, int]] = {
    1: {"low": 50, "moderate": 75, "high": 100},
    2: {"low": 100, "moderate": 150, "high": 200},
    3: {"low": 150, "moderate": 225, "high": 400},
    4: {"low": 250, "moderate": 375, "high": 500},
    5: {"low": 500, "moderate": 750, "high": 1100},
}
CHALLENGE_RATINGS: tuple[ChallengeRating, ...] = (
    "0",
    "1/8",
    "1/4",
    "1/2",
    "1",
    "2",
    "3",
    "4",
    "5",
)
COMPANION_CR_CAP: dict[int, ChallengeRating] = {1: "1/4", 2: "1", 3: "1", 4: "2", 5: "2"}
INSTINCT_STEPS: tuple[tuple[int, int], ...] = ((3, 8), (7, 6), (11, 4))
INSTINCT_TOP_SCORE = 2
COIN_CAP_CP = 100 * 100
SHORT_RESTS_PER_LONG_REST = 2
LIGHT_STEPS: tuple[Light, ...] = ("dark", "dim", "bright")
DIM_PASSIVE_PENALTY = 5
EXHAUSTION_PENALTY = 2
DEATH_SAVES = 3
DEATH_SAVE_DC = 10
MAX_EXHAUSTION = 6
TACTICAL_MIND_DIE = 10
GUIDANCE_DIE = 4
STANDARD_ARRAY: tuple[int, ...] = (15, 14, 13, 12, 10, 8)
POINT_BUY_COST: dict[int, int] = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
POINT_BUY_TOTAL = 27
INCREASE_SPLITS: tuple[tuple[int, ...], ...] = ((2, 1), (1, 1, 1))
ABILITIES: tuple[Ability, ...] = (
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
)
SKILL_ABILITY: dict[Skill, Ability] = {
    "acrobatics": "dexterity",
    "animal-handling": "wisdom",
    "arcana": "intelligence",
    "athletics": "strength",
    "deception": "charisma",
    "history": "intelligence",
    "insight": "wisdom",
    "intimidation": "charisma",
    "investigation": "intelligence",
    "medicine": "wisdom",
    "nature": "intelligence",
    "perception": "wisdom",
    "performance": "charisma",
    "persuasion": "charisma",
    "religion": "intelligence",
    "sleight-of-hand": "dexterity",
    "stealth": "dexterity",
    "survival": "wisdom",
}
KEEP: Slug = "keep"
TACTICAL_MIND: Slug = "fighter-tactical-mind"
CRITICAL_FACE = 20
RELENTLESS_ENDURANCE: Slug = "relentless-endurance"
LIFE_DOMAIN: Slug = "cleric-subclass"
FRENZY: Slug = "barbarian-subclass"
HUNTER: Slug = "ranger-subclass"
FIEND_PATRON: Slug = "warlock-subclass"
POTENT_CANTRIP: Slug = "wizard-subclass"
EXTRA_ATTACK_COUNT = 2
SEAR_UNDEAD: Slug = "cleric-sear-undead"
DICE_UPGRADE_LEVEL = 5
MAGIC_INITIATE: Slug = "magic-initiate"
AID_HP = 5
FALSE_LIFE_DICE: tuple[int, ...] = (4, 4)
FALSE_LIFE_BONUS = 4
FALSE_LIFE_PER_LEVEL = 5
RESTORED: tuple[Condition, ...] = ("blinded", "deafened", "paralyzed", "poisoned")
CHECK_DISADVANTAGE_CONDITIONS: tuple[Condition, ...] = ("frightened", "poisoned")
LARGE_FORM: Slug = "large-form"
POWERFUL_BUILD: Slug = "powerful-build"
MAGIC_INITIATE_ABILITY: dict[MagicInitiateList, CastingAbility] = {
    "cleric": "wisdom",
    "druid": "wisdom",
    "wizard": "intelligence",
}
CASTING_ABILITIES: tuple[CastingAbility, ...] = ("intelligence", "wisdom", "charisma")
LAY_ON_HANDS: Slug = "paladin-lay-on-hands"
LAY_ON_HANDS_CURE = 5
HUNTERS_MARK: Slug = "hunters-mark"
ELDRITCH_BLAST: Slug = "eldritch-blast"
MARTIAL_ARTS: Slug = "monk-martial-arts"
FONT_OF_MAGIC: Slug = "sorcerer-font-of-magic"
MADE_SLOT_COST: dict[int, int] = {1: 2, 2: 3, 3: 5}
MADE_SLOT_SORCERER_LEVEL: dict[int, int] = {1: 2, 2: 3, 3: 5}
ELDRITCH_MIND: Slug = "eldritch-mind"
PACT_OF_THE_BLADE: Slug = "pact-of-the-blade"
AGONIZING_BLAST: Slug = "agonizing-blast"
FIENDISH_VIGOR: Slug = "fiendish-vigor"
FIENDISH_VIGOR_HP = 12
REPELLING_BLAST: Slug = "repelling-blast"
THIRSTING_BLADE: Slug = "thirsting-blade"
TOME_RITUAL_LEVEL = 1
LUCKY: Slug = "luck"
RESOURCEFUL: Slug = "resourceful"
TRANCE: Slug = "trance"
SLEEP: Slug = "sleep"
SLEEP_FAILED: Condition = "unconscious"
DODGE: Slug = "dodge"
SHINING_SMITE: Slug = "shining-smite"
PACT_MAGIC: Slug = "warlock-pact-magic"
TWO_WEAPON_FIGHTING: Slug = "two-weapon-fighting"
SCHOLAR: Slug = "wizard-scholar"
SCHOLAR_SKILLS: tuple[Skill, ...] = (
    "arcana",
    "history",
    "investigation",
    "medicine",
    "nature",
    "religion",
)


def reached_spell_ids(parts: Collection[LevelSpells], level: int) -> tuple[Slug, ...]:
    return tuple(spell_id for part in parts if part.level <= level for spell_id in part.spell_ids)


def is_monk_weapon(weapon: Weapon) -> bool:
    return weapon.kind == "melee" and (weapon.category == "simple" or "light" in weapon.properties)


def damage_d6s(size: DamageSize, level: int) -> int:
    low, high = DAMAGE_D6S[size]
    return low if level <= 2 else high


def duration_tier(duration: Duration) -> Tier:
    match duration:
        case "instantaneous" | "1-round" | "1-minute":
            return "turn"
        case "10-minutes" | "1-hour":
            return "place"
        case "8-hours" | "24-hours" | "10-days" | "until-dispelled":
            return "long-rest"


def raised_light(light: Light, steps: int) -> Light:
    return LIGHT_STEPS[min(LIGHT_STEPS.index(light) + steps, len(LIGHT_STEPS) - 1)]


def level_for_xp(xp: int) -> int:
    return max(level for level, needed in XP_FOR_LEVEL.items() if xp >= needed)


def companion_cr_fits(challenge_rating: ChallengeRating, level: int) -> bool:
    cap = COMPANION_CR_CAP[level]
    return CHALLENGE_RATINGS.index(challenge_rating) <= CHALLENGE_RATINGS.index(cap)


def skill_name(skill: str) -> str:
    return " ".join(word if word == "of" else word.title() for word in skill.split("-"))
