from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple, Self

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.prompt import sentence
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.twentyfourxx.args import DefendHit, Helper, Roll
from rulehall.engines.twentyfourxx.panels import defence_decision
from rulehall.engines.twentyfourxx.rules import (
    HELP_DIE,
    HINDERED_DIE,
    lesser_hurt,
    risk_text,
    roll_band,
)
from rulehall.engines.twentyfourxx.sheet import Crewmate
from rulehall.engines.twentyfourxx.world import TwentyFourXXGame, TwentyFourXXWorld
from rulehall.engines.world import IS_DEAD

GEAR_TOOK_THE_HIT = (
    "the gear took the hit: do not apply `risk`; the engine removes the brief hindrance at the "
    "next scene"
)


class HelperDie(NamedTuple):
    who: Crewmate
    terms: Helper
    skill: str
    die: int


@dataclass(frozen=True, slots=True)
class DicePool:
    roll: Roll
    actor: Crewmate
    helper: HelperDie | None
    faces: tuple[int, ...]
    label: str

    @classmethod
    def build(cls, world: TwentyFourXXWorld, args: Roll, rulebook_skills: Sequence[str]) -> Self:
        actor = world.require_actor(args.actor_id)
        if not actor.alive:
            raise Refusal(IS_DEAD.format(name=actor.name))
        helper_die = None
        if (helper := args.helped_by) is not None:
            who = world.require_actor(helper.actor_id)
            if who is actor:
                raise Refusal(f"{actor.name} cannot help their own roll")
            rulebook_and_lead_skills = (*rulebook_skills, args.skill)
            helper_skill = who.require_sheet().skill_die(
                helper.skill or args.skill, rulebook_and_lead_skills
            )
            helper_die = HelperDie(who, helper, *helper_skill)

        label, die = actor.require_sheet().skill_die(args.skill, rulebook_skills)
        faces = [HINDERED_DIE if args.hindered else die]
        if args.helped:
            faces.append(HELP_DIE)
        if helper_die is not None:
            faces.append(HINDERED_DIE if helper_die.terms.hindered else helper_die.die)
        return cls(roll=args, actor=actor, helper=helper_die, faces=tuple(faces), label=label)

    def at_risk(self) -> list[Crewmate]:
        return [self.actor] if self.helper is None else [self.actor, self.helper.who]

    def lines(self) -> tuple[str, str]:
        args = self.roll
        line = f"{args.what} — {self.actor.card_line(sentence(self.label))} d{self.faces[0]}"
        if args.helped:
            line += f", helped ({args.helped})"
        if (helper := self.helper) is not None:
            hindered = f", hindered ({helper.terms.hindered})" if helper.terms.hindered else ""
            skill = sentence(helper.skill or "unskilled")
            line += f", helped by {helper.who.name} ({skill} d{self.faces[-1]}{hindered})"
        if args.hindered:
            line += f", hindered ({args.hindered})"
        return line, f"{line}, risking {risk_text(args.risk, harm=args.harm, deadly=args.deadly)}"


def defend_or_land(
    draft: TwentyFourXXGame, pool: DicePool, rolled: DiceEvent, choices: dict[Slug, Slug | None]
) -> list[Fact]:
    roll = pool.roll
    band = roll_band(max(rolled.rolled))
    hurt = (band == "disaster" and roll.harm) or (band != "success" and roll.deadly)
    ship_functions_taken = {item_id for item_id in choices.values() if item_id in draft.world.ship}
    for who in pool.at_risk() if hurt else ():
        defences = [
            (item_id, gear)
            for item_id, gear in draft.world.defences_for(who)
            if item_id not in ship_functions_taken
        ]
        if who.id in choices or not defences:
            continue
        hit = (
            f"{who.name} is maimed"
            if band == "setback"
            else f"{sentence(roll.risk)} hits {who.name}"
        )
        draft.pending = defence_decision(
            f"{roll.what}: {band}. {hit}.",
            DefendHit(roll=roll, rolled=rolled, choices=choices),
            who.id,
            defences,
        )
        return []
    return land(draft, pool, band, rolled, choices)


def land(
    draft: TwentyFourXXGame,
    pool: DicePool,
    band: str,
    rolled: DiceEvent,
    choices: dict[Slug, Slug | None],
) -> list[Fact]:
    world = draft.world
    world.work_rolled = True
    roll = pool.roll
    line, staked = pool.lines()
    facts = [pool.actor.fact(f"{staked} → {band}", card=f"{line} → {band}", dice=(rolled,))]
    if band != "success":
        for who in reversed(pool.at_risk()):
            item_id, hindrance = choices.get(who.id), ""
            if item_id is not None and not world.require_gear(who, item_id).harmless:
                hindrance = lesser_hurt(roll.setback_hurt, deadly=roll.deadly)
            facts.extend(
                world.take_hit(
                    who,
                    item_id,
                    hindrance,
                    risk=roll.risk,
                    setback_hurt=roll.setback_hurt,
                    disaster=band == "disaster",
                    deadly=roll.deadly,
                    harm=roll.harm,
                )
            )
    if any(chosen is not None for chosen in choices.values()):
        facts.append(Fact(trace=GEAR_TOOK_THE_HIT))
    return facts
