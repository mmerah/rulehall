from typing import Annotated

from pydantic import Field

from rulehall.core.tools import PlayerFacing
from rulehall.core.validation import Frozen, Slug

ACTOR = "Exact id of a hired party member here who acts. Null for the player."
NAME_MAX = 48
BE_SHORT = f"Name it in three or four words, never more than {NAME_MAX} characters."
ShortName = Annotated[PlayerFacing, Field(max_length=NAME_MAX)]


class Attempt(Frozen):
    what: PlayerFacing = Field(
        min_length=1,
        description="The attempt, in a few words the player reads.",
    )


class Words(Frozen):
    words: str = Field(min_length=1)


class Reveal(Frozen):
    target_id: Slug = Field(description="Exact id of something hidden here.")


class Kill(Frozen):
    target_id: Slug = Field(description="Exact id of who here died.")


class JoinParty(Frozen):
    target_id: Slug = Field(description="Exact id of who is joining.")


class HireOrJoin(JoinParty):
    target_id: Slug = Field(description="Exact id of who here joins or is hired.")
    terms: str = Field(
        default="",
        description="Empty when they only come along. When the player hires them to work: what "
        "for and on what terms, as agreed.",
    )


class LeaveParty(Frozen):
    target_id: Slug = Field(description="Exact id of the party member leaving.")


class Direct(Frozen):
    text: PlayerFacing = Field(
        min_length=1,
        description=(
            "Brief factual notes for the narrator to phrase. Answer each question in the player "
            "action. Include the result, its known reason, and details needed for the next "
            "choice. For a request or warning, give what the person wants and the reason they "
            "share. Use facts the player can know now. Identify claims and unknown reasons as "
            "such. Keep every outcome consistent with tool results."
        ),
    )
