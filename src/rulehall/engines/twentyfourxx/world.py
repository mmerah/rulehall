from collections import Counter
from collections.abc import Sequence
from typing import Self, cast

from pydantic import Field

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.model import Game
from rulehall.core.prompt import lines_of
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, slug
from rulehall.core.views import Rows, filled, tag_of
from rulehall.engines.entities import (
    PLAYER_ID,
    Sheeted,
    Thing,
    changed_tags,
    tag_card,
)
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.twentyfourxx.rules import (
    BRIEF,
    DEFAULT_DIE,
    SkillDie,
    brief_hindrance,
    raised,
    spared,
)

STARTING_CREDITS = 2
MAIMED = "Maimed"
ALREADY_MAIMED = "{who} is already maimed: the engine writes no second maim"
GEAR_KEPT = "a setback is a lesser consequence: the gear named for {who} stays whole"
SHIP_FUNCTIONS: tuple[str, ...] = (
    "Comms",
    "Crafts",
    "Drive",
    "Equipment",
    "Hull armor",
    "Sensors",
    "Weapons",
)  # the SRD's seven, in its order
SHIP_IDS: tuple[Slug, ...] = tuple(slug(name, ()) for name in SHIP_FUNCTIONS)
UPGRADE_COST = 10
ALREADY_BROKEN = "{name} is already broken"
BREAKS_HARMLESSLY = "{name} breaks harmlessly. Leave `hindrance` empty"
SHIP_AWAY = "The ship is not here"
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
JOB_TAKEN = "Job taken"
JOB_OPEN = "a job is open: {job}. Call `job` `finish` first if that job is over or failed for good"


class Kit(Frozen):
    name: str
    bulky: bool = False
    breaks: int = Field(default=1, ge=1)
    harmless: bool = False  # SRD: "break harmlessly for defense"


class Gear(Mutable):
    name: str
    bulky: bool = False
    breaks: int = Field(default=1, ge=1)  # a vest breaks once; battle armor "up to 3x"
    broken_times: int = Field(default=0, ge=0)
    upgrades: list[str] = Field(default_factory=list)
    harmless: bool = False

    @property
    def broken(self) -> bool:
        return self.broken_times >= self.breaks

    def notes(self) -> str:
        return ", ".join(self.marks())

    def marks(self) -> tuple[str, ...]:
        parts: list[str] = []
        if self.bulky:
            parts.append("bulky")
        if self.harmless:
            parts.append("breaks harmlessly")
        if self.broken:
            parts.append("broken")
        elif self.breaks > 1 and self.broken_times > 0:
            parts.append(f"broken {self.broken_times}/{self.breaks}")
        parts.extend(f"upgraded: {name}" if name else "upgraded" for name in self.upgrades)
        return tuple(parts)


class CrewSheet(Mutable):
    items: dict[Slug, Gear] = Field(default_factory=dict)
    specialty: str
    origin: str = ""
    traits: tuple[str, ...] = ()  # an alien's two; an android's body
    skills: dict[str, SkillDie] = Field(default_factory=dict)  # keyed by the pack skill's name
    credits: int = Field(default=STARTING_CREDITS, ge=0)
    hindrances: list[str] = Field(default_factory=list)

    def best_skill(self) -> tuple[str, int]:
        return max(self.skills.items(), key=lambda skill: skill[1], default=("", DEFAULT_DIE))

    def rows(self) -> Rows:
        skills = ", ".join(f"{skill} d{die}" for skill, die in self.skills.items())
        return filled(
            ("Specialty", self.specialty),
            ("Origin", self.origin),
            ("Traits", ", ".join(self.traits)),
            ("Skills", skills),
            ("Credits", f"₡{self.credits}"),
            ("Hindrances", ", ".join(self.hindrances)),
        )

    def gear_text(self, *, ids: bool = False) -> str:
        return ", ".join(
            (tag_of(item.name, key) if ids else item.name)
            + (f" ({notes})" if (notes := item.notes()) else "")
            for key, item in self.items.items()
        )

    def require(self, item_id: Slug, owner: str) -> Gear:
        item = self.items.get(item_id)
        if item is None:
            raise Refusal(f"{item_id!r} is not among {owner}'s items")
        return item

    def drop_item(self, item_id: Slug, owner: Thing) -> list[Fact]:
        if (item := self.items.pop(item_id, None)) is None:
            return []
        return [owner.fact(f"{owner.mention} drops {item.name}", card=f"Dropped {item.name}")]


