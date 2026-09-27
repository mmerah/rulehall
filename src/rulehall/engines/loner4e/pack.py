from collections.abc import Callable
from typing import Self

from pydantic import Field, model_validator

from rulehall.core.play import DecisionOption
from rulehall.core.prompt import Sections
from rulehall.core.validation import Frozen, Slug
from rulehall.engines.loner4e.rules import MEANWHILE_QUESTION
from rulehall.engines.packs import (
    NPCS,
    Block,
    CastPack,
    Named,
    PackBody,
    PackHead,
    block_line,
    check_items,
    check_lines,
    with_ids,
)

WORLDSMITH_GUIDANCE = (
    "LONER 4E AUTHORING\n"
    "Every character is a person, an object, a vehicle or a curse. "
    "Each character has a one-line `concept`, `tags` by kind, and luck of its own. "
    "The tag kinds are `skill`, `frailty` and `gear`. A `relationship` tag, such as `Uneasy "
    "Ally`, goes on the NPC, never on the player, and only once play has earned it. "
    "Luck shows how long a character holds out in a conflict. Luck is not health. "
    "Write a group of similar opponents, such as a squad or a mob, as one character with "
    "`group` true: the engine gives it one luck pool for the whole group. Do not write the group "
    "as several characters. "
    "A living character can have a `goal`, a `motive` and a `nemesis`. An object, a vehicle "
    "and a curse have none of these. "
    "Every scene acts on the `goal` of the player, or brings the `nemesis` of the player "
    "nearer. A blank goal or motive on the player's sheet is fine: let the first scenes offer "
    "them. "
    "A place's tags go in `details`, never in a character's tags or in a cast entry under the "
    "id `scene`, which names the scene. "
    "The opposition's tags say what they are doing now, such as `Searching for the "
    "Protagonist`. "
    "Give a door or a storm the `skill` tags and the `frailty` tags that it resists with. "
    "Tags are free text. Use entries from the selected pack when they fit. Invent a tag for "
    "this scenario when the invented tag is clearer. Only a pack tag has a meaning that the "
    "game master can look up. An invented tag that does not show what it does needs one "
    "sentence in the `brief` of that character. The game master judges from that sentence "
    "whether the tag helps or hinders. "
    "Use the factions, the people and the monsters of a pack: file one into `cast` under a new "
    "id, copy its tags and its drives, and write a `brief` for this scene. Take names from the "
    "name lists of the pack when the setting has them.\n\n"
    "Loner has no pre-written story: the oracle discovers the world. Leave open what the "
    "oracle can answer. Write places, people, their tags and what they want, never a secret "
    "answer. Write in `arc` loose pressure only: what the opposition wants and the open "
    "threads, never a plot or a planned twist. A cast entry elsewhere is someone who may turn "
    "up, not a secret. Someone the player left behind stays behind until the "
    "story brings them back; a Meanwhile changes what they are doing. Surprise comes from the "
    "oracle, the twists and the transitions, not from you. WHAT THE PROTAGONIST CARRIES "
    "FORWARD, when shown, is what became of the world of the protagonist's past adventures: it "
    "stands."
)
OPENING_FRAME = (
    "Open in the middle of a tense moment: the protagonist has a goal, an obstacle in the way, "
    "and time pressing. When the source is only a prompt, write a premise and a web of people "
    "who may turn up, not a plot."
)
DRAMATIC = (
    "The scene closed ({reason}). {words}DRAMATIC: open on what is pressing. Something "
    "external has moved; the protagonist responds. Place it where the player was heading when "
    "the fiction allows."
)
TIPPED = (
    "The quiet scene tipped into urgency on those words: open on that action, still "
    "unresolved, so the player plays it."
)
MEANWHILE = (
    "MEANWHILE: the world's turn. Cut to whoever holds power, where the protagonist is not: "
    "what they do out of the protagonist's sight, never beside them; write their new tags in "
    f'`power`. The oracle said "{{ally}}" to "{MEANWHILE_QUESTION}". On a yes, also write in '
    "`ally` the new tags of the NPC most affected and let the next scene show what they did. "
    "On a no, allies hold: `ally` is null, and no ally moves under `power`. {then}"
)
MEANWHILE_TWIST = "The world's turn brought a twist: {twist}. Read it in what moved off screen."
MEANWHILE_DRAMATIC = "Then write the next scene in `scene`. {dramatic}"
MEANWHILE_QUIET = (
    "Then write no scene: leave `scene` null. The protagonist gets a quiet window and chooses "
    "its aim."
)
LIVING_WORLD = (
    "THE LIVING WORLD: the adventure ended: {why}. One line each; the player reads them, so "
    "name only what the player has met, and write no id in a line."
)
OFFSCREEN = "Off screen: {offscreen}. Let this scene show it where it touches the aim."
QUIET = (
    'QUIET: the protagonist has initiative and the world is receptive. Their aim: "{aim}". '
    "Write the place and the people for it. `goal` is that aim. Settle nothing: "
    "the oracle answers whether it works."
)


class Fate(Frozen):
    entity_id: Slug = Field(description="Exact id of an NPC the player has met.")
    line: str = Field(
        min_length=1,
        description="How the relationship stands, what they want now, gone or still in play. "
        "Leave out their name: the engine writes it.",
    )


class LivingWorld(Frozen):
    people: tuple[Fate, ...] = Field(description="For each NPC who mattered, one entry.")
    places: tuple[str, ...] = Field(
        description="For each location that featured, one line: what changed there, and "
        "whether it stays accessible, dangerous or relevant."
    )
    events: tuple[str, ...] = Field(
        description="For each event, thread or faction that mattered, one line: settled or "
        "still hanging, and the pressure it keeps on the world."
    )

    @model_validator(mode="after")
    def _one_line_at_least(self) -> Self:
        if not (self.people or self.places or self.events):
            raise ValueError("write at least one line")
        return self

    def lines(self, name_of: Callable[[Slug], str]) -> tuple[str, ...]:
        people = (f"{name_of(fate.entity_id)}: {fate.line}" for fate in self.people)
        return (*people, *self.places, *self.events)


class Loner4eBlock(Block):
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


class Loner4ePack(CastPack[Loner4eBlock]):
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


class Loner4eBody(PackBody):
    factions: tuple[Loner4eBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="The powers that control this setting, such as a guild, a cult or a "
        "city watch. Write each one as the SRD prints it.",
    )
    npcs: tuple[Loner4eBlock, ...] = Field(min_length=1, max_length=6, description=NPCS)
    monsters: tuple[Loner4eBlock, ...] = Field(
        min_length=1,
        max_length=6,
        description="What is against the player and is not a person: a beast, a machine, a "
        "storm, a curse.",
    )
