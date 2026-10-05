from collections.abc import Iterable, Mapping, Sequence

from pydantic import Field

from rulehall.core.prompt import Prompt, lines_of, section_if, sections
from rulehall.core.tools import render_schema
from rulehall.core.validation import Frozen, Refusal
from rulehall.core.views import BattleChoice
from rulehall.engines.pokemon.battle.assessment import (
    AimedHit,
    Assessment,
    Effect,
    Hit,
    OwnMon,
    OwnMove,
    SeenMon,
    SeenMove,
    StatLine,
)
from rulehall.engines.pokemon.battle.choices import Hand
from rulehall.engines.pokemon.battle.history import (
    FIELD_WORDS,
    STAT_WORDS,
    STATUS_WORDS,
    hp_percent,
    recent_turns,
)
from rulehall.engines.pokemon.battle.models import Battler, BattleSetup, RoleSeat
from rulehall.engines.pokemon.dex import ITEMS, Move, dex

FOE_ROLE = "You are {name}, a Pokemon trainer, in a battle against {foes}."
ALLY_ROLE = "You are {name}, a Pokemon trainer. You fight beside {player} against {foe}."
TASK = (
    "Each turn you get the state of the battle and pick one command for each of your Pokemon "
    "listed in THE CHOICES. Aim to win the battle: knock out every foe Pokemon and keep yours "
    "alive. Before you answer, check who moves first, which move knocks out or hurts the most, "
    "and what the foe will likely do. Answer with JSON only."
)
HOW_A_BATTLE_WORKS = (
    "- Each trainer has a team of up to 6 Pokemon. Only the Pokemon on the field fight; the "
    "others wait on the bench.",
    "- Each turn, every trainer picks one command for each of their Pokemon on the field: use one "
    "of its moves, or switch it with a Pokemon from the bench. Then the turn plays out.",
    "- Order in a turn: switches happen first. Then the moves go by priority: a move with a "
    "higher priority (Quick Attack is +1) always goes before one with a lower priority. Within "
    "the same priority, the Pokemon with the higher Speed moves first; a tie is random. "
    "Paralysis halves Speed, Tailwind doubles it, and under Trick Room the slowest moves first.",
    "- HP: a Pokemon at 0 HP faints (it is knocked out, a KO) and cannot fight again this battle. "
    "A trainer whose Pokemon have all fainted loses. When one of yours faints, you send in "
    "another from the bench before the next turn.",
    "- Damage: physical moves use the user's Attack against the target's Defense; special moves "
    "use Sp. Atk against Sp. Def. Status moves deal no damage: they change stats, cause a "
    "status or change the field. A move of one of the user's own types does 1.5x.",
    "- Types: a move does 2x on a target weak to its type (4x if both of the target's types are "
    "weak), 0.5x on a target that resists it (0.25x if both resist), and nothing on an immune "
    "type (no effect). See the TYPE CHART.",
    "- Each hit rolls between 85% and 100% of its full damage. A critical hit (rare) does 1.5x. "
    "A move with less than 100% accuracy can miss.",
    "- Stat stages: some moves raise or lower Attack, Defense, Sp. Atk, Sp. Def, Speed, "
    "accuracy or evasion by stages, from -6 to +6. +1 is 1.5x, +2 is 2x, -1 is 2/3x. Stages "
    "reset when the Pokemon leaves the field.",
    "- Status (one at a time, it stays after a switch): burned (loses 1/16 HP each turn, its "
    "physical moves do half damage), poisoned (loses 1/8 HP each turn), badly poisoned (loses "
    "more each turn), paralysed (Speed halved, 25% chance to lose its turn), asleep (cannot move "
    "for 1 to 3 turns), frozen (cannot move until it thaws, 20% chance each turn).",
    "- Short effects such as confusion, Leech Seed, Taunt or a Substitute end when the Pokemon "
    "leaves the field. Hazards such as Stealth Rock or Spikes stay on a side and hurt each of "
    "its Pokemon that comes in.",
    "- Each Pokemon has one ability and may hold one item; both can change damage, Speed or "
    "give effects. You know your own. A foe's ability and item show only once revealed in the "
    "battle.",
    "- Switching costs the turn of the Pokemon that switches. The Pokemon that comes in takes "
    "the moves aimed at the one that left.",
)
DOUBLES_RULES = (
    "- Two Pokemon a side are on the field at once, at positions 1 and 2.",
    "- A move aimed at one Pokemon needs a target number in its command: 1 and 2 are the foes at "
    "positions 1 and 2; -1 and -2 are your side's positions (to aim a move at your partner).",
    "- Some moves hit several Pokemon at once: both foes, or everyone else on the field, your "
    "partner included. A move that hits more than one Pokemon does 0.75x to each; the damage "
    "numbers already count this.",
    "- Two attacks on one foe can knock it out when one cannot. Protect blocks moves aimed at "
    "the user for one turn, but it often fails when used two turns in a row.",
)
COMMANDS = (
    "Copy each command exactly as THE CHOICES write it. `move N` uses move N of that Pokemon; "
    "`move N T` uses move N at target T; `switch N` sends in your Pokemon number N from YOUR "
    "POKEMON. Give one command for each Pokemon in THE CHOICES, in their order. Two of your "
    "Pokemon cannot switch to the same Pokemon."
)
READING_THE_STATE = (
    "- Damage is a percent of the target's current HP, from the lowest to the highest damage "
    "roll, with no critical hit, if the move hits. KO: even the lowest roll knocks it out. KO on "
    "a high roll: only some rolls do. Protect, a Substitute, or a foe's ability or item not "
    "revealed yet can change it.",
    "- THE CHOICES give the damage of each move of your Pokemon on the field. YOUR BENCH DAMAGE "
    "gives what your bench Pokemon would deal if they came in.",
    "- DAMAGE YOU TAKE gives what each foe move seen so far would do to your Pokemon. A foe may "
    "have moves not seen yet.",
    "- Foe stats are estimates from species and level; the real ones can differ a little.",
    "- SPEED ORDER lists the Pokemon on the field in the order they move this turn. Their Speed "
    "counts stat stages, paralysis, Tailwind and known items and abilities.",
    "- SUGGESTION is what a simple rule would pick: a sure KO first, else the most damage, else "
    "a switch to the bench Pokemon that hits hardest. It ignores Speed, status moves and what "
    "the foe will do. Take it as a hint only.",
)
TACTICS = (
    "- First look for a knock-out: a move marked KO does at least the target's remaining HP. A "
    "sure KO is better than a stronger move that needs a high roll.",
    "- Check the SPEED ORDER: a faster foe that can knock your Pokemon out stops your move. "
    "Use a priority move, or see the switch rule below.",
    "- Use moves that are super effective; avoid moves the target resists or is immune to.",
    "- Staying in and attacking is the default. Switch only to dodge a sure knock-out, and only "
    "when a bench Pokemon takes clearly less damage; DAMAGE YOU TAKE shows how your bench "
    "Pokemon would fare. A switch costs the turn.",
    "- A Pokemon that just came in stays and fights. Do not switch it out again.",
    "- Status and stat-raising moves pay off early, while your Pokemon is healthy and safe. "
    "When it is in danger, attack.",
    "- A foe likely has moves of its own types, even if you have not seen them yet.",
)
LINE_MAX = 120
LINE = (
    "Something you say aloud this turn, in your style, at most one short sentence. Leave it empty "
    "on most turns; speak on a key moment: a knock-out, your last Pokemon, a turn-around."
)
TURNS_SHOWN = 3
STAT_NAMES = ("Attack", "Defense", "Sp. Atk", "Sp. Def", "Speed")
EFFECTIVENESS = {
    4.0: "4x super effective",
    2.0: "2x super effective",
    0.5: "0.5x not very effective",
    0.25: "0.25x not very effective",
}
VOLATILE_WORDS = {
    "confusion": "confused: may hurt itself instead of moving",
    "substitute": "behind a Substitute: the doll takes damage in its place",
    "taunt": "taunted: can use only attacking moves",
    "encore": "under Encore: must repeat its last move",
    "leechseed": "seeded: loses 1/8 of its HP each turn to the other side",
    "stall": "used Protect or a like move last turn: another one now will likely fail",
    "disable": "one of its moves is disabled",
    "torment": "tormented: cannot use the same move twice in a row",
    "attract": "in love: often too infatuated to move",
    "yawn": "drowsy: falls asleep at the end of the next turn unless it switches out",
    "perishsong": "under Perish Song: faints in a few turns unless it switches out",
    "curse": "cursed: loses 1/4 of its HP each turn",
    "partiallytrapped": "trapped and hurt each turn by a binding move",
    "trapped": "cannot switch out",
    "focusenergy": "pumped: lands critical hits more often",
    "charge": "charged: its next Electric move does double damage",
    "destinybond": "Destiny Bond: a foe that knocks it out this turn faints too",
    "mustrecharge": "must recharge: cannot act this turn",
    "lockedmove": "locked into its rampage move for a few turns",
    "twoturnmove": "charging a two-turn move",
    "healblock": "cannot heal",
    "aquaring": "Aqua Ring: heals a little each turn",
    "ingrain": "rooted: heals each turn, cannot switch out",
    "magnetrise": "floating: immune to Ground moves",
    "smackdown": "knocked to the ground: Ground moves hit it",
    "saltcure": "salt cured: loses HP each turn",
    "throatchop": "cannot use sound moves",
    "flashfire": "Flash Fire: its Fire moves are powered up",
    "tarshot": "covered in tar: Fire moves do double damage to it",
    "nightmare": "has nightmares: loses 1/4 of its HP each turn while asleep",
    "embargo": "cannot use its held item",
}
OWN_VOLATILE_WORDS = {"choicelock": "locked into one move by its choice item"}
TRICK_ROOM = "trickroom"


