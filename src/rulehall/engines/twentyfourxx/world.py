from random import Random
from typing import Annotated

from pydantic import Field

from rulehall.core.creation import ANSWER_MAX
from rulehall.core.facts import Fact, roll
from rulehall.core.game import Game
from rulehall.core.prompt import lines_of
from rulehall.core.validation import Frozen, Refusal, Slug, slug
from rulehall.core.views import Rows
from rulehall.engines.name_leaks import unmet_people_named
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.sheet import PLAYER_ID
from rulehall.engines.twentyfourxx.rules import (
    BRIEF,
    NO_WORK,
    ODD_WORK,
    TWO_JOBS_FOUND,
    brief_hindrance,
    lesser_hurt,
    outcome_band,
)
from rulehall.engines.twentyfourxx.sheet import MAIMED, SHIP_FUNCTIONS, SHIP_IDS, Crewmate, Gear

ALREADY_MAIMED = "{who} is already maimed: the engine writes no second maim"
UPGRADE_COST = 10
ALREADY_BROKEN = "{name} is already broken"
BREAKS_HARMLESSLY = "{name} breaks harmlessly: leave `hindrance` empty"
SHIP_AWAY = "the ship is not here"
LET_GO = "let go from the crew"
NO_PAY_FIGURE = (
    "Name no credit figure: each operator's pay is a d6 rolled when the job is finished."
)
NEW_LEAD = (
    "The player is now {name}; {dead} is dead. Only the hindrances on {name}'s sheet describe "
    "{name}'s body."
)
FIND_FIRST = (
    "no work was looked for since the last job: call `job` `find` first, so the dice decide the "
    "offer, then `take` the job the player agrees to"
)
WORK_AT = "Work at "
TWO_JOBS = (
    "offer two jobs with `direct`; the player picks in their words; `job` `take` records the pick"
)
ODD_JOB = (
    "offer one job with `direct`, and let something about it seem off; write what seems off in "
    "`terms` when the player takes it"
)
NO_JOB = (
    "no work, unless the crew takes a job that leaves them owing somebody: offer that with "
    "`direct`; write the debt in `terms` when the player takes it"
)
JOB_TAKEN = "Job taken"
JOB_OPEN = "a job is open: {job}; call `job` `finish` first if that job is over or failed for good"


class SheetProposal(Frozen):
    """An operator's creation choices. The engine builds the sheet from them: the specialty's
    skills and kit, the origin's increases, traits and body, the starting kit and ₡2."""

    specialty: str = Field(description="One of the specialties in ENGINE GUIDANCE.")
    specialty_skills: str = Field(
        default="",
        description="The specialty's skills option, when it offers one. Empty otherwise.",
    )
    weapon: str = Field(
        default="",
        description="The specialty's weapon option, when it offers one. Empty otherwise.",
    )
    origin: str = Field(description="One of the origins in ENGINE GUIDANCE.")
    traits: tuple[Annotated[str, Field(max_length=ANSWER_MAX)], ...] = Field(
        default=(),
        description="One invented trait for each the origin gives, such as 'wings'. Empty "
        "otherwise.",
    )
    body: str = Field(
        default="", description="The origin's body option, when it offers one. Empty otherwise."
    )
    increases: tuple[Annotated[str, Field(max_length=ANSWER_MAX)], ...] = Field(
        default=(),
        description="One skill for each increase the origin gives: from the skills in ENGINE "
        "GUIDANCE, or one you invent that fits. A skill named twice rises twice.",
    )


class NewcomerProposal(Frozen):
    name: str = Field(min_length=1, description="The operator's name, as the player gave it.")
    brief: str = Field(min_length=1, description="Who they are, in one line.")
    sheet: SheetProposal


