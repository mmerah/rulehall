from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, ValidationInfo, model_validator

from rulehall.core.tools import PlayerFacing
from rulehall.core.validation import Frozen, Slug, check_unique
from rulehall.engines.args import ACTOR, BE_SHORT, Attempt, ShortName
from rulehall.engines.lite5e.data import Ability, DamageType, GearId, LevelPickKind, Skill
from rulehall.engines.lite5e.rules import (
    DIFFICULTY_DC,
    DIFFICULTY_MEANING,
    DamageSize,
    Difficulty,
    Edge,
    FormationRow,
)

type SaveDamage = Literal["none", "light", "moderate", "heavy"]
type OnFail = Literal["poisoned", "prone", "exhaustion"]
type Opening = Literal["face_to_face", "party_ambush", "foe_ambush"]
type GearUseKind = Literal["equip", "unequip", "drink", "drop"]
UniqueSlugs = Annotated[
    tuple[Slug, ...], AfterValidator(lambda ids, info: _checked_unique(ids, info))
]

DIFFICULTY = " ".join(
    f"{word} is DC {DIFFICULTY_DC[word]}: {meaning}" for word, meaning in DIFFICULTY_MEANING.items()
)
TARGETS = "Exact ids of the party members it hits. 'player' for the player."
RECEIVER = "Exact id of the class companion who gets it. Null for the player."
DAMAGE_TYPE = "The damage type, such as fire or bludgeoning."
GEAR_ID = (
    "Exact id of SRD gear or of a magic item. Magic armor and magic weapons join the magic item "
    "id to the id of the base piece: armor-1-chain-mail is Chain Mail +1, weapon-2-longsword is "
    "Longsword +2."
)


class DifficultyDc(Frozen):
    kind: Literal["difficulty"] = Field(description="A difficulty word sets the DC.")
    difficulty: Difficulty = Field(description=DIFFICULTY)


class TargetDc(Frozen):
    kind: Literal["target"] = Field(description="The world sets the DC from a target here.")
    target_id: Slug = Field(
        description="Exact id of a hidden thing, a trap, a person here, or the place behind a "
        "locked way."
    )


type CheckDc = Annotated[DifficultyDc | TargetDc, Field(discriminator="kind")]


class AbilityCheck(Attempt):
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    skill: Skill | None = Field(default=None, description="The skill, or null.")
    tool_id: Slug | None = Field(
        default=None, description="Exact id of a tool the actor carries, or null."
    )
    ability: Ability | None = Field(
        default=None, description="The ability, only for a check with no skill and no tool."
    )
    dc: CheckDc = Field(description="What sets the DC: a difficulty word or a target.")
    helper_id: Slug | None = Field(
        default=None,
        description="Exact id of a party member here who helps, or null. It gives Advantage.",
    )
    edge: Edge = Field(default="none", description="Your own Advantage or Disadvantage, if any.")
    edge_reason: PlayerFacing = Field(
        default="", description="Why, in a few words the player reads. Empty with no edge."
    )

    @property
    def target_id(self) -> Slug | None:
        return self.dc.target_id if isinstance(self.dc, TargetDc) else None

    @model_validator(mode="after")
    def _one_way_and_a_reason_for_the_edge(self) -> Self:
        if (self.ability is None) == (self.skill is None and self.tool_id is None):
            raise ValueError("give an ability only when the check has no skill and no tool")
        if (self.edge == "none") != (not self.edge_reason):
            raise ValueError("an edge and an edge_reason come together")
        return self


class TrapDanger(Frozen):
    kind: Literal["trap"] = Field(
        description="A trap here fires: a save. It sets the ability, the DC, the damage and the "
        "condition."
    )
    hazard_id: Slug = Field(description="Exact id of the trap here.")


class SaveThreat(Frozen):
    ability: Ability = Field(description="The ability that saves.")
    difficulty: Difficulty = Field(description=DIFFICULTY)
    damage: SaveDamage = Field(
        default="none", description="The damage of a failure. A success takes half."
    )
    damage_type: DamageType | None = Field(
        default=None, description=f"{DAMAGE_TYPE} Null with no damage."
    )
    on_fail: OnFail | None = Field(
        default=None,
        description="What a failure adds, or null. One Exhaustion level at most per place "
        "between rests.",
    )

    @model_validator(mode="after")
    def _damage_with_a_type(self) -> Self:
        if (self.damage == "none") != (self.damage_type is None):
            raise ValueError("a damage and a damage_type come together")
        return self


class SaveDanger(SaveThreat):
    kind: Literal["save"] = Field(
        description="A danger that allows a dodge: a save. A success takes half the damage."
    )


class CertainDanger(Frozen):
    kind: Literal["certain"] = Field(description="Harm that the story makes certain: no save.")
    damage: DamageSize = Field(description="The size of the damage.")
    damage_type: DamageType = Field(description=DAMAGE_TYPE)
    reason: PlayerFacing = Field(min_length=1, description="What hurts, in a few words.")