class Offer(Frozen):
    slot: int
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


def opponent_system(setup: BattleSetup, seat: RoleSeat) -> str:
    ally = setup.ally
    if seat == "foe":
        against = setup.player_name if ally is None else f"{setup.player_name} and {ally.name}"
        role, style, own = (
            FOE_ROLE.format(name=setup.foe_name, foes=against),
            setup.foe_style,
            setup.foes,
        )
    else:
        assert ally is not None
        player, foe = setup.player_name, setup.foe_name
        role = ALLY_ROLE.format(name=ally.name, player=player, foe=foe)
        style, own = ally.style, ally.team
    head = f"{role} Your style: {style}" if style else role
    doubles = (*DOUBLES_RULES, *_tag_rules(setup, seat)) if setup.double else ()
    body = sections(
        (
            ("YOUR TASK", TASK),
            ("HOW A BATTLE WORKS", "\n".join(HOW_A_BATTLE_WORKS)),
            *section_if("DOUBLE BATTLE", "\n".join(doubles)),
            ("COMMANDS", COMMANDS),
            ("READING THE STATE", "\n".join(READING_THE_STATE)),
            ("TACTICS", "\n".join(TACTICS)),
            ("TYPE CHART", _type_chart()),
            ("YOUR MOVES, ABILITIES AND ITEMS", _glossary(own)),
        )
    )
    return f"{head}\n\n{body}"


