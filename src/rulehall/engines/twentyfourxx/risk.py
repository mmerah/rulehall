from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple, Self

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.prompt import sentence
from rulehall.core.validation import Refusal, Slug
from rulehall.engines.twentyfourxx.args import DefendHit, Helper, Roll, Staked
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
            if not helper.risk:
                helper = helper.model_copy(
                    update={
                        "risk": args.risk,
                        "harm": args.harm,
                        "deadly": args.deadly,
                        "setback_hurt": args.setback_hurt,
                    }
                )
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
        pool = cls(roll=args, actor=actor, helper=helper_die, faces=tuple(faces), label=label)
        world.check_defenses(
            [
                (who, stake.defend.item_id, stake.defend.hindrance)
                for who, stake in pool.stakes()
                if stake.defend is not None
            ]
        )
        return pool

    def stakes(self) -> list[tuple[Crewmate, Staked]]:
        staked: list[tuple[Crewmate, Staked]] = [(self.actor, self.roll)]
        if self.helper is not None:
            staked.append((self.helper.who, self.helper.terms))
        return staked

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
        staked = line
        if helper is not None and (terms := helper.terms).risk:
            risked = risk_text(terms.risk, harm=terms.harm, deadly=terms.deadly)
            staked += f", {helper.who.name} risking {risked}"
        return line, f"{staked}, risking {risk_text(args.risk, harm=args.harm, deadly=args.deadly)}"


def defend_or_land(
    draft: TwentyFourXXGame, pool: DicePool, rolled: DiceEvent, choices: dict[Slug, Slug | None]
) -> list[Fact]:
    band = roll_band(max(rolled.rolled))
    for who, stake in pool.stakes():
        hurt = (band == "disaster" and stake.harm) or (band != "success" and stake.deadly)
        defences = draft.world.defences_for(who)
        if not hurt or stake.defend is not None or who.id in choices or not defences:
            continue
        hit = (
            f"{who.name} is maimed"
            if band == "setback"
            else f"{sentence(stake.risk)} hits {who.name}"
        )
        draft.pending = defence_decision(
            f"{pool.roll.what}: {band}. {hit}.",
            DefendHit(roll=pool.roll, rolled=rolled, choices=choices),
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
    line, staked = pool.lines()
    facts = [pool.actor.fact(f"{staked} → {band}", card=f"{line} → {band}", dice=(rolled,))]
    if band != "success":
        # Hits land helper-first, the reverse of the actor-first claims checked before.
        for who, stake in reversed(pool.stakes()):
            defend = stake.defend
            item_id = None if defend is None else defend.item_id
            hindrance = "" if defend is None else defend.hindrance
            if (chosen := choices.get(who.id)) is not None:
                harmless = world.require_gear(who, chosen).harmless
                hurt = lesser_hurt(stake.setback_hurt, deadly=stake.deadly)
                item_id, hindrance = chosen, "" if harmless else hurt
            facts.extend(
                world.take_hit(
                    who,
                    item_id,
                    hindrance,
                    risk=stake.risk,
                    setback_hurt=stake.setback_hurt,
                    disaster=band == "disaster",
                    deadly=stake.deadly,
                    harm=stake.harm,
                )
            )
    if any(chosen is not None for chosen in choices.values()):
        facts.append(Fact(trace=GEAR_TOOK_THE_HIT))
    return facts
