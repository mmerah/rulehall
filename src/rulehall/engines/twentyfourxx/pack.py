from typing import Self

from pydantic import Field, model_validator

from rulehall.core.play import DecisionOption
from rulehall.core.prompt import Sections, section_if
from rulehall.core.validation import Frozen, Slug, check_unique, slug
from rulehall.engines.hiring import HIRED, UNWRITTEN_CAST
from rulehall.engines.packs import (
    Block,
    CastPack,
    Named,
    PackBody,
    PackHead,
    block_line,
    bullets,
    check_items,
    check_lines,
)
from rulehall.engines.twentyfourxx.rules import SkillDie
from rulehall.engines.twentyfourxx.sheet import Kit

WORLDSMITH_GUIDANCE = (
    "24XX AUTHORING\n"
    f"{UNWRITTEN_CAST}The player is an operator on a job in a hard science-fiction future. "
    "Write each scene as a work site, a station or a ship. Write the people who control "
    "these places. People the player left behind move on without them.\n\n"
    "Code files each `cast` entry under the slug of its name: Bray Kell is `bray-kell`. Name "
    "entries so in `present` and `hidden`. The crew's ship belongs to the rules: never file it "
    "in `cast`.\n\n"
    "A scene is one place. A scene ends when the player leaves the place. WHAT COMES NEXT holds "
    "the player's own words about where they go and what they are after. Build the scene the "
    "player asked for. When the player leaves, the new scene is the place they named: never "
    "short of it, and never back where they left. Only a complication keeps them in the same "
    "place. Give the player what they went to look for, or the reason they cannot "
    "have it. Never give the player silence. A complication changes that place. Keep what the "
    "brief does not move.\n\n"
    "Put something in `hidden` when the scene has something worth finding. `hidden` is not "
    "necessary. Never name a hidden entity in `title`, `situation` or `recap`. Never name a "
    "hidden entity in the `brief` or the sheet of anyone the player can see. The player reads "
    "all of that text, and a name there gives the player the find. A hidden entity can name "
    "itself. Write in `arc` what ties one hidden thing to another. THE SCENE NOW names who is "
    "hidden there. Never put an entry the player has met in `hidden`. A hidden person's `brief` "
    "is what the player sees on meeting them. Put their secret in `arc`, never in the "
    "`brief`.\n\n"
    "Surprise the player. Turn an established fact against the player, or bring back something "
    "the player has stopped thinking about. Make the surprise from what exists. Never invent "
    "what the source would not hold."
)
COMPLICATING = (
    "The game master brings a complication into the scene the player is in: {brief}. Write the "
    "new situation as a new scene. You can keep the same `place_id`, and this is usual. Leave "
    "`location` empty: the player has not moved. Everyone here stays, unless the brief moves "
    "them. Change the situation. Do not change the player's answer to it. The player has not "
    "acted, so settle nothing for the player. Write in `recap` the scene as it was before it "
    "changed."
)
HIRING = (
    f"{HIRED}Choose the specialty, the origin and their options from ENGINE GUIDANCE for a "
    "character that a crew can hire for this work."
)
NEWCOMING = (
    "The player's operator is dead and no hired member lives. A new operator joins the crew "
    "and leads: {who}. They join in THE SCENE NOW, where the dead operator fell, and nowhere "
    "else. Write them from the player's words, and choose their specialty, "
    "origin and options from ENGINE GUIDANCE."
)
SKILL_COUNT = 17


class SkillChoice(DecisionOption):
    skills: dict[str, SkillDie]


class Specialty(DecisionOption):
    skills: dict[str, SkillDie]
    choice: tuple[SkillChoice, ...] = ()
    kit: tuple[Kit, ...] = ()
    kit_choice: tuple[Kit, ...] = ()

    def line(self) -> str:
        parts = [", ".join(f"{skill} d{die}" for skill, die in self.skills.items())]
        if self.choice:
            parts.append(f"skills, one of: {' / '.join(option.name for option in self.choice)}")
        if self.kit:
            parts.append(f"takes {', '.join(kit.name for kit in self.kit)}")
        if self.kit_choice:
            parts.append(f"weapon, one of: {' / '.join(kit.name for kit in self.kit_choice)}")
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