class Crewmate(Sheeted[CrewSheet]):
    def rows(self) -> Rows:
        return self.sheet.rows() if self.sheet is not None else ()

    def line(self, *, rows: Rows | None = None, detail: str = "", gear: bool = True) -> str:
        if gear and self.sheet is not None and (carried := self.sheet.gear_text(ids=True)):
            detail = "; ".join(part for part in (detail, carried) if part)
        return super().line(rows=rows, detail=detail)

    def pay(self, cost: int) -> None:
        sheet = self.require_sheet()
        if cost > sheet.credits:
            raise Refusal(f"{self.name} has only ₡{sheet.credits}, not ₡{cost}")
        sheet.credits -= cost

    def change_hindrances(self, gained: Sequence[str], lost: Sequence[str]) -> list[Fact]:
        sheet = self.require_sheet()
        carried = {hindrance.casefold(): hindrance for hindrance in sheet.hindrances}
        gained = [name for name in gained if name.casefold() not in carried]
        lost = [
            carried.get(name.casefold()) or carried.get(brief_hindrance(name).casefold(), name)
            for name in lost
        ]
        if not gained and not lost:
            return []
        sheet.hindrances = changed_tags(self.name, "hindrance", sheet.hindrances, gained, lost)
        card = tag_card(gained, lost, "Hindered: ", "Recovered: ", joiner=" / ")
        trace = f"{self.mention} — {card}"
        return [self.fact(trace, card=self.card_line(card))]

    def gain_item(self, name: str, *, bulky: bool, breaks: int, cost: int) -> list[Fact]:
        self.pay(cost)
        items = self.require_sheet().items
        items[slug(name, [*items, *SHIP_IDS])] = Gear(name=name, bulky=bulky, breaks=breaks)
        suffix = f" (₡{cost})" if cost > 0 else ""
        card = f"Gained {name}{suffix}"
        trace = f"{self.mention} gains {name}{suffix}"
        return [self.fact(trace, card=self.card_line(card))]

    def repair_item(self, item: Gear, cost: int) -> list[Fact]:
        if item.broken_times == 0:
            raise Refusal(f"{item.name} is not broken")
        self.pay(cost)
        item.broken_times = 0
        trace = f"{self.mention} repairs {item.name}"
        return [self.fact(trace, card=self.card_line(f"Repaired {item.name}"))]

    def spend(self, amount: int, why: str) -> list[Fact]:
        self.pay(amount)
        trace = f"{self.mention} spends ₡{amount} — {why}"
        return [self.fact(trace, card=self.card_line(f"₡{amount} spent — {why}"))]

    def carry(self, hindrance: str) -> bool:
        hindrances = self.require_sheet().hindrances
        if hindrance in hindrances:
            return False
        hindrances.append(hindrance)
        return True

    def hinder(self, name: str) -> list[Fact]:
        if not self.carry(name):
            return []
        return [
            self.fact(
                f"{self.mention} is hindered — {name}",
                card=self.card_line(f"Hindered: {name}"),
            )
        ]

    def maimed(self) -> bool:
        return MAIMED in self.require_sheet().hindrances

    def raise_skill(self, skill: str) -> list[Fact]:
        sheet = self.require_sheet()
        if (new_die := raised(sheet.skills.get(skill))) is None:
            raise Refusal(f"{self.name}'s {skill} is already at d12. Raise another skill for them.")
        sheet.skills[skill] = new_die
        trace = f"{self.mention} — {skill} rises to d{new_die}"
        return [self.fact(trace, card=self.card_line(f"Job done: {skill} d{new_die}"))]

    def earn(
        self, credits: int, *, dice: tuple[DiceEvent, ...] = (), giver: Thing | None = None
    ) -> list[Fact]:
        sheet = self.require_sheet()
        sheet.credits += credits
        source = f" from {giver.name}" if giver is not None else ""
        return [
            self.fact(
                f"{self.mention} earns ₡{credits}{source} → ₡{sheet.credits}",
                card=self.card_line(f"+₡{credits}{source} → ₡{sheet.credits}"),
                dice=dice,
            )
        ]


