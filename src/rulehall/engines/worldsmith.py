from pydantic import BaseModel

from rulehall.core.prompt import Prompt, Sections, section_if, sections
from rulehall.core.tools import schema_text

SOURCELESS = "(none — write from what is below)"
SCOPELESS = "(none — this is a pack, not a scenario: a genre kit, not one adventure)"
PACK_SO_FAR = "THE PACK SO FAR"
SOURCE_BOUND = (
    "Take everything from SOURCE MATERIAL: its premise and, when it has one, its document. "
    "Use nothing from outside it."
)
HEAD_ASK = (
    "Write the head of a pack for this setting. A pack is a genre kit. The worldsmith reads the "
    "pack when it writes scenarios in this setting. Write `backdrop` as a few paragraphs. Say "
    "what this world is and what a story in it is about. The creation tables hold the names a "
    "player picks from. Give a one-line `brief` only where the name does not explain itself. "
    "The name lists must fit the setting. Write six to twelve names in each list. Leave a list "
    "empty when the setting has no such names. Write `rules` as prose: the one special rule of "
    "the genre. Leave `rules` empty when the genre has no special rule. "
    f"{SOURCE_BOUND}"
)
BODY_ASK = (
    "Write the rest of the pack. THE PACK SO FAR is the head. Everything you write belongs to "
    "that setting. The player meets the cast blocks in play. Write each cast block complete, so "
    "that a scene can file it into its cast as it stands. A location says what is found there "
    "and who the player can meet there. A seed is a one-line adventure premise. A player can "
    "start a scenario from a seed. "
    f"{SOURCE_BOUND}"
)


def render_worldsmith(
    role: str,
    *,
    source: str,
    backdrop: str = "",
    scope: str,
    world_sections: Sections,
    intent: str,
    guidance: str,
    answer_model: type[BaseModel],
) -> Prompt:
    return Prompt(
        system=sections((("YOUR ROLE", role),)),
        user=sections(
            (
                ("SOURCE MATERIAL", source or SOURCELESS),
                *section_if("BACKDROP", backdrop),
                ("THE SCOPE OF PLAY", scope or SCOPELESS),
                *world_sections,
                ("WHAT COMES NEXT", intent),
                ("ENGINE GUIDANCE", guidance),
                ("ANSWER WITH", schema_text(answer_model)),
            )
        ),
    )