def render_opponent(
    setup: BattleSetup,
    seat: RoleSeat,
    assessment: Assessment,
    offers: Sequence[Offer],
    hand: Hand,
    log: Sequence[str],
) -> Prompt:
    doubles = setup.double
    own = _field_first(mon for mon in assessment.team if mon.slot - 1 in hand)
    partner = _field_first(mon for mon in assessment.team if mon.slot - 1 not in hand)
    foes = _field_first(assessment.foes)
    able = sum(mon.hp > 0 for mon in own)
    unseen = f", {assessment.unseen} more not seen yet" if assessment.unseen else ""
    parts = (
        (f"TURN {assessment.turn}", "\n".join(_field_lines(assessment))),
        (
            f"YOUR POKEMON ({able} of {len(own)} can fight)",
            "\n".join(_own_block(mon, doubles=doubles, numbered=True) for mon in own),
        ),
        *section_if(
            f"YOUR PARTNER {setup.player_name.upper()}'S POKEMON",
            "\n".join(_own_block(mon, doubles=doubles, numbered=False) for mon in partner),
        ),
        (
            f"FOE POKEMON ({len(foes)} seen{unseen})",
            lines_of(_foe_block(mon, doubles=doubles) for mon in foes),
        ),
        (
            "RECENT TURNS",
            lines_of(recent_turns(log, _owners(setup, seat), TURNS_SHOWN)),
        ),
        *section_if("YOUR BENCH DAMAGE", _bench_damage(own)),
        ("DAMAGE YOU TAKE", _damage_taken(own)),
        ("SPEED ORDER", _speed_order(assessment, own, partner, foes)),
        ("SUGGESTION", _suggestion(assessment, offers)),
        ("THE CHOICES", _choices(assessment, offers, doubles=doubles)),
        ("ANSWER WITH", render_schema(OpponentAnswer)),
    )
    return Prompt(system=opponent_system(setup, seat), user=sections(parts))


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
    knockouts = [command for command, aimed in hits.items() if any(h.knocks_out for h in aimed)]
    if knockouts:
        return knockouts[0]
    shares = {command: share for command, aimed in hits.items() if (share := _best_share(aimed))}
    bench = {
        command: share
        for number, command in _numbered(offered, "switch").items()
        if (share := _best_share(hit for move in team[number].moves for hit in move.hits))
    }
    best = max(shares, key=shares.__getitem__, default=None) or max(
        bench, key=bench.__getitem__, default=None
    )
    return best or offered[0]