class TwentyFourXXBlock(Block):
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    skills: tuple[str, ...] = Field(min_length=1)
    items: tuple[str, ...] = ()
    hindrances: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _reads_in_a_block(self) -> Self:
        check_lines("a block field", (self.name, self.brief))
        check_items("a block list", (*self.skills, *self.items, *self.hindrances))
        return self

    def line(self) -> str:
        return block_line(
            self.name,
            self.brief,
            ("skills", ", ".join(self.skills)),
            ("items", ", ".join(self.items)),
            ("hindrances", ", ".join(self.hindrances)),
        )


class TwentyFourXXPack(CastPack[TwentyFourXXBlock]):
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


class SheetProposal(Frozen):
    """An operator's creation choices. The engine builds the sheet from them: the specialty's
    skills and kit, the origin's increases, traits and body, the starting kit and ₡2."""

    specialty: str = Field(description="One of the specialties in ENGINE GUIDANCE.")
    specialty_skills: str = Field(
        default="",
        description="The specialty's skills option, when it offers one. Empty otherwise.",
    )
    weapon: str = Field(
        default="",
        description="The specialty's weapon option, when it offers one. Empty otherwise.",
    )
    origin: str = Field(description="One of the origins in ENGINE GUIDANCE.")
    traits: tuple[str, ...] = Field(
        default=(),
        description="One invented trait for each the origin gives, such as 'wings'. Empty "
        "otherwise.",
    )
    body: str = Field(
        default="", description="The origin's body option, when it offers one. Empty otherwise."
    )
    increases: tuple[str, ...] = Field(
        default=(),
        description="One skill for each increase the origin gives: from the skills in ENGINE "
        "GUIDANCE, or one you invent that fits. A skill named twice rises twice.",
    )


class NewcomerProposal(Frozen):
    name: str = Field(min_length=1, description="The operator's name, as the player gave it.")
    brief: str = Field(min_length=1, description="Who they are, in one line.")
    sheet: SheetProposal


class SpecialtyProposal(Named):
    """A written pack has no pick inside a pick, so a specialty names its own skills."""

    # `default=...` is pydantic for required: a pick's prompt text, which `Named` lets be empty.
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


class OriginProposal(Named):
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
        taken: list[Slug] = []
        specialties: list[Specialty] = []
        for proposal in self.specialties:
            # Appended as each id is made: two rows sharing a name must not share an id.
            specialties.append(
                Specialty(
                    id=slug(proposal.name, taken),
                    name=proposal.name,
                    brief=proposal.brief,
                    skills=dict.fromkeys(proposal.skills, 8),
                    kit=tuple(Kit(name=name) for name in proposal.kit),
                )
            )
            taken.append(specialties[-1].id)
        origins: list[Origin] = []
        for proposal in self.origins:
            origins.append(
                Origin(
                    id=slug(proposal.name, taken),
                    name=proposal.name,
                    brief=proposal.brief,
                    increases=proposal.increases,
                    invents=proposal.invents,
                )
            )
            taken.append(origins[-1].id)
        return {
            **super().pack_fields(),
            "specialties": tuple(specialties),
            "origins": tuple(origins),
        }


class TwentyFourXXBody(PackBody):
    factions: tuple[TwentyFourXXBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="The powers that control this setting, such as a company, a union or a fleet.",
    )
    npcs: tuple[TwentyFourXXBlock, ...] = Field(
        min_length=1, max_length=6, description="People a player could meet and work with."
    )
    monsters: tuple[TwentyFourXXBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player: a boarding crew, a drone, a thing in the hold.",
    )
