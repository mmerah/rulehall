from collections.abc import Awaitable, Callable
from functools import partial

from nicegui import ui

from rulehall.engines.pokemon.champions.args import MoveSlotEdit, SlotEdit
from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.unsaved import ITEM
from rulehall.engines.pokemon.champions.views import (
    Choice,
    PickField,
    TeamBuilderSlot,
    TeamBuilderView,
)
from rulehall.engines.pokemon.sprites import item_sprite
from rulehall.screens.pokemon.catalog_picker import EditTeam, FindSprite, slot_sprite
from rulehall.ui.panel_parts import avatar, tag_row
from rulehall.ui.widgets import heading, icon_button, media_url


class TeamRail:
    def __init__(
        self,
        edit: EditTeam,
        select: Callable[[int], Awaitable[None]],
        find_sprite: FindSprite,
        view: TeamBuilderView,
        number: int,
        *,
        enabled: bool,
    ) -> None:
        self.edit = edit
        self.select = select
        self.find_sprite = find_sprite
        self.view = view
        self.number = number
        self.enabled = enabled
        self.draw()

    def show(self, view: TeamBuilderView, number: int, *, enabled: bool) -> None:
        drawn = (_cards(self.view), self.number, self.enabled)
        self.view, self.number, self.enabled = view, number, enabled
        if (_cards(view), number, enabled) != drawn:
            self.draw.refresh()

    @ui.refreshable_method
    def draw(self) -> None:
        filled = sum(slot.filled for slot in self.view.slots)
        heading(f"Team {filled}/{len(self.view.slots)}")
        with ui.element("div").classes("game-builder-cards"):
            for number, slot in enumerate(self.view.slots, start=1):
                self.draw_card(number, slot)

    def draw_card(self, number: int, slot: TeamBuilderSlot) -> None:
        state = "invalid" if slot.error else "empty" if not slot.filled else "filled"
        classes = f"game-builder-card game-builder-card-{state}"
        selected = number == self.number
        if selected:
            classes += " game-rail-on"
        name = slot.name if slot.filled else "Empty slot"
        with ui.element("div").classes(classes) as card:
            card.props.update(
                {
                    "tabindex": "0",
                    "role": "button",
                    "aria-label": f"Slot {number}: {name}, {_status_words(slot)}",
                }
            )
            if selected:
                card.props["aria-current"] = "true"
            ui.label(str(number)).classes("game-builder-card-number")
            if slot.filled:
                avatar(slot_sprite(self.find_sprite, slot), slot.name)
            else:
                ui.icon("sym_r_add_circle").classes("game-builder-card-add")
            with ui.column().classes("game-gap-0 game-builder-card-body"):
                ui.label(name).classes("game-builder-card-name")
                if slot.tags:
                    tag_row(slot.tags)
                if slot.brief:
                    ui.label(slot.brief).classes("game-builder-card-brief")
                elif (suggestion := _suggestion(slot)) is not None:
                    ui.label(f"Try {suggestion.name}").classes("game-builder-card-brief")
                with ui.row().classes("items-center no-wrap game-builder-card-meta game-gap-sm"):
                    self.draw_status(slot)
                    self.draw_item(slot)
            if self.view.edit_lock:
                ui.icon("sym_r_lock").classes("game-builder-card-lock").tooltip(self.view.edit_lock)
            else:
                self.draw_card_menu(number, slot)
        chosen = partial(self.select, number)
        card.on("click", chosen).on("keydown.enter", chosen).on("keydown.space.prevent", chosen)

    def draw_card_menu(self, number: int, slot: TeamBuilderSlot) -> None:
        with (
            icon_button("sym_r_more_vert", f"Slot {number} actions")
            .props("dense")
            .classes("game-builder-card-menu")
            .on("click.stop", js_handler="() => {}"),
            ui.menu(),
        ):
            for label, target in (("Move up", number - 1), ("Move down", number + 1)):
                ui.menu_item(label, on_click=partial(self.move_slot, number, target)).set_enabled(
                    self.enabled and 1 <= target <= len(self.view.slots)
                )
            ui.menu_item("Clear slot", on_click=partial(self.clear_slot, number)).set_enabled(
                self.enabled and slot.filled
            )

    def draw_status(self, slot: TeamBuilderSlot) -> None:
        if slot.error:
            with ui.label("⚠ fix").classes("game-builder-status game-builder-status-invalid"):
                ui.tooltip(slot.error).classes("game-help-tip")
        elif slot.edited:
            ui.label("● edited").classes("game-builder-status game-builder-status-edited")
        elif slot.filled:
            ui.label("✓ ready").classes("game-builder-status game-builder-status-ready")

    def draw_item(self, slot: TeamBuilderSlot) -> None:
        item = _picked_item(slot)
        if item is None:
            return
        sprite = self.find_sprite(item_sprite(item.choice_id))
        if sprite is not None:
            image = ui.element("img").classes("game-builder-card-item")
            image.props.update({"src": media_url(sprite.path), "alt": "", "title": item.name})
        if item.choice_id in champions_data().legal.mega_formes:
            ui.label("◆ Mega").classes("game-builder-card-mega").tooltip(
                f"{item.name}: this Pokemon can Mega Evolve"
            )

    async def move_slot(self, number: int, target: int) -> None:
        if await self.edit("move_slot", MoveSlotEdit(slot=number, to_slot=target)):
            await self.select(target)

    async def clear_slot(self, number: int) -> None:
        await self.edit("clear_slot", SlotEdit(slot=number), undo=f"Slot {number} cleared.")


def _cards(view: TeamBuilderView) -> tuple[object, ...]:
    return (
        view.edit_lock,
        *(
            (
                slot.name,
                slot.sprite,
                slot.tags,
                slot.brief,
                slot.filled,
                slot.edited,
                slot.error,
                _picked_item(slot),
                _suggestion(slot),
            )
            for slot in view.slots
        ),
    )


def _status_words(slot: TeamBuilderSlot) -> str:
    if slot.error:
        return f"needs a fix: {slot.error}"
    if slot.edited:
        return "edited"
    return "ready" if slot.filled else "empty"


def _picked_item(slot: TeamBuilderSlot) -> Choice | None:
    return next(
        (
            each.picked[0]
            for each in slot.fields
            if isinstance(each, PickField) and each.field_id == ITEM and each.picked
        ),
        None,
    )


def _suggestion(slot: TeamBuilderSlot) -> Choice | None:
    if slot.filled:
        return None
    return next(
        (each.pinned[0] for each in slot.fields if isinstance(each, PickField) and each.pinned),
        None,
    )
