from typing import Self

from pydantic import Field, model_validator

from rulehall.core.prompt import Sections, section_if
from rulehall.core.validation import Frozen
from rulehall.engines.hiring import HIRED
from rulehall.engines.packs import NPCS, Pack, PackBody, PackHead, bullets, check_lines
from rulehall.engines.tunnelgoons.world import ABILITY_POINTS, AbilityScores

WORLDSMITH_GUIDANCE = (
    "TUNNEL GOONS AUTHORING\n"
    "Every npc needs `hp`. The `hp` value is the Health of the npc and its Difficulty "
    "Score. Set `hp` to 8 for easy, to 10 for moderate, or to 12 for hard. Use the people "
    "and the monsters of a pack: file one as an npc under a new id. Give a monster the "
    "`hp` that the pack prints."
)
HIRE_GUIDANCE = (
    "TUNNEL GOONS HIRING\n"
    f"Divide {ABILITY_POINTS} points across the three abilities. Brute is hitting things "
    "and acts of strength. Skulker is quiet movement, aiming and balance. Erudite is "
    "reading, perception and speech. Give the abilities only."
)
HIRING = (
    f"{HIRED}Write the three abilities of this character from ENGINE GUIDANCE. Make the "
    "abilities fit the character and the work."
)


class TunnelGoonsBlock(Frozen):
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    hp: int = Field(ge=1)  # Health and Difficulty Score at once: 8 easy, 10 moderate, 12 hard

    @model_validator(mode="after")
    def _reads_in_a_block(self) -> Self:
        check_lines("a block field", (self.name, self.brief))
        return self

    def line(self) -> str:
        return f"{self.name} — {self.brief} (hp {self.hp})"


class TunnelGoonsPack(Pack):
    items: tuple[str, ...] = ()  # the create page hints with these names
    factions: tuple[TunnelGoonsBlock, ...] = ()
    npcs: tuple[TunnelGoonsBlock, ...] = ()
    monsters: tuple[TunnelGoonsBlock, ...] = ()

    def sections(self, *, opening: bool) -> Sections:
        return (
            *super().sections(opening=opening),
            *section_if("ITEMS", ", ".join(self.items)),
            *bullets("FACTIONS", (block.line() for block in self.factions)),
            *bullets("PEOPLE", (block.line() for block in self.npcs)),
            *bullets("MONSTERS", (block.line() for block in self.monsters)),
        )


class AbilitiesProposal(Frozen):
    abilities: AbilityScores = Field(
        min_length=3,
        max_length=3,
        description=(
            f"Points in brute, skulker and erudite. The three share exactly "
            f"{ABILITY_POINTS} points."
        ),
    )

    @model_validator(mode="after")
    def _points_spent(self) -> Self:
        total = sum(self.abilities.values())
        if total != ABILITY_POINTS:
            raise ValueError(
                f"the three abilities must share exactly {ABILITY_POINTS} points, not {total}"
            )
        return self


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
    factions: tuple[TunnelGoonsBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="The powers that control this setting, such as a guild, a cult or a warband.",
    )
    npcs: tuple[TunnelGoonsBlock, ...] = Field(min_length=1, max_length=6, description=NPCS)
    monsters: tuple[TunnelGoonsBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player and is not a person: a beast, a horror, a "
        "thing in the dark.",
    )
