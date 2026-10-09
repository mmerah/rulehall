from typing import Literal

from pydantic import Field

from rulehall.core.tools import PlayerFacing
from rulehall.core.validation import Frozen, Slug

type TeamEdit = Literal[
    "pick",
    "set_points",
    "apply_quick",
    "apply_preset",
    "move_slot",
    "clear_slot",
    "import_text",
    "load_template",
    "copy_registered_team",
    "fill_empty_slots",
    "save",
    "discard",
]


class Recruit(Frozen):
    species_id: Slug = Field(
        description="Exact id of a species legal in the format, such as 'garchomp'."
    )
    how: PlayerFacing = Field(
        min_length=1,
        description="How the Pokemon joins the player, such as 'traded for at the practice "
        "hall'. The player reads it.",
    )


class SlotEdit(Frozen):
    slot: int = Field(ge=1)


class MoveSlotEdit(SlotEdit):
    to_slot: int = Field(ge=1)


class PickEdit(SlotEdit):
    field_id: Slug
    choice_ids: tuple[Slug, ...]
    preset: bool = False


class PointsEdit(SlotEdit):
    field_id: Slug
    row: int = Field(ge=0)
    points: int = Field(ge=0)


class ChoiceEdit(SlotEdit):
    field_id: Slug
    choice_id: Slug


class PresetEdit(SlotEdit):
    preset_id: Slug


class PasteEdit(Frozen):
    text: str = Field(min_length=1)


class TemplateEdit(Frozen):
    template_id: Slug
