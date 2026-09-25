from collections.abc import Callable
from functools import partial
from pathlib import Path

from nicegui import ui

from rulehall.app.session import GameService
from rulehall.core.play import Exchange
from rulehall.core.validation import Slug
from rulehall.core.views import SCENE_TAB, MapView, Panel, PanelRow, PlayerView, Sprite, Subject
from rulehall.ui import transcript
from rulehall.ui.widgets import (
    PASS_THROUGH,
    entity_row,
    heading,
    icon_button,
    labeled_value,
    map_chart,
    map_options,
    section,
)

JOURNAL_TAB = "Journal"
# Not the header's `menu_book`: two buttons with one icon make every icon locator ambiguous.
TAB_ICONS = {SCENE_TAB: "sym_r_map", JOURNAL_TAB: "sym_r_history_edu"}
PANEL_TAB_ICON = "sym_r_backpack"


class SceneMap:
    def __init__(self, session: GameService, prefill: Callable[[str], None]) -> None:
        self.session = session
        self.prefill = prefill
        self.chart: ui.echart | None = None

    def sync(self, map_view: MapView | None, drawn: MapView | None) -> None:
        if map_view == drawn:
            return
        if map_view is not None and self.chart is not None:
            self.chart.props["options"] = map_options(map_view, self.session.engine.look)
            return
        self.draw.refresh(map_view)

    @ui.refreshable_method
    def draw(self, map_view: MapView | None) -> None:
        self.chart = None
        if map_view is not None:
            with section("Map"):
                self.chart = map_chart(map_view, self.session.engine.look, self.picked)

    def picked(self, index: int) -> None:
        map_view = self.session.player_view().map
        nodes = () if map_view is None else map_view.nodes
        if index < len(nodes) and (words := nodes[index].prefill):
            self.prefill(words)


class DrawerTab:
    def __init__(
        self, session: GameService, name: str, open_row: Callable[[PanelRow], None]
    ) -> None:
        self.session = session
        self.name = name
        self.open_row = open_row
        self.icons: dict[Slug, Sprite | Path | None] = {}

    def sync(self, view: PlayerView, drawn: PlayerView) -> None:
        if self.contents(view) != self.contents(drawn):
            self.panels.refresh(view)

    def sync_icons(self, view: PlayerView) -> None:
        if any(self.session.icon(subject_id) != icon for subject_id, icon in self.icons.items()):
            self.panels.refresh(view)

    def contents(self, view: PlayerView) -> tuple[Subject, tuple[Panel, ...]]:
        return view.player, tuple(panel for panel in view.panels if panel.tab == self.name)

    @ui.refreshable_method
    def panels(self, view: PlayerView) -> None:
        self.icons = {}
        player, panels = self.contents(view)
        for panel in panels:
            with section(panel.title, classes="game-portrait" if panel.portrait else ""):
                if panel.portrait:
                    entity_row(
                        self.drawn_icon(player.id), player.name, player.brief, alive=player.alive
                    )
                if not panel.rows:
                    ui.label("nothing").classes("text-sm opacity-60")
                for row in panel.rows:
                    panel_row(row, self.drawn_icon, self.open_row)

    def drawn_icon(self, subject_id: Slug) -> Sprite | Path | None:
        self.icons[subject_id] = icon = self.session.icon(subject_id)
        return icon


class Journal:
    def __init__(self) -> None:
        self.entries: ui.element

    def build(self, history: tuple[Exchange, ...]) -> None:
        heading("Chronicle")
        self.entries = ui.element("div").style(PASS_THROUGH)
        self.redraw(history)

    def sync(self, history: tuple[Exchange, ...], drawn: tuple[Exchange, ...]) -> None:
        appended = transcript.appended_since(history, drawn)
        if appended is None:
            self.redraw(history)
            return
        first = len(history) - len(appended) + 1
        with self.entries:
            for number, exchange in enumerate(appended, start=first):
                _ = _journal_entry(number, exchange).move(target_index=0)

    def redraw(self, history: tuple[Exchange, ...]) -> None:
        self.entries.clear()
        with self.entries:
            for number, exchange in reversed(list(enumerate(history, start=1))):
                _ = _journal_entry(number, exchange)


