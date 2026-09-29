from collections.abc import Iterable, Sequence

from pydantic import Field

from rulehall.core.prompt import Prompt, lines_of, sections
from rulehall.core.tools import render_schema
from rulehall.core.validation import Frozen, Loose, Refusal
from rulehall.core.views import BattleChoice
from rulehall.engines.pokemon.battle.choices import Hand
from rulehall.engines.pokemon.battle.models import STATUSES, BattleSetup, RoleSeat

FOE_ROLE = "You are {name}, a Pokemon trainer, in a battle against {foes}."
ALLY_ROLE = "You are {name}, a Pokemon trainer. You fight beside {player} against {foe}."
TASK = (
    "Pick your choice for this turn, one for each of your Pokemon in battle. The damage ranges "
    "are exact: the least and the most HP a move takes, with no critical hit. Aim to win the "
    "battle: knock out your foes' Pokemon, keep yours alive, and switch when your Pokemon can do "
    "little. Answer with JSON only."
)
LINE_MAX = 120
LINE = (
    "Something you say aloud this turn, in your style, at most one short sentence. Leave it empty "
    "on most turns; speak on a key moment: a knock-out, your last Pokemon, a turn-around."
)


class SeenMove(Loose):
    name: str
    type: str


class Threat(SeenMove):
    user: str
    damage: tuple[int, int] | None


class Hit(Loose):
    target: int
    name: str
    damage: tuple[int, int] | None
    percent: tuple[int, int] | None

    @property
    def low(self) -> int:
        return 0 if self.percent is None else self.percent[0]


class OwnMove(SeenMove):
    pp: int
    maxpp: int
    disabled: bool
    multihit: int | tuple[int, int] | None
    target: str
    hits: tuple[Hit, ...]


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
    threats: tuple[Threat, ...]


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


class Offer(Frozen):
    mon_name: str
    choices: tuple[BattleChoice, ...]


class OpponentAnswer(Frozen):
    commands: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "One command for each Pokemon in THE CHOICES, in the same order, as written there: "
            '["move 2"], or ["move 1 2", "switch 3"].'
        ),
    )
    # One protocol line: a newline would break it, and a leading slash is a chat command.
    line: str = Field(
        default="", max_length=LINE_MAX, pattern=r"^([^/\r\n][^\r\n]*)?$", description=LINE
    )


def render_opponent(
    setup: BattleSetup,
    seat: RoleSeat,
    assessment: Assessment,
    offers: Sequence[Offer],
    hand: Hand,
) -> Prompt:
    team = lines_of(_own_line(mon) for mon in assessment.team if mon.slot - 1 in hand)
    foes = lines_of(_seen_line(mon) for mon in assessment.foes)
    offered = "\n".join(
        f"For {offer.mon_name}:\n"
        + lines_of(f"- {choice.command}: {choice.name}" for choice in offer.choices)
        for offer in offers
    )
    ally = setup.ally
    if seat == "foe":
        against = setup.player_name if ally is None else f"{setup.player_name} and {ally.name}"
        role, style = FOE_ROLE.format(name=setup.foe_name, foes=against), setup.foe_style
    else:
        assert ally is not None
        player, foe = setup.player_name, setup.foe_name
        role, style = ALLY_ROLE.format(name=ally.name, player=player, foe=foe), ally.style
    return Prompt(
        system=f"{role} {TASK} Your style: {style}" if style else f"{role} {TASK}",
        user=sections(
            (
                ("YOUR POKEMON", team),
                ("YOUR FOES' POKEMON", foes),
                ("THE CHOICES", offered),
                ("ANSWER WITH", render_schema(OpponentAnswer)),
            )
        ),
    )


def check_commands(offers: Sequence[Offer], answer: OpponentAnswer) -> None:
    if len(answer.commands) != len(offers):
        names = ", ".join(offer.mon_name for offer in offers)
        raise Refusal(f"give {len(offers)} commands, one for each of: {names}")
    for offer, command in zip(offers, answer.commands, strict=True):
        offered = [choice.command for choice in offer.choices]
        if command not in offered:
            raise Refusal(
                f"{command!r} is not a choice for {offer.mon_name}; pick one of: "
                f"{', '.join(offered)}"
            )
    switches = [command for command in answer.commands if command.startswith("switch ")]
    if len(set(switches)) < len(switches):
        raise Refusal("two of your Pokemon cannot switch to the same Pokemon")


