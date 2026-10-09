from collections.abc import Awaitable, Callable
from functools import partial

from nicegui import ui
from nicegui.events import GenericEventArguments
from pydantic import StrictInt, TypeAdapter

from rulehall.core.views import Tag
from rulehall.engines.pokemon.champions.views import Choice, PointRow, PointsField
from rulehall.ui.panel_parts import tag_row

type SendPoints = Callable[[int, int], Awaitable[bool]]
type ApplyQuick = Callable[[Choice], Awaitable[object]]

STEP_IDLE = 0.4
BIG_STEP = 8
FLASH_SECONDS = 1.6
POINTS = TypeAdapter[int](StrictInt)
INVALID = "game-points-invalid"
MARKS = {
    "raised": Tag(name="▲", help="The nature raises this stat by 10%."),
    "lowered": Tag(name="▼", help="The nature lowers this stat by 10%."),
}


class PointsLine:
    def __init__(self, editor: "PointsEditor", index: int, row: PointRow) -> None:
        self.row = row
        with ui.element("div").classes("game-points-row") as self.element:
            with ui.element("div").classes("game-points-line"):
                ui.label(row.name).classes("game-points-name")
                self.lower = ui.button(
                    icon="sym_r_remove", on_click=partial(editor.step, index, -1)
                )
                self.lower.props(f'flat round dense aria-label="Lower {row.name}"').classes(
                    "game-points-step"
                )
                with ui.element("div").classes("game-points-slider") as slider_box:
                    self.slider = ui.slider(min=0, max=editor.field.row_max, value=row.points)
                    self.slider.props(f'label aria-label="{row.name}"')
                    self.slider.on("change", partial(editor.slid, index))
                self.points = ui.label().classes("game-points-value")
                self.raise_ = ui.button(icon="sym_r_add", on_click=partial(editor.step, index, 1))
                self.raise_.props(f'flat round dense aria-label="Raise {row.name}"').classes(
                    "game-points-step"
                )
                self.number = ui.number(min=0, max=editor.field.row_max, precision=0, format="%d")
                self.number.props(f'dense aria-label="{row.name} points"').classes(
                    "game-points-number"
                )
                self.number.on("blur", partial(editor.typed, index))
                self.number.on("keydown.enter", partial(editor.typed, index))
                self.final = ui.label().classes("game-points-final")
                self.marks = ui.element("div").classes("game-points-marks")
            self.hint = ui.label().classes("game-points-hint")
        # Arrows on a stepper or the slider go through the idle flush: one save, not one per key.
        for control in (self.lower, slider_box, self.raise_):
            for key, by in (
                ("left.exact", -1),
                ("right.exact", 1),
                ("shift.left", -BIG_STEP),
                ("shift.right", BIG_STEP),
            ):
                control.on(f"keydown.capture.{key}.stop.prevent", partial(editor.step, index, by))
            control.on("keydown.capture.home.stop.prevent", partial(editor.step_to, index, 0))
            control.on(
                "keydown.capture.end.stop.prevent",
                partial(editor.step_to, index, editor.field.row_max),
            )
        self.show(row, row.points)

    def show(self, row: PointRow, points: int) -> None:
        self.row = row
        self.slider.value = points
        self.number.value = points
        mark = "" if row.mark is None else f", {row.mark}"
        self.slider.props(f'aria-valuetext="{row.name} {points} points, final {row.final}{mark}"')
        self.points.set_text(str(points))
        self.final.set_text(str(row.final))
        self.marks.clear()
        with self.marks:
            tag_row(() if row.mark is None else (MARKS[row.mark],))
        self.hint.set_text(row.hint)
        self.hint.classes(remove="game-points-flash")

    def flash(self, left: int) -> None:
        self.hint.set_text(f"{left} left")
        self.hint.classes("game-points-flash")
        with self.element:
            ui.timer(FLASH_SECONDS, lambda: self.show(self.row, self.row.points), once=True)

    def set_enabled(self, *, enabled: bool) -> None:
        for control in (self.lower, self.raise_, self.slider, self.number):
            control.set_enabled(enabled)


