from support.pokemon import ENGINE


def test_a_region_pack_puts_its_formes_in_place_of_the_base() -> None:
    alola = ENGINE.packs.require("alola").species
    paldea = ENGINE.packs.require("paldea").species
    kalos = ENGINE.packs.require("kalos").species

    assert "rattataalola" in alola
    assert "rattata" not in alola
    assert "taurospaldeablaze" in paldea
    assert "tauros" not in paldea
    assert {"meowstic", "meowsticf"} <= set(kalos)
