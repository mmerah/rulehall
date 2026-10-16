from typing import Self

from pydantic import Field, model_validator

from rulehall.core.decisions import Option
from rulehall.core.validation import Slug, check_unique
from rulehall.engines.lite5e.data import Ability, Skill, StartingGear, StatBlockId, srd
from rulehall.engines.lite5e.rules import MAGIC_INITIATE, MagicInitiateList
from rulehall.engines.packs import NPCS, CastEntry, CastPack, PackBody, cast_entry_line, check_lines


class Background(Option):
    brief: str = Field(min_length=1)
    abilities: tuple[Ability, Ability, Ability]
    feat_id: Slug
    magic_initiate_list: MagicInitiateList | None = None
    skill_ids: tuple[Skill, Skill]
    tool_id: Slug
    gear: tuple[StartingGear, ...] = Field(min_length=1)
    gp: int = Field(ge=0)

    @model_validator(mode="after")
    def _shape_of_the_srd(self) -> Self:
        check_unique("abilities", self.abilities)
        check_unique("skill_ids", self.skill_ids)
        check_unique("gear ids", (part.gear_id for part in self.gear))
        if (self.feat_id == MAGIC_INITIATE) != (self.magic_initiate_list is not None):
            raise ValueError(f"{self.id}: a Magic Initiate list goes exactly with Magic Initiate")
        return self


class Lite5eCastEntry(CastEntry):
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    stat_block_id: StatBlockId = Field(
        description="The id of the SRD stat block that gives this entry its numbers, such as "
        "'bandit', 'wolf' or 'tough'. The name is yours; the numbers are the stat block's."
    )

    @model_validator(mode="after")
    def _reads_on_one_line(self) -> Self:
        check_lines("a cast entry field", (self.name, self.brief))
        return self

    def line(self) -> str:
        return cast_entry_line(self.name, self.brief, ("stat block", self.stat_block_id))


class Lite5ePack(CastPack[Lite5eCastEntry]):
    backgrounds: tuple[Background, ...] = ()

    @model_validator(mode="after")
    def _ids_of_the_srd(self) -> Self:
        check_unique("background ids", (background.id for background in self.backgrounds))
        data = srd()
        feats = data.character_options.feats
        if strays := sorted(
            background.feat_id
            for background in self.backgrounds
            if background.feat_id not in feats or feats[background.feat_id].type != "origin"
        ):
            raise ValueError(f"no origin feats of the SRD: {strays}")
        if strays := sorted(
            background.tool_id
            for background in self.backgrounds
            if (tool := data.gear.gear.get(background.tool_id)) is None or tool.group != "tool"
        ):
            raise ValueError(f"no tools of the SRD: {strays}")
        return self


class Lite5eBody(PackBody):
    npcs: tuple[Lite5eCastEntry, ...] = Field(min_length=1, max_length=6, description=NPCS)
    monsters: tuple[Lite5eCastEntry, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player and is not a person: a beast, a raider, a "
        "thing in the ruins.",
    )