def greedy_choice(assessment: Assessment, choices: Sequence[BattleChoice], slot: int) -> str:
    team = {mon.slot: mon for mon in assessment.team}
    # The actives lead the team, in field order: field slot 0 is team slot 1.
    active = team.get(slot + 1)
    partnered = any(mon.active and mon.hp > 0 and mon.slot != slot + 1 for mon in assessment.team)
    spread = {
        f"move {number}"
        for number, move in enumerate(() if active is None else active.moves, 1)
        if partnered and move.target == "allAdjacent"
    }
    allowed = [choice.command for choice in choices if not choice.refusal]
    offered = [command for command in allowed if command not in spread] or allowed
    hits = {
        command: _aimed_hits(active, command)
        for command in offered
        if active is not None and command.startswith("move ")
    }
    lows = {command: low for command, aimed in hits.items() if (low := _best_low(aimed)) > 0}
    bench = {
        command: low
        for number, command in _numbered(offered, "switch").items()
        if (low := _best_low(hit for move in team[number].moves for hit in move.hits)) > 0
    }
    # The player's actives lead their team too: target 1 is the first foe.
    knockouts = [
        command
        for command in lows
        if any(
            hit.low > 0 and hit.low >= assessment.foes[hit.target - 1].percent
            for hit in hits[command]
        )
    ]
    if knockouts:
        return knockouts[0]
    best = max(lows, key=lows.__getitem__, default=None) or max(
        bench, key=bench.__getitem__, default=None
    )
    return best or offered[0]


def _own_line(mon: OwnMon) -> str:
    head = f"- {mon.slot}. {_headline(mon.name, mon.level, mon.types, mon.status, mon.boosts)}"
    if mon.hp == 0:
        return f"{head}, fainted"
    moves = "; ".join(_move_text(move) for move in mon.moves)
    lines = [f"{head}, {mon.hp}/{mon.maxhp} HP" + (" (active)" if mon.active else "")]
    lines.append(f"  moves: {moves}")
    for user in dict.fromkeys(threat.user for threat in mon.threats):
        takes = "; ".join(
            f"{threat.name} {_damage_text(threat.damage)}"
            for threat in mon.threats
            if threat.user == user
        )
        lines.append(f"  takes from {user}: {takes}")
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


def _move_text(move: OwnMove) -> str:
    text = f"{move.name} ({move.type}, {move.pp}/{move.maxpp} PP)"
    if move.disabled:
        return f"{text} disabled"
    count = ""
    if isinstance(move.multihit, tuple):
        count = f" a hit, {_range(move.multihit)} hits"
    elif move.multihit is not None:
        count = f" a hit, {move.multihit} hits"
    dealt = ", ".join(
        f"{_range(hit.damage)} HP{count} to {hit.name} ({_range(hit.percent)}% of its full HP)"
        for hit in move.hits
        if hit.damage is not None and hit.percent is not None
    )
    return f"{text} {dealt or 'no damage'}"


def _numbered(commands: Sequence[str], verb: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for command in commands:
        head, _, number = command.partition(" ")
        if head == verb:
            found[int(number)] = command
    return found


def _aimed_hits(mon: OwnMon, command: str) -> tuple[Hit, ...]:
    _, number, *target = command.split()
    hits = mon.moves[int(number) - 1].hits if int(number) <= len(mon.moves) else ()
    return tuple(hit for hit in hits if not target or hit.target == int(target[0]))


def _best_low(hits: Iterable[Hit]) -> int:
    return max((hit.low for hit in hits), default=0)


def _damage_text(damage: tuple[int, int] | None) -> str:
    return "no damage" if damage is None else f"{_range(damage)} HP"


def _range(pair: tuple[int, int]) -> str:
    low, high = pair
    return f"{low} to {high}"