class FallDanger(Frozen):
    kind: Literal["fall"] = Field(description="A fall: no save, bludgeoning damage.")
    falling_feet: int = Field(ge=10, description="How far the fall is, in feet.")


type Danger = Annotated[
    TrapDanger | SaveDanger | CertainDanger | FallDanger, Field(discriminator="kind")
]


class Harm(Frozen):
    actor_ids: UniqueSlugs = Field(min_length=1, description=TARGETS)
    danger: Danger = Field(description="What threatens them.")


class CastSpell(Frozen):
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    spell_id: Slug = Field(description="Exact id of the spell.")
    slot_level: int | None = Field(
        default=None,
        ge=1,
        le=9,
        description="A slot above the spell's level, to cast it higher. Null otherwise.",
    )
    target_ids: UniqueSlugs = Field(
        default=(),
        description="Exact ids of the persons, party members or items it affects. Empty for "
        "the caster or no target.",
    )


class Rest(Frozen):
    kind: Literal["short", "long"] = Field(description="A short rest or a long rest.")


class StartBattle(Frozen):
    foe_ids: UniqueSlugs = Field(
        min_length=1,
        description="Exact ids of the persons here who fight the party. A group fights whole.",
    )
    opening: Opening = Field(
        description="face_to_face: nobody is surprised. party_ambush: the party strikes first "
        "from hiding. foe_ambush: the hidden foes here strike first."
    )


class InspirationReward(Frozen):
    kind: Literal["inspiration"] = Field(
        description="Heroic Inspiration for a bold or fitting choice. A member holds one at most, "
        "and gets one at most between long rests."
    )
    actor_id: Slug | None = Field(default=None, description=RECEIVER)
    reason: PlayerFacing = Field(min_length=1, description="The bold or fitting choice.")


class GoalReward(Frozen):
    kind: Literal["goal"] = Field(
        description="The XP of a goal that GOALS lists, when the party completes it. "
        "Each goal pays once. The party levels up when its XP is enough."
    )
    goal_id: Slug = Field(description="Exact id of the goal that is done.")


class CoinChange(Frozen):
    kind: Literal["coins"] = Field(
        description="Give or take the party's coins for the story: a reward, a bribe or a fee. "
        "One change is 100 gp at most."
    )
    cp: int = Field(
        description="The change in copper pieces: 100 cp is 1 gp. Positive gives, negative takes."
    )
    reason: PlayerFacing = Field(min_length=1, description="Why, in a few words.")

    @model_validator(mode="after")
    def _changes_something(self) -> Self:
        if self.cp == 0:
            raise ValueError("a change of 0 cp changes nothing")
        return self


type RewardKind = Annotated[
    InspirationReward | GoalReward | CoinChange, Field(discriminator="kind")
]


class GiveReward(Frozen):
    reward: RewardKind = Field(description="What the party gets or loses.")


class KeyedWay(Frozen):
    from_id: Slug = Field(description="Exact id of one end of the way with a lock.")
    to_id: Slug = Field(description="Exact id of the other end of the way.")

    def joins(self, start_id: Slug, end_id: Slug) -> bool:
        return {self.from_id, self.to_id} == {start_id, end_id}


class MakeItem(Frozen):
    holder_id: Slug = Field(
        description="Exact id of a party member, a living person here, or this place."
    )
    name: ShortName = Field(min_length=1, description=f"The item's name. {BE_SHORT}")
    note: PlayerFacing = Field(min_length=1, description="What it is or says, in one line.")
    opens: KeyedWay | None = Field(
        default=None,
        description="The way with a lock that this item is the key to. Null: it is no key.",
    )


class Trade(Frozen):
    gear_id: GearId = Field(description=GEAR_ID)
    kind: Literal["buy", "sell"] = Field(
        description="buy with the party's coins, or sell gear a party member holds for half "
        "its price."
    )
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    count: int = Field(default=1, ge=1, description="How many.")


class LevelPick(Frozen):
    actor_id: Slug
    kind: LevelPickKind
    pick_id: Slug


class HitDie(Frozen):
    actor_id: Slug


class Unprepare(Frozen):
    actor_id: Slug
    drop_id: Slug


class HeldGear(Frozen):
    actor_id: Slug
    gear_id: Slug


class GearUse(HeldGear):
    kind: GearUseKind


class GearGift(HeldGear):
    to_id: Slug


class LayOnHands(Frozen):
    actor_id: Slug
    target_id: Slug
    cure: bool


class FontOfMagic(Frozen):
    actor_id: Slug
    slot_level: int


class FormationEdit(Frozen):
    actor_id: Slug
    row: FormationRow


def _checked_unique(ids: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
    check_unique(info.field_name or "ids", ids)
    return ids
