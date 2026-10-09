from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from nicegui import ui

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Slug
from rulehall.core.views import (
    SCENE_TAB,
    Panel,
    PanelRow,
    PlayerView,
    Sprite,
)
from rulehall.ui.composer import composer_lock
from rulehall.ui.panel_parts import PickOption, panel_row
from rulehall.ui.scene_map import SceneMap
from rulehall.ui.surfaces import Screen
from rulehall.ui.widgets import icon_button, section

SCENE_TAB_ICON = "sym_r_map"
PANEL_TAB_ICON = "sym_r_backpack"
PHONE_WIDTH = 600


class PanelSection:
    def __init__(
        self,
        session: GameSession,
        panel: Panel,
        open_row: Callable[[PanelRow], None],
        pick: PickOption,
        *,
        enabled: bool,
    ) -> None:
        self.session = session
        self.panel = panel
        self.open_row = open_row
        self.pick = pick
        self.enabled = enabled
        self.choices: list[tuple[ui.button, ActionOption]] = []
        self.icons: dict[Slug, Sprite | Path | None] = {}
        self.draw()

    def sync(self, panel: Panel, *, enabled: bool) -> None:
        redraw = panel != self.panel
        self.panel, self.enabled = panel, enabled
        if redraw:
            self.draw.refresh()
        else:
            self.enable_choices()

    def sync_icons(self) -> None:
        if any(self.session.icon(subject_id) != icon for subject_id, icon in self.icons.items()):
            self.draw.refresh()

    @ui.refreshable_method
    def draw(self) -> None:
        self.icons = {}
        self.choices = []
        with section(self.panel.title, help=self.panel.help):
            if not self.panel.rows:
                ui.label("nothing").classes("text-sm opacity-60")
            for row in self.panel.rows:
                self.choices += panel_row(row, self.recorded_icon, self.open_row, self.pick)
        self.enable_choices()

    def enable_choices(self) -> None:
        for button, option in self.choices:
            button.set_enabled(self.enabled and not option.refusal)

    def recorded_icon(self, subject_id: Slug) -> Sprite | Path | None:
        self.icons[subject_id] = icon = self.session.icon(subject_id)
        return icon


class DrawerTab:
    def __init__(
        self,
        session: GameSession,
        name: str,
        open_row: Callable[[PanelRow], None],
        pick: PickOption,
    ) -> None:
        self.session = session
        self.name = name
        self.open_row = open_row
        self.pick = pick
        self.sections: list[PanelSection] = []

    def sync(self, view: PlayerView, *, enabled: bool) -> None:
        panels = self.contents(view)
        if [panel.title for panel in panels] != [each.panel.title for each in self.sections]:
            self.draw_panels.refresh(view, enabled=enabled)
            return
        for each, panel in zip(self.sections, panels, strict=True):
            each.sync(panel, enabled=enabled)

    def sync_icons(self) -> None:
        for each in self.sections:
            each.sync_icons()

    def contents(self, view: PlayerView) -> tuple[Panel, ...]:
        return tuple(panel for panel in view.panels if panel.tab == self.name)

    @ui.refreshable_method
    def draw_panels(self, view: PlayerView, *, enabled: bool) -> None:
        self.sections = [
            PanelSection(self.session, panel, self.open_row, self.pick, enabled=enabled)
            for panel in self.contents(view)
        ]


