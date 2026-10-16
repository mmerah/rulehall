from collections.abc import Callable
from random import Random

import pytest
from support.lite5e import ScriptedDice
from support.lite5e_battle import fight, foe, lay, member

from rulehall.engines.lite5e.battle.attack import (
    HELP,
    NEXT_ATTACK_ADVANTAGE,
    advantage_of,
    roll_attack,
)
from rulehall.engines.lite5e.battle.specs import (
    ActionSpec,
    weapon_action,
)
from rulehall.engines.lite5e.battle.state import (
    Effect,
    Fight,
)
from rulehall.engines.lite5e.rules import Edge


def _fight(rng: Random | None = None) -> Fight:
    ann = member("ann", weapon_ids=("longsword", "longbow"))
    bo = member("bo", "rogue", weapon_ids=("shortbow",))
    foes = [foe("wolf-1", "wolf"), foe("wolf-2", "wolf"), foe("bandit", "bandit", "back")]
    return fight([(ann, "front"), (bo, "back")], foes, rng or Random(1))


def _weapon(f: Fight, actor_id: str, weapon_id: str) -> ActionSpec:
    return weapon_action(f.require_member(actor_id).require_sheet(), weapon_id, off_hand=False)


def test_advantage_and_disadvantage_cancel() -> None:
    f = _fight()
    at = f.battle.require_combatant
    lay(f, "wolf-1", "prone")
    lay(f, "ann", "poisoned")
    mode, reasons = advantage_of(f, at("ann"), at("wolf-1"), _weapon(f, "ann", "longsword"))
    assert mode == "none"
    assert set(reasons) == {"advantage: target prone", "disadvantage: poisoned"}


def _mark(f: Fight, effect_id: str, source_id: str) -> None:
    f.battle.effects.append(
        Effect(holder_id="wolf-1", source_id=source_id, effect_id=effect_id, uses=1)
    )


SOURCES: list[tuple[str, Callable[[Fight], None], str, str, str, Edge]] = [
    ("prone close", lambda f: lay(f, "wolf-1", "prone"), "ann", "longsword", "wolf-1", "advantage"),
    ("prone far", lambda f: lay(f, "bandit", "prone"), "bo", "shortbow", "bandit", "disadvantage"),
    ("engaged ranged", lambda _: None, "ann", "longbow", "wolf-1", "disadvantage"),
    ("unseen", lambda f: lay(f, "ann", "invisible"), "ann", "longsword", "wolf-1", "advantage"),
    (
        "restrained",
        lambda f: lay(f, "wolf-1", "restrained"),
        "ann",
        "longsword",
        "wolf-1",
        "advantage",
    ),
    (
        "paralyzed",
        lambda f: lay(f, "wolf-1", "paralyzed"),
        "ann",
        "longsword",
        "wolf-1",
        "advantage",
    ),
    (
        "mark",
        lambda f: _mark(f, NEXT_ATTACK_ADVANTAGE, "wolf-2"),
        "ann",
        "longsword",
        "wolf-1",
        "advantage",
    ),
    ("help", lambda f: _mark(f, HELP, "bo"), "ann", "longsword", "wolf-1", "advantage"),
    ("own help", lambda f: _mark(f, HELP, "ann"), "ann", "longsword", "wolf-1", "none"),
]


@pytest.mark.parametrize(
    ("setup", "attacker", "weapon_id", "target", "mode"),
    [case[1:] for case in SOURCES],
    ids=[case[0] for case in SOURCES],
)
def test_each_source_of_advantage(
    setup: Callable[[Fight], None], attacker: str, weapon_id: str, target: str, mode: Edge
) -> None:
    f = _fight()
    setup(f)
    at = f.battle.require_combatant
    assert advantage_of(f, at(attacker), at(target), _weapon(f, attacker, weapon_id))[0] == mode


def test_a_hit_on_a_paralyzed_target_is_critical_only_in_the_close_band() -> None:
    f = _fight(ScriptedDice(15, 15))
    lay(f, "wolf-1", "paralyzed")
    at = f.battle.require_combatant
    close = roll_attack(f, at("ann"), at("wolf-1"), _weapon(f, "ann", "longsword"), "none")
    near = roll_attack(f, at("bo"), at("wolf-1"), _weapon(f, "bo", "shortbow"), "none")
    assert close.critical
    assert near.hit
    assert not near.critical
