from random import Random

from support.lite5e import ScriptedDice
from support.lite5e_battle import SteadyDice, fight, foe, member

from rulehall.engines.lite5e.battle.attack import resisted
from rulehall.engines.lite5e.battle.damage import (
    DamageRoll,
    Dealt,
    repeat_saves,
    resolve,
    roll_damage,
    take_damage,
)
from rulehall.engines.lite5e.battle.specs import (
    SaveSpec,
    spell_action,
    stat_block_action,
    weapon_action,
)
from rulehall.engines.lite5e.battle.state import (
    Effect,
    Fight,
)
from rulehall.engines.lite5e.data import srd
from rulehall.engines.lite5e.rules import FormationRow


def _fight(rng: Random, *foes_and_rows: tuple[str, str, FormationRow]) -> Fight:
    ann = member("ann", weapon_ids=("greatsword",))
    bo = member("bo", "rogue", weapon_ids=("dagger",))
    cleo = member("cleo", "cleric", level=3)
    foes = [foe(foe_id, block, row) for foe_id, block, row in foes_and_rows]
    return fight([(ann, "front"), (bo, "front"), (cleo, "back")], foes, rng)


def test_a_critical_hit_doubles_the_sneak_attack_dice_once_per_turn() -> None:
    f = _fight(Random(3), ("bandit", "bandit", "front"))
    at = f.battle.require_combatant
    sheet = f.require_member("bo").require_sheet()
    sheet.picks["origin-feat"].remove("savage-attacker")
    dagger = weapon_action(sheet, "dagger", off_hand=False)
    first = roll_damage(f, at("bo"), at("bandit"), dagger, critical=True, mode="advantage")
    assert [event.faces for event in first.dice] == [(4, 4), (6, 6)]
    again = roll_damage(f, at("bo"), at("bandit"), dagger, mode="advantage")
    assert [event.faces for event in again.dice] == [(4,)]


def test_resistance_immunity_and_vulnerability() -> None:
    f = _fight(Random(1), ("rats", "swarm-of-rats", "front"), ("skeleton", "skeleton", "front"))
    at = f.battle.require_combatant
    assert resisted(f, at("rats"), 9, "piercing") == 4
    assert resisted(f, at("skeleton"), 9, "bludgeoning") == 18
    assert resisted(f, at("skeleton"), 9, "poison") == 0
    assert resisted(f, at("ann"), 9, "poison") == 9


def test_a_fireball_rolls_once_hits_every_goblin_and_then_checks_morale() -> None:
    wizard = member("wiz", "wizard", level=5)
    group = [foe(f"goblin-{number}", "goblin-warrior") for number in range(1, 5)]
    f = fight([(wizard, "back")], group, ScriptedDice(*(1,) * 8, 1, 1, 1, 1, 1))
    goblins = f.battle.foes()
    goblins[0].hp.current = 5
    fireball = spell_action(wizard.require_sheet(), "fireball", 3)
    facts = resolve(f, f.battle.require_combatant("wiz"), fireball, [goblins[0]])
    assert [goblin.hp.current for goblin in goblins] == [0, *(goblins[1].hp.maximum - 8,) * 3]
    assert [goblin.withdrawal for goblin in goblins] == [None, *("surrendered",) * 3]
    traces = [fact.trace for fact in facts]
    morale = [index for index, trace in enumerate(traces) if trace.startswith("morale of")]
    harmed = [index for index, trace in enumerate(traces) if "takes 8 fire damage" in trace]
    assert len(morale) == 1
    assert len(harmed) == 4
    assert morale[0] > harmed[-1]


def test_one_repeat_save_ends_every_condition_of_the_same_spell() -> None:
    f = _fight(ScriptedDice(20), ("bandit", "bandit", "front"))
    save = SaveSpec(ability="wisdom", dc=13)
    f.battle.effects.extend(
        Effect(
            holder_id="bandit",
            source_id="cleo",
            effect_id="hideous-laughter",
            condition=condition,
            save_ends=save,
        )
        for condition in ("prone", "incapacitated")
    )
    facts = repeat_saves(f, f.battle.require_combatant("bandit"))
    assert f.battle.effects == []
    assert len([fact for fact in facts if fact.dice]) == 1


def test_a_halved_roll_halves_its_total() -> None:
    rolled = DamageRoll(
        dealt=(Dealt(amount=7, damage_type="fire"), Dealt(amount=5, damage_type="cold")), dice=()
    )
    assert sum(part.amount for part in rolled.halved().dealt) == 6


def test_a_reduction_comes_before_resistance_and_the_cantrip_once_per_turn() -> None:
    f = _fight(SteadyDice(4), ("bandit", "bandit", "front"))
    at = f.battle.require_combatant
    f.battle.effects.extend(
        Effect(holder_id="ann", source_id="cleo", effect_id=effect_id, damage_type="piercing")
        for effect_id in ("resistance", "protection-from-energy")
    )
    hp = f.require_member("ann").require_sheet().vitals.hp
    hp.current = hp.maximum = 40
    parts = (Dealt(amount=5, damage_type="piercing"), Dealt(amount=6, damage_type="piercing"))
    _, facts = take_damage(f, at("bandit"), at("ann"), DamageRoll(dealt=parts, dice=()))
    _ = take_damage(f, at("bandit"), at("ann"), DamageRoll(dealt=parts, dice=()))
    assert hp.current == 40 - (11 - 4) // 2 - 11 // 2
    assert any(fact.card.endswith("-2 damage") for fact in facts)


def test_ghoul_claws_spare_an_elf() -> None:
    elf = member("ann", species_id="elf", subspecies_id="elven-lineage-drow")
    elf.require_sheet().inspiration = False
    f = fight([(elf, "front")], [foe("ghoul", "ghoul")], ScriptedDice(19, 2, 1))
    claw = stat_block_action(srd().require_stat_block("ghoul").require_action("claw"))
    _ = resolve(f, f.battle.require_combatant("ghoul"), claw, [f.battle.require_combatant("ann")])
    assert not f.battle.has_condition("ann", "paralyzed")
