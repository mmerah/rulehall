import re
from collections.abc import Sequence

from pydantic import Field

from rulehall.core.prompt import Prompt, lines_of, sections
from rulehall.core.tools import render_schema
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.lite5e.battle.foes import bare_plan, gauge_band, health_band
from rulehall.engines.lite5e.battle.state import Battle, Fight, FoeCombatant, MemberCombatant
from rulehall.engines.lite5e.battle.turns import ROUND
from rulehall.engines.lite5e.data import StatBlock, StatBlockAction
from rulehall.engines.lite5e.rules import ABILITIES
from rulehall.engines.sheet import Gauge

ROLE = "You play the foes in a battle against the party of {party}."
TASK = (
    "Each call names the foes whose turns come before the party acts again. Pick one plan for "
    "each of them from THE CHOICES. Aim to win the battle: drop the party's members and keep "
    "your foes standing. Before you answer, check who is hurt, who is in reach, and what each "
    "stat block does best. Answer with JSON only."
)
HOW_A_BATTLE_WORKS = (
    "- There is no grid. Each side has a front row and a back row. When a side's front row has "
    "no active creature, its back row counts as its front row.",
    "- Range bands: a creature in your own row is close, and your own other row is near. Your "
    "front row to the enemy front row is close; your front row to the enemy back row, or your "
    "back row to the enemy front row, is near; your back row to the enemy back row is far.",
    "- Melee reaches close. A reach of 10 ft also reaches near, from your back row onto the "
    "enemy front row only. A range of 30 ft or less reaches near; a longer range reaches far.",
    "- A ranged attack from your front row has disadvantage while the enemy front row has an "
    "active creature.",
    "- A creature that moves from its front row to its back row while the enemy front row has "
    "an active creature takes an opportunity attack, unless it disengages.",
    "- Health bands: unhurt, hurt, bloodied (half HP or less) and down (0 HP). A member who is "
    "down makes death saves; an attack on it has advantage.",
)
PLAN_GRAMMAR = (
    "- Each plan in THE CHOICES is a whole turn: the move when one is needed (`front, ` or "
    "`back, `), then the attack or action and the id of its first target, such as "
    "`scimitar mira` or `back, shortbow rook`. A note in brackets, such as (disadvantage), tells "
    "how the roll goes; you can leave it out.",
    "- `escape` tries to break free of a grapple, a web or a net. `front` only moves to the front "
    "row. `hold` does nothing.",
    "- A foe with bonus plans can add one after a semicolon: `scimitar mira; nimble escape: back`.",
    "- Give one command for each foe, in the order of THE CHOICES, each written as listed there.",
)
LINE_MAX = 120
LINE = (
    "Something one of your foes says aloud, in its own voice, at most one short sentence. Leave "
    "it empty on most calls; speak on a key moment: a member drops, a foe falls, the tide turns."
)
ROUNDS_SHOWN = 2
HP_CHANGE = re.compile(r"(?:HP maximum )?[+-]\d+(?: HP)? → (\d+)/(\d+)")
HP_COUNT = re.compile(r"(?<=temporary HP) \d+| at \d+ HP")


class FoeOffer(Frozen):
    combatant_id: Slug
    name: str
    plans: tuple[str, ...]
    bonus_plans: tuple[str, ...] = ()


class OpponentAnswer(Frozen):
    commands: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "One command for each foe in THE CHOICES, in the same order, each a plan from its "
            'list, with an optional bonus plan after a semicolon: ["scimitar mira"], or '
            '["shortbow rook", "scimitar mira; nimble escape: back"].'
        ),
    )
    line: str = Field(default="", max_length=LINE_MAX, pattern=r"^[^\r\n]*$", description=LINE)


def opponent_system(fight: Fight) -> str:
    party = ", ".join(fight.name_of(member) for member in fight.battle.member_combatants())
    blocks = {foe.stat_block_id: foe.stat_block() for foe in fight.battle.foes()}
    body = sections(
        (
            ("YOUR TASK", TASK),
            ("HOW A BATTLE WORKS", "\n".join(HOW_A_BATTLE_WORKS)),
            ("PLANS", "\n".join(PLAN_GRAMMAR)),
            ("YOUR STAT BLOCKS", "\n\n".join(_block_text(block) for block in blocks.values())),
        )
    )
    return f"{ROLE.format(party=party)}\n\n{body}"


def render_opponent(fight: Fight, offers: Sequence[FoeOffer]) -> Prompt:
    battle = fight.battle
    parts = (
        (
            f"ROUND {battle.round}",
            f"Light: {battle.light}. Cover: {'yes' if battle.cover else 'no'}.",
        ),
        ("YOUR FOES", lines_of(_foe_line(fight, foe) for foe in battle.foes())),
        (
            "THE PARTY",
            lines_of(_member_line(fight, member) for member in battle.member_combatants()),
        ),
        ("RECENT TURNS", lines_of(f"- {_banded(line)}" for line in _recent_rounds(battle))),
        ("THE CHOICES", "\n\n".join(_offer_text(offer) for offer in offers)),
        ("ANSWER WITH", render_schema(OpponentAnswer)),
    )
    return Prompt(system=opponent_system(fight), user=sections(parts))


