from collections.abc import Iterable, Mapping, Sequence

from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Slug
from rulehall.core.views import MapEdge, MapNode, MapNodeKind, MapView, Panel, PanelRow
from rulehall.engines.bases.maps.world import EXTEND_REQUEST, Dweller, Item, MapWorld, Place, Way

MORE_MAP = ActionOption(
    id=EXTEND_REQUEST,
    name="More map",
    help="Say where you head; the map grows.",
    action_name="extend",
    needs_words=True,
)
GO_TO = "I go to {name}"
TRY_WAY = "I try the way to {name}"
HEAD_BACK = "I head back to {name}"
TAKE_UNKNOWN_WAY = "I take the unknown way out of {name}"
UNEXPLORED_NAME = "???"
UNEXPLORED_HELP = "A way you have not taken yet; where it leads is unknown until you go."


def carried_panel[P: Dweller, I: Item, L: Place, WayT: Way](
    world: MapWorld[P, I, L, WayT],
) -> Panel:
    return Panel(
        title="Carrying",
        help="What you hold; drop an item to leave it in this place.",
        rows=tuple(
            PanelRow(
                name=item.name,
                brief=item.brief,
                icon_id=item.id,
                options=(
                    ActionOption(
                        id=f"drop-{item.id}",
                        name="Drop here",
                        action_name="drop_here",
                        args={"item_id": item.id},
                    ),
                ),
            )
            for item in world.carried(world.player.id)
        ),
    )


def ways_panel[P: Dweller, I: Item, L: Place, WayT: Way](world: MapWorld[P, I, L, WayT]) -> Panel:
    return Panel(
        title="Ways out",
        help="The known ways on from this place; a locked one must be opened before you pass.",
        rows=tuple(
            _way_row(world, way) for way in world.ways.get(world.current.id, ()) if way.known
        ),
    )


def map_view[P: Dweller, I: Item, L: Place, WayT: Way](world: MapWorld[P, I, L, WayT]) -> MapView:
    here = world.current
    region = world.current_region
    region_places = world.visited_region_places()
    visited = world.visited_places()
    visited_ids = {place.id for place in visited}
    region_place_ids = {place.id for place in region_places}
    boxes = {
        other.start_id: MapNode(
            id=other.start_id,
            name=other.name,
            kind="region",
            prefill=HEAD_BACK.format(name=other.name),
        )
        for other in world.regions
        if other is not region and visited_ids.intersection(other.place_ids)
    }
    named = [
        (place.id, _node_id(world, boxes, place.id), _node_id(world, boxes, way.to_id), way)
        for place in visited
        for way in world.ways.get(place.id, ())
        if way.known and world.require_place(way.to_id).known
    ]
    pairs: dict[tuple[Slug, Slug], bool] = {}
    # The way from here decides, so the dashed edge agrees with the node's prefill.
    for from_id, from_node_id, to_node_id, way in sorted(
        named, key=lambda named_way: named_way[0] == here.id
    ):
        # A way out of a boxed place counts only when its end is drawn: a box or a visited place.
        drawn = from_id in region.place_ids or to_node_id in boxes or way.to_id in region_place_ids
        if not drawn or from_node_id == to_node_id:
            continue
        pair = (
            (from_node_id, to_node_id) if from_node_id < to_node_id else (to_node_id, from_node_id)
        )
        if from_id == here.id:
            pairs[pair] = way.locked
        else:
            pairs[pair] = pairs.get(pair, False) or way.locked
    nodes: dict[Slug, MapNode] = {}
    stub_edges: list[MapEdge] = []
    for place_number, place in enumerate(region_places, 1):
        if place.id not in nodes:
            nodes[place.id] = _map_node(world, place, kind="visited")
        known_ways = (way for way in world.ways.get(place.id, ()) if way.known)
        for way_number, way in enumerate(known_ways, 1):
            if world.is_unexplored(way):
                # A stub id is positional: the destination id would reach the browser.
                stub_id = f"way-{place_number}-{way_number}"
                nodes[stub_id] = MapNode(
                    id=stub_id,
                    name=UNEXPLORED_NAME,
                    kind="unexplored",
                    prefill=TAKE_UNKNOWN_WAY.format(name=here.name)
                    if place.id == here.id
                    else HEAD_BACK.format(name=place.name),
                )
                stub_edges.append(MapEdge(from_id=place.id, to_id=stub_id, locked=way.locked))
            elif way.to_id not in nodes and _node_id(world, boxes, way.to_id) not in boxes:
                destination = world.require_place(way.to_id)
                nodes[way.to_id] = _map_node(
                    world, destination, kind="visited" if destination.id in visited_ids else "seen"
                )
    for box_id in _box_order(list(boxes), pairs, set(nodes)):
        nodes[box_id] = boxes[box_id]
    return MapView(
        region_id=region.start_id,
        region_name=region.name,
        nodes=tuple(nodes.values()),
        edges=(
            *(
                MapEdge(from_id=from_id, to_id=to_id, locked=locked)
                for (from_id, to_id), locked in pairs.items()
            ),
            *stub_edges,
        ),
        here_id=here.id,
    )


def _way_row[P: Dweller, I: Item, L: Place, WayT: Way](
    world: MapWorld[P, I, L, WayT], way: WayT
) -> PanelRow:
    brief = "locked" if way.locked else ""
    if world.is_unexplored(way):
        return PanelRow(name=UNEXPLORED_NAME, brief=brief, help=UNEXPLORED_HELP)
    return PanelRow(name=world.require_place(way.to_id).name, brief=brief)


def _map_node[P: Dweller, I: Item, L: Place, WayT: Way](
    world: MapWorld[P, I, L, WayT], place: L, *, kind: MapNodeKind
) -> MapNode:
    here_id = world.current.id
    way = world.find_way(here_id, place.id)
    if place.id == here_id:
        text = ""
    elif way is not None and way.known:
        text = TRY_WAY if way.locked else GO_TO
    else:
        text = HEAD_BACK if kind == "visited" else GO_TO
    return MapNode(id=place.id, name=place.name, kind=kind, prefill=text.format(name=place.name))


def _node_id[P: Dweller, I: Item, L: Place, WayT: Way](
    world: MapWorld[P, I, L, WayT], boxes: Mapping[Slug, MapNode], place_id: Slug
) -> Slug:
    start_id = world.require_region(place_id).start_id
    return start_id if start_id in boxes else place_id


def _box_order(
    box_ids: Sequence[Slug], pairs: Iterable[tuple[Slug, Slug]], placed_ids: set[Slug]
) -> list[Slug]:
    linked: dict[Slug, set[Slug]] = {}
    for first_id, second_id in pairs:
        linked.setdefault(first_id, set()).add(second_id)
        linked.setdefault(second_id, set()).add(first_id)
    reached = set(placed_ids)
    remaining = list(box_ids)
    order: list[Slug] = []
    while remaining:
        ring = [box_id for box_id in remaining if linked.get(box_id, set()) & reached] or remaining
        order += ring
        reached.update(ring)
        remaining = [box_id for box_id in remaining if box_id not in reached]
    return order
