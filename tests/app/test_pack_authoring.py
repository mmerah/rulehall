import json
from pathlib import Path

import pytest
from pydantic import JsonValue
from support.table import LONER3E, ScriptedSpawner, narrowed, offline_settings

from rulehall.app.runtime import Runtime
from rulehall.core.validation import Refusal
from rulehall.engines.loner3e.pack import Loner3ePack

PREMISE = "A drowned coast where the lower town is under water and the bells still ring."
SKILLS: list[JsonValue] = [
    {"name": "Reads the tide"},
    {"name": "Holds their breath"},
    {"name": "Knots and splices"},
    {"name": "Talks the docks"},
    {"name": "Walks the rooftops"},
    {"name": "Finds the way down"},
]
_HEAD: dict[str, JsonValue] = {
    "backdrop": "The sea took the lower town and left the towers standing in it.",
    "names": {"female": ["Elira"], "male": ["Toma"], "surnames": ["Vane"]},
    "rules": "",
    "spends_luck": False,
    "concepts": [
        {"name": "A salt diver", "brief": "Works the flooded streets for what is left."},
        {"name": "A lamp keeper"},
        {"name": "A tide reader"},
        {"name": "A wreck broker"},
        {"name": "A bell ringer"},
        {"name": "A ferry hand"},
    ],
    "skills": SKILLS,
    "frailties": [
        {"name": "Owes the wrecking crew"},
        {"name": "Afraid of the deep"},
        {"name": "Coughs in cold air"},
        {"name": "Cannot swim"},
        {"name": "Too well known"},
        {"name": "Sleeps badly"},
    ],
    "gear": [
        {"name": "A drowned lantern"},
        {"name": "A coil of wet rope"},
        {"name": "A gutting knife"},
        {"name": "A cork float"},
        {"name": "A tin whistle"},
        {"name": "A sealed tin of matches"},
    ],
}
_LOCATIONS: list[JsonValue] = [
    {"name": "The Bell Tower", "brief": "Standing in the water, still ringing the hour."},
    {"name": "The Rope Walk", "brief": "A rooftop road the salvagers strung together."},
    {"name": "The Dry Quarter", "brief": "The streets the sea has not reached yet."},
]
_BLOCK: dict[str, JsonValue] = {
    "name": "The Wrecking Crew",
    "concept": "They own what the water takes",
    "skills": ["Knows every wreck"],
    "frailties": ["Owed by everyone"],
}
_BODY: dict[str, JsonValue] = {
    "locations": _LOCATIONS,
    "seeds": [
        "A salt barge comes in with no crew aboard.",
        "The bell rings twice at the wrong hour.",
        "A diver surfaces speaking a language nobody knows.",
        "The rope walk is cut in the night.",
        "A creditor buys every wreck at once.",
        "The tide stops going out.",
    ],
    "factions": [_BLOCK],
    "npcs": [{**_BLOCK, "name": "Hana", "concept": "A ferrywoman who knows the streets"}],
    "monsters": [{**_BLOCK, "name": "The Thing Below", "concept": "It rings the bell"}],
}


async def test_a_written_pack_lands_on_disk_and_in_the_running_engine(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path, [_head(), _body()])

    pack_id = await runtime.new_pack(LONER3E, "Salt and Ash", PREMISE, None, "")

    assert pack_id == "salt-and-ash"
    assert (tmp_path / "packs" / "loner3e" / "salt-and-ash.json").is_file()
    pack = narrowed(runtime.engines[LONER3E].packs.written[pack_id], Loner3ePack)
    assert [option.id for option in pack.skills[:2]] == ["reads-the-tide", "holds-their-breath"]
    assert pack.source.startswith("written in this app")


async def test_a_head_whose_label_makes_no_id_is_re_prompted_with_the_reason(
    tmp_path: Path,
) -> None:
    unnamed = _head(skills=[{"name": "???"}, *SKILLS[1:]])
    runtime, spawner = _runtime(tmp_path, [unnamed, _head(), _body()])

    pack_id = await runtime.new_pack(LONER3E, "Salt and Ash", PREMISE, None, "")

    assert "makes no id" in spawner.prompts[1][1]
    assert pack_id in runtime.engines[LONER3E].packs.written


async def test_a_body_that_never_lands_leaves_no_pack_written(tmp_path: Path) -> None:
    thin = json.dumps({"locations": _LOCATIONS})
    runtime, _ = _runtime(tmp_path, [_head(), thin, thin])

    with pytest.raises(Refusal, match="the worldsmith answered nothing usable"):
        _ = await runtime.new_pack(LONER3E, "Salt and Ash", PREMISE, None, "")

    assert not (tmp_path / "packs").exists()
    assert runtime.engines[LONER3E].packs.written == {}


def _runtime(tmp_path: Path, answers: list[str]) -> tuple[Runtime, ScriptedSpawner]:
    settings = offline_settings(tmp_path).model_copy(update={"packs_dir": tmp_path / "packs"})
    spawner = ScriptedSpawner(answers={"worldsmith": answers})
    return Runtime(settings, spawner=spawner), spawner


def _head(**changes: JsonValue) -> str:
    return json.dumps(_HEAD | changes)


def _body(**changes: JsonValue) -> str:
    return json.dumps(_BODY | changes)
