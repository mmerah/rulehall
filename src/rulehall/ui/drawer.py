from collections.abc import Callable
from functools import partial
from pathlib import Path

from nicegui import ui
from nicegui.events import EChartPointClickEventArguments

from rulehall.app.game_session import GameSession, SessionSnapshot
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
from rulehall.ui.panel_parts import panel_row
from rulehall.ui.widgets import PASS_THROUGH, heading, icon_button, section

JOURNAL_TAB = "Journal"
# Not the header's `menu_book`: two buttons with one icon make every icon locator ambiguous.
TAB_ICONS = {SCENE_TAB: "sym_r_map", JOURNAL_TAB: "sym_r_history_edu"}
PANEL_TAB_ICON = "sym_r_backpack"


class SceneMap:
    def __init__(self, session: GameSession, prefill: Callable[[str], None]) -> None:
        self.session = session
        self.prefill = prefill
        self.chart: ui.echart | None = None

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        map_view = now.view.map
        if map_view == drawn.view.map:
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
                self.chart = map_chart(map_view, self.session.engine.look, self.node_clicked)

    def node_clicked(self, index: int) -> None:
        map_view = self.session.player_view().map
        nodes = () if map_view is None else map_view.nodes
        if index < len(nodes) and (words := nodes[index].prefill):
            self.prefill(words)


class DrawerTab:
    def __init__(
        self, session: GameSession, name: str, open_row: Callable[[PanelRow], None]
    ) -> None:
        self.session = session
        self.name = name
        self.open_row = open_row
        self.icons: dict[Slug, Sprite | Path | None] = {}

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        if self.contents(now.view) != self.contents(drawn.view):
            self.draw_panels.refresh(now.view)

    def sync_icons(self, view: PlayerView) -> None:
        if any(self.session.icon(subject_id) != icon for subject_id, icon in self.icons.items()):
            self.draw_panels.refresh(view)

    def contents(self, view: PlayerView) -> tuple[Panel, ...]:
        return tuple(panel for panel in view.panels if panel.tab == self.name)

    @ui.refreshable_method
    def draw_panels(self, view: PlayerView) -> None:
        self.icons = {}
        for panel in self.contents(view):
            with section(panel.title):
                if not panel.rows:
                    ui.label("nothing").classes("text-sm opacity-60")
                for row in panel.rows:
                    panel_row(row, self.recorded_icon, self.open_row)

    def recorded_icon(self, subject_id: Slug) -> Sprite | Path | None:
        self.icons[subject_id] = icon = self.session.icon(subject_id)
        return icon


class Journal:
    def __init__(self, now: SessionSnapshot) -> None:
        heading("Chronicle")
        self.entries = ui.element("div").style(PASS_THROUGH)
        self.redraw(now.log_entries)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        history = now.log_entries
        appended = transcript.appended_since(history, drawn.log_entries)
        if appended is None:
            self.redraw(history)
            return
        first = len(history) - len(appended) + 1
        with self.entries:
            for number, entry in enumerate(appended, start=first):
                _ = _journal_entry(number, entry).move(target_index=0)

    def redraw(self, history: tuple[LogEntry, ...]) -> None:
        self.entries.clear()
        with self.entries:
            for number, entry in reversed(list(enumerate(history, start=1))):
                _ = _journal_entry(number, entry)


class Drawer:
    def __init__(
        self,
        session: GameSession,
        view: PlayerView,
        open_row: Callable[[PanelRow], None],
        prefill: Callable[[str], None],
    ) -> None:
        names = dict.fromkeys((SCENE_TAB, *(panel.tab for panel in view.panels)))
        self.tabs = tuple(DrawerTab(session, name, open_row) for name in names)
        self.names = (*names, JOURNAL_TAB)
        self.scene_map = SceneMap(session, prefill)
        self.journal: Journal
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
                    ui.tabs(on_change=lambda event: self.mark_rail(str(event.value)))
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
                        tab.draw_panels(now.view)
                with ui.tab_panel(JOURNAL_TAB), ui.scroll_area().classes("w-full h-full"):
                    self.journal = Journal(now)

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        if now.view is not drawn.view:
            self.scene_map.sync(now, drawn)
            for tab in self.tabs:
                tab.sync(now, drawn)
        self.journal.sync(now, drawn)

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


def map_chart(view: MapView, look: Look | None, pick: Callable[[int], None]) -> ui.echart:
    def clicked(event: EChartPointClickEventArguments) -> None:
        if event.data_type == "node":
            pick(event.data_index)

    # Inline, not a class: a hidden tab's chart falls back to its inline size, and a zero throws.
    return ui.echart(map_options(view, look), on_point_click=clicked).style(
        "width: 100%; height: 16rem"
    )


def map_options(view: MapView, look: Look | None) -> dict[str, object]:
    colours = theme.palette(look)
    index = {node.id: at for at, node in enumerate(view.nodes)}
    # NiceGUI's point click reads args['value'] unguarded; every node and link must carry one.
    nodes = [
        {
            "name": node.name,
            "value": node.id,
            "symbolSize": 18 if node.id == view.here_id else 12,
            "itemStyle": _map_style(node, view.here_id, colours),
            "label": _map_style(node, view.here_id, colours),
        }
        for node in view.nodes
    ]
    links = [
        {
            "source": index[edge.from_id],
            "target": index[edge.to_id],
            "value": 0,
            "lineStyle": {"type": "dashed" if edge.locked else "solid"},
        }
        for edge in view.edges
    ]
    series = {
        "type": "graph",
        "layout": "force",
        "roam": "move",
        "force": {
            "initLayout": "circular",
            "repulsion": 300,
            "edgeLength": 100,
            "layoutAnimation": False,
        },
        "label": {"show": True, "position": "right", "fontFamily": colours["game-body"]},
        "lineStyle": {"color": colours["game-muted"], "opacity": 0.6, "width": 2},
        "data": nodes,
        "links": links,
    }
    return {"animation": False, "series": [series]}


def _map_style(node: MapNode, here_id: Slug, colours: dict[str, str]) -> dict[str, str | float]:
    fill = "game-accent" if node.id == here_id else "game-text" if node.visited else "game-muted"
    return {"color": colours[fill], "opacity": 1 if node.visited else 0.5}


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
