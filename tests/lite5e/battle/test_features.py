from random import Random

from support.lite5e_battle import fight, foe, lay, member, play_first_pick

from rulehall.engines.lite5e.battle.actions import HANDLERS, member_aims
from rulehall.engines.lite5e.battle.specs import SpellNumbers
from rulehall.engines.lite5e.battle.state import Effect, Fight, MemberCombatant
from rulehall.engines.lite5e.data import srd
from rulehall.engines.lite5e.rules import FormationRow

TABLE_CAST: tuple[tuple[str, str, str | None], ...] = (
    ("fighter", "dragonborn", "draconic-ancestor-red"),
    ("barbarian", "goliath", "giant-ancestry-clouds-jaunt"),
    ("rogue", "orc", None),
    *(
        (class_id, "human", None)
        for class_id in (
            "cleric",
            "wizard",
            "paladin",
            "ranger",
            "warlock",
            "bard",
            "druid",
            "monk",
            "sorcerer",
        )
    ),
)


def _player(f: Fight) -> MemberCombatant:
    found = f.battle.require_combatant("player")
    assert isinstance(found, MemberCombatant)
    return found


def _table_fight(cast: tuple[str, str, str | None], row: FormationRow, *, formed: bool) -> Fight:
    class_id, species_id, subspecies_id = cast
    hero = member(
        "player",
        class_id,
        species_id,
        subspecies_id=subspecies_id,
        level=5,
        weapon_ids=("shortsword", "dagger", "dagger"),
    )
    sheet = hero.require_sheet()
    for gear_id in ("healers-kit", "alchemists-fire", "potion-of-healing"):
        sheet.add_gear(gear_id, 1)
    hurt, downed = member("ann"), member("cy")
    hurt.require_sheet().vitals.hp.current = 1
    goblins = [foe("goblin-1", "goblin-warrior"), foe("goblin-2", "goblin-warrior")]
    for goblin in goblins:
        goblin.hp.current = 1
    f = fight(
        [(hero, row), (hurt, row), (downed, row)],
        [foe("ogre", "ogre"), *goblins, foe("zombie", "zombie", "back")],
        Random(1),
    )
    downed.require_sheet().vitals.hp.current = 0
    _player(f).turns = 1
    f.battle.cover = True
    f.battle.budget.light_weapon_id = "shortsword"
    lay(f, "ann", "poisoned")
    lay(f, "player", "burning")
    numbers = SpellNumbers(attack_bonus=5, save_dc=13, modifier=3, healing_bonus=3)
    for lasting in srd().battle_actions:
        if lasting.play == "lasting-strike":
            level = srd().require_spell(lasting.action_id).level
            f.battle.effects.append(
                Effect(
                    holder_id="player",
                    source_id="player",
                    effect_id=lasting.action_id,
                    slot_level=level,
                    numbers=numbers,
                )
            )
    if row == "front":
        f.battle.effects.append(
            Effect(holder_id="player", source_id="ogre", effect_id="test", escape_dc=10)
        )
    if formed:
        f.battle.effects.append(
            Effect(
                holder_id="player",
                source_id="player",
                effect_id="wild-shape",
                stat_block_id="wolf",
            )
        )
    return f


def test_every_battle_action_row_plays() -> None:
    rows = srd().battle_actions
    played: set[int] = set()
    commands: set[str] = set()
    for cast in TABLE_CAST:
        for row in ("front", "back"):
            for formed in (False, True) if cast[0] == "druid" else (False,):
                f = _table_fight(cast, row, formed=formed)
                for aim in member_aims(f, _player(f)):
                    if aim.command() in commands:
                        continue
                    _ = play_first_pick(_table_fight(cast, row, formed=formed), aim)
                    commands.add(aim.command())
                    played.add(rows.index(aim.row))
    assert [row.action_id for index, row in enumerate(rows) if index not in played] == []
    assert {row.action_id for row in rows if row.play is None} == set(HANDLERS)


def test_a_healer_s_kit_stabilizes_and_stays_in_the_pack() -> None:
    hero, downed = member("player"), member("cy")
    hero.require_sheet().add_gear("healers-kit", 1)
    f = fight([(hero, "front"), (downed, "front")], [foe("ogre", "ogre")], Random(1))
    downed.require_sheet().vitals.hp.current = 0
    kit = next(aim for aim in member_aims(f, _player(f)) if aim.action_id == "healers-kit")
    _ = play_first_pick(f, kit)
    assert downed.require_sheet().vitals.stable
    assert hero.require_sheet().gear["healers-kit"] == 1
