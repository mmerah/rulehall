import re

import pytest
from support.lite5e import (
    GATE,
    HALL,
    PIT,
    PURSE,
    VAULT,
    ScriptedDice,
    hero,
    person,
    sheet_proposal,
    world,
)

from rulehall.core.facts import Fact
from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.args import (
    AbilityCheck,
    CastSpell,
    GearUse,
    Harm,
    KeyedWay,
    MakeItem,
    Trade,
)
from rulehall.engines.lite5e.world import Lite5eWorld
from rulehall.engines.sheet import PLAYER_ID


def checked(built: Lite5eWorld, *faces: int, **fields: object) -> list[Fact]:
    dc = (
        {"kind": "target", "target_id": fields.pop("target_id")}
        if "target_id" in fields
        else {"kind": "difficulty", "difficulty": fields.pop("difficulty")}
    )
    check = AbilityCheck.model_validate({"what": "try", "dc": dc, **fields})
    return built.check(check, ScriptedDice(*faces))


def harmed(built: Lite5eWorld, *faces: int, **danger: object) -> list[Fact]:
    harm = Harm.model_validate({"actor_ids": ("player",), "danger": danger})
    return built.harm(harm, ScriptedDice(*faces))


def dc_of(facts: list[Fact]) -> int:
    return next(int(found[1]) for fact in facts if (found := re.search(r"vs DC (\d+)", fact.trace)))


def told(facts: list[Fact]) -> str:
    return "\n".join(fact.trace + fact.card for fact in facts if fact.told)


def test_the_narrator_never_reads_a_persons_dc_or_passive_perception() -> None:
    built = world(person("guard", GATE, "guard"))
    facts = checked(built, 20, skill="stealth", target_id="guard")
    assert "DC" not in told(facts)
    assert "12" not in told(facts)
    assert "success" in told(facts)


def test_a_search_reveals_and_a_failure_waits_for_a_move() -> None:
    built = world()
    with pytest.raises(Refusal, match="perception or investigation"):
        _ = checked(built, 20, skill="stealth", target_id=PURSE)
    _ = checked(built, 2, skill="perception", target_id=PURSE)
    assert "failure" in built.settled_lines()
    with pytest.raises(Refusal, match="Move or rest"):
        _ = checked(built, 20, skill="perception", target_id=PURSE)
    _ = checked(built, 20, skill="investigation", target_id=PURSE)
    assert built.items[PURSE].known


def test_a_lock_check_unlocks_and_a_disarm_clears_the_trap() -> None:
    built = world()
    _ = built.move(HALL, ())
    _ = checked(built, 10, tool_id="thieves-tools", target_id=VAULT)
    assert not built.ways[HALL][1].locked
    assert built.items[PIT].known
    _ = checked(built, 10, skill="sleight-of-hand", target_id=PIT)
    assert built.items[PIT].trap is None


def test_a_lock_check_takes_thieves_tools_alone_or_athletics() -> None:
    built = world()
    _ = built.move(HALL, ())
    with pytest.raises(Refusal, match="thieves-tools alone"):
        _ = checked(built, 10, tool_id="thieves-tools", skill="insight", target_id=VAULT)
    assert built.ways[HALL][1].locked


def test_time_offscreen_never_opens_a_way_with_a_lock() -> None:
    built = world()
    with pytest.raises(Refusal, match="does not open offscreen"):
        _ = built.open_way(built.places[HALL], built.places[VAULT])
    assert built.ways[HALL][1].locked


def test_only_the_key_of_a_way_opens_its_lock() -> None:
    built = world()
    _ = built.move(HALL, ())
    _ = built.make_item(MakeItem(holder_id=PLAYER_ID, name="Letter", note="A sealed letter"))
    with pytest.raises(Refusal, match="has a lock"):
        _ = built.unlock_by_story(VAULT)
    stray = KeyedWay(from_id=GATE, to_id=HALL)
    with pytest.raises(Refusal, match="no locked way with a lock"):
        _ = built.make_item(MakeItem(holder_id=PLAYER_ID, name="Key", note="Iron", opens=stray))
    vault = KeyedWay(from_id=VAULT, to_id=HALL)
    _ = built.make_item(MakeItem(holder_id=PLAYER_ID, name="Key", note="Iron", opens=vault))
    _ = built.unlock_by_story(VAULT)
    assert not built.ways[HALL][1].locked
    with pytest.raises(Refusal, match="no locked way with a lock"):
        _ = built.make_item(MakeItem(holder_id=PLAYER_ID, name="Spare", note="Iron", opens=vault))


def test_a_save_and_a_fall_stop_at_1_hp() -> None:
    built = world()
    sheet = built.player.require_sheet()
    fire = {"ability": "strength", "difficulty": "hard", "damage": "heavy", "damage_type": "fire"}
    _ = harmed(built, 1, 6, 6, 6, kind="save", **fire)
    assert sheet.vitals.hp.current == 1
    sheet.vitals.hp.current = sheet.vitals.hp.maximum
    _ = harmed(built, 6, 6, 6, 6, 6, 6, kind="fall", falling_feet=60)
    assert sheet.vitals.hp.current == 1


def test_kill_takes_only_a_captive() -> None:
    built = world(person("guard", GATE, "guard"), person("thief", GATE, "bandit", captive=True))
    with pytest.raises(Refusal, match="captive"):
        _ = built.kill("guard")
    _ = built.kill("thief")
    assert not built.npcs["thief"].alive


def test_drinking_a_potion_spends_it_and_heals() -> None:
    built = world()
    sheet = built.player.require_sheet()
    sheet.add_gear("potion-of-healing", 1)
    potions = sheet.gear["potion-of-healing"]
    sheet.vitals.hp.current = 1

    drink = GearUse(actor_id=PLAYER_ID, gear_id="potion-of-healing", kind="drink")
    _ = built.use_gear(drink, ScriptedDice(2, 2))

    assert sheet.gear.get("potion-of-healing", 0) == potions - 1
    assert sheet.vitals.hp.current == 1 + 2 + 2 + 2


def test_a_shop_sells_its_stock_and_buys_back_at_half() -> None:
    built = world()
    coins = built.player.require_sheet()
    coins.coins_cp = before = 10000
    with pytest.raises(Refusal, match="does not sell"):
        _ = built.trade(Trade(kind="buy", gear_id="weapon-1-longsword"))
    _ = built.trade(Trade(kind="buy", gear_id="potion-of-healing"))
    _ = built.trade(Trade(kind="sell", gear_id="potion-of-healing"))
    assert coins.coins_cp == before - 2500


def test_a_hidden_item_cannot_move_before_it_is_found() -> None:
    built = world()
    with pytest.raises(Refusal, match="must find it first"):
        _ = built.move_item(PURSE, "player")
    assert not built.items[PURSE].known


def test_a_spell_takes_no_more_targets_than_its_cast_level_allows() -> None:
    built = world(
        person("bandits", GATE, "bandit", count=2),
        player=hero(sheet_proposal("cleric", "dwarf")),
    )
    for target_ids in ((PLAYER_ID, "bandits"), ("bandits",)):
        cast = CastSpell(spell_id="cure-wounds", target_ids=target_ids)
        with pytest.raises(Refusal, match="1 at most"):
            _ = built.cast(cast, ScriptedDice())
