from pydantic import Field

from rulehall.core.validation import Frozen, Slug


class Enter(Frozen):
    target_id: Slug = Field(description="Exact id of a cast member not already here.")


class Leave(Frozen):
    target_id: Slug = Field(description="Exact id of someone here.")
