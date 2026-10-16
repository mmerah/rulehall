from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from nicegui import ui

from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.pokemon.champions.args import PickEdit, PointsEdit
from rulehall.engines.pokemon.champions.unsaved import SPECIES
from rulehall.engines.pokemon.champions.views import (
    Catalog,
    Choice,
    PickField,
    PointsField,
    TeamBuilderSlot,
    TeamBuilderView,
)
from rulehall.screens.pokemon.catalog_picker import CatalogPicker, EditTeam, FindSprite, slot_sprite
from rulehall.screens.pokemon.points_editor import PointsEditor
from rulehall.ui.panel_parts import avatar, choice_button, tag_row
from rulehall.ui.widgets import alert, heading, help_tip, icon_button


class PlayOption(Protocol):
    async def __call__(self, option: ActionOption, *, undo: str = "") -> bool: ...


@dataclass(frozen=True, slots=True)
class SlotEditorCallbacks:
    edit: EditTeam
    play: PlayOption
    select: Callable[[int], Awaitable[None]]
    find_sprite: FindSprite
    catalog: Callable[[Slug], Catalog]
    ask_replaced: Callable[[PickField], Awaitable[int | None]]
    focus_first: Callable[[str], None]


class SlotEditor:
    def __init__(
        self,
        picker: CatalogPicker,
        callbacks: SlotEditorCallbacks,
        view: TeamBuilderView,
        number: int,
        *,
        enabled: bool,
    ) -> None:
        self.picker = picker
        self.callbacks = callbacks
        self.view = view
        self.number = number
        self.enabled = enabled
        self.points: PointsEditor | None = None
        self.draw()

    @property
    def slot(self) -> TeamBuilderSlot:
        return self.view.slots[self.number - 1]

    def show(self, view: TeamBuilderView, number: int, *, enabled: bool) -> None:
        old = self.slot
        moved = (number, enabled, len(view.slots)) != (
            self.number,
            self.enabled,
            len(self.view.slots),
        )
        self.view, self.number, self.enabled = view, number, enabled
        if moved:
            self.draw.refresh()
            return
        if self.slot == old:
            return
        points = points_field(self.slot)
        if (
            self.points is not None
            and not self.points.element.is_deleted
            and points is not None
            and _without_points(old) == _without_points(self.slot)
            and self.points.fits(points)
        ):
            self.points.sync(points, enabled=self.enabled)
            return
        self.draw.refresh()

    @ui.refreshable_method
    def draw(self) -> None:
        slot = self.slot
        with ui.element("div").classes("w-full game-builder-editor-head"):
            icon_button("sym_r_chevron_left", "Previous slot", partial(self.step_slot, -1))
            if slot.filled:
                avatar(slot_sprite(self.callbacks.find_sprite, slot), slot.name)
            with ui.column().classes("game-gap-0 game-builder-editor-name"):
                ui.label(slot.name if slot.filled else "Empty slot").classes("game-title")
                with ui.row().classes("items-center game-gap-sm game-builder-editor-sub"):
                    ui.label(f"Slot {self.number} of {len(self.view.slots)}").classes("game-hint")
                    if slot.tags:
                        tag_row(slot.tags)
            icon_button("sym_r_chevron_right", "Next slot", partial(self.step_slot, 1))
        if slot.error:
            ui.label(f"⚠ {slot.error}").classes("game-builder-field-error")
        if slot.presets:
            with ui.column().classes(
                "w-full game-builder-section game-builder-section-slot game-builder-presets "
                "game-gap-md"
            ):
                heading("Presets", help="A preset fills the whole set at once.")
                with ui.element("div").classes("game-builder-preset-row"):
                    for choice in slot.presets:
                        self.draw_preset(choice)
        picks = [each for each in slot.fields if isinstance(each, PickField)]
        with ui.column().classes(
            "w-full game-builder-section game-builder-section-slot game-gap-md"
        ):
            heading("Set")
            for pick in picks:
                if pick.picks == 1:
                    self.draw_pick(pick)
        for pick in picks:
            if pick.picks > 1:
                with ui.column().classes(
                    "w-full game-builder-section game-builder-section-moves game-gap-md"
                ):
                    self.draw_moves(pick)
        self.points = None
        if (points := points_field(slot)) is not None:
            with ui.column().classes(
                "w-full game-builder-section game-builder-section-points game-gap-md"
            ):
                self.points = PointsEditor(
                    points,
                    partial(self.set_points, self.number),
                    self.apply_choice,
                    enabled=self.enabled,
                )

    def draw_preset(self, choice: Choice) -> None:
        sprite = choice.sprites[0] if choice.sprites else None
        choice_button(
            choice.name,
            choice.refusal or choice.brief,
            partial(self.apply_choice, choice),
            enabled=self.enabled and choice.option is not None and not choice.refusal,
            help=choice.help,
            tags=choice.tags,
            icon=None if sprite is None else self.callbacks.find_sprite(sprite),
        ).classes("game-builder-preset")

    def draw_pick(self, pick: PickField) -> None:
        picked = pick.picked[0] if pick.picked else None
        with ui.element("div").classes(_field_classes(pick)):
            help_tip(pick.help, ui.label(pick.label).classes("game-builder-field-label"))
            self.pick_button(pick, 0, picked)
            if pick.error:
                ui.label(pick.error).classes("game-builder-field-error")
            self.draw_pinned(pick)

    def draw_moves(self, pick: PickField) -> None:
        heading(pick.label, help=pick.help)
        with ui.element("div").classes(_field_classes(pick)):
            for index in range(pick.picks):
                picked = pick.picked[index] if index < len(pick.picked) else None
                with ui.element("div").classes("game-builder-move"):
                    self.pick_button(pick, index, picked)
                    if picked is not None:
                        icon_button(
                            "sym_r_close",
                            f"Clear {picked.name}",
                            partial(self.clear_move, pick, index),
                        ).props("dense").classes("game-builder-move-clear").set_enabled(
                            self.enabled
                        )
            if pick.error:
                ui.label(pick.error).classes("game-builder-field-error")
            self.draw_pinned(pick)

    def pick_button(self, pick: PickField, index: int, picked: Choice | None) -> ui.button:
        button = ui.button(on_click=partial(self.open_field, pick, index))
        button.props("outline no-caps aria-haspopup=listbox").classes("game-builder-pick")
        name = "Choose" if picked is None else picked.name
        button.props.update(
            {"aria-label": f"{pick.label}: {name}", "data-focus": f"pick-{pick.field_id}-{index}"}
        )
        with (
            button.set_enabled(self.enabled),
            ui.row().classes("w-full items-center no-wrap game-gap-md"),
        ):
            if picked is not None and picked.sprites:
                avatar(self.callbacks.find_sprite(picked.sprites[0]), picked.name)
            with ui.column().classes("game-gap-0 game-builder-pick-body"):
                with ui.row().classes("w-full items-center no-wrap game-gap-sm"):
                    ui.label(name).classes(
                        "game-builder-pick-name"
                        + (" game-builder-pick-empty" if picked is None else "")
                    )
                    if picked is not None and picked.tags:
                        tag_row(picked.tags, opens=False)
                if picked is not None and picked.brief:
                    ui.label(picked.brief).classes("game-builder-pick-brief")
            if picked is not None and picked.badge:
                ui.label(picked.badge).classes("game-builder-badge")
        return button

    def draw_pinned(self, pick: PickField) -> None:
        if not pick.pinned:
            return
        with ui.row().classes("items-center game-builder-pinned game-gap-sm"):
            ui.label("Common" if self.slot.filled else "Suggested").classes("game-hint")
            for choice in pick.pinned:
                index = None if pick.picks > 1 else 0
                chip = (
                    ui.button(
                        f"{choice.name} {choice.badge}".strip(),
                        on_click=partial(self.pick, pick, index, choice.choice_id),
                    )
                    .props("outline dense no-caps")
                    .classes("game-builder-chip")
                )
                chip.set_enabled(self.enabled and not choice.refusal)
                if choice.refusal:
                    chip.tooltip(choice.refusal)

    async def step_slot(self, by: int) -> None:
        await self.callbacks.select((self.number - 1 + by) % len(self.view.slots) + 1)

    async def flush_points(self) -> None:
        if self.points is not None and self.points.pending:
            await self.points.flush()

    def drop_pending(self) -> None:
        if self.points is not None:
            self.points.drop_pending()

    def open_field(self, pick: PickField, index: int | None) -> None:
        try:
            catalog = self.callbacks.catalog(pick.catalog_id)
        except Refusal as refused:
            alert(str(refused))
            return
        pinned_title = f"Common on {self.slot.name}" if self.slot.filled else "Suggested"
        self.picker.show(
            catalog,
            partial(self.pick, pick, index),
            picked=[choice.choice_id for choice in pick.picked],
            pinned=pick.pinned,
            pinned_title=pinned_title,
        )

    async def pick(self, pick: PickField, index: int | None, choice_id: Slug) -> None:
        current = tuple(choice.choice_id for choice in pick.picked)
        if index is None:
            if choice_id in current:
                return
            index = (
                len(current)
                if len(current) < pick.picks
                else await self.callbacks.ask_replaced(pick)
            )
            if index is None:
                return
        choice_ids = picked_ids(current, index, choice_id)
        if choice_ids == current:
            return
        if await self.callbacks.edit(
            "pick",
            PickEdit(slot=self.number, field_id=pick.field_id, choice_ids=choice_ids),
            undo="Placed with its top preset." if pick.field_id == SPECIES else "",
        ):
            self.callbacks.focus_first(pick_target(pick.field_id, index))

    async def clear_move(self, pick: PickField, index: int) -> None:
        current = tuple(choice.choice_id for choice in pick.picked)
        await self.callbacks.edit(
            "pick",
            PickEdit(
                slot=self.number,
                field_id=pick.field_id,
                choice_ids=current[:index] + current[index + 1 :],
            ),
        )

    async def set_points(self, slot: int, row: int, points: int) -> bool:
        return await self.callbacks.edit(
            "set_points", PointsEdit(slot=slot, row=row, points=points)
        )

    async def apply_choice(self, choice: Choice) -> None:
        if choice.option is not None:
            await self.callbacks.play(choice.option, undo=f"{choice.name} applied.")


def picked_ids(current: Sequence[Slug], index: int, choice_id: Slug) -> tuple[Slug, ...]:
    ids = list(current)
    if choice_id in ids:
        if index < len(ids):
            other = ids.index(choice_id)
            ids[other], ids[index] = ids[index], ids[other]
        return tuple(ids)
    if index < len(ids):
        ids[index] = choice_id
    else:
        ids.append(choice_id)
    return tuple(ids)


def points_field(slot: TeamBuilderSlot) -> PointsField | None:
    return next((each for each in slot.fields if isinstance(each, PointsField)), None)


def pick_target(field_id: Slug, index: int) -> str:
    return f'.game-builder-editor [data-focus="pick-{field_id}-{index}"]'


def _without_points(slot: TeamBuilderSlot) -> TeamBuilderSlot:
    return slot.model_copy(
        update={"fields": tuple(f for f in slot.fields if not isinstance(f, PointsField))}
    )


def _field_classes(pick: PickField) -> str:
    return "w-full game-builder-field" + (" game-builder-field-invalid" if pick.error else "")
