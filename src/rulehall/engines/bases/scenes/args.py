from pydantic import Field

from rulehall.core.log import Voice
from rulehall.core.validation import Frozen, Slug


class Enter(Frozen):
    target_id: Slug = Field(description="Exact id of a cast member not already here.")
    voice: Voice | None = Field(
        default=None,
        description="Only for someone not yet in the cast: how they sound read aloud. "
        "Feminine, masculine, or other for creatures, machines and voices that are neither. "
        "Leave it null for a cast member.",
    )


class Leave(Frozen):
    target_id: Slug = Field(description="Exact id of someone here.")
