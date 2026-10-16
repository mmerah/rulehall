from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from rulehall.core.validation import Frozen, Slug, check_unique


class MoveItem(Frozen):
    item_id: Slug = Field(description="Exact id of an item here or carried.")
    holder_id: Slug = Field(description="Exact id of the player, an npc here, or this place.")


class DropHere(Frozen):
    item_id: Slug


class MoveTo(Frozen):
    to_id: Slug = Field(description="Exact id of the place to move to.")
    with_ids: tuple[Slug, ...] = Field(
        default=(),
        description="Exact ids of living npcs here who follow one time. Party members come "
        "without this field.",
    )


class UnlockWay(Frozen):
    to_id: Slug = Field(description="Exact id of the locked way's destination.")


class ExtendMap(Frozen):
    heading: str = Field(
        min_length=1,
        description="Where the player heads past the map's edge, in their own words.",
    )


class WalkChange(Frozen):
    kind: Literal["walk"] = Field(
        description="A dweller walks along one unlocked way, also into or out of the player's "
        "place."
    )
    dweller_id: Slug = Field(description="Exact id of the dweller.")
    to_id: Slug = Field(description="Exact id of the place.")


class CarryChange(Frozen):
    kind: Literal["carry"] = Field(description="An item goes to a place or to a living dweller.")
    item_id: Slug = Field(description="Exact id of the item.")
    to_id: Slug = Field(description="Exact id of the place or the dweller.")


class ShutChange(Frozen):
    kind: Literal["shut"] = Field(
        description="A way that the player knows locks on both sides. The player always keeps "
        "one open way out."
    )
    from_id: Slug = Field(description="Exact id of one end of the way.")
    to_id: Slug = Field(description="Exact id of the other end of the way.")


class OpenChange(Frozen):
    kind: Literal["open"] = Field(
        description="A locked way that the player knows unlocks on both sides."
    )
    from_id: Slug = Field(description="Exact id of one end of the way.")
    to_id: Slug = Field(description="Exact id of the other end of the way.")


class FallChange(Frozen):
    kind: Literal["fall"] = Field(description="A dweller away from the player dies.")
    dweller_id: Slug = Field(description="Exact id of the dweller.")


type MeanwhileChange = Annotated[
    WalkChange | CarryChange | ShutChange | OpenChange | FallChange, Field(discriminator="kind")
]


class Meanwhile(Frozen):
    changes: tuple[MeanwhileChange, ...] = Field(
        description="Each dweller, item and way changes at most once. Party members and their "
        "items never change."
    )

    @model_validator(mode="after")
    def _once_each(self) -> Self:
        check_unique("dwellers, items or ways in one call", map(_subject, self.changes))
        return self


def _subject(change: MeanwhileChange) -> str:
    match change:
        case WalkChange() | FallChange():
            return change.dweller_id
        case CarryChange():
            return change.item_id
        case ShutChange() | OpenChange():
            return " <-> ".join(sorted((change.from_id, change.to_id)))
