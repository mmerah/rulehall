from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Frozen, Slug, check_unique
from rulehall.core.views import Sprite, Tag


class Facet(Frozen):
    name: str
    value: str


class CatalogOrder(Frozen):
    name: str
    choice_ids: tuple[Slug, ...]


class Choice(Frozen):
    choice_id: Slug
    name: str
    brief: str = ""
    help: str = ""
    sprites: tuple[Sprite, ...] = ()
    tags: tuple[Tag, ...] = ()
    badge: str = ""
    group: str = ""
    refusal: str = ""
    search_text: str = ""
    facets: tuple[Facet, ...] = ()
    option: ActionOption | None = None


class Catalog(Frozen):
    catalog_id: Slug
    title: str
    choices: tuple[Choice, ...]
    facets: tuple[str, ...]
    orders: tuple[CatalogOrder, ...]
    columns: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _orders_list_every_choice_once(self) -> Self:
        ids = [choice.choice_id for choice in self.choices]
        check_unique("choice ids", ids)
        if wrong := sorted(
            order.name for order in self.orders if sorted(order.choice_ids) != sorted(ids)
        ):
            raise ValueError(f"orders that do not list every choice once: {wrong}")
        return self


class PickField(Frozen):
    kind: Literal["pick"] = "pick"
    field_id: Slug
    label: str
    catalog_id: Slug
    picked: tuple[Choice, ...]
    picks: int = Field(default=1, ge=1)
    pinned: tuple[Choice, ...] = ()
    error: str = ""
    help: str = ""


class PointRow(Frozen):
    name: str
    points: int = Field(ge=0)
    final: int = Field(ge=0)
    mark: Literal["raised", "lowered"] | None = None
    hint: str = ""


class PointsField(Frozen):
    kind: Literal["points"] = "points"
    field_id: Slug
    label: str
    rows: tuple[PointRow, ...]
    row_max: int = Field(ge=1)
    budget: int = Field(ge=1)
    quick: tuple[Choice, ...]
    error: str = ""

    @property
    def used(self) -> int:
        return sum(row.points for row in self.rows)

    @property
    def left(self) -> int:
        return self.budget - self.used


type TeamBuilderField = Annotated[PickField | PointsField, Field(discriminator="kind")]


class Advice(Frozen):
    advice_id: Slug
    severity: Literal["info", "warning", "error", "good"]
    text: str
    fix: ActionOption | None = None


class TeamBuilderSlot(Frozen):
    name: str
    sprite: Sprite | None
    tags: tuple[Tag, ...]
    brief: str
    filled: bool
    edited: bool
    error: str = ""
    fields: tuple[TeamBuilderField, ...]
    presets: tuple[Choice, ...] = ()


class TeamBuilderView(Frozen):
    title: str
    slots: tuple[TeamBuilderSlot, ...]
    advice: tuple[Advice, ...]
    dirty: bool
    locked_reason: str = ""
    save_lock: str = ""
    copyable: bool = False
    pending_team_open: bool = False


class ImportPreview(Frozen):
    rows: tuple[TeamBuilderSlot, ...]
    notes: tuple[str, ...]
    importable: bool
