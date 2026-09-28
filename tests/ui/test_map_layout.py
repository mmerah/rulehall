from rulehall.core.views import MapEdge, MapNode, MapView
from rulehall.ui.map_layout import map_cells


def test_remembered_rooms_stay_put_and_no_two_rooms_share_a_cell() -> None:
    names = ("hall", "cellar", "tower", "vault", "garden")
    nodes = tuple(
        MapNode(id=name, name=name, visited=True, unexplored=False, prefill="") for name in names
    )
    edges = tuple(
        MapEdge(from_id=from_id, to_id=to_id, locked=False)
        for from_id, to_id in (
            ("hall", "cellar"),
            ("hall", "tower"),
            ("hall", "vault"),
            ("vault", "garden"),
        )
    )
    before = MapView(nodes=nodes[:3], edges=edges[:2], here_id="hall")
    remembered = {"hall": (2, 0), "cellar": (0, 1), "tower": (1, 1)}

    after = map_cells(
        MapView(nodes=nodes, edges=edges, here_id="vault"), map_cells(before, remembered)
    )

    assert {node_id: after[node_id] for node_id in remembered} == remembered
    assert len(set(after.values())) == len(names)
