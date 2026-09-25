from rulehall.core.play import PendingOption
from rulehall.core.validation import Slug
from rulehall.core.views import MapEdge, MapNode, MapView, Panel, PanelRow
from rulehall.engines.rooms.world import Dweller, Place, RoomWorld

GO_TO = "I go to {name}"
TRY_WAY = "I try the way to {name}"
HEAD_BACK = "I head back to {name}"


def carried_panel[N: Dweller](world: RoomWorld[N]) -> Panel:
    return Panel(
        title="Carrying",
        rows=tuple(
            item.subject().row(
                (
                    PendingOption(
                        id="drop",
                        name="Drop here",
                        action_name="drop_here",
                        args={"item_id": item.id},
                    ),
                )
            )
            for item in world.carried(world.player.id)
        ),
    )


def ways_panel[N: Dweller](world: RoomWorld[N]) -> Panel:
    return Panel(
        title="Ways out",
        rows=tuple(
            PanelRow(
                name=world.require_place(way.to_id).name,
                brief="locked" if way.locked else "",
            )
            for way in world.ways.get(world.current.id, ())
            if way.known
        ),
    )


def map_view[N: Dweller](world: RoomWorld[N]) -> MapView:
    visited = world.visited_places()
    visited_ids = {place.id for place in visited}
    known = [
        (place.id, way) for place in visited for way in world.ways.get(place.id, ()) if way.known
    ]
    far_ids = dict.fromkeys(way.to_id for _, way in known if way.to_id not in visited_ids)
    pairs: dict[tuple[Slug, Slug], bool] = {}
    here_id = world.current.id
    # The way from here decides, so the dashed edge agrees with the node's prefill.
    for from_id, way in sorted(known, key=lambda known_way: known_way[0] == here_id):
        pair = (from_id, way.to_id) if from_id < way.to_id else (way.to_id, from_id)
        if from_id == here_id:
            pairs[pair] = way.locked
        else:
            pairs[pair] = pairs.get(pair, False) or way.locked
    return MapView(
        nodes=tuple(
            _map_node(world, place, visited=place.id in visited_ids)
            for place in (*visited, *map(world.require_place, far_ids))
        ),
        edges=tuple(
            MapEdge(from_id=from_id, to_id=to_id, locked=locked)
            for (from_id, to_id), locked in pairs.items()
        ),
        here_id=here_id,
    )


def _map_node[N: Dweller](world: RoomWorld[N], place: Place, *, visited: bool) -> MapNode:
    here_id = world.current.id
    way = world.way(here_id, place.id)
    if place.id == here_id:
        text = ""
    elif way is not None and way.known:
        text = TRY_WAY if way.locked else GO_TO
    else:
        text = HEAD_BACK if visited else GO_TO
    return MapNode(
        id=place.id, name=place.name, visited=visited, prefill=text.format(name=place.name)
    )
