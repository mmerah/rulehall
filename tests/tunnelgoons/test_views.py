from support.tunnelgoons import ENGINE, HALL, small_world


def test_master_sections_names_the_hidden_npc_and_the_locked_way() -> None:
    state = small_world()
    world = state.world
    world.visits.append(HALL)
    sections = dict(ENGINE.master_sections(state))
    assert "Robo Mantis" in sections["HIDDEN HERE (the player has not found these)"]
    assert "locked" in sections["WAYS OUT"]