def _tag_rules(setup: BattleSetup, seat: RoleSeat) -> tuple[str, ...]:
    ally = setup.ally
    if ally is None:
        return ()
    if seat == "ally":
        return (
            f"- You play position 2 with your own Pokemon. Your partner {setup.player_name} "
            "plays position 1 with theirs; you cannot command them.",
        )
    return (
        f"- Your foes are two trainers: {setup.player_name} at position 1 and {ally.name} at "
        "position 2, each with their own Pokemon.",
    )


def _type_chart() -> str:
    lines = [
        "How much each attacking type does to each defending type. Any pair not listed does "
        "1x. For a Pokemon with two types, multiply both values."
    ]
    for attacker, matchups in dex().type_chart.items():
        parts = (
            f"{label} on {', '.join(types)}"
            for label, types in (
                ("2x", matchups.strong),
                ("0.5x", matchups.weak),
                ("0x", matchups.none),
            )
            if types
        )
        lines.append(f"- {attacker}: {'; '.join(parts)}")
    return "\n".join(lines)


def _glossary(battlers: Sequence[Battler]) -> str:
    known = dex()
    moves = dict.fromkeys(move.move_id for battler in battlers for move in battler.moves)
    abilities = dict.fromkeys(battler.ability for battler in battlers)
    items = dict.fromkeys(battler.item_id for battler in battlers if battler.item_id)
    return lines_of(
        (
            *(
                f"- {found.name} (move): {_move_facts(found)}"
                for move_id in moves
                if (found := known.moves.get(move_id)) is not None
            ),
            *(f"- {name} (ability): {known.abilities.get(name, '')}" for name in abilities),
            *(
                f"- {ITEMS[item_id].name if item_id in ITEMS else item_id} (held item): "
                f"{known.items.get(item_id.replace('-', ''), '')}"
                for item_id in items
            ),
        )
    )


