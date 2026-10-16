import json
from collections.abc import Callable

import pytest
from support.lite5e import GATE, HALL, PIT, VAULT, map_proposal

from rulehall.core.stores import read_model
from rulehall.core.validation import Refusal, parse_json
from rulehall.engines.lite5e.args import KeyedWay
from rulehall.engines.lite5e.data import (
    DATA_DIR,
    BestiaryFile,
    SpellsFile,
    srd,
)
from rulehall.engines.lite5e.pack import Lite5ePack
from rulehall.engines.lite5e.world import Lite5eMapProposal
from rulehall.engines.lite5e.worldsmith import check_opening

SHIPPED_PACK = DATA_DIR.parent / "packs" / "srd.json"


def test_shipped_files_load() -> None:
    assert srd().bestiary.stat_blocks
    assert srd().spells.spells
    assert srd().gear.weapons
    assert srd().character_options.classes
    assert read_model(SHIPPED_PACK, Lite5ePack).backgrounds


def test_heavy_armor_ignores_dexterity_and_medium_armor_caps_only_a_bonus() -> None:
    armor = srd().gear.armor
    assert armor["chain-mail"].worn_armor_class(-1) == 16
    assert armor["breastplate"].worn_armor_class(-1) == 13
    assert armor["breastplate"].worn_armor_class(3) == 16


def test_unknown_rider_id_is_refused() -> None:
    payload = json.loads((DATA_DIR / "bestiary.json").read_text(encoding="utf-8"))
    block_id, index = next(
        (block_id, index)
        for block_id, block in srd().bestiary.stat_blocks.items()
        for index, attack in enumerate(block.actions)
        if attack.riders
    )
    payload["stat_blocks"][block_id]["actions"][index]["riders"][0]["rider_id"] = "no-such-rider"
    with pytest.raises(Refusal, match="rider_id"):
        parse_json(BestiaryFile, json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value", "refusal"),
    [
        ("feat_id", "archery", "origin feats"),
        ("tool_id", "rope", "tools"),
        ("gear", [{"gear_id": "no-such-gear", "count": 1}], "no gear id of the SRD"),
    ],
)
def test_a_pack_naming_an_unknown_srd_id_is_refused(
    field: str, value: object, refusal: str
) -> None:
    payload = json.loads(SHIPPED_PACK.read_text(encoding="utf-8"))
    payload["backgrounds"][1][field] = value
    with pytest.raises(Refusal, match=refusal):
        parse_json(Lite5ePack, json.dumps(payload))


def test_wrong_attribution_is_refused() -> None:
    payload = json.loads((DATA_DIR / "spells.json").read_text(encoding="utf-8"))
    payload["attribution"] = "other"
    with pytest.raises(Refusal, match="attribution"):
        parse_json(SpellsFile, json.dumps(payload))


def _known_pit() -> Lite5eMapProposal:
    proposal = map_proposal()
    proposal.items[PIT].known = True
    return proposal


def _lock_on_an_open_way() -> Lite5eMapProposal:
    proposal = map_proposal()
    proposal.ways[GATE][0].lock = "easy"
    return proposal


def _lock_harder_one_way() -> Lite5eMapProposal:
    proposal = map_proposal()
    proposal.ways[VAULT][0].lock = "hard"
    return proposal


def _written_key() -> Lite5eMapProposal:
    proposal = map_proposal()
    proposal.items[PIT].opens = KeyedWay(from_id=HALL, to_id=VAULT)
    return proposal


def _dagger_shop() -> Lite5eMapProposal:
    proposal = map_proposal()
    proposal.places[GATE].shop = ("dagger",)
    return proposal


@pytest.mark.parametrize(
    ("build_proposal", "refusal"),
    [
        (_known_pit, "`find`"),
        (_lock_on_an_open_way, "`lock`"),
        (_lock_harder_one_way, "way back"),
        (_written_key, "`opens`"),
        (_dagger_shop, "stock only magic"),
    ],
)
def test_an_opening_that_names_what_the_map_or_the_srd_lacks_is_refused(
    build_proposal: Callable[[], Lite5eMapProposal], refusal: str
) -> None:
    with pytest.raises(Refusal, match=refusal):
        check_opening(build_proposal())
