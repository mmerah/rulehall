from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Literal, cast

from nicegui import app, ui
from nicegui.events import GenericEventArguments, KeyEventArguments, ValueChangeEventArguments
from pydantic import Field, TypeAdapter

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.config import read_settings, save_settings
from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Frozen, Refusal, Slug, parse
from rulehall.core.views import Sprite, Surface, require_view
from rulehall.engines.pokemon.champions.args import (
    MoveSlotEdit,
    PasteEdit,
    PickEdit,
    PointsEdit,
    SlotEdit,
    TeamEdit,
)
from rulehall.engines.pokemon.champions.data import champions_data
from rulehall.engines.pokemon.champions.panels import team_option
from rulehall.engines.pokemon.champions.paste import export_paste
from rulehall.engines.pokemon.champions.pending import ABILITY, ITEM, MOVES, NATURE, SPECIES
from rulehall.engines.pokemon.champions.team_builder import (
    SLOT_CATALOGS,
    TEAM_BUILDER_SURFACE_ID,
    TEMPLATES_CATALOG,
    import_preview,
    team_builder_catalog,
    team_builder_view,
)
from rulehall.engines.pokemon.champions.views import (
    Advice,
    Catalog,
    Choice,
    ImportPreview,
    PickField,
    PointsField,
    TeamBuilderField,
    TeamBuilderSlot,
    TeamBuilderView,
)
from rulehall.engines.pokemon.champions.world import ChampionsWorld
from rulehall.engines.pokemon.sprites import item_sprite
from rulehall.screens.pokemon.catalog_picker import CatalogPicker
from rulehall.screens.pokemon.points_editor import PointsEditor
from rulehall.ui.panel_parts import avatar, choice_button, tag_row
from rulehall.ui.surfaces import ScreenHost
from rulehall.ui.widgets import (
    Confirm,
    alert,
    attempt,
    done,
    entered_text,
    failure_notice,
    heading,
    help_tip,
    icon_button,
    media_url,
)

type Pane = Literal["slot", "moves", "points", "tips"]

PANE = TypeAdapter[Pane](Pane)
EDIT_FAILED = failure_notice("The team was not changed.")
UNDO_SECONDS = 8.0
SAVE_KEY = "Ctrl + S"
SAVE_WAITS = "Save waits for the end of the event."
MOVE_KEYS = ("q", "w", "e", "r")
FIELD_KEYS = {SPECIES: "s", ITEM: "i", ABILITY: "a", NATURE: "n", MOVES: "m"}
WIDE_PANES: dict[Pane, str] = {"slot": "Slot", "tips": "Tips"}
PHONE_PANES: dict[Pane, str] = {"slot": "Set", "moves": "Moves", "points": "Points", "tips": "Tips"}
SEVERITY_ICONS = {
    "info": "sym_r_info",
    "warning": "sym_r_warning",
    "error": "sym_r_error",
    "good": "sym_r_check_circle",
}
SEVERITY_WORDS = {"info": "Note", "warning": "Warning", "error": "Error", "good": "Good"}
KEY_MAP = (
    ("1 to 6", "Select a slot"),
    ("[  ]", "Previous or next slot"),
    ("s", "Choose the species"),
    ("i", "Choose the item"),
    ("a", "Choose the ability"),
    ("n", "Choose the nature"),
    ("m", "Add a move, or pick the one it replaces"),
    ("q w e r", "Choose move 1, 2, 3 or 4"),
    ("p", "Go to the presets"),
    ("Alt + ↑ ↓", "Move the focused slot up or down"),
    ("Ctrl + S", "Save the team"),
    ("Ctrl + Shift + V", "Import a paste"),
    ("Ctrl + Shift + C", "Export the team"),
    ("/", "Search in an open list"),
    ("↑ ↓  Enter  Esc", "Move, pick, close in a list"),
    ("← →", "Stat points ±1 on a focused stepper, or the slider in Expert"),
    ("Shift + ← →", "Stat points ±8 there"),
    ("Home  End", "Stat points to 0 or to the most there"),
    ("?", "Show these keys"),
)
EDITING = "game-builder-editing"
ADVICE_FOLDED = "game-builder-advice-folded"
FIRST_PICK = ".game-builder-editor .game-builder-pick"
FIRST_STEPPER = ".game-builder-editor .game-points-invalid .game-points-step"
FOCUS_PRESETS = ".game-builder-presets .q-btn"


