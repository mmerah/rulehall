from typing import Self

from pydantic import Field, model_validator

from rulehall.core.play import DecisionOption
from rulehall.core.prompt import Sections
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.loner3e.rules import DIE_FACE
from rulehall.engines.packs import (
    NPCS,
    Named,
    Pack,
    PackBody,
    PackHead,
    block_line,
    bullets,
    check_items,
    check_lines,
    with_ids,
)

WORLDSMITH_GUIDANCE = (
    "LONER 3E AUTHORING\n"
    "Every character is a person, an object, a vehicle or a curse. "
    "Each character has a one-line `concept`, `tags` by kind, and luck of its own. "
    "The tag kinds are `skill`, `frailty` and `gear`. "
    "Luck shows how long a character holds out in a conflict. Luck is not health. "
    "Give 6 luck to a character who can stand against the player. "
    "Give 2 or 3 luck to minor opposition that falls in one or two exchanges. "
    "Write a group of similar opponents as one character. Give that character one luck pool "
    "for the strength of the whole group. Do not write the group as several characters. "
    "Write `luck` full: make `current` equal to `maximum`. "
    "A living character can have a `goal`, a `motive` and a `nemesis`. An object, a vehicle "
    "and a curse have none of these. "
    "Every scene acts on the `goal` of the player, or brings the `nemesis` of the player "
    "nearer. "
    "Give a door or a storm the `skill` tags and the `frailty` tags that it resists with. "
    "Tags are free text. Use entries from the selected pack when they fit. Invent a tag for "
    "this scenario when the invented tag is clearer. Only a pack tag has a meaning that the "
    "game master can look up. An invented tag that does not show what it does needs one "
    "sentence in the `brief` of that character. The game master judges positions from that "
    "sentence. "
    "Use the factions, the people and the monsters of a pack: file one into `cast` under a new "
    "id, copy its tags and its drives, write a `brief` for this scene, and give it luck by the "
    "rule above. Take names from the name lists of the pack when the setting has them."
)


class Loner3eBlock(Frozen):
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
    def _reads_in_a_block(self) -> Self:
        check_lines(
            "a block field", (self.name, self.concept, self.goal, self.motive, self.nemesis)
        )
        check_items("a block list", (*self.skills, *self.frailties, *self.gear))
        return self

    def line(self) -> str:
        return block_line(
            self.name,
            self.concept,
            ("skills", ", ".join(self.skills)),
            ("frailties", ", ".join(self.frailties)),
            ("gear", ", ".join(self.gear)),
            ("goal", self.goal),
            ("motive", self.motive),
            ("nemesis", self.nemesis),
        )


class Loner3ePack(Pack):
    concepts: tuple[DecisionOption, ...] = Field(min_length=1)
    skills: tuple[DecisionOption, ...] = Field(min_length=1)
    frailties: tuple[DecisionOption, ...] = Field(min_length=1)
    gear: tuple[DecisionOption, ...] = Field(min_length=1)
    spends_luck: bool = False  # AP01: `rules` spends Luck, so `spend_luck` is allowed
    factions: tuple[Loner3eBlock, ...] = ()
    npcs: tuple[Loner3eBlock, ...] = ()
    monsters: tuple[Loner3eBlock, ...] = ()
    twist_subjects: tuple[str, ...] | None = None
    twist_actions: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _twist_columns_pair_up(self) -> Self:
        if (self.twist_subjects is None) != (self.twist_actions is None):
            raise ValueError("twist_subjects and twist_actions come together or not at all")
        for column in (self.twist_subjects, self.twist_actions):
            if column is not None and len(column) != DIE_FACE:
                raise ValueError("a twist column is one d6: exactly six entries")
        return self

    def sections(self, *, opening: bool) -> Sections:
        tags = "\n".join(
            f"{kind}: {', '.join(entry.name for entry in entries)}"
            for kind, entries in (
                ("concepts", self.concepts),
                ("skills", self.skills),
                ("frailties", self.frailties),
                ("gear", self.gear),
            )
        )
        return (
            *super().sections(opening=opening),
            ("TRAIT TAGS", tags),
            *bullets("FACTIONS", (block.line() for block in self.factions)),
            *bullets("PEOPLE", (block.line() for block in self.npcs)),
            *bullets("MONSTERS", (block.line() for block in self.monsters)),
        )


class Loner3eHead(PackHead):
    concepts: tuple[Named, ...] = Field(
        min_length=6,
        max_length=36,
        description="One-line concepts. A player picks a character from these, such as "
        "'A salvager who works the drowned streets'.",
    )
    skills: tuple[Named, ...] = Field(
        min_length=6,
        max_length=36,
        description="Free text skill tags. Each tag says what a character does well, such "
        "as 'Reads old stonework'.",
    )
    frailties: tuple[Named, ...] = Field(
        min_length=6,
        max_length=36,
        description="Free text frailty tags. Each tag says what works against a character, "
        "such as 'Owes the wrong people'.",
    )
    gear: tuple[Named, ...] = Field(
        min_length=6,
        max_length=36,
        description="Free text gear tags. Each tag is a thing a character carries, such as "
        "'A lantern that will not drown'.",
    )
    spends_luck: bool = Field(description="True only when `rules` gives a cost in luck.")

    def pack_fields(self) -> dict[str, object]:
        taken: list[Slug] = []
        return {
            **super().pack_fields(),
            "concepts": with_ids(self.concepts, taken),
            "skills": with_ids(self.skills, taken),
            "frailties": with_ids(self.frailties, taken),
            "gear": with_ids(self.gear, taken),
        }


class Loner3eBody(PackBody):
    factions: tuple[Loner3eBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="The powers that control this setting, such as a guild, a cult or a "
        "city watch. Write each one as the SRD prints it.",
    )
    npcs: tuple[Loner3eBlock, ...] = Field(min_length=1, max_length=6, description=NPCS)
    monsters: tuple[Loner3eBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player and is not a person: a beast, a machine, a "
        "storm, a curse.",
    )
