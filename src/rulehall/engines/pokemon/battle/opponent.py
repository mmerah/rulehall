from collections.abc import Sequence

from pydantic import Field

from rulehall.core.prompt import Prompt, lines_of, sections
from rulehall.core.tools import schema_text
from rulehall.core.validation import Frozen, Loose, Refusal
from rulehall.core.views import Choice
from rulehall.engines.pokemon.battle.models import STATUSES, BattleSetup

ROLE = (
    "You are {foe}, a Pokemon trainer, in a battle against {player}. Pick your choice for this "
    "turn. The damage ranges are exact: the least and the most HP a move takes, with no critical "
    "hit. Aim to win the battle: knock out the player's Pokemon, keep yours alive, and switch when "
    "your Pokemon can do little. Answer with JSON only."
)


class SeenMove(Loose):
    name: str
    type: str
    damage: tuple[int, int] | None = None


class OwnMove(SeenMove):
    pp: int
    maxpp: int
    disabled: bool
    multihit: int | tuple[int, int] | None
    percent: tuple[int, int] | None


class OwnMon(Loose):
    slot: int
    name: str
    level: int
    types: tuple[str, ...]
    hp: int
    maxhp: int
    status: str
    active: bool
    boosts: dict[str, int]
    moves: tuple[OwnMove, ...]
    threats: tuple[SeenMove, ...]


class SeenMon(Loose):
    name: str
    level: int
    types: tuple[str, ...]
    percent: int
    status: str
    active: bool
    out: bool
    boosts: dict[str, int]
    moves: tuple[SeenMove, ...]


class Assessment(Loose):
    team: tuple[OwnMon, ...]
    foes: tuple[SeenMon, ...]


class OpponentAnswer(Frozen):
    command: str = Field(description='One of THE CHOICES, as written there: "move 2", "switch 3".')


def render_opponent(
    setup: BattleSetup, assessment: Assessment, choices: Sequence[Choice]
) -> Prompt:
    target = next((mon for mon in assessment.foes if mon.active), None)
    target_name = "the player's Pokemon" if target is None else target.name
    team = lines_of(_own_line(mon, target_name) for mon in assessment.team)
    foes = lines_of(_seen_line(mon) for mon in assessment.foes)
    offered = lines_of(f"- {choice.command}: {choice.name}" for choice in choices)
    role = ROLE.format(foe=setup.foe_name, player=setup.player_name)
    return Prompt(
        system=f"{role} Your style: {setup.foe_style}" if setup.foe_style else role,
        user=sections(
            (
                ("YOUR POKEMON", team),
                ("THE PLAYER'S POKEMON", foes),
                ("THE CHOICES", offered),
                ("ANSWER WITH", schema_text(OpponentAnswer)),
            )
        ),
    )


def check_command(choices: Sequence[Choice], answer: OpponentAnswer) -> None:
    offered = [choice.command for choice in choices]
    if answer.command not in offered:
        raise Refusal(f"{answer.command!r} is not a choice; pick one of: {', '.join(offered)}")


def greedy_choice(assessment: Assessment, choices: Sequence[Choice]) -> str:
    offered = [choice.command for choice in choices if not choice.refusal]
    team = {mon.slot: mon for mon in assessment.team}
    active = next((mon for mon in assessment.team if mon.active), None)
    target = next((mon for mon in assessment.foes if mon.active), None)
    lows = {
        command: low
        for number, command in _numbered(offered, "move").items()
        if active is not None and (low := _low(active, number)) > 0
    }
    bench = {
        command: low
        for number, command in _numbered(offered, "switch").items()
        if (low := _best_low(team[number])) > 0
    }
    knockouts = [
        command for command, low in lows.items() if target is not None and low >= target.percent
    ]
    if knockouts:
        return knockouts[0]
    best = max(lows, key=lows.__getitem__, default=None) or max(
        bench, key=bench.__getitem__, default=None
    )
    return best or offered[0]


def _own_line(mon: OwnMon, target_name: str) -> str:
    head = f"- {mon.slot}. {_headline(mon.name, mon.level, mon.types, mon.status, mon.boosts)}"
    if mon.hp == 0:
        return f"{head}, fainted"
    moves = "; ".join(_move_text(move, target_name) for move in mon.moves)
    takes = "; ".join(
        f"{threat.name} {'no damage' if threat.damage is None else f'{_range(threat.damage)} HP'}"
        for threat in mon.threats
    )
    lines = [f"{head}, {mon.hp}/{mon.maxhp} HP" + (" (active)" if mon.active else "")]
    lines.append(f"  moves: {moves}")
    if takes:
        lines.append(f"  takes from {target_name}: {takes}")
    return "\n".join(lines)


def _seen_line(mon: SeenMon) -> str:
    if not mon.out:
        return f"- {mon.name} L{mon.level} {'/'.join(mon.types)}, not sent out yet"
    head = f"- {_headline(mon.name, mon.level, mon.types, mon.status, mon.boosts)}"
    if mon.percent == 0:
        return f"{head}, fainted"
    seen = ", ".join(f"{move.name} ({move.type})" for move in mon.moves) or "none yet"
    where = " (active)" if mon.active else ""
    return f"{head}, {mon.percent}% HP{where}; moves seen: {seen}"


def _headline(
    name: str, level: int, types: Sequence[str], status: str, boosts: dict[str, int]
) -> str:
    text = f"{name} L{level} {'/'.join(types)}"
    if status in STATUSES:
        text += f", {status}"
    if boosts:
        text += ", " + ", ".join(f"{stat} {stages:+d}" for stat, stages in boosts.items())
    return text


def _move_text(move: OwnMove, target_name: str) -> str:
    text = f"{move.name} ({move.type}, {move.pp}/{move.maxpp} PP)"
    if move.disabled:
        return f"{text} disabled"
    if move.damage is None or move.percent is None:
        return f"{text} no damage"
    hits = ""
    if isinstance(move.multihit, tuple):
        hits = f" a hit, {_range(move.multihit)} hits"
    elif move.multihit is not None:
        hits = f" a hit, {move.multihit} hits"
    return (
        f"{text} {_range(move.damage)} HP{hits} to {target_name} "
        f"({_range(move.percent)}% of its full HP)"
    )


def _numbered(commands: Sequence[str], verb: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for command in commands:
        head, _, number = command.partition(" ")
        if head == verb:
            found[int(number)] = command
    return found


def _low(mon: OwnMon, number: int) -> int:
    percent = mon.moves[number - 1].percent if number <= len(mon.moves) else None
    return 0 if percent is None else percent[0]


def _best_low(mon: OwnMon) -> int:
    return max((move.percent[0] for move in mon.moves if move.percent is not None), default=0)


def _range(pair: tuple[int, int]) -> str:
    low, high = pair
    return f"{low} to {high}"