def _move_facts(move: Move) -> str:
    power = f", power {move.power}" if move.power else ""
    accuracy = "never misses" if move.accuracy is None else f"{move.accuracy}% accuracy"
    return f"{move.type}, {move.category.lower()}{power}, {accuracy}. {move.text}"


def _field_lines(assessment: Assessment) -> tuple[str, str, str]:
    field = (
        *((_effect_text(assessment.weather, lasting=True),) if assessment.weather else ()),
        *((_effect_text(assessment.terrain, lasting=True),) if assessment.terrain else ()),
        *(_effect_text(effect) for effect in assessment.rooms),
    )
    own = [_effect_text(effect) for effect in assessment.own_side]
    foe = [_effect_text(effect) for effect in assessment.foe_side]
    return (
        f"Field: {'; '.join(field) or 'nothing special'}.",
        f"Your side: {'; '.join(own) or 'nothing'}.",
        f"Foe side: {'; '.join(foe) or 'nothing'}.",
    )


def _effect_text(effect: Effect, *, lasting: bool = False) -> str:
    words = FIELD_WORDS.get(effect.id)
    text = effect.name if words is None else f"{words[0]}: {words[1]}"
    if effect.layers > 1:
        text += f" (x{effect.layers})"
    if effect.turns:
        text += f" ({effect.turns} turns left)"
    elif lasting:
        text += " (until a move changes it)"
    return text


def _own_block(mon: OwnMon, *, doubles: bool, numbered: bool) -> str:
    number = f"{mon.slot}. " if numbered else ""
    head = f"- {number}{_named(mon.name, mon.species)}, level {mon.level}, {'/'.join(mon.types)}"
    if mon.hp == 0:
        return f"{head}: fainted"
    shown = VOLATILE_WORDS | OWN_VOLATILE_WORDS
    condition = _condition(mon.status, mon.boosts, mon.volatiles, shown)
    moves = ", ".join(move.name for move in mon.moves)
    return "\n".join(
        (
            f"{head}: {_place(mon.position, doubles=doubles, own=True)}",
            f"  HP {mon.hp}/{mon.maxhp} ({hp_percent(mon.hp, mon.maxhp)}%){condition}",
            f"  Ability: {mon.ability}. Item: {mon.item or 'none'}.",
            f"  Stats: {_stats_text(mon.stats)}. Speed now: {mon.speed}.",
            f"  Moves: {moves}",
        )
    )


def _foe_block(mon: SeenMon, *, doubles: bool) -> str:
    head = f"- {_named(mon.name, mon.species)}, level {mon.level}, {'/'.join(mon.types)}"
    if mon.percent == 0:
        return f"{head}: fainted"
    condition = _condition(mon.status, mon.boosts, mon.volatiles, VOLATILE_WORDS)
    if mon.ability is not None:
        ability = mon.ability
    else:
        ability = f"not revealed yet (it can be {' or '.join(mon.abilities)})"
    item = "not revealed yet" if mon.item is None else mon.item or "none"
    seen = [f"    - {_seen_move_text(move)}" for move in mon.moves]
    return "\n".join(
        (
            f"{head}: {_place(mon.position, doubles=doubles, own=False)}",
            f"  HP {mon.percent}%{condition}",
            f"  Ability: {ability}. Item: {item}.",
            f"  Estimated stats: {_stats_text(mon.stats)}. Speed now: about {mon.speed}.",
            f"  Moves seen:{'' if seen else ' none yet'}",
            *seen,
        )
    )


def _named(name: str, species: str) -> str:
    return name if name == species else f"{name} ({species})"


def _place(position: int, *, doubles: bool, own: bool) -> str:
    if not position:
        return "on the bench"
    if not doubles:
        return "on the field"
    return f"on the field at position {position} (target {'-' if own else ''}{position})"


