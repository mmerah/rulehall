from typing import Self

from pydantic import Field, model_validator

from rulehall.core.decisions import DecisionOption
from rulehall.core.prompt import Sections, section_if
from rulehall.core.validation import check_unique, slugs
from rulehall.engines.packs import (
    CastEntry,
    CastPack,
    PackBody,
    PackHead,
    TableEntry,
    bullets,
    cast_entry_line,
    check_items,
    check_lines,
)
from rulehall.engines.twentyfourxx.rules import SkillDie
from rulehall.engines.twentyfourxx.sheet import Kit


class SkillChoice(DecisionOption):
    skills: dict[str, SkillDie]


class Weapon(DecisionOption):
    kit: Kit


class Specialty(DecisionOption):
    skills: dict[str, SkillDie]
    choice: tuple[SkillChoice, ...] = ()
    kit: tuple[Kit, ...] = ()
    kit_choice: tuple[Weapon, ...] = ()

    def line(self) -> str:
        parts = [", ".join(f"{skill} d{die}" for skill, die in self.skills.items())]
        if self.choice:
            parts.append(f"skills, one of: {' / '.join(option.name for option in self.choice)}")
        if self.kit:
            parts.append(f"takes {', '.join(kit.name for kit in self.kit)}")
        if self.kit_choice:
            parts.append(f"weapon, one of: {' / '.join(weapon.name for weapon in self.kit_choice)}")
        return f"{self.name}: {'; '.join(part for part in parts if part)}"


class Body(DecisionOption):
    kit: Kit | None = None


class Origin(DecisionOption):
    increases: int = 0
    invents: int = 0
    choice: tuple[Body, ...] = ()

    def line(self) -> str:
        gives: list[str] = []
        if self.increases:
            gives.append(f"skill increases: {self.increases}")
        if self.invents:
            gives.append(f"traits to invent: {self.invents}")
        if self.choice:
            gives.append(f"body, one of: {' / '.join(body.name for body in self.choice)}")
        line = f"{self.name} — {self.brief}"
        return f"{line} ({'; '.join(gives)})" if gives else line


class TwentyFourXXCastEntry(CastEntry):
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    skills: tuple[str, ...] = Field(min_length=1)
    items: tuple[str, ...] = ()
    hindrances: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _reads_on_one_line(self) -> Self:
        check_lines("a cast entry field", (self.name, self.brief))
        check_items("a cast entry list", (*self.skills, *self.items, *self.hindrances))
        return self

    def line(self) -> str:
        return cast_entry_line(
            self.name,
            self.brief,
            ("skills", ", ".join(self.skills)),
            ("items", ", ".join(self.items)),
            ("hindrances", ", ".join(self.hindrances)),
        )


class TwentyFourXXPack(CastPack[TwentyFourXXCastEntry]):
    skills: tuple[DecisionOption, ...] = ()
    specialties: tuple[Specialty, ...] = ()
    origins: tuple[Origin, ...] = ()
    starting_kit: tuple[Kit, ...] = ()

    @model_validator(mode="after")
    def _every_pick_told(self) -> Self:
        untold = [option.id for option in (*self.specialties, *self.origins) if not option.brief]
        if untold:
            raise ValueError(f"no brief for {', '.join(untold)}")
        return self

    def specialty_lines(self) -> str:
        return "\n".join(specialty.line() for specialty in self.specialties)

    def table_sections(self) -> Sections:
        return (
            *section_if("SPECIALTIES", self.specialty_lines()),
            *bullets("ORIGINS", (origin.line() for origin in self.origins)),
        )


class SpecialtyProposal(TableEntry):
    """A written pack has no pick inside a pick, so a specialty names its own skills."""

    # `default=...` is pydantic for required: a pick's prompt text, empty in a `TableEntry`.
    brief: str = Field(
        default=...,
        min_length=1,
        max_length=200,
        description="The line a player reads for this specialty, such as 'You cut steel "
        "and read the welds'.",
    )
    skills: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="The skills that this specialty starts at d8. Use plain names, such as "
        "'Salvage'.",
    )
    kit: tuple[str, ...] = Field(
        default=(),
        max_length=3,
        description="What this specialty starts with, such as 'cutting torch'. Empty when "
        "the specialty starts with nothing of its own.",
    )

    @model_validator(mode="after")
    def _skills_are_distinct_and_read_in_a_block(self) -> Self:
        check_unique("skills", self.skills)
        check_items("a specialty list", (*self.skills, *self.kit))
        return self


class OriginProposal(TableEntry):
    """Where an operator comes from, and what the origin gives at creation."""

    brief: str = Field(
        default=...,
        min_length=1,
        max_length=200,
        description="The line a player reads for this origin, such as 'Born on the belt, "
        "and it shows'.",
    )
    increases: int = Field(
        default=0,
        ge=0,
        le=3,
        description="How many starting skills this origin raises by one step, such as 3 for "
        "an origin with many skills.",
    )
    invents: int = Field(
        default=0,
        ge=0,
        le=3,
        description="How many traits this origin lets a player invent, such as 2 for an "
        "alien origin.",
    )


class TwentyFourXXHead(PackHead):
    specialties: tuple[SpecialtyProposal, ...] = Field(
        min_length=1, max_length=6, description="The trades a player selects an operator from."
    )
    origins: tuple[OriginProposal, ...] = Field(
        min_length=1, max_length=6, description="Where an operator can come from in this setting."
    )

    def pack_fields(self) -> dict[str, object]:
        ids = iter(slugs(proposal.name for proposal in (*self.specialties, *self.origins)))
        specialties = tuple(
            Specialty(
                id=next(ids),
                name=proposal.name,
                brief=proposal.brief,
                skills=dict.fromkeys(proposal.skills, 8),
                kit=tuple(Kit(name=name) for name in proposal.kit),
            )
            for proposal in self.specialties
        )
        origins = tuple(
            Origin(
                id=next(ids),
                name=proposal.name,
                brief=proposal.brief,
                increases=proposal.increases,
                invents=proposal.invents,
            )
            for proposal in self.origins
        )
        return {**super().pack_fields(), "specialties": specialties, "origins": origins}


class TwentyFourXXBody(PackBody):
    factions: tuple[TwentyFourXXCastEntry, ...] = Field(
        min_length=1,
        max_length=6,
        description="The powers that control this setting, such as a company, a union or a fleet.",
    )
    npcs: tuple[TwentyFourXXCastEntry, ...] = Field(
        min_length=1, max_length=6, description="People a player could meet and work with."
    )
    monsters: tuple[TwentyFourXXCastEntry, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player: a boarding crew, a drone, a thing in the hold.",
    )