class TeamBuilderPlace(Frozen):
    open: bool = False
    slot: int = Field(default=1, ge=1)
    advice: bool = True


class Shortcut(Frozen):
    name: Literal["save", "import", "export"]


class Swipe(Frozen):
    by: Literal[-1, 1]


class TeamBuilderInput(ui.element, component="team_builder_input.js"):
    pass


@dataclass(slots=True)
class CatalogMemo:
    world: ChampionsWorld
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
        self.dragged_slot: int | None = None
        self.dragged_move: int | None = None
        self.previewed = ""
        self.exported = ""
        self.points: PointsEditor | None = None
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
        self.keyboard: ui.keyboard
        self.input: TeamBuilderInput
        self.input_active = False
        self.edit_buttons: list[ui.button] = []
        self.save_buttons: list[ui.button] = []
        self.save_tips: list[ui.tooltip] = []
        self.copy_button: ui.button
        self.import_dialog: ui.dialog
        self.paste: ui.textarea
        self.preview_box: ui.column
        self.replace_button: ui.button
        self.export_dialog: ui.dialog
        self.export_box: ui.textarea
        self.keys_dialog: ui.dialog
        self.replace_dialog: ui.dialog
        self.replace_title: ui.label
        self.replace_box: ui.element

    def build_banner(self) -> None:
        with (
            ui.column().classes(
                "game-card game-decision game-banner w-full game-gap-lg"
            ) as self.banner,
            ui.row().classes("w-full items-center no-wrap game-banner-head game-gap-xl"),
        ):
            ui.icon(self.opener_icon).classes("game-card-icon")
            with ui.column().classes("game-banner-text game-gap-3xs"):
                ui.label("team").classes("game-banner-label")
                self.banner_text = ui.label().classes("game-banner-body")
            with ui.row().classes("items-center no-wrap game-banner-actions game-gap-md"):
                ui.button(self.opener_label, on_click=self.show).props("outline")
        self.banner.set_visibility(False)

    def build(self, now: SessionSnapshot) -> None:
        surface = now.require_surface(TEAM_BUILDER_SURFACE_ID)
        self.view = (
            _team_builder_view(surface)
            if surface.live
            else team_builder_view(_require_champions_world(self.session))
        )
        self.slot = min(self.slot, len(self.view.slots))
        self.enabled = _enabled(self.view, now)
        self.build_dialogs()
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
                        on_click=self.copy_to_pending_team,
                    )
                    .props("outline no-caps")
                    .tooltip("Edit a copy during the event; save it once the event ends.")
                )
                self.copy_button.set_enabled(now.working_role is None)
            self.draw_panes()
            with ui.element("div").classes("game-builder-grid") as self.grid:
                with ui.element("div").classes("game-builder-rail"):
                    self.draw_rail()
                with ui.element("div").classes("game-builder-editor"):
                    self.draw_editor()
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
                    self.save_tips.append(ui.tooltip(SAVE_KEY))
                ui.button("Done", on_click=self.leave_slot).props("color=primary").classes(
                    "game-builder-foot-done"
                )
            with ui.row().classes("items-center no-wrap game-builder-toast game-gap-md") as toast:
                self.toast = toast
                toast.props("role=status aria-live=polite")
                self.toast_text = ui.label()
                ui.button("Undo", on_click=self.undo).props("flat dense no-caps")
            self.toast.set_visibility(False)
            self.keyboard = ui.keyboard(
                self.pressed, active=False, ignore=["input", "textarea", "select"]
            )
            self.input = TeamBuilderInput()
            self.input.on("shortcut", self.shortcut)
            self.input.on("swipe", self.swiped)
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
        surface = now.require_surface(TEAM_BUILDER_SURFACE_ID)
        live = surface.live
        if self.shown and not live:
            self.shown = False
            self.remember()
        self.column.set_visibility(self.shown)
        self.banner.set_visibility(live and not self.shown and now.working_role is None)
        self.copy_button.set_enabled(now.working_role is None)
        self.keyboard.active = self.shown
        if self.input_active != self.shown:
            self.input_active = self.shown
            self.input.props["active"] = self.shown
            self.input.update()
        if live:
            view = _team_builder_view(surface)
            self.apply(view, enabled=_enabled(view, now))

    def apply(self, view: TeamBuilderView, *, enabled: bool) -> None:
        if view is self.view and enabled == self.enabled:
            return
        before, self.view = self.view, view
        if enabled != self.enabled or len(view.slots) != len(before.slots):
            self.enabled = enabled
            self.slot = min(self.slot, len(view.slots))
            self.draw_rail.refresh()
            self.draw_editor.refresh()
            self.draw_advice.refresh()
        else:
            if _cards(view) != _cards(before):
                self.draw_rail.refresh()
            if (old := before.slots[self.slot - 1]) != self.selected:
                self.sync_editor(old, self.selected)
            if view.advice != before.advice:
                self.draw_advice.refresh()
        self.show_state()
        self.input.run_method("refocus")

    def sync_editor(self, old: TeamBuilderSlot, new: TeamBuilderSlot) -> None:
        points = _points_field(new)
        if (
            self.points is not None
            and not self.points.element.is_deleted
            and points is not None
            and _without_points(old) == _without_points(new)
            and self.points.fits(points)
        ):
            self.points.sync(points, enabled=self.enabled)
            self.show_foot()
            return
        self.draw_editor.refresh()

    @property
    def selected(self) -> TeamBuilderSlot:
        return self.view.slots[self.slot - 1]

    @property
    def expert(self) -> bool:
        return self.session.live_settings.current.pokemon.expert_team_builder

    def show_state(self) -> None:
        view = self.view
        self.title.set_text(view.title)
        self.pill.set_text(_pill(view))
        self.pill.classes(
            add="game-builder-pill-dirty" if view.dirty else "",
            remove="" if view.dirty else "game-builder-pill-dirty",
        )
        self.banner_text.set_text(_banner(view))
        self.locked_text.set_text(view.save_lock if view.locked_reason else SAVE_WAITS)
        self.locked.set_visibility(bool(view.save_lock))
        self.copy_button.set_visibility(view.copyable)
        for button in self.edit_buttons:
            button.set_enabled(self.enabled)
        for button in self.save_buttons:
            button.set_enabled(self.enabled and not view.save_lock)
        for tip in self.save_tips:
            tip.set_text(view.save_lock or SAVE_KEY)
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
        points = _points_field(self.selected)
        used = "" if points is None else f"{points.used}/{points.budget} {points.label} · "
        error = _first_error(self.selected)
        self.foot_text.set_text(used + (f"⚠ {error}" if error else "✓ no problems"))

    def draw_head(self) -> None:
        expert = self.expert
        with ui.row().classes("w-full items-center no-wrap game-builder-head game-gap-md"):
            icon_button("sym_r_arrow_back", "Back to the story", self.close)
            with ui.column().classes("game-gap-0 game-builder-heading"):
                self.title = ui.label().classes("game-title game-builder-title")
                self.pill = ui.label().classes("game-builder-pill")
                self.pill.props("role=status aria-live=polite")
            ui.space()
            ui.switch("Expert", value=expert, on_change=self.set_expert).classes(
                "game-builder-expert"
            ).tooltip("Expert shows every slider, number box and hint")
            icon_button("sym_r_keyboard", "Keyboard keys", self.keys_dialog.open).classes(
                "game-builder-keys-button"
            )
        with ui.row().classes("w-full items-center game-builder-tools game-gap-sm"):
            self.edit_buttons += [
                ui.button("Import", icon="sym_r_content_paste", on_click=self.open_import)
                .props("flat no-caps")
                .tooltip("Ctrl + Shift + V"),
                ui.button("Start from…", icon="sym_r_auto_awesome", on_click=self.start_from)
                .props("flat no-caps")
                .tooltip("Load a whole team that won events"),
                ui.button("Discard", icon="sym_r_delete_sweep", on_click=self.discard).props(
                    "flat no-caps"
                ),
            ]
            ui.button("Export", icon="sym_r_ios_share", on_click=self.open_export).props(
                "flat no-caps"
            ).tooltip("Ctrl + Shift + C")
            ui.space()
            save = ui.button("Save team", icon="sym_r_save", on_click=self.save)
            self.save_buttons.append(save.props("color=primary").classes("game-builder-save"))
            with save:
                self.save_tips.append(ui.tooltip(SAVE_KEY))
        self.column.classes("game-builder-expert-on" if expert else "game-builder-simple")

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
    def draw_rail(self) -> None:
        filled = sum(slot.filled for slot in self.view.slots)
        heading(f"Team {filled}/{len(self.view.slots)}")
        with ui.element("div").classes("game-builder-cards"):
            for number, slot in enumerate(self.view.slots, start=1):
                self.draw_card(number, slot)

    def draw_card(self, number: int, slot: TeamBuilderSlot) -> None:
        state = "invalid" if slot.error else "empty" if not slot.filled else "filled"
        classes = f"game-builder-card game-builder-card-{state}"
        selected = number == self.slot
        if selected:
            classes += " game-rail-on"
        name = slot.name if slot.filled else "Empty slot"
        locked = bool(self.view.locked_reason)
        with ui.element("div").classes(classes) as card:
            card.props.update(
                {
                    "tabindex": "0",
                    "role": "button",
                    "aria-label": f"Slot {number}: {name}, {_status_words(slot)}",
                    "data-focus": f"card-{number}",
                    "draggable": "true" if self.enabled else "false",
                }
            )
            if selected:
                card.props["aria-current"] = "true"
            ui.label(str(number)).classes("game-builder-card-number")
            if slot.filled:
                avatar(self._sprite(slot), slot.name)
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
            if locked:
                ui.icon("sym_r_lock").classes("game-builder-card-lock").tooltip(
                    self.view.locked_reason
                )
            else:
                self.draw_card_menu(number, slot)
        chosen = partial(self.select, number)
        card.on("click", chosen).on("keydown.enter", chosen).on("keydown.space.prevent", chosen)
        card.on("keydown.alt.up.prevent", partial(self.move_slot, number, number - 1))
        card.on("keydown.alt.down.prevent", partial(self.move_slot, number, number + 1))
        card.on(
            "dragstart",
            partial(self.drag_slot, number),
            js_handler="(e) => { e.dataTransfer.setData('text/plain', ''); emit(); }",
        )
        card.on("dragover.prevent", js_handler="() => {}")
        card.on("drop.prevent", partial(self.drop_slot, number))

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
        sprite = self.session.find_asset(item_sprite(item.choice_id))
        if sprite is not None:
            image = ui.element("img").classes("game-builder-card-item")
            image.props.update({"src": media_url(sprite.path), "alt": "", "title": item.name})
        if item.choice_id in champions_data().legal.mega_formes:
            ui.label("◆ Mega").classes("game-builder-card-mega").tooltip(
                f"{item.name}: this Pokemon can Mega Evolve"
            )

    @ui.refreshable_method
    def draw_editor(self) -> None:
        slot = self.selected
        count = len(self.view.slots)
        with ui.element("div").classes("w-full game-builder-editor-head"):
            icon_button("sym_r_chevron_left", "Previous slot", partial(self.step_slot, -1))
            if slot.filled:
                avatar(self._sprite(slot), slot.name)
            with ui.column().classes("game-gap-0 game-builder-editor-name"):
                ui.label(slot.name if slot.filled else "Empty slot").classes("game-title")
                with ui.row().classes("items-center game-gap-sm game-builder-editor-sub"):
                    ui.label(f"Slot {self.slot} of {count}").classes("game-hint")
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
        if (points := _points_field(slot)) is not None:
            with ui.column().classes(
                "w-full game-builder-section game-builder-section-points game-gap-md"
            ):
                self.points = PointsEditor(
                    points,
                    partial(self.set_points, self.slot, points.field_id),
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
            icon=None if sprite is None else self.session.find_asset(sprite),
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
                with ui.element("div").classes("game-builder-move") as row:
                    ui.label(MOVE_KEYS[index] if index < len(MOVE_KEYS) else "").classes(
                        "game-builder-move-key"
                    )
                    self.pick_button(pick, index, picked)
                    if picked is not None:
                        icon_button(
                            "sym_r_close",
                            f"Clear {picked.name}",
                            partial(self.clear_move, pick, index),
                        ).props("dense").classes("game-builder-move-clear").set_enabled(
                            self.enabled
                        )
                if picked is not None and self.enabled:
                    row.props("draggable=true")
                    row.on(
                        "dragstart",
                        partial(self.drag_move, index),
                        js_handler="(e) => { e.dataTransfer.setData('text/plain', ''); emit(); }",
                    )
                row.on("dragover.prevent", js_handler="() => {}")
                row.on("drop.prevent", partial(self.drop_move, pick, index))
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
                avatar(self.session.find_asset(picked.sprites[0]), picked.name)
            with ui.column().classes("game-gap-0 game-builder-pick-body"):
                with ui.row().classes("w-full items-center no-wrap game-gap-sm"):
                    ui.label(name).classes(
                        "game-builder-pick-name"
                        + (" game-builder-pick-empty" if picked is None else "")
                    )
                    if picked is not None and picked.tags:
                        tag_row(picked.tags)
                if picked is not None and picked.brief:
                    ui.label(picked.brief).classes("game-builder-pick-brief")
            if picked is not None and picked.badge:
                ui.label(picked.badge).classes("game-builder-badge")
        return button

    def draw_pinned(self, pick: PickField) -> None:
        if not pick.pinned:
            return
        with ui.row().classes("items-center game-builder-pinned game-gap-sm"):
            ui.label("Common" if self.selected.filled else "Suggested").classes("game-hint")
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
                ui.button("Fix", on_click=partial(self.fix, fix)).props(
                    "outline dense no-caps"
                ).set_enabled(self.enabled)

    def build_dialogs(self) -> None:
        with (
            ui.dialog() as self.import_dialog,
            ui.card().classes(
                "game-row-dialog game-builder-dialog game-builder-import game-gap-md"
            ),
        ):
            ui.label("Import a team").classes("game-title game-builder-dialog-title")
            with ui.column().classes("w-full game-builder-dialog-body game-gap-md"):
                ui.label(
                    "Paste a team exported from a team builder, then check it before it replaces "
                    "yours."
                ).classes("game-hint")
                self.paste = (
                    ui.textarea("Team paste", on_change=self.paste_changed)
                    .props(remove="autogrow")
                    .props("rows=8 input-class=game-builder-mono")
                    .classes("w-full")
                )
                self.preview_box = ui.column().classes("w-full game-gap-0")
            with ui.row().classes("w-full justify-end game-builder-dock game-gap-md"):
                ui.button("Cancel", on_click=self.import_dialog.close).props("flat no-caps")
                ui.button("Check", on_click=self.preview).props("outline no-caps")
                self.replace_button = ui.button("Replace team", on_click=self.replace_team)
                self.replace_button.props("color=primary no-caps").set_enabled(False)
        with (
            ui.dialog() as self.export_dialog,
            ui.card().classes("game-row-dialog game-builder-dialog game-gap-md"),
        ):
            ui.label("Export the team").classes("game-title game-builder-dialog-title")
            self.export_box = (
                ui.textarea("Team paste")
                .props(remove="autogrow")
                .props("readonly rows=12 input-class=game-builder-mono")
                .classes("w-full")
            )
            with ui.row().classes("w-full justify-end game-builder-dock game-gap-md"):
                ui.button("Close", on_click=self.export_dialog.close).props("flat no-caps")
                ui.button("Copy", icon="sym_r_content_copy", on_click=self.copy_export).props(
                    "color=primary no-caps"
                )
        with (
            ui.dialog() as self.keys_dialog,
            ui.card().classes("game-row-dialog game-builder-dialog game-gap-md"),
        ):
            ui.label("Keyboard keys").classes("game-title game-builder-dialog-title")
            with ui.element("div").classes("game-builder-keys"):
                for keys, action in KEY_MAP:
                    ui.label(keys).classes("game-builder-key")
                    ui.label(action)
            with ui.row().classes("w-full justify-end"):
                ui.button("Close", on_click=self.keys_dialog.close).props("flat no-caps")
        with (
            ui.dialog() as self.replace_dialog,
            ui.card().classes("game-row-dialog game-gap-md"),
        ):
            self.replace_title = ui.label().classes("game-title game-builder-dialog-title")
            ui.label("A set holds four moves. Pick the one to drop.").classes("game-hint")
            self.replace_box = ui.element("div").classes("game-builder-replace")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=self.replace_dialog.close).props("flat no-caps")

    def dialog_open(self) -> bool:
        return (
            self.picker.open
            or any(
                dialog.value
                for dialog in (
                    self.import_dialog,
                    self.export_dialog,
                    self.keys_dialog,
                    self.replace_dialog,
                )
            )
            or bool(self.confirm.value)
        )

    async def pressed(self, event: KeyEventArguments) -> None:
        modifiers = event.modifiers
        if (
            not event.action.keydown
            or not self.shown
            or self.dialog_open()
            or modifiers.ctrl
            or modifiers.meta
            or modifiers.alt
        ):
            return
        key = event.key.name
        if key.isdecimal() and 1 <= int(key) <= len(self.view.slots):
            await self.select(int(key))
        elif key in ("[", "]"):
            await self.step_slot(-1 if key == "[" else 1)
        elif key in MOVE_KEYS:
            self.open_keyed_field(MOVES, MOVE_KEYS.index(key))
        elif key == "p":
            self.input.run_method("focusFirst", FOCUS_PRESETS)
        elif key == "?":
            self.keys_dialog.open()
        elif field_id := next((each for each, typed in FIELD_KEYS.items() if typed == key), None):
            self.open_keyed_field(field_id, None if field_id == MOVES else 0)

    async def shortcut(self, event: GenericEventArguments) -> None:
        name = parse(Shortcut, event.args).name
        if name == "save":
            await self.save()
        elif name == "import":
            self.open_import()
        else:
            self.open_export()

    async def swiped(self, event: GenericEventArguments) -> None:
        await self.step_slot(parse(Swipe, event.args).by)

    async def select(self, number: int) -> None:
        await self.flush_points()
        self.slot = number
        self.editing = True
        self.grid.classes(EDITING)
        self.remember()
        self.draw_rail.refresh()
        self.draw_editor.refresh()
        self.show_foot()
        self.input.run_method("refocus")

    async def step_slot(self, by: int) -> None:
        await self.select((self.slot - 1 + by) % len(self.view.slots) + 1)

    async def leave_slot(self) -> None:
        await self.flush_points()
        self.editing = False
        self.grid.classes(remove=EDITING)
        self.show_foot()

    async def flush_points(self) -> None:
        if self.points is not None and self.points.pending:
            await self.points.flush()

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

    def open_keyed_field(self, field_id: str, index: int | None) -> None:
        pick = next(
            (
                each
                for each in self.selected.fields
                if isinstance(each, PickField) and each.field_id == field_id
            ),
            None,
        )
        if pick is None or not self.enabled:
            return
        self.open_field(pick, None if index is None else min(index, pick.picks - 1))

    def open_field(self, pick: PickField, index: int | None) -> None:
        try:
            catalog = self.catalog(pick.catalog_id)
        except Refusal as refused:
            alert(str(refused))
            return
        pinned_title = f"Common on {self.selected.name}" if self.selected.filled else "Suggested"
        self.picker.show(
            catalog,
            partial(self.pick, pick, index),
            picked=[choice.choice_id for choice in pick.picked],
            pinned=pick.pinned,
            pinned_title=pinned_title,
        )

    def catalog(self, catalog_id: Slug) -> Catalog:
        world = _require_champions_world(self.session)
        if self.catalog_memo is None or self.catalog_memo.world is not world:
            self.catalog_memo = CatalogMemo(world)
        catalogs = self.catalog_memo.catalogs
        key = (self.slot if catalog_id in SLOT_CATALOGS else None, catalog_id)
        if key not in catalogs:
            catalogs[key] = team_builder_catalog(world, self.slot, catalog_id)
        return catalogs[key]

    async def pick(self, pick: PickField, index: int | None, choice_id: Slug) -> None:
        current = tuple(choice.choice_id for choice in pick.picked)
        if index is None:
            if choice_id in current:
                return
            index = len(current) if len(current) < pick.picks else await self.ask_replaced(pick)
            if index is None:
                return
        choice_ids = picked_ids(current, index, choice_id)
        if choice_ids == current:
            return
        preset = not self.expert
        placed = preset and pick.field_id == SPECIES
        await self.edit(
            "pick",
            PickEdit(slot=self.slot, field_id=pick.field_id, choice_ids=choice_ids, preset=preset),
            undo="Placed with its top preset." if placed else "",
        )

    async def ask_replaced(self, pick: PickField) -> int | None:
        self.replace_title.set_text(f"Replace which {pick.label.lower().removesuffix('s')}?")
        self.replace_box.clear()
        with self.replace_box:
            for index, choice in enumerate(pick.picked):
                ui.button(choice.name, on_click=partial(self.replace_dialog.submit, index)).props(
                    "outline no-caps"
                ).classes("game-builder-pick")
        chosen: object = await self.replace_dialog
        return chosen if isinstance(chosen, int) else None

    async def clear_move(self, pick: PickField, index: int) -> None:
        current = tuple(choice.choice_id for choice in pick.picked)
        await self.edit(
            "pick",
            PickEdit(
                slot=self.slot,
                field_id=pick.field_id,
                choice_ids=current[:index] + current[index + 1 :],
            ),
        )

    def drag_move(self, index: int) -> None:
        self.dragged_move = index

    async def drop_move(self, pick: PickField, index: int) -> None:
        start, self.dragged_move = self.dragged_move, None
        current = tuple(choice.choice_id for choice in pick.picked)
        if start is None or start == index or index >= len(current):
            return
        await self.edit(
            "pick",
            PickEdit(
                slot=self.slot, field_id=pick.field_id, choice_ids=moved(current, start, index)
            ),
        )

    async def set_points(self, slot: int, field_id: Slug, row: int, points: int) -> bool:
        return await self.edit(
            "set_points", PointsEdit(slot=slot, field_id=field_id, row=row, points=points)
        )

    async def apply_choice(self, choice: Choice) -> None:
        if choice.option is not None:
            await self.play(choice.option, undo=f"{choice.name} applied.")

    async def move_slot(self, number: int, target: int) -> None:
        if not 1 <= target <= len(self.view.slots) or target == number:
            return
        if await self.edit("move_slot", MoveSlotEdit(slot=number, to_slot=target)):
            await self.select(target)

    async def clear_slot(self, number: int) -> None:
        await self.edit("clear_slot", SlotEdit(slot=number), undo=f"Slot {number} cleared.")

    def drag_slot(self, number: int) -> None:
        self.dragged_slot = number

    async def drop_slot(self, number: int) -> None:
        start, self.dragged_slot = self.dragged_slot, None
        if start is not None:
            await self.move_slot(start, number)

    async def fix(self, option: ActionOption) -> None:
        await self.play(option, undo="Fixed.")

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
        wrong = _first_wrong_field(self.selected)
        if isinstance(wrong, PointsField):
            self.show_pane("points")
            self.input.run_method("focusFirst", FIRST_STEPPER)
            return
        self.show_pane("moves" if wrong is not None and wrong.picks > 1 else "slot")
        target = (
            FIRST_PICK
            if wrong is None
            else f'.game-builder-editor [data-focus="pick-{wrong.field_id}-0"]'
        )
        self.input.run_method("focusFirst", target)

    async def discard(self) -> None:
        if not self.view.pending_team_open:
            return
        if not self.view.dirty or await self.confirm.ask(
            "Discard every unsaved change to the team?"
        ):
            await self.edit("discard")

    def open_import(self) -> None:
        if not self.enabled:
            return
        self.paste.value = ""
        self.paste_changed()
        self.import_dialog.open()

    def paste_changed(self) -> None:
        self.preview_box.clear()
        self.replace_button.set_enabled(False)

    def preview(self) -> None:
        text = entered_text(self.paste)
        self.paste_changed()
        if not text:
            return
        try:
            preview = import_preview(_require_champions_world(self.session), text)
        except Refusal as refused:
            alert(str(refused))
            return
        self.previewed = text
        with self.preview_box:
            self.draw_preview(preview)
        self.replace_button.set_enabled(preview.importable)

    def draw_preview(self, preview: ImportPreview) -> None:
        for row in preview.rows:
            with ui.element("div").classes("w-full game-builder-preview"):
                avatar(self._sprite(row), row.name)
                with ui.column().classes("game-gap-0 game-builder-card-body"):
                    with ui.row().classes("items-center no-wrap game-gap-sm"):
                        ui.label(row.name).classes("game-builder-card-name")
                        if row.tags:
                            tag_row(row.tags)
                    ui.label(row.error or row.brief).classes(
                        "game-builder-field-error" if row.error else "game-builder-card-brief"
                    )
                ui.label("⚠ fix" if row.error else "✓ ok").classes(
                    "game-builder-status "
                    + ("game-builder-status-invalid" if row.error else "game-builder-status-ready")
                )
        for note in preview.notes:
            ui.label(note).classes("game-hint game-builder-preview-note")

    async def replace_team(self) -> None:
        if self.view.dirty and not await self.confirm.ask(
            "Replace your unsaved team with the paste?"
        ):
            return
        if await self.edit("import_text", PasteEdit(text=self.previewed), undo="Team imported."):
            self.import_dialog.close()

    def open_export(self) -> None:
        self.exported = self.export_text()
        self.export_box.value = self.exported
        self.export_dialog.open()

    def copy_export(self) -> None:
        ui.clipboard.write(self.exported)
        done("Copied.")

    async def copy_to_pending_team(self) -> None:
        await self.edit("copy_registered_team", undo="Draft opened.")

    def export_text(self) -> str:
        return export_paste(_require_champions_world(self.session).shown_team().slots)

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

    def set_expert(self, event: ValueChangeEventArguments[bool | None]) -> None:
        expert = event.value is True
        save_settings({("pokemon", "expert_team_builder"): "true" if expert else "false"})
        live = self.session.live_settings
        live.current = read_settings().model_copy(update={"server": live.current.server})
        self.column.classes(
            add="game-builder-expert-on" if expert else "game-builder-simple",
            remove="game-builder-simple" if expert else "game-builder-expert-on",
        )

    async def edit(self, edit: TeamEdit, args: Frozen | None = None, *, undo: str = "") -> bool:
        return await self.play(team_option(edit, args), undo=undo)

    async def play(self, option: ActionOption, *, undo: str = "") -> bool:
        self.hide_undo()
        await self.flush_points()

        async def run() -> None:
            self.session.edit(option)
            self.apply_edited()

        played = await attempt(run, failed=EDIT_FAILED)
        if played and undo:
            self.offer_undo(undo)
        return played

    def apply_edited(self) -> None:
        now = self.session.snapshot()
        view = _team_builder_view(now.require_surface(TEAM_BUILDER_SURFACE_ID))
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
        if self.points is not None:
            self.points.drop_pending()

        async def run() -> None:
            self.session.undo_edit()
            self.apply_edited()

        await attempt(run, failed=EDIT_FAILED)

    def _sprite(self, slot: TeamBuilderSlot) -> Sprite | None:
        return None if slot.sprite is None else self.session.find_asset(slot.sprite)


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


