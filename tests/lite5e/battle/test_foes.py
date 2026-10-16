from random import Random

import pytest
from support.lite5e_battle import bonus_plan_texts, fight, foe, member, plan_texts

from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.foes import parse_plan, scripted_plan
from rulehall.engines.lite5e.battle.state import Fight, FoeCombatant, MemberCombatant
from rulehall.engines.lite5e.rules import FormationRow


def _fight(*foes: FoeCombatant, bo_row: FormationRow = "back") -> Fight:
    ann = member("ann", weapon_ids=("longsword",))
    bo = member("bo", "rogue", weapon_ids=("shortbow",))
    return fight([(ann, "front"), (bo, bo_row)], foes, Random(1))


def _foe(f: Fight, combatant_id: str) -> FoeCombatant:
    found = f.battle.require_combatant(combatant_id)
    assert isinstance(found, FoeCombatant)
    return found


def _member(f: Fight, actor_id: str) -> MemberCombatant:
    found = f.battle.require_combatant(actor_id)
    assert isinstance(found, MemberCombatant)
    return found


def _wound(f: Fight, actor_id: str, amount: int) -> None:
    _ = f.require_member(actor_id).require_sheet().vitals.hp.adjust(-amount)


def test_the_scripted_plan_never_targets_a_downed_member_while_another_is_in_reach() -> None:
    f = _fight(foe("wolf", "wolf"), bo_row="front")
    _wound(f, "ann", 100)
    plan = scripted_plan(f, _foe(f, "wolf"))
    assert plan.strikes[0].target_ids == ("bo",)
    assert all("ann" not in text for text in plan_texts(f, _foe(f, "wolf")))


def test_auto_takes_the_best_reaching_weapon_attack() -> None:
    ann = member("ann", weapon_ids=("longsword", "dagger", "longbow"))
    f = fight([(ann, "front")], [foe("wolf", "wolf")], Random(1))
    assert scripted_plan(f, _member(f, "ann")).text == "longsword wolf"
    assert ann.require_sheet().slots_spent == {}


def test_auto_strikes_without_a_move_from_the_back_row_when_the_front_row_is_empty() -> None:
    ann = member("ann", weapon_ids=("longsword",))
    f = fight([(ann, "back")], [foe("wolf", "wolf")], Random(1))
    assert scripted_plan(f, _member(f, "ann")).text == "longsword wolf"


@pytest.mark.parametrize(
    "foe_spec",
    [
        ("goblin", "goblin-warrior", "front"),
        ("wight", "wight", "back"),
        ("brass", "brass-dragon-wyrmling", "back"),
        ("allo", "allosaurus", "back"),
    ],
)
def test_parse_plan_round_trips_every_legal_plan(foe_spec: tuple[str, str, FormationRow]) -> None:
    combatant_id, stat_block_id, row = foe_spec
    f = _fight(foe(combatant_id, stat_block_id, row), foe("wolf", "wolf"))
    f.battle.cover = True
    combatant = _foe(f, combatant_id)
    for text in (*plan_texts(f, combatant), *bonus_plan_texts(f, combatant)):
        assert parse_plan(f, combatant, text).text == text


def test_parse_plan_refuses_a_plan_that_is_not_legal() -> None:
    f = _fight(foe("goblin", "goblin-warrior"))
    with pytest.raises(Refusal, match="no legal plan"):
        _ = parse_plan(f, _foe(f, "goblin"), "scimitar bo")
