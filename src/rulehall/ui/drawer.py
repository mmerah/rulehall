from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import cast

from nicegui import app, ui
from nicegui.events import EChartPointClickEventArguments
from pydantic import TypeAdapter

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.decisions import ActionOption
from rulehall.core.log import LogEntry
from rulehall.core.validation import Slug
from rulehall.core.views import (
    SCENE_TAB,
    Look,
    MapNode,
    MapView,
    Panel,
    PanelRow,
    PlayerView,
    Sprite,
)
from rulehall.ui import theme, transcript
from rulehall.ui.composer import composer_lock
from rulehall.ui.map_layout import MAP_COLUMNS, Cell, map_cells
from rulehall.ui.panel_parts import PickOption, panel_row
from rulehall.ui.widgets import PASS_THROUGH, heading, icon_button, section

JOURNAL_TAB = "Journal"
# Not the header's `menu_book`: two buttons with one icon make every icon locator ambiguous.
TAB_ICONS = {SCENE_TAB: "sym_r_map", JOURNAL_TAB: "sym_r_history_edu"}
PANEL_TAB_ICON = "sym_r_backpack"
# The drawer's 420px less its padding, on a desktop and a 390px phone alike.
MAP_WIDTH = 340
MAP_ROW_HEIGHT = 58
MAP_ROOM_SIZE = (MAP_WIDTH // MAP_COLUMNS - 14, 38)
MAP_STUB_SIZE = (40, 22)
MAP_LABEL_INSET = 8
MAP_FONT_SIZE = 11
MAP_LINE_HEIGHT = 12
MAP_WEIGHT = 400
MAP_HERE_WEIGHT = 600
MAP_LINK_OPACITY = 0.6
MAP_LINK_WIDTH = 2
PHONE_WIDTH = 600
REMEMBERED_CELLS = TypeAdapter(dict[Slug, tuple[int, int]])


class SceneMap:
    def __init__(self, session: GameSession, prefill: Callable[[str], None]) -> None:
        self.session = session
        self.prefill = prefill
        self.chart: ui.echart | None = None
        # Tab storage, not the save: a reload keeps the layout, and a layout is no game state.
        self.storage = cast("dict[str, object]", app.storage.tab)
        self.storage_key = f"map:{session.key.save_id}"
        self.cells = REMEMBERED_CELLS.validate_python(self.storage.get(self.storage_key, {}))

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        map_view = now.view.map
        if map_view == drawn.view.map:
            return
        if map_view is not None and self.chart is not None:
            self.place(map_view)
            self.chart.props["options"] = map_options(
                map_view, self.session.engine.look, self.cells
            )
            self.chart.style(map_size(self.cells))
            return
        self.draw.refresh(map_view)

    @ui.refreshable_method
    def draw(self, map_view: MapView | None) -> None:
        self.chart = None
        if map_view is not None:
            self.place(map_view)
            with section("Map"):
                self.chart = map_chart(
                    map_view, self.session.engine.look, self.cells, self.node_clicked
                )

    def place(self, map_view: MapView) -> None:
        self.cells = map_cells(map_view, self.cells)
        self.storage[self.storage_key] = self.cells

    def node_clicked(self, index: int) -> None:
        map_view = self.session.player_view().map
        nodes = () if map_view is None else map_view.nodes
        if index < len(nodes) and (words := nodes[index].prefill):
            self.prefill(words)


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


class Journal:
    def __init__(self, history: tuple[LogEntry, ...]) -> None:
        heading("Chronicle")
        self.entries = ui.element("div").style(PASS_THROUGH)
        self.history: tuple[LogEntry, ...] = ()
        self.sync(history)

    def sync(self, history: tuple[LogEntry, ...]) -> None:
        appended = transcript.appended_since(history, self.history)
        if appended is None:
            self.entries.clear()
            appended = history
        first = len(history) - len(appended) + 1
        with self.entries:
            for number, entry in enumerate(appended, start=first):
                _ = _journal_entry(number, entry).move(target_index=0)
        self.history = history


class Drawer:
    def __init__(
        self,
        session: GameSession,
        view: PlayerView,
        open_row: Callable[[PanelRow], None],
        pick: PickOption,
        prefill: Callable[[str], None],
    ) -> None:
        names = dict.fromkeys((SCENE_TAB, *(panel.tab for panel in view.panels)))
        self.session = session
        self.tabs = tuple(DrawerTab(session, name, open_row, pick) for name in names)
        self.names = (*names, JOURNAL_TAB)
        self.prefill = prefill
        self.scene_map = SceneMap(session, self.prefill_from_map)
        self.journal: Journal | None = None
        self.journal_area: ui.scroll_area
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

    def build(self, now: SessionSnapshot) -> None:
        self.side = ui.right_drawer(value=None).props("width=420").classes("game-drawer")
        with self.side, ui.column().classes("game-panel game-drawer-panel game-gap-0"):
            with ui.row().classes("w-full items-center no-wrap game-drawer-head game-gap-md"):
                with (
                    ui.tabs(on_change=lambda event: self.tab_changed(str(event.value)))
                    .classes("flex-grow game-segmented")
                    .props("inline-label no-caps") as self.tab_bar
                ):
                    for name in self.names:
                        ui.tab(name, icon=TAB_ICONS.get(name, PANEL_TAB_ICON))
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
                        tab.draw_panels(now.view, enabled=choosing(now))
                with ui.tab_panel(JOURNAL_TAB):
                    self.journal_area = ui.scroll_area().classes("w-full h-full")

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        enabled = choosing(now)
        if now.view is not drawn.view or enabled != choosing(drawn):
            self.scene_map.sync(now, drawn)
            for tab in self.tabs:
                tab.sync(now.view, enabled=enabled)
        if self.journal is not None:
            self.journal.sync(now.log_entries)

    def sync_icons(self) -> None:
        for tab in self.tabs:
            tab.sync_icons()

    def toggle(self) -> None:
        self.side.toggle()

    def prefill_from_map(self, words: str) -> None:
        self.prefill(words)
        ui.run_javascript(f"if (innerWidth < {PHONE_WIDTH}) getElement({self.side.id}).hide()")

    def show_tab(self, name: str) -> None:
        self.tab_bar.set_value(name)
        self.side.show()

    def tab_changed(self, name: str) -> None:
        self.mark_rail(name)
        if name == JOURNAL_TAB and self.journal is None:
            with self.journal_area:
                self.journal = Journal(self.session.log_entries())

    def mark_rail(self, active: str) -> None:
        for name, button in self.rail_buttons.items():
            button.classes(add="game-rail-on" if name == active else "", remove="game-rail-on")


def choosing(now: SessionSnapshot) -> bool:
    return not now.held_elsewhere and composer_lock(now) is None


def map_chart(
    view: MapView, look: Look | None, cells: dict[Slug, Cell], pick: Callable[[int], None]
) -> ui.echart:
    def clicked(event: EChartPointClickEventArguments) -> None:
        if event.data_type == "node":
            pick(event.data_index)

    # Inline, not a class: a hidden tab's chart falls back to its inline size, and a zero throws.
    return ui.echart(map_options(view, look, cells), on_point_click=clicked).style(map_size(cells))


def map_size(cells: dict[Slug, Cell]) -> str:
    return f"width: 100%; height: {map_rows(cells) * MAP_ROW_HEIGHT}px"


def map_rows(cells: dict[Slug, Cell]) -> int:
    return 1 + max(row for _, row in cells.values())


def map_options(view: MapView, look: Look | None, cells: dict[Slug, Cell]) -> dict[str, object]:
    colours = theme.palette(look)
    index = {node.id: at for at, node in enumerate(view.nodes)}
    unexplored_ids = {node.id for node in view.nodes if node.unexplored}
    links = [
        {
            "source": index[edge.from_id],
            "target": index[edge.to_id],
            "value": 0,
            "lineStyle": {
                "type": "dashed"
                if edge.locked
                else "dotted"
                if unexplored_ids & {edge.from_id, edge.to_id}
                else "solid"
            },
        }
        for edge in view.edges
    ]
    series = {
        "type": "graph",
        "coordinateSystem": "cartesian2d",
        "layout": "none",
        "symbol": "roundRect",
        "label": {
            "show": True,
            "position": "inside",
            "fontFamily": colours["game-body"],
            "fontSize": MAP_FONT_SIZE,
            "lineHeight": MAP_LINE_HEIGHT,
            "overflow": "break",
        },
        "lineStyle": {
            "color": colours["game-muted"],
            "opacity": MAP_LINK_OPACITY,
            "width": MAP_LINK_WIDTH,
        },
        "data": [_map_node(node, cells[node.id], view.here_id, colours) for node in view.nodes],
        "links": links,
    }
    return {
        "animation": False,
        "grid": {"left": 0, "right": 0, "top": 0, "bottom": 0},
        "xAxis": {"type": "value", "show": False, "min": 0, "max": MAP_COLUMNS},
        "yAxis": {
            "type": "value",
            "show": False,
            "inverse": True,
            "min": 0,
            "max": map_rows(cells),
        },
        "series": [series],
    }


def _map_node(
    node: MapNode, cell: Cell, here_id: Slug, colours: dict[str, str]
) -> dict[str, object]:
    here = node.id == here_id
    width, height = MAP_STUB_SIZE if node.unexplored else MAP_ROOM_SIZE
    ink = "game-bg" if here else "game-text" if node.visited else "game-muted"
    # NiceGUI's point click reads args['value'] unguarded; every node and link must carry one.
    # The id, not the name, keys a node: every unexplored way is named "???".
    return {
        "id": node.id,
        "name": node.name,
        "value": [cell[0] + 0.5, cell[1] + 0.5],
        "symbolSize": [width, height],
        "itemStyle": {
            "color": colours["game-accent" if here else "game-surface"],
            "borderColor": colours["game-accent" if here else "game-muted"],
            "borderWidth": 1,
            "borderType": "solid" if node.visited else "dashed",
        },
        "label": {
            "color": colours[ink],
            "width": width - MAP_LABEL_INSET,
            "fontWeight": MAP_HERE_WEIGHT if here else MAP_WEIGHT,
        },
    }


def _journal_entry(number: int, log_entry: LogEntry) -> ui.expansion:
    title = (
        transcript.CAUSE_LABELS[log_entry.cause] if log_entry.cause is not None else log_entry.words
    )
    with ui.expansion(f"turn {number}: {title}").classes("w-full game-card") as entry:
        for line in log_entry.lines:
            if line.speaker_id is None:
                ui.label(line.text).classes("whitespace-pre-wrap text-sm")
            else:
                with ui.row().classes("items-start no-wrap game-gap-sm"):
                    ui.label(f"{line.speaker}:").classes("font-bold whitespace-nowrap text-sm")
                    ui.label(line.text).classes("whitespace-pre-wrap text-sm")
    return entry
