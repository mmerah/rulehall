from typing import Self

from pydantic import Field, model_validator

from rulehall.core.prompt import Sections, section_if
from rulehall.engines.packs import NPCS, CastEntry, CastPack, PackBody, PackHead, check_lines


class TunnelGoonsCastEntry(CastEntry):
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    hp: int = Field(ge=1)

    @model_validator(mode="after")
    def _reads_on_one_line(self) -> Self:
        check_lines("a cast entry field", (self.name, self.brief))
        return self

    def line(self) -> str:
        return f"{self.name} — {self.brief} (hp {self.hp})"


class TunnelGoonsPack(CastPack[TunnelGoonsCastEntry]):
    items: tuple[str, ...] = ()

    def table_sections(self) -> Sections:
        return section_if("ITEMS", ", ".join(self.items))


class TunnelGoonsHead(PackHead):
    items: tuple[str, ...] = Field(
        min_length=6,
        max_length=36,
        description="Things a goon can start with. Use plain names, such as 'Bear trap'.",
    )

    @model_validator(mode="after")
    def _every_item_reads_on_one_line(self) -> Self:
        check_lines("an item", self.items)
        return self


class TunnelGoonsBody(PackBody):
    factions: tuple[TunnelGoonsCastEntry, ...] = Field(
        min_length=1,
        max_length=6,
        description="The powers that control this setting, such as a guild, a cult or a warband.",
    )
    npcs: tuple[TunnelGoonsCastEntry, ...] = Field(min_length=1, max_length=6, description=NPCS)
    monsters: tuple[TunnelGoonsCastEntry, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player and is not a person: a beast, a horror, a "
        "thing in the dark.",
    )