def check_commands(offers: Sequence[FoeOffer], answer: OpponentAnswer) -> None:
    if len(answer.commands) != len(offers):
        names = ", ".join(offer.name for offer in offers)
        raise Refusal(f"give {len(offers)} commands, one for each of: {names}")
    for offer, command in zip(offers, answer.commands, strict=True):
        plan, semicolon, bonus = (part.strip() for part in command.partition(";"))
        if not _offered(plan, offer.plans):
            raise Refusal(
                f"{plan!r} is not a plan for {offer.name}; pick one of: {', '.join(offer.plans)}"
            )
        if semicolon and not _offered(bonus, offer.bonus_plans):
            instead = (
                f"pick one of: {', '.join(offer.bonus_plans)}"
                if offer.bonus_plans
                else "it has none, so give its plan alone"
            )
            raise Refusal(f"{bonus!r} is not a bonus plan for {offer.name}; {instead}")


def _recent_rounds(battle: Battle) -> list[str]:
    first = ROUND.format(round=max(battle.round - ROUNDS_SHOWN + 1, 1))
    log = battle.log()
    starts = [at for at, line in enumerate(log) if line == first]
    return log[starts[-1] if starts else 0 :]


def _banded(line: str) -> str:
    def band(found: re.Match[str]) -> str:
        return gauge_band(Gauge(current=int(found[1]), maximum=int(found[2])))

    return HP_COUNT.sub("", HP_CHANGE.sub(band, line))


def _offered(text: str, offered: Sequence[str]) -> bool:
    return bare_plan(text) in {bare_plan(plan) for plan in offered}


def _offer_text(offer: FoeOffer) -> str:
    lines = [f"For {offer.name} ({offer.combatant_id}):", *(f"- {plan}" for plan in offer.plans)]
    if offer.bonus_plans:
        lines.append("Bonus plans:")
        lines.extend(f"- {plan}" for plan in offer.bonus_plans)
    return "\n".join(lines)


def _foe_line(fight: Fight, foe: FoeCombatant) -> str:
    head = f"- {foe.name} [{foe.combatant_id}], {foe.stat_block().name}"
    if foe.withdrawal is not None:
        return f"{head}: {foe.withdrawal}"
    if foe.hp.current == 0:
        return f"{head}: down"
    hp = f"HP {foe.hp.current}/{foe.hp.maximum}"
    return f"{head}, {foe.row} row, {hp}{_conditions(fight, foe.combatant_id)}"


def _member_line(fight: Fight, member: MemberCombatant) -> str:
    head = f"- {fight.name_of(member)} [{member.combatant_id}]"
    if fight.is_dead(member):
        return f"{head}: dead"
    if member.withdrawal == "left":
        return f"{head}: left the battle"
    band = health_band(fight, member)
    return f"{head}, {member.row} row, {band}{_conditions(fight, member.combatant_id)}"


def _conditions(fight: Fight, holder_id: Slug) -> str:
    conditions = fight.battle.conditions_on(holder_id)
    return f", {', '.join(conditions)}" if conditions else ""


def _block_text(block: StatBlock) -> str:
    scores = ", ".join(f"{ability[:3].upper()} {block.scores[ability]}" for ability in ABILITIES)
    lines = [
        f"{block.name} ({block.size} {block.creature_type}): AC {block.armor_class}, "
        f"HP {block.hit_points}, Speed {block.speed}",
        scores,
    ]
    for label, values in (
        ("Vulnerable", block.damage_vulnerabilities),
        ("Resists", block.damage_resistances),
        ("Immune", (*block.damage_immunities, *block.condition_immunities)),
        ("Traits", tuple(special.special_id for special in block.specials)),
    ):
        if values:
            lines.append(f"{label}: {', '.join(values)}")
    if block.multiattack is not None:
        lines.append(f"Multiattack: {block.multiattack.total} attacks")
    lines.extend(f"- {_entry_text(entry)}" for entry in block.actions)
    lines.extend(f"- Bonus action: {_entry_text(entry)}" for entry in block.bonus_actions)
    if block.death_burst is not None:
        lines.append(f"- On death: {_entry_text(block.death_burst)}")
    return "\n".join(lines)


def _entry_text(entry: StatBlockAction) -> str:
    if entry.kind == "save":
        where = (
            f"{entry.area.feet}-ft {entry.area.shape}"
            if entry.area is not None
            else f"range {entry.range_feet} ft"
        )
        head = (
            f"{entry.name} [{entry.action_id}]: {entry.ability} save DC {entry.dc}, {where}, "
            f"{entry.success} on a success"
        )
    else:
        reach = (
            f"reach {entry.reach_feet} ft" if entry.reach_feet is not None else ""
        ) or f"range {entry.range_feet} ft"
        head = f"{entry.name} [{entry.action_id}]: {entry.kind}, +{entry.to_hit} to hit, {reach}"
    damage = " + ".join(part.text() for part in entry.damage)
    riders = ", ".join(
        " ".join(filter(None, (rider.rider_id, rider.condition))) for rider in entry.riders
    )
    limits = (
        *(() if entry.usage.recharge_min is None else (f"recharge {entry.usage.recharge_min}-6",)),
        *(() if entry.usage.uses_per_day is None else (f"{entry.usage.uses_per_day}/day",)),
    )
    return ", ".join(part for part in (head, damage, riders and f"also {riders}", *limits) if part)