class Drawer:
    def __init__(
        self,
        session: GameService,
        view: PlayerView,
        open_row: Callable[[PanelRow], None],
        prefill: Callable[[str], None],
    ) -> None:
        names = dict.fromkeys((SCENE_TAB, *(panel.tab for panel in view.panels)))
        self.tabs = tuple(DrawerTab(session, name, open_row) for name in names)
        self.names = (*names, JOURNAL_TAB)
        self.scene_map = SceneMap(session, prefill)
        self.journal = Journal()
        self.rail_buttons: dict[str, ui.button] = {}
        self.side: ui.right_drawer
        self.tab_bar: ui.tabs

    def build_rail(self) -> None:
        with ui.column().classes("game-rail h-full items-center q-pt-md game-gap-md"):
            for name in self.names:
                icon = TAB_ICONS.get(name, PANEL_TAB_ICON)
                self.rail_buttons[name] = (
                    ui.button(name, icon=icon, on_click=partial(self.show_tab, name))
                    .props("flat")
                    .classes("game-rail-btn")
                )
        self.mark_rail(SCENE_TAB)

    def build(self, view: PlayerView, history: tuple[Exchange, ...]) -> None:
        self.side = ui.right_drawer(value=None).props("width=420").classes("game-drawer")
        with self.side, ui.column().classes("game-panel game-drawer-panel game-gap-0"):
            with ui.row().classes("w-full items-center no-wrap game-drawer-head game-gap-md"):
                with (
                    ui.tabs(on_change=lambda event: self.mark_rail(str(event.value)))
                    .classes("flex-grow game-segmented")
                    .props("inline-label no-caps") as self.tab_bar
                ):
                    for name in self.names:
                        ui.tab(name, icon=TAB_ICONS.get(name, PANEL_TAB_ICON))
                # Below 600px the drawer covers the header, so it needs its own close button.
                icon_button("sym_r_close", "Close", self.side.hide).classes("lt-sm")
            with ui.tab_panels(self.tab_bar, value=SCENE_TAB).classes("w-full flex-grow"):
                for tab in self.tabs:
                    with (
                        ui.tab_panel(tab.name),
                        ui.scroll_area().classes("w-full h-full"),
                        ui.column().classes("w-full game-gap-xl"),
                    ):
                        if tab.name == SCENE_TAB:
                            self.scene_map.draw(view.map)
                        tab.panels(view)
                with ui.tab_panel(JOURNAL_TAB), ui.scroll_area().classes("w-full h-full"):
                    self.journal.build(history)

    def sync(
        self,
        view: PlayerView,
        history: tuple[Exchange, ...],
        *,
        drawn_view: PlayerView,
        drawn_history: tuple[Exchange, ...],
    ) -> None:
        if view is not drawn_view:
            self.scene_map.sync(view.map, drawn_view.map)
            for tab in self.tabs:
                tab.sync(view, drawn_view)
        self.journal.sync(history, drawn_history)

    def sync_icons(self, view: PlayerView) -> None:
        for tab in self.tabs:
            tab.sync_icons(view)

    def toggle(self) -> None:
        self.side.toggle()

    def show_tab(self, name: str) -> None:
        self.tab_bar.set_value(name)
        self.side.show()

    def mark_rail(self, active: str) -> None:
        for name, button in self.rail_buttons.items():
            button.classes(add="game-rail-on" if name == active else "", remove="game-rail-on")


def panel_row(
    row: PanelRow,
    icon_of: Callable[[Slug], Sprite | Path | None],
    open_row: Callable[[PanelRow], None] | None = None,
) -> None:
    if row.icon_id is not None:
        drawn = entity_row(
            icon_of(row.icon_id),
            row.name,
            row.brief,
            alive=row.alive,
            tags=row.tags,
            meters=row.meters,
        )
    elif row.brief or row.tags or row.meters:
        drawn = labeled_value(row.name, row.brief, tags=row.tags, meters=row.meters)
    else:
        drawn = ui.label(row.name).classes("text-sm")
    if open_row is not None and (row.detail or row.options):
        opened = partial(open_row, row)
        drawn.classes("game-opens").props("tabindex=0 role=button")
        drawn.on("click", opened).on("keydown.enter", opened)
        drawn.on("keydown.space.prevent", opened)
        with drawn:
            ui.icon("sym_r_chevron_right").classes("game-opens-cue")


def _journal_entry(number: int, exchange: Exchange) -> ui.expansion:
    title = (
        transcript.CAUSE_LABELS[exchange.cause] if exchange.cause is not None else exchange.words
    )
    with ui.expansion(f"turn {number}: {title}").classes("w-full game-card") as entry:
        for line in exchange.lines:
            if line.speaker_id is None:
                ui.label(line.text).classes("whitespace-pre-wrap text-sm")
            else:
                with ui.row().classes("items-start no-wrap game-gap-sm"):
                    ui.label(f"{line.speaker}:").classes("font-bold whitespace-nowrap text-sm")
                    ui.label(line.text).classes("whitespace-pre-wrap text-sm")
    return entry
