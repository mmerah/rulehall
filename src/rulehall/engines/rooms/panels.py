from rulehall.core.decisions import ActionOption
from rulehall.core.validation import Slug
from rulehall.core.views import MapEdge, MapNode, MapView, Panel, PanelRow
from rulehall.engines.rooms.world import Dweller, Place, RoomWorld, Way

EXTEND: Slug = "extend"
MORE_MAP = ActionOption(
    id=EXTEND,
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


def carried_panel[P: Dweller](world: RoomWorld[P]) -> Panel:
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


def ways_panel[P: Dweller](world: RoomWorld[P]) -> Panel:
    return Panel(
        title="Ways out",
        help="The known ways on from this place; a locked one must be opened before you pass.",
        rows=tuple(
            _way_row(world, way) for way in world.ways.get(world.current.id, ()) if way.known
        ),
    )


def map_view[P: Dweller](world: RoomWorld[P]) -> MapView:
    visited = world.visited_places()
    visited_ids = {place.id for place in visited}
    named = [
        (place.id, way)
        for place in visited
        for way in world.ways.get(place.id, ())
        if way.known and world.require_place(way.to_id).known
    ]
    pairs: dict[tuple[Slug, Slug], bool] = {}
    here = world.current
    # The way from here decides, so the dashed edge agrees with the node's prefill.
    for from_id, way in sorted(named, key=lambda named_way: named_way[0] == here.id):
        pair = (from_id, way.to_id) if from_id < way.to_id else (way.to_id, from_id)
        if from_id == here.id:
            pairs[pair] = way.locked
        else:
            pairs[pair] = pairs.get(pair, False) or way.locked
    nodes: dict[Slug, MapNode] = {}
    stub_edges: list[MapEdge] = []
    for place_number, place in enumerate(visited, 1):
        if place.id not in nodes:
            nodes[place.id] = _map_node(world, place, visited=True)
        known_ways = (way for way in world.ways.get(place.id, ()) if way.known)
        for way_number, way in enumerate(known_ways, 1):
            if world.is_unexplored(way):
                # A stub id is positional: the destination id would reach the browser.
                stub_id = f"way-{place_number}-{way_number}"
                nodes[stub_id] = MapNode(
                    id=stub_id,
                    name=UNEXPLORED_NAME,
                    visited=False,
                    unexplored=True,
                    prefill=TAKE_UNKNOWN_WAY.format(name=here.name)
                    if place.id == here.id
                    else HEAD_BACK.format(name=place.name),
                )
                stub_edges.append(MapEdge(from_id=place.id, to_id=stub_id, locked=way.locked))
            elif way.to_id not in nodes:
                destination = world.require_place(way.to_id)
                nodes[way.to_id] = _map_node(
                    world, destination, visited=destination.id in visited_ids
                )
    return MapView(
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


def _way_row[P: Dweller](world: RoomWorld[P], way: Way) -> PanelRow:
    brief = "locked" if way.locked else ""
    if world.is_unexplored(way):
        return PanelRow(name=UNEXPLORED_NAME, brief=brief, help=UNEXPLORED_HELP)
    return PanelRow(name=world.require_place(way.to_id).name, brief=brief)


def _map_node[P: Dweller](world: RoomWorld[P], place: Place, *, visited: bool) -> MapNode:
    here_id = world.current.id
    way = world.find_way(here_id, place.id)
    if place.id == here_id:
        text = ""
    elif way is not None and way.known:
        text = TRY_WAY if way.locked else GO_TO
    else:
        text = HEAD_BACK if visited else GO_TO
    return MapNode(
        id=place.id,
        name=place.name,
        visited=visited,
        unexplored=False,
        prefill=text.format(name=place.name),
    )
