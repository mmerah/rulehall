import json

import pytest
from pydantic import ValidationError
from support.journey import ENGINE, started
from support.table import LIBRARY, POKEMON, SCENARIO_MODELS, scenario_for

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.journey.pack import JourneyPack


def test_a_region_pack_puts_its_formes_in_place_of_the_base() -> None:
    alola = ENGINE.packs.require_pack("alola").species_ids
    paldea = ENGINE.packs.require_pack("paldea").species_ids
    kalos = ENGINE.packs.require_pack("kalos").species_ids

    assert "rattataalola" in alola
    assert "rattata" not in alola
    assert "taurospaldeablaze" in paldea
    assert "tauros" not in paldea
    assert {"meowstic", "meowsticf"} <= set(kalos)


def test_the_national_pack_holds_every_base_species() -> None:
    national = ENGINE.packs.require_pack("national").species_ids

    assert "national" in {option.id for option in ENGINE.packs.options()}
    assert (national[0], national[-1]) == ("bulbasaur", "pecharunt")
    assert "rattata" in national
    assert "rattataalola" not in national


def test_a_joined_pack_adds_the_species_of_the_others_and_keeps_its_own_starters() -> None:
    kanto = ENGINE.packs.require_pack("srd")
    johto = ENGINE.packs.require_pack("johto")

    joined = ENGINE.packs.require_joined("srd", ("johto",))

    assert joined.species_ids[: len(kanto.species_ids)] == kanto.species_ids
    assert set(joined.species_ids) == {*kanto.species_ids, *johto.species_ids}
    assert len(set(joined.species_ids)) == len(joined.species_ids)
    assert (joined.starters, joined.backdrop) == (kanto.starters, kanto.backdrop)


def test_begin_and_restore_refuse_an_unknown_extra_pack() -> None:
    scenario_id = scenario_for(POKEMON)
    scenario = LIBRARY.read_scenario(scenario_id, SCENARIO_MODELS)
    character = LIBRARY.read_character("kael", ENGINE.id, ENGINE.character_model)
    smuggled = scenario.model_copy(update={"extra_pack_ids": ("nowhere",)})
    raw = json.loads(started().model_dump_json())
    raw["extra_pack_ids"] = ["nowhere"]

    with pytest.raises(Refusal, match="'nowhere' is not installed"):
        _ = ENGINE.begin(scenario_id, smuggled, character)
    with pytest.raises(Refusal, match="'nowhere' is not installed"):
        _ = ENGINE.restore(json.dumps(raw))


def test_a_journey_pack_refuses_a_forme_only_species() -> None:
    kanto = ENGINE.packs.require_pack("srd")
    raw = {**kanto.model_dump(), "species_ids": (*kanto.species_ids, "charizardmegax")}

    with pytest.raises(ValidationError, match="forme-only species"):
        _ = JourneyPack.model_validate(raw)
