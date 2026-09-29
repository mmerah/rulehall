from collections.abc import Sequence
from typing import Literal, get_args

from rulehall.engines.pokemon.battle.models import Battle, BattleSetup

type Moment = Literal["first-ball", "clutch", "alone", "critical", "knockout"]

MOMENTS: tuple[Moment, ...] = get_args(Moment.__value__)
HIGHLIGHTS_MAX = 3
CLUTCH_SHARE = 4
FAINTED = "0 fnt"


def battle_highlights(battle: Battle, log: Sequence[str]) -> tuple[str, ...]:
    setup = battle.setup
    found: list[tuple[Moment, str]] = []
    attack: tuple[str, str, str, bool] | None = None
    crits: set[str] = set()
    conditions: dict[str, str] = {}
    fainted: list[str] = []
    on_field: dict[str, str] = {}
    winner = ""
    for line in log:
        _, kind, *fields = line.split("|")
        match kind:
            case "move" if len(fields) >= 3:
                spread = any(field.startswith("[spread]") for field in fields[3:])
                attack = (_ident(fields[0]), fields[1], _ident(fields[2]), spread)
                crits.clear()
            case "turn" | "upkeep":
                attack = None
            case "-crit":
                crits.add(_ident(fields[0]))
            case "switch" | "drag":
                mon = _ident(fields[0])
                conditions[mon] = fields[2]
                if mon.startswith("p1"):
                    on_field[fields[0].partition(":")[0]] = mon
            case "-damage" | "-heal" | "-sethp":
                mon = _ident(fields[0])
                conditions[mon] = fields[1]
                knocked_out = kind == "-damage" and fields[1] == FAINTED and len(fields) == 2
                if knocked_out and attack is not None:
                    user, move, target, spread = attack
                    if mon == user or not (spread or mon == target):
                        continue
                    if mon in crits:
                        text = f"a critical hit from {_shown(setup, user)} knocked out"
                        found.append(("critical", f"{text} {_shown(setup, mon)}"))
                    else:
                        text = f"{_shown(setup, user)} knocked out {_shown(setup, mon)}"
                        found.append(("knockout", f"{text} with {move}"))
            case "faint":
                fainted.append(_ident(fields[0]))
            case "win":
                winner = fields[0]
            case _:
                pass
    knocked_out_foes = sum(mon.startswith("p2") for mon in fainted)
    standing = [mon for mon in on_field.values() if mon not in fainted]
    if winner == setup.player_name and knocked_out_foes == len(setup.foes) and standing:
        for mon in standing:
            hp, _, max_hp = conditions[mon].partition(" ")[0].partition("/")
            if max_hp and int(hp) * CLUTCH_SHARE <= int(max_hp):
                found.append(("clutch", f"{_shown(setup, mon)} won on {hp} HP"))
        fallen = sum(mon.startswith("p1") and not _allied(setup, mon) for mon in fainted)
        own = [mon for mon in standing if not _allied(setup, mon)]
        if len(setup.team) > 1 and fallen == len(setup.team) - 1 and own:
            found.append(("alone", f"{_shown(setup, own[0])} was the last Pokemon standing"))
    if battle.throws and battle.throws[0].caught:
        caught = f"{setup.player_name} caught the wild {setup.foes[0].name}"
        found.append(("first-ball", f"{caught} with the first ball"))
    # A later moment of the same kind ranks first: the fight builds to its end.
    found.reverse()
    ranked = sorted(found, key=lambda moment: MOMENTS.index(moment[0]))
    return tuple(text[:1].upper() + text[1:] for _, text in ranked[:HIGHLIGHTS_MAX])


def _ident(field: str) -> str:
    position, _, name = field.partition(": ")
    return f"{position[:2]}: {name}"


def _shown(setup: BattleSetup, mon: str) -> str:
    side, _, name = mon.partition(": ")
    if _allied(setup, mon):
        assert setup.ally is not None
        return f"{setup.ally.name}'s {name}"
    if side == "p1":
        return name
    return f"the wild {name}" if setup.wild else f"{setup.foe_name}'s {name}"


def _allied(setup: BattleSetup, mon: str) -> bool:
    # A name on both teams counts as the player's: the log cannot tell them apart.
    side, _, name = mon.partition(": ")
    ally = setup.ally
    return (
        side == "p1"
        and ally is not None
        and name in {battler.name for battler in ally.team}
        and name not in {battler.name for battler in setup.team}
    )
