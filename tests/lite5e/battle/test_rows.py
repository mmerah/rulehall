from random import Random

import pytest
from support.lite5e_battle import SteadyDice, fight, foe, member

from rulehall.core.validation import Refusal
from rulehall.engines.lite5e.battle.damage import change_row
from rulehall.engines.lite5e.battle.rows import (
    area_cap,
    area_targets,
    reaches,
)
from rulehall.engines.lite5e.battle.specs import (
    stat_block_action,
    weapon_action,
)
from rulehall.engines.lite5e.battle.state import Effect, Fight
from rulehall.engines.lite5e.battle.views import battle_view
from rulehall.engines.lite5e.data import Area, srd
from rulehall.engines.lite5e.rules import FormationRow


def _fight() -> Fight:
    ann = member("ann", weapon_ids=("longsword", "glaive", "longbow"))
    bo = member("bo", weapon_ids=("longsword", "glaive"))
    foes = [
        foe("wolf-1", "wolf"),
        foe("wolf-2", "wolf"),
        foe("wolf-3", "wolf"),
        foe("ogre", "ogre", "back"),
        foe("ankylosaurus", "ankylosaurus", "back"),
    ]
    return fight([(ann, "front"), (bo, "back")], foes, Random(1))


def test_reach_goes_from_the_back_row_onto_the_enemy_front_row_only() -> None:
    f = _fight()
    at = f.battle.require_combatant
    sheet = f.require_member("bo").require_sheet()
    glaive = weapon_action(sheet, "glaive", off_hand=False)
    longsword = weapon_action(sheet, "longsword", off_hand=False)
    assert reaches(f, at("bo"), at("wolf-1"), glaive)
    assert not reaches(f, at("bo"), at("ogre"), glaive)
    assert not reaches(f, at("bo"), at("wolf-1"), longsword)
    tail = stat_block_action(srd().require_stat_block("ankylosaurus").actions[0])
    assert reaches(f, at("ankylosaurus"), at("ann"), tail)
    assert not reaches(f, at("ankylosaurus"), at("bo"), tail)


def test_an_empty_front_row_lets_its_back_row_count_as_front() -> None:
    f = _fight()
    at = f.battle.require_combatant
    longsword = weapon_action(f.require_member("ann").require_sheet(), "longsword", off_hand=False)
    assert not reaches(f, at("ann"), at("ogre"), longsword)
    for wolf in f.battle.foes()[:3]:
        wolf.hp.current = 0
    assert reaches(f, at("ann"), at("ogre"), longsword)


def test_a_card_shows_the_row_the_rules_use() -> None:
    f = _fight()
    for wolf in f.battle.foes()[:3]:
        wolf.hp.current = 0
    view = battle_view(f, live=True, thinking=False, aiming="", picks=())
    rows = {card.combatant_id: card.row for card in view.foes}
    assert rows["ogre"] == "front"


def test_area_targets_keep_the_cap_and_one_row() -> None:
    f = _fight()
    at = f.battle.require_combatant
    small = area_cap(Area(feet=5, shape="sphere"))
    wolves = [at("wolf-1"), at("wolf-2")]
    assert area_targets(f, at("ann"), wolves, small) == wolves
    with pytest.raises(Refusal, match="one row"):
        area_targets(f, at("ann"), [at("wolf-1"), at("ogre")], small)
    with pytest.raises(Refusal, match="allies"):
        area_targets(f, at("ann"), [at("bo")], small)
    whole = area_targets(f, at("ann"), [at("ogre")], area_cap(Area(feet=20, shape="cube")))
    assert [c.combatant_id for c in whole] == ["ogre", "ankylosaurus"]
    with pytest.raises(Refusal, match="up to 2"):
        area_targets(f, at("ann"), [*wolves, at("wolf-3")], small)


def test_a_charmed_creature_cannot_reach_its_charmer() -> None:
    f = _fight()
    at = f.battle.require_combatant
    bite = stat_block_action(srd().require_stat_block("wolf").actions[0])
    f.battle.effects.append(
        Effect(holder_id="wolf-1", source_id="ann", effect_id="charm", condition="charmed")
    )
    assert not reaches(f, at("wolf-1"), at("ann"), bite)
    assert reaches(f, at("wolf-2"), at("ann"), bite)


def _falls_back_struck(bo_row: FormationRow) -> bool:
    ann = member("ann", weapon_ids=("longsword",))
    f = fight([(ann, "front"), (member("bo"), bo_row)], [foe("wolf", "wolf")], SteadyDice(15))
    facts = change_row(f, f.battle.require_combatant("ann"), provoking=True, teleport=False)
    return any("strikes as" in fact.trace for fact in facts)


def test_falling_back_provokes_only_when_it_leaves_the_front() -> None:
    assert _falls_back_struck("front")
    assert not _falls_back_struck("back")