class TwentyFourXXScene(SceneProposal[Crewmate]):
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
    dead_lead: str = ""

    @classmethod
    def opening(cls, proposal: SceneProposal[Crewmate], player: Crewmate) -> Self:
        world = super().opening(filed_by_name(proposal), player)
        # Safe: the engine's `opening` makes every opening a TwentyFourXXScene.
        opening = cast(TwentyFourXXScene, proposal)
        world.job = opening.job
        world.ship_at = opening.ship_at or world.scene.location
        world.check_unnamed(world.job)
        return world

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
        """The gear stands in the sheet rows already, so the line does not repeat it."""
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
        return [
            (item_id, gear)
            for item_id, gear in actor.require_sheet().items.items()
            if not gear.broken
        ]

    def defend(self, actor_id: Slug | None, item_id: Slug, hindrance: str) -> list[Fact]:
        actor = self.require_actor(actor_id)
        return self._break(actor, self.require_gear(actor, item_id), hindrance)

    def take_hit(
        self,
        actor: Crewmate,
        item_id: Slug | None,
        hindrance: str,
        *,
        risk: str,
        disaster: bool,
        deadly: bool,
        harm: bool,
    ) -> list[Fact]:
        if not disaster and not deadly:
            # SRD: a setback is a lesser consequence, so a harm is already brief and no gear breaks.
            kept = [actor.fact(GEAR_KEPT.format(who=actor.mention))] if item_id else []
            hurt = actor.hinder(brief_hindrance(spared(deadly=False))) if harm else []
            return [*kept, *hurt]
        if item_id is not None:
            item = self.require_gear(actor, item_id)
            return self._break(actor, item, hindrance)
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

    def check_defenses(self, claims: Sequence[tuple[Crewmate, Slug, str]]) -> None:
        resolved = [
            (self.require_gear(actor, item_id), hindrance) for actor, item_id, hindrance in claims
        ]
        # By identity: two actors can claim the same ship function, and Gear is unhashable.
        claimed = Counter(id(item) for item, _ in resolved)
        for item, hindrance in resolved:
            if item.breaks - item.broken_times < claimed[id(item)]:
                raise Refusal(ALREADY_BROKEN.format(name=item.name))
            if item.harmless:
                if hindrance:
                    raise Refusal(BREAKS_HARMLESSLY.format(name=item.name))
                continue
            if not hindrance:
                raise Refusal(f"name the hindrance that {item.name} leaves behind")

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

    def upgrade_refusal(self) -> str:
        if refusal := self.ship_refusal():
            return refusal
        if (credits := self.player.require_sheet().credits) < UPGRADE_COST:
            return f"{self.player.name} has only ₡{credits}, not ₡{UPGRADE_COST}"
        return ""

    def require_hold_item(self, item_id: Slug) -> Gear:
        item = self.hold.get(item_id)
        if item is None:
            raise Refusal(f"{item_id!r} is not in the ship's hold")
        return item

    def stow_item(self, actor: Crewmate, item_id: Slug) -> list[Fact]:
        if refusal := self.ship_refusal():
            raise Refusal(refusal)
        sheet = actor.require_sheet()
        item = sheet.require(item_id, actor.name)
        del sheet.items[item_id]
        self.hold[slug(item.name, self.hold)] = item
        trace = f"{actor.mention} stows {item.name} in the ship's hold"
        card = actor.card_line(f"Stowed {item.name}")
        return [actor.fact(trace, card=card)]

    def retrieve_item(self, actor: Crewmate, item_id: Slug) -> list[Fact]:
        if refusal := self.ship_refusal():
            raise Refusal(refusal)
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
        if refusal := self.upgrade_refusal():
            raise Refusal(refusal)
        self.player.pay(UPGRADE_COST)
        function.upgrades.append(upgrade)
        named = f": {upgrade}" if upgrade else ""
        trace = f"the ship's {function.name} is upgraded{named} (₡{UPGRADE_COST})"
        card = f"{function.name} upgraded{named} — ₡{UPGRADE_COST}"
        return [self.player.fact(trace, card=card)]

    def take_lead(self, member_id: Slug) -> list[Fact]:
        dead = self.player
        if dead.alive:
            raise Refusal(f"{dead.name} lives and leads")
        member = self.require_actor(member_id)
        if member is dead:
            raise Refusal(f"{dead.name} is dead and cannot lead")
        del self.cast[member.id]
        self.party.remove(member.id)
        self.scene.here.remove(member.id)
        return self.lead(member)

    def lead(self, member: Crewmate) -> list[Fact]:
        """The new lead takes the player's id, so no view shows them as someone else."""
        dead = self.player
        dead.id = slug(dead.name, [PLAYER_ID, *self.cast])
        member.id = PLAYER_ID
        self.player = member
        self.raise_owed = False
        self.dead_lead = dead.name
        self.cast[dead.id] = dead
        self.scene.here.append(dead.id)
        trace = f"{member.mention} takes the lead; {dead.tag} is dead"
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
        if entity_id not in self.party:
            return []
        facts = super().leave_party(entity_id)
        member = self.cast[entity_id]
        if not member.hired:
            return facts
        trace = f"{member.tag} is no longer with the crew"
        return [member.fact(trace, card=f"{member.name} leaves the crew")]

    def let_go(self, entry: Crewmate) -> bool:
        return entry.hired and entry.alive and entry.id not in self.party

    def last_seen(self, entity_id: Slug) -> str:
        seen = super().last_seen(entity_id)
        return f"{LET_GO}; {seen}" if self.let_go(self.cast[entity_id]) else seen

    def here_lines(self) -> str:
        return lines_of(
            other.line(detail=LET_GO if self.let_go(other) else "") for other in self.others()
        )

    def check_unnamed(self, *texts: str) -> None:
        """A name told to the player is someone they now know of; only the hidden stay unnamed."""
        self.hear(*texts)
        super().check_unnamed(*texts)

    def hear(self, *texts: str) -> None:
        hidden = self.hidden()
        for person in self.unmet_named(*texts):
            if person.id not in hidden:
                person.known = True

    def file_stranger(self, entity_id: Slug) -> list[Fact]:
        known = entity_id in self.cast or entity_id == self.player.id
        return [] if known else self.enter(entity_id)

    def enter(self, entity_id: Slug) -> list[Fact]:
        """An id the story just named files a met stranger, so play goes on."""
        if entity_id not in self.cast and entity_id != self.player.id:
            name = entity_id.replace("-", " ").title()
            super().check_unnamed(name)
            brief = f"met at {self.scene.title}"
            self.cast[entity_id] = Crewmate(id=entity_id, name=name, brief=brief)
        return super().enter(entity_id)

    def require_no_job(self) -> None:
        if self.job:
            raise Refusal(JOB_OPEN.format(job=self.job))

    def looked_at(self) -> str:
        """Where the last `find` since the last take looked, in any scene; empty when none."""
        for entry in reversed([entry for scene in self.scenes for entry in scene.settled]):
            if entry.question == JOB_TAKEN:
                return ""
            if entry.question.startswith(WORK_AT):
                return entry.question.removeprefix(WORK_AT)
        return ""

    def take_job(self, terms: str) -> list[Fact]:
        """A take while a job is open amends its terms: only `finish` closes it."""
        if not self.job and not self.looked_at():
            raise Refusal(FIND_FIRST)
        self.settle(JOB_TAKEN, terms)
        amended, self.job = bool(self.job), terms
        if amended:
            return [
                self.player.fact(f"the job's terms change: {terms}", card=f"New job terms\n{terms}")
            ]
        self.work_rolled = False
        return [self.player.fact(f"the job is taken: {terms}", card=f"{JOB_TAKEN}\n{terms}")]

    def close_job(self) -> None:
        self.job = ""


TwentyFourXXNext = NextProposal[Crewmate]

TwentyFourXXGame = Game[TwentyFourXXWorld]


def filed_by_name[P: SceneProposal[Crewmate]](proposal: P) -> P:
    """Code names every cast entry, so no id the worldsmith invents reaches the narrator."""
    filed: dict[Slug, Crewmate] = {}
    renamed: dict[str, Slug] = {}
    for key, entry in proposal.cast.items():
        entity_id = PLAYER_ID if key == PLAYER_ID else slug(entry.name, filed)
        renamed[key] = entity_id
        filed[entity_id] = entry.model_copy(update={"id": entity_id})

    def placed(listed: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(renamed.get(name, name) for name in listed)

    return proposal.model_copy(
        update={
            "cast": filed,
            "present": placed(proposal.present),
            "hidden": placed(proposal.hidden),
        }
    )
