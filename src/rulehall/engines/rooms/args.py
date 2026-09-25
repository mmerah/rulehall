from typing import Self

from pydantic import Field, model_validator

from rulehall.core.validation import Frozen, Slug

ELSEWHERE = "ELSEWHERE (time has passed; you can move what the player cannot see)"
NOTHING_OFFSCREEN = "no time has passed offscreen; call this only while ELSEWHERE is shown"
MOVES_OFFSCREEN = "something moves where the player cannot see"
MOVED_CARD = "Elsewhere, something moves."


class MoveItem(Frozen):
    item_id: Slug = Field(description="Exact id of an item here or carried.")
    to_id: Slug = Field(description="Exact id of the player, an npc here, or this place.")


class DropHere(Frozen):
    item_id: Slug


class Move(Frozen):
    to_id: Slug = Field(description="Exact id of the place to move to.")
    with_ids: tuple[Slug, ...] = Field(
        default=(),
        description="Exact ids of living npcs here who follow one time. Party members come "
        "without this field.",
    )


class UnlockWay(Frozen):
    to_id: Slug = Field(description="Exact id of the locked way's destination.")


class Meanwhile(Frozen):
    dweller_id: Slug | None = Field(
        default=None, description="Exact id of a dweller elsewhere who walks to a new place."
    )
    dweller_to_id: Slug | None = Field(
        default=None, description="Exact id of the place the dweller walks to."
    )
    item_id: Slug | None = Field(
        default=None, description="Exact id of a loose item elsewhere that moves to a new place."
    )
    item_to_id: Slug | None = Field(
        default=None, description="Exact id of the place the item moves to."
    )
    shut_from_id: Slug | None = Field(
        default=None, description="Exact id of one end of the way that shuts."
    )
    shut_to_id: Slug | None = Field(
        default=None, description="Exact id of the other end of the way that shuts."
    )

    @model_validator(mode="after")
    def _paired(self) -> Self:
        pairs = (
            (self.dweller_id, self.dweller_to_id),
            (self.item_id, self.item_to_id),
            (self.shut_from_id, self.shut_to_id),
        )
        for first, second in pairs:
            if (first is None) != (second is None):
                raise ValueError("each of the three pairs takes both ends or neither")
        if all(first is None for first, _ in pairs):
            raise ValueError("give a dweller, an item or a way to shut")
        return self
