from typing import Self

from pydantic import Field, model_validator

from rulehall.core.decisions import DecisionOption
from rulehall.core.prompt import Sections
from rulehall.core.validation import Slug, slugs
from rulehall.engines.packs import (
    NPCS,
    CastEntry,
    CastPack,
    PackBody,
    PackHead,
    TableEntry,
    cast_entry_line,
    check_items,
    check_lines,
)


class Loner4eCastEntry(CastEntry):
    """A faction, an npc or a monster, as the SRD prints it. The worldsmith copies it into cast."""

    name: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    skills: tuple[str, ...] = Field(min_length=1)
    frailties: tuple[str, ...] = Field(min_length=1)
    gear: tuple[str, ...] = ()
    goal: str = ""
    motive: str = ""
    nemesis: str = ""

    @model_validator(mode="after")
    def _reads_on_one_line(self) -> Self:
        check_lines(
            "a cast entry field", (self.name, self.concept, self.goal, self.motive, self.nemesis)
        )
        check_items("a cast entry list", (*self.skills, *self.frailties, *self.gear))
        return self

    def line(self) -> str:
        return cast_entry_line(
            self.name,
            self.concept,
            ("skills", ", ".join(self.skills)),
            ("frailties", ", ".join(self.frailties)),
            ("gear", ", ".join(self.gear)),
            ("goal", self.goal),
            ("motive", self.motive),
            ("nemesis", self.nemesis),
        )


class Loner4ePack(CastPack[Loner4eCastEntry]):
    concepts: tuple[DecisionOption, ...] = Field(min_length=1)
    skills: tuple[DecisionOption, ...] = Field(min_length=1)
    frailties: tuple[DecisionOption, ...] = Field(min_length=1)
    gear: tuple[DecisionOption, ...] = Field(min_length=1)
    spends_luck: bool = False

    def table_sections(self) -> Sections:
        tags = "\n".join(
            f"{kind}: {', '.join(entry.name for entry in entries)}"
            for kind, entries in (
                ("concepts", self.concepts),
                ("skills", self.skills),
                ("frailties", self.frailties),
                ("gear", self.gear),
            )
        )
        return (("TRAIT TAGS", tags),)


class Loner4eHead(PackHead):
    concepts: tuple[TableEntry, ...] = Field(
        min_length=6,
        max_length=36,
        description="One-line concepts. A player picks a character from these, such as "
        "'A salvager who works the drowned streets'.",
    )
    skills: tuple[TableEntry, ...] = Field(
        min_length=6,
        max_length=36,
        description="Free text skill tags. Each tag says what a character does well, such "
        "as 'Reads old stonework'.",
    )
    frailties: tuple[TableEntry, ...] = Field(
        min_length=6,
        max_length=36,
        description="Free text frailty tags. Each tag says what works against a character, "
        "such as 'Owes the wrong people'.",
    )
    gear: tuple[TableEntry, ...] = Field(
        min_length=6,
        max_length=36,
        description="Free text gear tags. Each tag is a thing a character carries, such as "
        "'A lantern that will not drown'.",
    )
    spends_luck: bool = Field(description="True only when `rules` gives a cost in luck.")

    def pack_fields(self) -> dict[str, object]:
        fields = super().pack_fields()
        taken: list[Slug] = []
        for field, rows in (
            ("concepts", self.concepts),
            ("skills", self.skills),
            ("frailties", self.frailties),
            ("gear", self.gear),
        ):
            ids = slugs((row.name for row in rows), taken)
            taken += ids
            fields[field] = tuple(
                DecisionOption(id=row_id, name=row.name, brief=row.brief)
                for row_id, row in zip(ids, rows, strict=True)
            )
        return fields


class Loner4eBody(PackBody):
    factions: tuple[Loner4eCastEntry, ...] = Field(
        min_length=1,
        max_length=6,
        description="The powers that control this setting, such as a guild, a cult or a "
        "city watch. Write each one as the SRD prints it.",
    )
    npcs: tuple[Loner4eCastEntry, ...] = Field(min_length=1, max_length=6, description=NPCS)
    monsters: tuple[Loner4eCastEntry, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player and is not a person: a beast, a machine, a "
        "storm, a curse.",
    )