def _condition(
    status: str, boosts: Mapping[str, int], volatiles: Iterable[str], shown: Mapping[str, str]
) -> str:
    parts = (
        *((f"status: {STATUS_WORDS[status]}",) if status in STATUS_WORDS else ()),
        *(
            (
                "stat stages: "
                + ", ".join(
                    f"{STAT_WORDS.get(stat, stat)} {stages:+d}" for stat, stages in boosts.items()
                ),
            )
            if boosts
            else ()
        ),
        *(shown[volatile] for volatile in volatiles if volatile in shown),
    )
    return "".join(f"; {part}" for part in parts)


def _stats_text(stats: StatLine) -> str:
    return ", ".join(f"{name} {value}" for name, value in zip(STAT_NAMES, stats, strict=True))


def _move_state(move: OwnMove) -> str:
    facts = [move.type, move.category.lower(), f"{move.pp}/{move.maxpp} PP"]
    if move.priority:
        facts.append(f"priority {move.priority:+d}")
    if move.lock:
        facts.append(f"cannot use now: {move.lock}")
    return ", ".join(facts)


def _seen_move_text(move: SeenMove) -> str:
    found = dex().moves.get(move.move_id)
    priority = f" (priority {move.priority:+d})" if move.priority else ""
    facts = "" if found is None else f": {_move_facts(found)}"
    return f"{_seen_move_name(move)}{priority}{facts}"


def _seen_move_name(move: SeenMove) -> str:
    found = dex().moves.get(move.move_id)
    return move.move_id if found is None else found.name


def _field_first[M: OwnMon | SeenMon](mons: Iterable[M]) -> tuple[M, ...]:
    return tuple(sorted(mons, key=lambda mon: (not mon.position, mon.position)))


def _owners(setup: BattleSetup, seat: RoleSeat) -> dict[str, str]:
    own, other = ("p2", "p1") if seat == "foe" else ("p1", "p2")
    owners = {own: "your", other: "the foe's"}
    if seat == "ally" and setup.ally is not None:
        allied = {battler.name for battler in setup.ally.team}
        owners |= {
            f"p1: {battler.name}": "your partner's"
            for battler in setup.team
            if battler.name not in allied
        }
    return owners


def _bench_damage(own: Sequence[OwnMon]) -> str:
    blocks: list[str] = []
    for mon in own:
        if mon.hp == 0 or mon.active:
            continue
        dealt = [
            f"- {move.name} on {_aimed_name(hit)}: {_hit_text(hit)}"
            for move in mon.moves
            for hit in move.hits
        ]
        blocks.append("\n".join((f"{mon.name} (if it came in):", *(dealt or ["- no damage"]))))
    return "\n\n".join(blocks)


def _damage_taken(own: Sequence[OwnMon]) -> str:
    blocks: list[str] = []
    for mon in own:
        if mon.hp == 0:
            continue
        place = "on the field" if mon.active else "if it came in"
        threats = [
            f"- the foe's {threat.user}'s {threat.name}: {_hit_text(threat)}"
            for threat in mon.threats
        ]
        told = threats or ["- no foe move seen yet"]
        blocks.append("\n".join((f"{mon.name} ({place}):", *told)))
    return "\n\n".join(blocks)


def _hit_text(hit: Hit) -> str:
    if hit.shield:
        return f"no effect: its {hit.shield} blocks it"
    percents = hit.percents
    if hit.multiplier == 0:
        return "no effect"
    if percents is None:
        return "no direct damage"
    if hit.one_hit_ko:
        return "KO if it hits: a one-hit KO move"
    low, high = percents
    fewest, most = hit.hits
    parts = [
        f"{low}-{high}%, no KO: its {hit.endured} leaves it at 1 HP"
        if hit.endured
        else "KO"
        if hit.knocks_out
        else f"{low}-{high}%, KO on a high roll"
        if high >= 100
        else f"{low}-{high}%"
    ]
    if most > 1:
        parts.append(f"{fewest} to {most} hits" if fewest != most else f"{most} hits")
    if label := EFFECTIVENESS.get(hit.multiplier):
        parts.append(label)
    return ", ".join(parts)