class PointsEditor:
    def __init__(
        self, field: PointsField, send: SendPoints, apply_quick: ApplyQuick, *, enabled: bool
    ) -> None:
        self.field = field
        self.send = send
        self.apply_quick = apply_quick
        self.pending: dict[int, int] = {}
        self.asked: dict[int, int] = {}
        self.idle: ui.timer | None = None
        with ui.column().classes("w-full game-points game-gap-md") as self.element:
            with ui.row().classes("w-full items-center no-wrap game-gap-md"):
                ui.label(field.label).classes("game-eyebrow")
                ui.space()
                self.counter = ui.label().classes("game-points-counter")
                self.counter.props("role=status aria-live=polite")
            self.lines = [PointsLine(self, index, row) for index, row in enumerate(field.rows)]
            self.error = ui.label().classes("game-builder-field-error")
            with ui.element("div").classes("game-points-quick"):
                self.quick_buttons = [
                    ui.button(choice.name, on_click=partial(apply_quick, choice))
                    .props("outline dense no-caps")
                    .classes("game-points-chip")
                    .tooltip(choice.help or choice.brief)
                    for choice in field.quick
                ]
        self.show_counter()
        self.set_enabled(enabled=enabled)

    def sync(self, field: PointsField, *, enabled: bool) -> None:
        self.field = field
        asked, self.asked = self.asked, {}
        for index, (line, row) in enumerate(zip(self.lines, field.rows, strict=True)):
            if index in self.pending:
                continue
            line.show(row, row.points)
            if index in asked and asked[index] > row.points:
                line.flash(max(field.left, 0))
        self.show_counter()
        self.set_enabled(enabled=enabled)

    def fits(self, field: PointsField) -> bool:
        return [row.name for row in field.rows] == [line.row.name for line in self.lines] and [
            choice.choice_id for choice in field.quick
        ] == [choice.choice_id for choice in self.field.quick]

    def set_enabled(self, *, enabled: bool) -> None:
        for line in self.lines:
            line.set_enabled(enabled=enabled)
        for button, choice in zip(self.quick_buttons, self.field.quick, strict=True):
            button.set_enabled(enabled and choice.option is not None and not choice.refusal)

    def show_counter(self) -> None:
        used = self.used()
        left = self.field.budget - used
        self.counter.set_text(f"Used {used} · Left {left} of {self.field.budget}")
        self.counter.classes(
            add="game-points-over" if left < 0 else "",
            remove="" if left < 0 else "game-points-over",
        )
        self.error.set_text(self.field.error)
        self.error.set_visibility(bool(self.field.error))
        self.element.classes(
            add=INVALID if self.field.error else "", remove="" if self.field.error else INVALID
        )

    def used(self) -> int:
        return sum(self.pending.get(index, row.points) for index, row in enumerate(self.field.rows))

    def step(self, index: int, by: int) -> None:
        self.step_to(index, self.pending.get(index, self.field.rows[index].points) + by)

    def step_to(self, index: int, points: int) -> None:
        points = min(max(points, 0), self.field.row_max)
        self.pending[index] = points
        line = self.lines[index]
        line.show(line.row, points)
        self.show_counter()
        if self.idle is not None:
            self.idle.cancel()
        with self.element:
            self.idle = ui.timer(STEP_IDLE, self.flush, once=True)

    async def slid(self, index: int, event: GenericEventArguments) -> None:
        await self.commit(index, POINTS.validate_python(event.args))

    async def typed(self, index: int) -> None:
        value = self.lines[index].number.value
        if value is None or int(value) == self.field.rows[index].points:
            return
        await self.commit(index, min(max(int(value), 0), self.field.row_max))

    def drop_pending(self) -> None:
        if self.idle is not None:
            self.idle.cancel()
            self.idle = None
        self.pending = {}

    async def flush(self) -> None:
        pending = self.pending
        self.drop_pending()
        for index, points in pending.items():
            if points != self.field.rows[index].points:
                await self.commit(index, points)

    async def commit(self, index: int, points: int) -> None:
        self.asked[index] = points
        sent = await self.send(index, points)
        self.asked.pop(index, None)
        if not sent and not self.element.is_deleted and index not in self.pending:
            row = self.field.rows[index]
            self.lines[index].show(row, row.points)
            self.show_counter()
