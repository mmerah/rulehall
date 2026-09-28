from rulehall.core.validation import Slug
from rulehall.core.views import MapView

type Cell = tuple[int, int]
type Line = tuple[Cell, Cell]

MAP_COLUMNS = 3
# A room's half extent in cells: the box the chart draws around a cell's centre.
ROOM_HALF_WIDTH = 0.45
ROOM_HALF_HEIGHT = 0.35
LINE_THROUGH_ROOM_COST = 100
CROSSING_COST = 30
DISTANCE_COST = 10
# Steps from the anchor, best first; the anchor itself is free only when no neighbour is placed.
PREFERRED_STEPS = (
    (0, 0),
    (0, 1),
    (1, 0),
    (-1, 0),
    (1, 1),
    (-1, 1),
    (0, 2),
    (0, -1),
    (1, -1),
    (-1, -1),
)


def map_cells(view: MapView, remembered: dict[Slug, Cell]) -> dict[Slug, Cell]:
    linked: dict[Slug, list[Slug]] = {node.id: [] for node in view.nodes}
    for edge in view.edges:
        linked[edge.from_id].append(edge.to_id)
        linked[edge.to_id].append(edge.from_id)
    cells = {node.id: remembered[node.id] for node in view.nodes if node.id in remembered}
    lines = [(cells[a], cells[b]) for a in cells for b in linked[a] if b in cells and a < b]
    for node in view.nodes:
        if node.id in cells:
            continue
        taken = set(cells.values())
        last_row = max((row for _, row in taken), default=-1)
        placed = [cells[other_id] for other_id in linked[node.id] if other_id in cells]
        anchor = placed[0] if placed else (MAP_COLUMNS // 2, last_row + 1)
        # Only rows near the neighbours and the map's bottom are searched, so a big map stays fast.
        near_rows = {row for _, row in (anchor, *placed)} | {last_row}
        rows = {
            row
            for near_row in near_rows
            for row in range(near_row - 2, near_row + 3)
            if 0 <= row <= last_row + 2
        }
        free = [
            (column, row)
            for row in sorted(rows)
            for column in range(MAP_COLUMNS)
            if (column, row) not in taken
        ]
        cells[node.id] = min(free, key=lambda cell: _cost(cell, anchor, placed, taken, lines))
        lines += [(cells[node.id], other) for other in placed]
    return cells


def _cost(cell: Cell, anchor: Cell, placed: list[Cell], taken: set[Cell], lines: list[Line]) -> int:
    new_lines = [(cell, other) for other in placed]
    through = sum(_passes_through(line, room) for line in new_lines for room in taken)
    through += sum(_passes_through(line, cell) for line in lines)
    crossings = sum(_crosses(new, old) for new in new_lines for old in lines)
    distance = sum(max(abs(cell[0] - column), abs(cell[1] - row)) for column, row in placed)
    step = (cell[0] - anchor[0], cell[1] - anchor[1])
    preference = PREFERRED_STEPS.index(step) if step in PREFERRED_STEPS else len(PREFERRED_STEPS)
    return (
        LINE_THROUGH_ROOM_COST * through
        + CROSSING_COST * crossings
        + DISTANCE_COST * distance
        + preference
    )


def _passes_through(line: Line, room: Cell) -> bool:
    (ax, ay), (bx, by) = line
    x, y = room
    if room in line or not (
        min(ax, bx) - ROOM_HALF_WIDTH <= x <= max(ax, bx) + ROOM_HALF_WIDTH
        and min(ay, by) - ROOM_HALF_HEIGHT <= y <= max(ay, by) + ROOM_HALF_HEIGHT
    ):
        return False
    sides = {
        _side(line[0], line[1], (x + dx, y + dy))
        for dx in (-ROOM_HALF_WIDTH, ROOM_HALF_WIDTH)
        for dy in (-ROOM_HALF_HEIGHT, ROOM_HALF_HEIGHT)
    }
    return not (sides == {1} or sides == {-1})


def _crosses(first: Line, second: Line) -> bool:
    (a, b), (c, d) = first, second
    if len({a, b, c, d}) < 4:
        return False
    return _side(a, b, c) * _side(a, b, d) < 0 and _side(c, d, a) * _side(c, d, b) < 0


def _side(start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]) -> int:
    turn = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])
    return (turn > 0) - (turn < 0)