class TwentyFourXXSceneProposal(SceneProposal[Crewmate]):
    job: str = Field(
        default="",
        description="The work the player already has when play starts, in the terms they "
        f"agreed to. {NO_PAY_FIGURE} Leave it empty when the player starts with no work. The "
        "player reads this text: name nothing hidden in it.",
    )
    ship_at: str = Field(
        default="",
        description="The `location` where the crew's ship is docked, when that is not the "
        "location of this scene. Empty when the ship is docked here.",
    )


class TwentyFourXXWorld(SceneWorld[Crewmate]):
    job: str = ""
    ship: dict[Slug, Gear] = Field(
        default_factory=lambda: {
            key: Gear(name=name, harmless=name == "Hull armor")
            for key, name in zip(SHIP_IDS, SHIP_FUNCTIONS, strict=True)
        }
    )
    hold: dict[Slug, Gear] = Field(default_factory=dict)
    ship_at: str = ""
    raise_owed: bool = False
    work_rolled: bool = False
    work_found_at: str = ""
    dead_lead: str = ""

    def apply_opening_extras(self, proposal: TwentyFourXXSceneProposal) -> None:
        self.job = proposal.job
        self.ship_at = proposal.ship_at or self.scene.location
        self.hear(self.job)
        self.refuse_unmet_names(self.job)

    def scene_lines(self) -> str:
        return "\n".join(line for line in (super().scene_lines(), self.new_lead_line()) if line)

    def new_lead_line(self) -> str:
        if not self.dead_lead:
            return ""
        return NEW_LEAD.format(name=self.player.name, dead=self.dead_lead)

    def ship_here(self) -> bool:
        return self.ship_at.casefold() == self.scene.location.casefold()

    def dock_here(self) -> None:
        self.ship_at = self.scene.location

    def ship_line(self) -> str:
        return "the ship is docked here" if self.ship_here() else f"the ship is at {self.ship_at}"

    def sheet_rows(self) -> Rows:
        gear = self.player.require_sheet().gear_text()
        rows = self.player.rows()
        return (*rows, ("Gear", gear)) if gear else rows

    def player_line(self) -> str:
        return self.player.line(rows=self.sheet_rows(), gear=False)

    def require_gear(self, actor: Crewmate, item_id: Slug, *, hold: bool = False) -> Gear:
        held = self.hold.get(item_id) if hold and self.ship_here() else None
        item = actor.require_sheet().items.get(item_id) or self.ship.get(item_id) or held
        if item is None:
            raise Refusal(f"{item_id!r} is not among {actor.name}'s items or the ship's functions")
        return item

    def require_function(self, function_id: Slug) -> Gear:
        function = self.ship.get(function_id)
        if function is None:
            raise Refusal(f"{function_id!r} is not a ship function")
        return function

    def defences_for(self, actor: Crewmate) -> list[tuple[Slug, Gear]]:
        ship = self.ship if self.ship_here() else {}
        items = {**actor.require_sheet().items, **ship}
        return [(item_id, gear) for item_id, gear in items.items() if not gear.broken]

    def defend(self, actor_id: Slug | None, item_id: Slug, hindrance: str) -> list[Fact]:
        actor = self.require_actor(actor_id)
        gear = self.require_gear(actor, item_id)
        if item_id in self.ship:
            self.require_ship_here()
        return self._break(actor, gear, hindrance)

    def take_hit(
        self,
        actor: Crewmate,
        item_id: Slug | None,
        hindrance: str,
        *,
        risk: str,
        setback_hurt: str,
        disaster: bool,
        deadly: bool,
        harm: bool,
    ) -> list[Fact]:
        if not disaster and not deadly:
            return (
                actor.hinder(brief_hindrance(lesser_hurt(setback_hurt, deadly=False)))
                if harm
                else []
            )
        if item_id is not None:
            return self._break(actor, self.require_gear(actor, item_id), hindrance)
        if not deadly:
            return actor.change_hindrances([risk], []) if harm else []
        if disaster:
            return self.kill(actor.id)
        if actor.maimed():
            return [actor.fact(ALREADY_MAIMED.format(who=actor.mention))]
        return actor.hinder(MAIMED)

    def end_brief_hindrances(self) -> list[Fact]:
        facts: list[Fact] = []
        for actor in (self.player, *self.hired_party_members()):
            hindrances = actor.require_sheet().hindrances
            if briefs := [hindrance for hindrance in hindrances if hindrance.startswith(BRIEF)]:
                facts.extend(actor.change_hindrances((), briefs))
        return facts

    def _break(self, actor: Crewmate, item: Gear, hindrance: str) -> list[Fact]:
        if item.broken:
            raise Refusal(ALREADY_BROKEN.format(name=item.name))
        if item.harmless:
            if hindrance:
                raise Refusal(BREAKS_HARMLESSLY.format(name=item.name))
            item.broken_times += 1
            trace = f"{actor.mention} breaks {item.name}, harmlessly"
            return [actor.fact(trace, card=actor.card_line(f"{item.name} breaks"))]
        if not hindrance:
            raise Refusal("name the hindrance that the hit becomes")
        hindrance = brief_hindrance(hindrance)
        actor.carry(hindrance)
        item.broken_times += 1
        card = actor.card_line(f"{item.name} breaks — {hindrance}")
        trace = f"{actor.mention} breaks {item.name} — {hindrance}"
        return [actor.fact(trace, card=card)]

    def ship_refusal(self) -> str:
        return "" if self.ship_here() else SHIP_AWAY

    def require_ship_here(self) -> None:
        if refusal := self.ship_refusal():
            raise Refusal(refusal)

    def require_hold_item(self, item_id: Slug) -> Gear:
        item = self.hold.get(item_id)
        if item is None:
            raise Refusal(f"{item_id!r} is not in the ship's hold")
        return item

    def stow_item(self, actor: Crewmate, item_id: Slug) -> list[Fact]:
        self.require_ship_here()
        sheet = actor.require_sheet()
        item = sheet.require_item(item_id, actor.name)
        del sheet.items[item_id]
        self.hold[slug(item.name, self.hold)] = item
        trace = f"{actor.mention} stows {item.name} in the ship's hold"
        card = actor.card_line(f"Stowed {item.name}")
        return [actor.fact(trace, card=card)]

    def retrieve_item(self, actor: Crewmate, item_id: Slug) -> list[Fact]:
        self.require_ship_here()
        items = actor.require_sheet().items
        item = self.require_hold_item(item_id)
        del self.hold[item_id]
        items[slug(item.name, [*items, *SHIP_IDS])] = item
        trace = f"{actor.mention} takes {item.name} from the ship's hold"
        card = actor.card_line(f"Took {item.name} from the hold")
        return [actor.fact(trace, card=card)]

    def lose_hold_item(self, item_id: Slug, why: str) -> list[Fact]:
        item = self.require_hold_item(item_id)
        del self.hold[item_id]
        return [
            Fact(
                trace=f"{item.name} is gone from the ship's hold — {why}",
                told=True,
                card=f"Lost from the hold: {item.name}",
            )
        ]

    def upgrade_ship(self, function_id: Slug, upgrade: str) -> list[Fact]:
        function = self.require_function(function_id)
        self.require_ship_here()
        self.player.pay(UPGRADE_COST)
        function.upgrades.append(upgrade)
        trace = f"the ship's {function.name} is upgraded: {upgrade} (₡{UPGRADE_COST})"
        card = f"{function.name} upgraded: {upgrade} — ₡{UPGRADE_COST}"
        return [self.player.fact(trace, card=card)]

    def take_lead(self, member_id: Slug) -> list[Fact]:
        dead = self.player
        if dead.alive:
            raise Refusal(f"{dead.name} lives and leads")
        member = self.require_actor(member_id)
        if member is dead:
            raise Refusal(f"{dead.name} is dead and cannot lead")
        del self.cast[member.id]
        self.party_ids.remove(member.id)
        self.scene.here_ids.remove(member.id)
        return self.lead(member)

    def lead(self, member: Crewmate) -> list[Fact]:
        dead = self.player
        dead.id = slug(dead.name, [PLAYER_ID, *self.cast])
        member.id = PLAYER_ID
        self.player = member
        self.raise_owed = False
        self.dead_lead = dead.name
        self.cast[dead.id] = dead
        self.scene.here_ids.append(dead.id)
        trace = f"{member.mention} takes the lead; {dead.ref} is dead"
        facts = [member.fact(trace, card=f"{member.name} leads now")]
        carried = dead.require_sheet().items
        if carried:
            stowed = ", ".join(item.name for item in carried.values())
            for item in carried.values():
                self.hold[slug(item.name, self.hold)] = item
            carried.clear()
            trace = f"the crew stows what {dead.name} carried in the ship's hold: {stowed}"
            facts.append(Fact(trace=trace, told=True, card=f"To the hold: {stowed}"))
        if credits := dead.require_sheet().credits:
            dead.require_sheet().credits = 0
            facts.extend(member.earn(credits, giver=dead))
        return facts

    def leave_party(self, entity_id: Slug) -> list[Fact]:
        if entity_id not in self.party_ids:
            return []
        facts = super().leave_party(entity_id)
        member = self.cast[entity_id]
        if not member.has_sheet:
            return facts
        trace = f"{member.ref} is no longer with the crew"
        return [member.fact(trace, card=f"{member.name} leaves the crew")]

    def was_let_go(self, entry: Crewmate) -> bool:
        return entry.has_sheet and entry.alive and entry.id not in self.party_ids

    def last_seen(self, entity_id: Slug) -> str:
        seen = super().last_seen(entity_id)
        return f"{LET_GO}; {seen}" if self.was_let_go(self.cast[entity_id]) else seen

    def here_lines(self) -> str:
        return lines_of(
            other.line(detail=LET_GO if self.was_let_go(other) else "") for other in self.others()
        )

    def hear(self, *texts: str) -> None:
        hidden = self.hidden()
        for person in unmet_people_named("\n".join(texts), self.people()):
            if person.id not in hidden:
                person.known = True

    def enter_if_stranger(self, entity_id: Slug, /) -> list[Fact]:
        return [] if self.find_entity(entity_id) is not None else self.enter(entity_id)

    def require_no_job(self) -> None:
        if self.job:
            raise Refusal(JOB_OPEN.format(job=self.job))

    def find_work(self, where: str, rng: Random) -> list[Fact]:
        self.require_no_job()
        rolled = roll((6,), where, rng)
        face = rolled.face
        result = outcome_band(face, NO_WORK, ODD_WORK, TWO_JOBS_FOUND)
        self.settle(f"{WORK_AT}{where}", result)
        self.work_found_at = where
        return [
            rolled.fact,
            self.player.card_fact(f"{where} — d6 → {result}", (rolled.event,)),
            Fact(trace=outcome_band(face, NO_JOB, ODD_JOB, TWO_JOBS)),
        ]

    def take_job(self, terms: str) -> list[Fact]:
        if not self.job and not self.work_found_at:
            raise Refusal(FIND_FIRST)
        self.settle(JOB_TAKEN, terms)
        self.work_found_at = ""
        amended, self.job = bool(self.job), terms
        if amended:
            return [
                self.player.fact(f"the job's terms change: {terms}", card=f"New job terms\n{terms}")
            ]
        self.work_rolled = False
        return [self.player.fact(f"the job is taken: {terms}", card=f"{JOB_TAKEN}\n{terms}")]

    def close_job(self) -> None:
        self.job = ""


TwentyFourXXNextProposal = NextProposal[Crewmate]


TwentyFourXXGame = Game[TwentyFourXXWorld]
