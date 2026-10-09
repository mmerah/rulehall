from rulehall.screens.pokemon.team_builder import moved, picked_ids


def test_a_pick_fills_the_open_slot_or_replaces_the_one_aimed_at() -> None:
    assert picked_ids(("protect",), 1, "fakeout") == ("protect", "fakeout")
    assert picked_ids(("protect", "fakeout"), 0, "tailwind") == ("tailwind", "fakeout")


def test_a_move_already_in_the_set_swaps_places_instead_of_doubling() -> None:
    assert picked_ids(("protect", "fakeout"), 0, "fakeout") == ("fakeout", "protect")
    assert picked_ids(("protect", "fakeout"), 2, "fakeout") == ("protect", "fakeout")


def test_a_dragged_move_lands_where_it_is_dropped() -> None:
    assert moved(("a", "b", "c", "d"), 0, 2) == ("b", "c", "a", "d")
    assert moved(("a", "b", "c", "d"), 3, 0) == ("d", "a", "b", "c")
