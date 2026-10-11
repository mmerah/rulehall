from collections.abc import Callable
from typing import cast

from nicegui import app, ui
from nicegui.events import EChartPointClickEventArguments
from pydantic import TypeAdapter

from rulehall.app.game_session import GameSession, SessionSnapshot
from rulehall.core.validation import Slug
from rulehall.core.views import Look, MapNode, MapView
from rulehall.ui import theme
from rulehall.ui.map_layout import MAP_COLUMNS, Cell, map_cells
from rulehall.ui.widgets import section

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
MAP_REGION_BORDER = 2
REMEMBERED_CELLS = TypeAdapter(dict[Slug, tuple[int, int]])


class SceneMap:
    def __init__(self, session: GameSession, prefill: Callable[[str], None]) -> None:
        self.session = session
        self.prefill = prefill
        self.chart: ui.echart | None = None
        # Tab storage, not the save: a reload keeps the layout, and a layout is no game state.
        self.storage = cast("dict[str, object]", app.storage.tab)
        self.cells: dict[Slug, Cell] = {}

    def sync(self, now: SessionSnapshot, drawn: SessionSnapshot) -> None:
        map_view = now.view.map
        drawn_view = drawn.view.map
        if map_view == drawn_view:
            return
        if (
            map_view is not None
            and drawn_view is not None
            and map_view.region_id == drawn_view.region_id
            and self.chart is not None
        ):
            self.place(map_view, self.cells)
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
            remembered = self.storage.get(self.storage_key(map_view), {})
            self.place(map_view, REMEMBERED_CELLS.validate_python(remembered))
            with section(f"Map — {map_view.region_name}"):
                self.chart = map_chart(
                    map_view, self.session.engine.look, self.cells, self.node_clicked
                )

    def storage_key(self, map_view: MapView) -> str:
        return f"map:{self.session.key.save_id}:{map_view.region_id}"

    def place(self, map_view: MapView, remembered: dict[Slug, Cell]) -> None:
        self.cells = map_cells(map_view, remembered)
        self.storage[self.storage_key(map_view)] = self.cells

    def node_clicked(self, index: int) -> None:
        map_view = self.session.player_view().map
        nodes = () if map_view is None else map_view.nodes
        if index < len(nodes) and (words := nodes[index].prefill):
            self.prefill(words)


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
    unexplored_ids = {node.id for node in view.nodes if node.kind == "unexplored"}
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
    is_region = node.kind == "region"
    width, height = MAP_STUB_SIZE if node.kind == "unexplored" else MAP_ROOM_SIZE
    ink = (
        "game-bg" if here else "game-muted" if node.kind in ("seen", "unexplored") else "game-text"
    )
    border = "game-accent" if here else "game-text" if is_region else "game-muted"
    # NiceGUI's point click reads args['value'] unguarded; every node and link must carry one.
    # The id, not the name, keys a node: every unexplored way is named "???".
    return {
        "id": node.id,
        "name": node.name,
        "value": [cell[0] + 0.5, cell[1] + 0.5],
        "symbol": "rect" if is_region else "roundRect",
        "symbolSize": [width, height],
        "itemStyle": {
            "color": colours["game-accent" if here else "game-surface"],
            "borderColor": colours[border],
            "borderWidth": MAP_REGION_BORDER if is_region else 1,
            "borderType": "solid" if node.kind in ("visited", "region") else "dashed",
        },
        "label": {
            "color": colours[ink],
            "width": width - MAP_LABEL_INSET,
            "fontWeight": MAP_HERE_WEIGHT if here else MAP_WEIGHT,
            "fontStyle": "italic" if is_region else "normal",
        },
    }