class Drawer:
    def __init__(
        self,
        session: GameSession,
        view: PlayerView,
        open_row: Callable[[PanelRow], None],
        pick: PickOption,
        prefill: Callable[[str], None],
        open_surface: Callable[[Slug], None],
        screens: Mapping[Slug, Screen],
    ) -> None:
        names = dict.fromkeys((SCENE_TAB, *(panel.tab for panel in view.panels)))
        self.session = session
        self.tabs = tuple(DrawerTab(session, name, open_row, pick) for name in names)
        self.prefill = prefill
        self.open_surface = open_surface
        self.screens = screens
        self.openers: dict[Slug, ui.button] = {}
        self.scene_map = SceneMap(session, self.prefill_from_map)
        self.rail_buttons: dict[str, ui.button] = {}
        self.side: ui.right_drawer
        self.tab_bar: ui.tabs

    def build_rail(self) -> None:
        with ui.column().classes("game-rail h-full items-center q-pt-md game-gap-md"):
            for tab in self.tabs:
                name = tab.name
                icon = tab_icon(name)
                self.rail_buttons[name] = (
                    ui.button(name, icon=icon, on_click=partial(self.show_tab, name))
                    .props("flat")
                    .classes("game-rail-btn")
                )
        self.mark_rail(SCENE_TAB)

    def build(self, now: SessionSnapshot) -> None:
        self.side = ui.right_drawer(value=None).props("width=420").classes("game-drawer")
        with self.side, ui.column().classes("game-panel game-drawer-panel game-gap-0"):
            with ui.row().classes("w-full items-center no-wrap game-drawer-head game-gap-md"):
                with (
                    ui.tabs(on_change=lambda event: self.mark_rail(str(event.value)))
                    .classes("flex-grow game-segmented")
                    .props("inline-label no-caps") as self.tab_bar
                ):
                    for tab in self.tabs:
                        ui.tab(tab.name, icon=tab_icon(tab.name))
                icon_button("sym_r_close", "Close", self.side.hide).classes("lt-sm")
            with ui.tab_panels(self.tab_bar, value=SCENE_TAB).classes("w-full flex-grow"):
                for tab in self.tabs:
                    with (
                        ui.tab_panel(tab.name),
                        ui.scroll_area().classes("w-full h-full"),
                        ui.column().classes("w-full game-gap-xl"),
                    ):
                        if tab.name == SCENE_TAB:
                            self.scene_map.draw(now.view.map)
                        for surface in now.surfaces:
                            if surface.tab == tab.name:
                                self.draw_opener(surface.surface_id)
                        tab.draw_panels(now.view, enabled=choosing(now))
        self.enable_openers(now)

    def draw_opener(self, surface_id: Slug) -> None:
        screen = self.screens[surface_id]

        def opened() -> None:
            self.open_surface(surface_id)
            self.hide_on_phone()

        self.openers[surface_id] = (
            ui.button(screen.opener_label, icon=screen.opener_icon, on_click=opened)
            .props("outline")
            .classes("w-full")
        )

    def enable_openers(self, now: SessionSnapshot) -> None:
        for surface in now.surfaces:
            opener = self.openers.get(surface.surface_id)
            if opener is not None and opener.enabled != surface.live:
                opener.set_enabled(surface.live)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        self.enable_openers(now)
        enabled = choosing(now)
        if now.view is not drawn.view or enabled != choosing(drawn):
            self.scene_map.sync(now, drawn)
            for tab in self.tabs:
                tab.sync(now.view, enabled=enabled)

    def sync_icons(self) -> None:
        for tab in self.tabs:
            tab.sync_icons()

    def toggle(self) -> None:
        self.side.toggle()

    def prefill_from_map(self, words: str) -> None:
        self.prefill(words)
        self.hide_on_phone()

    def hide_on_phone(self) -> None:
        ui.run_javascript(f"if (innerWidth < {PHONE_WIDTH}) getElement({self.side.id}).hide()")

    def show_tab(self, name: str) -> None:
        self.tab_bar.set_value(name)
        self.side.show()

    def mark_rail(self, active: str) -> None:
        for name, button in self.rail_buttons.items():
            button.classes(add="game-rail-on" if name == active else "", remove="game-rail-on")


def tab_icon(name: str) -> str:
    return SCENE_TAB_ICON if name == SCENE_TAB else PANEL_TAB_ICON


def choosing(now: SessionSnapshot) -> bool:
    return not now.held_elsewhere and composer_lock(now) is None