def _speed_order(
    assessment: Assessment,
    own: Sequence[OwnMon],
    partner: Sequence[OwnMon],
    foes: Sequence[SeenMon],
) -> str:
    trick_room = any(room.id == TRICK_ROOM for room in assessment.rooms)
    racers = [
        *((f"your {mon.name}", str(mon.speed), mon.speed) for mon in own if mon.active and mon.hp),
        *(
            (f"your partner's {mon.name}", str(mon.speed), mon.speed)
            for mon in partner
            if mon.active and mon.hp
        ),
        *(
            (f"the foe's {mon.name}", f"about {mon.speed}", mon.speed)
            for mon in foes
            if mon.active and mon.percent
        ),
    ]
    racers.sort(key=lambda racer: racer[2], reverse=not trick_room)
    lines = [
        "Slowest first: Trick Room is up." if trick_room else "Fastest first.",
        *(f"{rank}. {name}: Speed {speed}" for rank, (name, speed, _) in enumerate(racers, 1)),
    ]
    quick = [
        *(
            f"your {mon.name}'s {move.name} ({move.priority:+d})"
            for mon in own
            if mon.active and mon.hp
            for move in mon.moves
            if move.priority
        ),
        *(
            f"the foe's {mon.name}'s {_seen_move_name(move)} ({move.priority:+d})"
            for mon in foes
            if mon.active and mon.percent
            for move in mon.moves
            if move.priority
        ),
    ]
    if quick:
        lines.append(f"Moves with a priority skip this order: {', '.join(quick)}.")
    return "\n".join(lines)


def _suggestion(assessment: Assessment, offers: Sequence[Offer]) -> str:
    picks: list[str] = []
    for offer in offers:
        command = greedy_choice(assessment, offer.choices, offer.slot)
        name = next(choice.name for choice in offer.choices if choice.command == command)
        picks.append(f"- For {offer.mon_name}: {command} ({name})")
    return "\n".join(picks)


def _choices(assessment: Assessment, offers: Sequence[Offer], *, doubles: bool) -> str:
    team = {mon.slot: mon for mon in assessment.team}
    blocks: list[str] = []
    for offer in offers:
        where = f" at position {offer.slot + 1}" if doubles else ""
        lines = [f"For {offer.mon_name}{where}:"]
        lines.extend(
            f"- {choice.command}: {choice.name}{_choice_facts(choice.command, offer.slot, team)}"
            for choice in offer.choices
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _choice_facts(command: str, slot: int, team: Mapping[int, OwnMon]) -> str:
    verb, number, *target = command.split()
    if verb == "switch" and (mon := team.get(int(number))) is not None:
        return f" ({mon.hp}/{mon.maxhp} HP)"
    user = team.get(slot + 1)
    if verb != "move" or user is None or int(number) > len(user.moves):
        return ""
    move = user.moves[int(number) - 1]
    hits = [hit for hit in move.hits if not target or hit.target == int(target[0])]
    if target and hits:
        return f" ({_move_state(move)}): {_hit_text(hits[0])}"
    dealt = "; ".join(f"{_aimed_name(hit)} {_hit_text(hit)}" for hit in hits)
    return f" ({_move_state(move)})" + (f": {dealt}" if dealt else "")


def _aimed_name(hit: AimedHit) -> str:
    return f"your partner {hit.name}" if hit.target < 0 else hit.name


def _numbered(commands: Sequence[str], verb: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for command in commands:
        head, _, number = command.partition(" ")
        if head == verb:
            found[int(number)] = command
    return found


def _aimed_hits(mon: OwnMon, command: str) -> tuple[AimedHit, ...]:
    _, number, *target = command.split()
    hits = mon.moves[int(number) - 1].hits if int(number) <= len(mon.moves) else ()
    return tuple(
        hit for hit in hits if hit.target > 0 and (not target or hit.target == int(target[0]))
    )


def _best_share(hits: Iterable[AimedHit]) -> int:
    return max((hit.dealt_share for hit in hits if hit.target > 0), default=0)