def moved(ids: Sequence[Slug], start: int, end: int) -> tuple[Slug, ...]:
    reordered = list(ids)
    reordered.insert(end, reordered.pop(start))
    return tuple(reordered)


def _require_champions_world(session: GameSession) -> ChampionsWorld:
    world = session.state.world
    if not isinstance(world, ChampionsWorld):
        raise TypeError(f"the team builder edits a ChampionsWorld, not {type(world).__name__}")
    return world


def _team_builder_view(surface: Surface) -> TeamBuilderView:
    return require_view(surface.view, TeamBuilderView)


def _enabled(view: TeamBuilderView, now: SessionSnapshot) -> bool:
    return not view.locked_reason and now.working_role is None


def _pill(view: TeamBuilderView) -> str:
    if view.locked_reason:
        return "Locked"
    if view.save_lock:
        return "● Draft · saves after the event"
    return "● Unsaved changes" if view.dirty else "✓ Saved"


def _banner(view: TeamBuilderView) -> str:
    if view.copyable:
        return "The team is locked for the event. Copy it to a draft to plan changes."
    if view.locked_reason:
        return f"The team is locked: {view.locked_reason}."
    if view.save_lock:
        return "A draft of the team waits here. Save it once the event ends."
    if view.dirty:
        return "Unsaved team changes. They wait here until you save or discard them."
    return "Build, tune and save the team you register for events."


def _cards(view: TeamBuilderView) -> tuple[object, ...]:
    return (
        view.locked_reason,
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


def _points_field(slot: TeamBuilderSlot) -> PointsField | None:
    return next((each for each in slot.fields if isinstance(each, PointsField)), None)


def _without_points(slot: TeamBuilderSlot) -> TeamBuilderSlot:
    return slot.model_copy(
        update={"fields": tuple(f for f in slot.fields if not isinstance(f, PointsField))}
    )


def _first_wrong_field(slot: TeamBuilderSlot) -> TeamBuilderField | None:
    return next((each for each in slot.fields if each.error), None)


def _first_error(slot: TeamBuilderSlot) -> str:
    return slot.error or next((each.error for each in slot.fields if each.error), "")


def _field_classes(pick: PickField) -> str:
    return "w-full game-builder-field" + (" game-builder-field-invalid" if pick.error else "")
