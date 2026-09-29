from support.pokemon import ENGINE


def test_a_region_pack_puts_its_formes_in_place_of_the_base() -> None:
    alola = ENGINE.packs.require_pack("alola").species_ids
    paldea = ENGINE.packs.require_pack("paldea").species_ids
    kalos = ENGINE.packs.require_pack("kalos").species_ids

    assert "rattataalola" in alola
    assert "rattata" not in alola
    assert "taurospaldeablaze" in paldea
    assert "tauros" not in paldea
    assert {"meowstic", "meowsticf"} <= set(kalos)
