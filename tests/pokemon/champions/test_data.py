import json

import pytest

from rulehall.core.validation import Refusal, parse_json
from rulehall.engines.pokemon.champions.data import DATA_FILE, ChampionsData, champions_data


def test_shipped_data_loads() -> None:
    assert champions_data().real_teams


def test_team_with_one_species_twice_is_refused() -> None:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    sets = payload["real_teams"][0]["sets"]
    sets[1] = {**sets[0], "item_id": sets[1]["item_id"]}
    with pytest.raises(Refusal, match="duplicate species"):
        parse_json(ChampionsData, json.dumps(payload))


def test_team_with_two_formes_of_one_species_is_refused() -> None:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    sets = payload["real_teams"][0]["sets"]
    for index, species_id in enumerate(("indeedee", "indeedeef")):
        sets[index] = {**payload["presets"][species_id][0], "item_id": sets[index]["item_id"]}
    with pytest.raises(Refusal, match="duplicate species"):
        parse_json(ChampionsData, json.dumps(payload))


def test_role_with_an_illegal_move_is_refused() -> None:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    payload["roles"]["speed-control"]["move_ids"].append("notamove")
    with pytest.raises(Refusal, match="not legal"):
        parse_json(ChampionsData, json.dumps(payload))


def test_mega_forme_that_is_a_legal_species_is_refused() -> None:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    payload["legal"]["mega_formes"]["abomasite"]["abomasnow"] = "abomasnow"
    with pytest.raises(Refusal, match="no Mega forme"):
        parse_json(ChampionsData, json.dumps(payload))
