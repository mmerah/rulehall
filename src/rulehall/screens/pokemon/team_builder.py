import json
from dataclasses import dataclass, field
from functools import partial
from typing import Literal, cast

from nicegui import app, ui
from nicegui.events import ValueChangeEventArguments
from pydantic import Field, TypeAdapter

from rulehall.app.game_session import SessionSnapshot
from rulehall.core.decisions import ActionOption
from rulehall.core.game import AnyGame
from rulehall.core.validation import Frozen, Refusal, Slug, parse
from rulehall.core.views import ScreenSlot, require_view
from rulehall.engines.pokemon.champions.args import PasteEdit, TeamEdit
from rulehall.engines.pokemon.champions.panels import team_option
from rulehall.engines.pokemon.champions.team_builder import (
    SLOT_CATALOGS,
    TEAM_BUILDER_SCREEN_ID,
    TEMPLATES_CATALOG,
    team_catalog,
    team_export_text,
    team_import_preview,
)
from rulehall.engines.pokemon.champions.views import (
    Advice,
    Catalog,
    PointsField,
    TeamBuilderField,
    TeamBuilderSlot,
    TeamBuilderView,
)
from rulehall.screens.pokemon.catalog_picker import CatalogPicker
from rulehall.screens.pokemon.slot_editor import (
    SlotEditor,
    SlotEditorCallbacks,
    pick_target,
    points_field,
)
from rulehall.screens.pokemon.team_dialogs import TeamDialogs
from rulehall.screens.pokemon.team_rail import TeamRail
from rulehall.ui.screen_host import ScreenHost, screen_banner
from rulehall.ui.widgets import (
    Confirm,
    alert,
    attempt,
    done,
    failure_notice,
    heading,
    icon_button,
)

type Pane = Literal["slot", "moves", "points", "tips"]

PANE = TypeAdapter[Pane](Pane)
EDIT_FAILED = failure_notice("The team was not changed.")
UNDO_SECONDS = 8.0
SAVE_TIP = "Check the whole team and save it."
SAVE_WAITS = "Save waits for the end of the event."
WIDE_PANES: dict[Pane, str] = {"slot": "Slot", "tips": "Tips"}
PHONE_PANES: dict[Pane, str] = {"slot": "Set", "moves": "Moves", "points": "Points", "tips": "Tips"}
SEVERITY_ICONS = {
    "info": "sym_r_info",
    "warning": "sym_r_warning",
    "error": "sym_r_error",
    "good": "sym_r_check_circle",
}
SEVERITY_WORDS = {"info": "Note", "warning": "Warning", "error": "Error", "good": "Good"}
EDITING = "game-builder-editing"
ADVICE_FOLDED = "game-builder-advice-folded"
FIRST_PICK = ".game-builder-editor .game-builder-pick"
SELECTED_CARD = '.game-builder-rail [aria-current="true"]'
FIRST_STEPPER = ".game-builder-editor .game-points-invalid .game-points-step"


class TeamBuilderPlace(Frozen):
    open: bool = False
    slot: int = Field(default=1, ge=1)
    advice: bool = True


@dataclass(slots=True)
class CatalogMemo:
    state: AnyGame
    catalogs: dict[tuple[int | None, Slug], Catalog] = field(default_factory=dict)


class TeamBuilderScreen:
    opener_label = "Open team builder"
    opener_icon = "sym_r_edit_note"

    def __init__(self, host: ScreenHost) -> None:
        self.host = host
        self.session = host.session
        # Tab storage, not the save: where the player looks is no game state.
        self.storage = cast("dict[str, object]", app.storage.tab)
        self.storage_key = f"builder:{self.session.key.save_id}"
        place = parse(TeamBuilderPlace, self.storage.get(self.storage_key, {}))
        self.shown = place.open
        self.slot = place.slot
        self.advice_open = place.advice
        self.view: TeamBuilderView
        self.enabled = True
        self.editing = False
        self.pane: Pane = "slot"
        self.undo_timer: ui.timer | None = None
        self.catalog_memo: CatalogMemo | None = None
        self.picker = CatalogPicker(self.session.find_asset)
        self.confirm = Confirm(keep="Keep editing", confirm="Go ahead")
        self.banner: ui.column
        self.banner_text: ui.label
        self.column: ui.column
        self.title: ui.label
        self.pill: ui.label
        self.locked: ui.row
        self.locked_text: ui.label
        self.grid: ui.element
        self.wide_tabs: ui.tabs
        self.phone_tabs: ui.tabs
        self.foot_text: ui.label
        self.toast: ui.row
        self.toast_text: ui.label
        self.edit_buttons: list[ui.button] = []
        self.save_buttons: list[ui.button] = []
        self.save_tips: list[ui.tooltip] = []
        self.copy_button: ui.button
        self.dialogs: TeamDialogs
        self.rail: TeamRail
        self.editor: SlotEditor

    def build_banner(self) -> None:
        self.banner, self.banner_text = screen_banner(self, "team", "")
        self.banner.set_visibility(False)

    def build(self, now: SessionSnapshot) -> None:
        self.view = _team_builder_view(now.require_screen_slot(TEAM_BUILDER_SCREEN_ID))
        self.slot = min(self.slot, len(self.view.slots))
        self.enabled = _enabled(self.view, now)
        self.dialogs = TeamDialogs(
            self.session.find_asset,
            lambda text: team_import_preview(self.session.state, text),
            self.replace_team,
        )
        callbacks = SlotEditorCallbacks(
            edit=self.edit,
            play=self.play,
            select=self.select,
            find_sprite=self.session.find_asset,
            catalog=self.catalog,
            ask_replaced=self.dialogs.ask_replaced,
            focus_first=self.focus_first,
        )
        with ui.column().classes(
            "w-full flex-grow min-h-0 game-builder game-gap-md"
        ) as self.column:
            self.column.props("tabindex=-1")
            self.draw_head()
            with ui.row().classes(
                "w-full items-center game-builder-locked game-gap-md"
            ) as self.locked:
                ui.icon("sym_r_lock").classes("game-card-icon")
                self.locked_text = ui.label().classes("game-builder-locked-text")
                self.copy_button = (
                    ui.button(
                        "Copy to a new draft",
                        icon="sym_r_content_copy",
                        on_click=self.copy_to_unsaved_team,
                    )
                    .props("outline no-caps")
                    .tooltip("Edit a copy during the event; save it once the event ends.")
                )
                self.copy_button.set_enabled(now.working_role is None)
            self.draw_panes()
            with ui.element("div").classes("game-builder-grid") as self.grid:
                with ui.element("div").classes("game-builder-rail"):
                    self.rail = TeamRail(
                        self.edit,
                        self.select,
                        self.session.find_asset,
                        self.view,
                        self.slot,
                        enabled=self.enabled,
                    )
                with ui.element("div").classes("game-builder-editor"):
                    self.editor = SlotEditor(
                        self.picker, callbacks, self.view, self.slot, enabled=self.enabled
                    )
                with ui.element("div").classes("game-builder-advice"):
                    self.draw_advice()
            if not self.advice_open:
                self.grid.classes(ADVICE_FOLDED)
            with ui.row().classes("w-full items-center no-wrap game-builder-foot game-gap-md"):
                self.foot_text = ui.label().classes("game-builder-foot-text")
                self.foot_text.props("aria-live=polite")
                save = ui.button("Save team", icon="sym_r_save", on_click=self.save)
                self.save_buttons.append(
                    save.props("color=primary").classes("game-builder-foot-save")
                )
                with save:
                    self.save_tips.append(ui.tooltip(SAVE_TIP))
                ui.button("Done", on_click=self.leave_slot).props("color=primary").classes(
                    "game-builder-foot-done"
                )
            with ui.row().classes("items-center no-wrap game-builder-toast game-gap-md") as toast:
                self.toast = toast
                toast.props("role=status aria-live=polite")
                self.toast_text = ui.label()
                ui.button("Undo", on_click=self.undo).props("flat dense no-caps")
            self.toast.set_visibility(False)
        self.column.set_visibility(False)
        self.show_state()

    def show(self) -> None:
        self.shown = True
        self.remember()
        self.host.on_toggle()
        ui.run_javascript(f"requestAnimationFrame(() => getHtmlElement({self.column.id})?.focus())")

    def close(self) -> None:
        self.shown = False
        self.remember()
        self.host.on_toggle()

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:  # noqa: ARG002
        screen_slot = now.require_screen_slot(TEAM_BUILDER_SCREEN_ID)
        view = _team_builder_view(screen_slot) if screen_slot.live else None
        if self.shown and not screen_slot.live:
            self.shown = False
            self.remember()
        self.column.set_visibility(self.shown)
        self.banner.set_visibility(
            view is not None and not view.registered and not self.shown and now.working_role is None
        )
        self.copy_button.set_enabled(now.working_role is None)
        if view is not None:
            self.apply(view, enabled=_enabled(view, now))

    def apply(self, view: TeamBuilderView, *, enabled: bool) -> None:
        if view is self.view and enabled == self.enabled:
            return
        drawn = (self.view.advice, len(self.view.slots), self.enabled)
        self.view, self.enabled = view, enabled
        self.slot = min(self.slot, len(view.slots))
        self.rail.show(view, self.slot, enabled=enabled)
        self.editor.show(view, self.slot, enabled=enabled)
        if (view.advice, len(view.slots), enabled) != drawn:
            self.draw_advice.refresh()
        self.show_state()

    def show_state(self) -> None:
        view = self.view
        self.title.set_text(view.title)
        self.pill.set_text(_pill(view))
        self.pill.classes(
            add="game-builder-pill-dirty" if view.dirty else "",
            remove="" if view.dirty else "game-builder-pill-dirty",
        )
        self.banner_text.set_text(_banner(view))
        self.locked_text.set_text(view.save_lock if view.edit_lock else SAVE_WAITS)
        self.locked.set_visibility(bool(view.save_lock))
        self.copy_button.set_visibility(not view.copy_lock)
        for button in self.edit_buttons:
            button.set_enabled(self.enabled)
        for button in self.save_buttons:
            button.set_enabled(self.enabled and not view.save_lock)
        for tip in self.save_tips:
            tip.set_text(view.save_lock or SAVE_TIP)
        self.show_foot()

    def show_foot(self) -> None:
        if not self.editing:
            filled = sum(slot.filled for slot in self.view.slots)
            wrong = next(
                (
                    f"⚠ Slot {number}: {error}"
                    for number, slot in enumerate(self.view.slots, start=1)
                    if (error := _first_error(slot))
                ),
                "✓ no problems",
            )
            self.foot_text.set_text(f"Team {filled}/{len(self.view.slots)} · {wrong}")
            return
        points = points_field(self.editor.slot)
        used = "" if points is None else f"{points.used}/{points.budget} {points.label} · "
        error = _first_error(self.editor.slot)
        self.foot_text.set_text(used + (f"⚠ {error}" if error else "✓ no problems"))

    def draw_head(self) -> None:
        with ui.row().classes("w-full items-center no-wrap game-builder-head game-gap-md"):
            icon_button("sym_r_arrow_back", "Back to the story", self.close)
            with ui.column().classes("game-gap-0 game-builder-heading"):
                self.title = ui.label().classes("game-title game-builder-title")
                self.pill = ui.label().classes("game-builder-pill")
                self.pill.props("role=status aria-live=polite")
        with ui.row().classes("w-full items-center game-builder-tools game-gap-sm"):
            self.edit_buttons += [
                ui.button("Import", icon="sym_r_content_paste", on_click=self.open_import).props(
                    "flat no-caps"
                ),
                ui.button("Start from…", icon="sym_r_auto_awesome", on_click=self.start_from)
                .props("flat no-caps")
                .tooltip("Load a whole team that won events"),
                ui.button("Discard", icon="sym_r_delete_sweep", on_click=self.discard).props(
                    "flat no-caps"
                ),
            ]
            ui.button("Export", icon="sym_r_ios_share", on_click=self.open_export).props(
                "flat no-caps"
            )
            ui.space()
            save = ui.button("Save team", icon="sym_r_save", on_click=self.save)
            self.save_buttons.append(save.props("color=primary").classes("game-builder-save"))
            with save:
                self.save_tips.append(ui.tooltip(SAVE_TIP))

    def draw_panes(self) -> None:
        with ui.row().classes("w-full game-builder-panes game-gap-md"):
            self.wide_tabs = self.pane_tabs(WIDE_PANES, "game-builder-tabs-wide")
            self.phone_tabs = self.pane_tabs(PHONE_PANES, "game-builder-tabs-phone")

    def pane_tabs(self, panes: dict[Pane, str], classes: str) -> ui.tabs:
        with (
            ui.tabs(on_change=self.set_pane)
            .classes(f"game-segmented {classes}")
            .props("no-caps dense") as tabs
        ):
            for pane, label in panes.items():
                ui.tab(pane, label=label)
        tabs.set_value(self.pane)
        return tabs

    @ui.refreshable_method
    def draw_advice(self) -> None:
        with ui.row().classes("w-full items-center no-wrap game-builder-advice-head game-gap-sm"):
            heading("Advice")
            folded = not self.advice_open
            icon_button(
                "sym_r_right_panel_open" if folded else "sym_r_right_panel_close",
                "Show the advice" if folded else "Hide the advice",
                self.fold_advice,
            ).props("dense").classes("game-builder-fold")
        with ui.column().classes("w-full game-gap-0 game-builder-advice-body"):
            if not self.view.advice:
                ui.label("Nothing to point out.").classes("game-hint")
            for advice in self.view.advice:
                self.draw_tip(advice)

    def draw_tip(self, advice: Advice) -> None:
        with ui.row().classes(
            f"w-full no-wrap items-start game-builder-tip game-builder-tip-{advice.severity} "
            "game-gap-md"
        ):
            ui.icon(SEVERITY_ICONS[advice.severity]).classes("game-builder-tip-icon")
            with ui.column().classes("game-gap-0 game-builder-tip-body"):
                ui.label(SEVERITY_WORDS[advice.severity]).classes("game-builder-tip-kind")
                ui.label(advice.text)
            if (fix := advice.fix) is not None:
                ui.button("Fix", on_click=partial(self.play, fix, undo="Fixed.")).props(
                    "outline dense no-caps"
                ).set_enabled(self.enabled)

    async def select(self, number: int) -> None:
        await self.editor.flush_points()
        self.slot = number
        self.editing = True
        self.grid.classes(EDITING)
        self.remember()
        self.rail.show(self.view, number, enabled=self.enabled)
        self.editor.show(self.view, number, enabled=self.enabled)
        self.show_foot()
        self.focus_first(SELECTED_CARD)

    async def leave_slot(self) -> None:
        await self.editor.flush_points()
        self.editing = False
        self.grid.classes(remove=EDITING)
        self.show_foot()

    def set_pane(
        self, event: ValueChangeEventArguments[str | ui.tab | ui.tab_panel | None]
    ) -> None:
        self.show_pane(PANE.validate_python(event.value))

    def show_pane(self, pane: Pane) -> None:
        if pane == self.pane:
            return
        self.grid.classes(add=f"game-builder-show-{pane}", remove=f"game-builder-show-{self.pane}")
        self.pane = pane
        self.wide_tabs.set_value(pane if pane in WIDE_PANES else "slot")
        self.phone_tabs.set_value(pane)

    def fold_advice(self) -> None:
        self.advice_open = not self.advice_open
        self.grid.classes(
            add="" if self.advice_open else ADVICE_FOLDED,
            remove=ADVICE_FOLDED if self.advice_open else "",
        )
        self.remember()
        self.draw_advice.refresh()

    def remember(self) -> None:
        self.storage[self.storage_key] = TeamBuilderPlace(
            open=self.shown, slot=self.slot, advice=self.advice_open
        ).model_dump()

    def catalog(self, catalog_id: Slug) -> Catalog:
        state = self.session.state
        if self.catalog_memo is None or self.catalog_memo.state is not state:
            self.catalog_memo = CatalogMemo(state)
        catalogs = self.catalog_memo.catalogs
        key = (self.slot if catalog_id in SLOT_CATALOGS else None, catalog_id)
        if key not in catalogs:
            catalogs[key] = team_catalog(state, self.slot, catalog_id)
        return catalogs[key]

    async def save(self) -> None:
        if not self.enabled or self.view.save_lock:
            return
        if await self.edit("save"):
            done("Team saved.")
            return
        await self.show_first_error()

    async def show_first_error(self) -> None:
        number = next(
            (
                number
                for number, slot in enumerate(self.view.slots, start=1)
                if _first_error(slot) or not slot.filled
            ),
            None,
        )
        if number is None:
            return
        await self.select(number)
        wrong = _first_wrong_field(self.editor.slot)
        if isinstance(wrong, PointsField):
            self.show_pane("points")
            self.focus_first(FIRST_STEPPER)
            return
        self.show_pane("moves" if wrong is not None and wrong.picks > 1 else "slot")
        self.focus_first(FIRST_PICK if wrong is None else pick_target(wrong.field_id, 0))

    def focus_first(self, selector: str) -> None:
        ui.run_javascript(
            f"requestAnimationFrame(() => {{ const target = getHtmlElement({self.column.id})"
            f"?.querySelector({json.dumps(selector)}); "
            "target?.scrollIntoView({block: 'center', behavior: 'smooth'}); "
            "target?.focus({preventScroll: true}); })"
        )

    async def discard(self) -> None:
        if not self.view.unsaved_team_open:
            return
        if not self.view.dirty or await self.confirm.ask(
            "Discard every unsaved change to the team?"
        ):
            await self.edit("discard")

    def open_import(self) -> None:
        if self.enabled:
            self.dialogs.open_import()

    async def replace_team(self, text: str) -> bool:
        if self.view.dirty and not await self.confirm.ask(
            "Replace your unsaved team with the paste?"
        ):
            return False
        return await self.edit("import_text", PasteEdit(text=text), undo="Team imported.")

    def open_export(self) -> None:
        self.dialogs.open_export(team_export_text(self.session.state))

    async def copy_to_unsaved_team(self) -> None:
        await self.edit("copy_registered_team", undo="Draft opened.")

    def start_from(self) -> None:
        try:
            catalog = self.catalog(TEMPLATES_CATALOG)
        except Refusal as refused:
            alert(str(refused))
            return
        self.picker.show(catalog, partial(self.load_template, catalog))

    async def load_template(self, catalog: Catalog, choice_id: Slug) -> None:
        choice = next(choice for choice in catalog.choices if choice.choice_id == choice_id)
        if choice.option is None:
            return
        if self.view.dirty and not await self.confirm.ask(
            "Replace your unsaved team with this team?"
        ):
            return
        await self.play(choice.option, undo=f"{choice.name} loaded.")

    async def edit(self, edit: TeamEdit, args: Frozen | None = None, *, undo: str = "") -> bool:
        return await self.play(team_option(edit, args), undo=undo)

    async def play(self, option: ActionOption, *, undo: str = "") -> bool:
        self.hide_undo()
        await self.editor.flush_points()

        async def run() -> None:
            self.session.edit(option)
            self.apply_edited()

        played = await attempt(run, failed=EDIT_FAILED)
        if played and undo:
            self.offer_undo(undo)
        return played

    def apply_edited(self) -> None:
        now = self.session.snapshot()
        view = _team_builder_view(now.require_screen_slot(TEAM_BUILDER_SCREEN_ID))
        self.apply(view, enabled=_enabled(view, now))

    def offer_undo(self, text: str) -> None:
        self.toast_text.set_text(text)
        self.toast.set_visibility(True)
        with self.column:
            self.undo_timer = ui.timer(UNDO_SECONDS, self.hide_undo, once=True)

    def hide_undo(self) -> None:
        if self.undo_timer is not None:
            self.undo_timer.cancel()
            self.undo_timer = None
        self.toast.set_visibility(False)

    async def undo(self) -> None:
        self.hide_undo()
        self.editor.drop_pending()

        async def run() -> None:
            self.session.undo_edit()
            self.apply_edited()

        await attempt(run, failed=EDIT_FAILED)


def _team_builder_view(screen_slot: ScreenSlot) -> TeamBuilderView:
    return require_view(screen_slot.view, TeamBuilderView)


def _enabled(view: TeamBuilderView, now: SessionSnapshot) -> bool:
    return not view.edit_lock and now.working_role is None


def _pill(view: TeamBuilderView) -> str:
    if view.edit_lock:
        return "Locked"
    if view.save_lock:
        return "● Draft · saves after the event"
    return "● Unsaved changes" if view.dirty else "✓ Saved"


def _banner(view: TeamBuilderView) -> str:
    if view.edit_lock:
        return f"The team is locked: {view.edit_lock}."
    if view.dirty:
        return "Unsaved team changes. They wait here until you save or discard them."
    return "Build, tune and save the team you register for events."


def _first_wrong_field(slot: TeamBuilderSlot) -> TeamBuilderField | None:
    return next((each for each in slot.fields if each.error), None)


def _first_error(slot: TeamBuilderSlot) -> str:
    return slot.error or next((each.error for each in slot.fields if each.error), "")
