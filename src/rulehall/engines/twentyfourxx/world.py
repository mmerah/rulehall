from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Self, cast

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.model import Game
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, slug
from rulehall.core.views import Rows, filled, tag_of
from rulehall.engines.entities import OpeningProposal, Sheeted, Thing, joined
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.twentyfourxx.rules import SkillDie, raised

STARTING_CREDITS = 2
MAIMED = "Maimed"
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
SHIP_HERE = (
    "True when the crew's ship is docked here or the crew can reach it from here. "
    "The crew can stow and take gear from its hold only then."
)


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
    upgraded: bool = False
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
        if self.upgraded:
            parts.append("upgraded")
        return tuple(parts)


class CrewSheet(Mutable):
    items: dict[Slug, Gear] = Field(default_factory=dict)
    specialty: str
    origin: str = ""  # empty on a hired member: the worldsmith writes no origin
    traits: tuple[str, ...] = ()  # an alien's two; an android's body
    skills: dict[str, SkillDie] = Field(default_factory=dict)  # keyed by the pack skill's name
    credits: int = Field(default=STARTING_CREDITS, ge=0)
    hindrances: list[str] = Field(default_factory=list)

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
        item = self.require(item_id, owner.name)
        del self.items[item_id]
        return [owner.fact(f"{owner.mention} drops {item.name}", card=f"Dropped {item.name}")]


class Crewmate(Sheeted[CrewSheet]):
    leads: SkipJsonSchema[bool] = False

    @property
    def mention(self) -> str:
        return f"the player {self.tag}" if self.leads else self.tag

    def card_line(self, line: str) -> str:
        return line if self.leads else f"{self.name}: {line}"

    def rows(self) -> Rows:
        return self.sheet.rows() if self.sheet is not None else ()

    def required(self) -> str:
        return joined(super().required(), "not leading" if self.leads else "")

    def line(self, *, rows: Rows | None = None, detail: str = "", gear: bool = True) -> str:
        if gear and self.sheet is not None and (carried := self.sheet.gear_text(ids=True)):
            detail = "; ".join(part for part in (detail, carried) if part)
        return super().line(rows=rows, detail=detail)

    def sign_on(
        self,
        specialty: str,
        skills: Mapping[str, SkillDie],
        items: dict[Slug, Gear],
        hindrances: Sequence[str],
    ) -> str:
        self.sheet = CrewSheet(
            specialty=specialty,
            skills=dict(skills),
            credits=0,
            items=items,
            hindrances=list(hindrances),
        )
        return specialty

    def pay(self, cost: int) -> None:
        sheet = self.require_sheet()
        if cost > sheet.credits:
            raise Refusal(f"{self.name} has only ₡{sheet.credits}, not ₡{cost}")
        sheet.credits -= cost

    def change_hindrances(self, gained: Sequence[str], lost: Sequence[str]) -> list[Fact]:
        sheet = self.require_sheet()
        sheet.hindrances = self.changed_tags("hindrance", sheet.hindrances, gained, lost)
        parts: list[str] = []
        if gained:
            parts.append(f"Hindered: {', '.join(gained)}")
        if lost:
            parts.append(f"Recovered: {', '.join(lost)}")
        card = " / ".join(parts)
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

    def hinder(self, name: str) -> list[Fact]:
        sheet = self.require_sheet()
        if name in sheet.hindrances:
            return []
        sheet.hindrances.append(name)
        return [
            self.fact(
                f"{self.mention} is hindered — {name}",
                card=self.card_line(f"Hindered: {name}"),
            )
        ]

    def raise_skill(self, skill: str) -> list[Fact]:
        sheet = self.require_sheet()
        if (new_die := raised(sheet.skills.get(skill))) is None:
            raise Refusal(f"{self.name}'s {skill} is already at d12. Raise another skill for them.")
        sheet.skills[skill] = new_die
        trace = f"{self.mention} — {skill} rises to d{new_die}"
        return [self.fact(trace, card=self.card_line(f"Job done: {skill} d{new_die}"))]

    def earn(self, credits: int, event: DiceEvent) -> list[Fact]:
        sheet = self.require_sheet()
        sheet.credits += credits
        return [
            self.fact(
                f"{self.mention} earns ₡{credits} → ₡{sheet.credits}",
                card=self.card_line(f"+₡{credits} → ₡{sheet.credits}"),
                dice=(event,),
            )
        ]


class TwentyFourXXScene(SceneProposal[Crewmate]):
    job: str = Field(
        default="",
        description="The work the player already has when play starts, in the terms they "
        "agreed to. Leave it empty when the player starts with no work. The player reads this "
        "text: name nothing hidden in it.",
    )
    ship_here: bool = Field(description=SHIP_HERE)


class TwentyFourXXNext(NextProposal[Crewmate]):
    ship_here: bool = Field(description=SHIP_HERE)


class TwentyFourXXWorld(SceneWorld[Crewmate]):
    job: str = ""
    ship: dict[Slug, Gear] = Field(
        default_factory=lambda: {
            key: Gear(name=name, harmless=name == "Hull armor")
            for key, name in zip(SHIP_IDS, SHIP_FUNCTIONS, strict=True)
        }
    )
    hold: dict[Slug, Gear] = Field(default_factory=dict)
    ship_here: bool = False

    @model_validator(mode="after")
    def _only_the_player_leads(self) -> Self:
        if not self.player.leads or any(entry.leads for entry in self.cast.values()):
            raise ValueError("the player, and only the player, leads")
        return self

    @classmethod
    def opening(cls, proposal: SceneProposal[Crewmate], player: Crewmate) -> Self:
        player.leads = True
        world = super().opening(proposal, player)
        # Safe: the engine's `opening` makes every opening a TwentyFourXXScene.
        world.job = cast(TwentyFourXXScene, proposal).job
        world.check_unnamed(world.job)
        return world

    def absorb(self, proposal: OpeningProposal) -> None:
        # Safe: the engine's `opening` and `next_proposal` make every proposal one of these two.
        self.ship_here = cast(TwentyFourXXScene | TwentyFourXXNext, proposal).ship_here

    def sheet_rows(self) -> Rows:
        gear = self.player.require_sheet().gear_text()
        rows = self.player.rows()
        return (*rows, ("Gear", gear)) if gear else rows

    def player_line(self) -> str:
        """The gear stands in the sheet rows already, so the line does not repeat it."""
        return self.player.line(rows=self.sheet_rows(), gear=False)

    def require_gear(self, actor: Crewmate, item_id: Slug) -> Gear:
        item = actor.require_sheet().items.get(item_id) or self.ship.get(item_id)
        if item is None:
            raise Refusal(f"{item_id!r} is not among {actor.name}'s items or the ship's functions")
        return item

    def defend(self, actor_id: Slug | None, item_id: Slug, hindrance: str) -> list[Fact]:
        actor = self.require_actor(actor_id)
        item = self.require_gear(actor, item_id)
        if item.broken:
            raise Refusal(ALREADY_BROKEN.format(name=item.name))
        return self._break(actor, item, hindrance)

    def take_hit(
        self,
        actor: Crewmate,
        item_id: Slug | None,
        hindrance: str,
        *,
        risk: str,
        disaster: bool,
        deadly: bool,
    ) -> list[Fact]:
        if not disaster and not deadly:
            return []
        if item_id is not None:
            item = self.require_gear(actor, item_id)
            return self._break(actor, item, hindrance)
        if not deadly:
            return []
        if disaster:
            return self.kill(actor.id)
        return actor.hinder(f"{MAIMED} — {risk}")

    def check_defenses(self, claims: Sequence[tuple[Crewmate, Slug, str]]) -> None:
        resolved = [
            (actor, self.require_gear(actor, item_id), hindrance)
            for actor, item_id, hindrance in claims
        ]
        # By identity: two actors can claim the same ship function, and Gear is unhashable.
        claimed = Counter(id(item) for _, item, _ in resolved)
        for actor, item, hindrance in resolved:
            if item.breaks - item.broken_times < claimed[id(item)]:
                raise Refusal(ALREADY_BROKEN.format(name=item.name))
            if item.harmless:
                if hindrance:
                    raise Refusal(BREAKS_HARMLESSLY.format(name=item.name))
                continue
            if not hindrance:
                raise Refusal(f"name the hindrance that {item.name} leaves behind")
            if hindrance in actor.require_sheet().hindrances:
                raise Refusal(f"{actor.name} already carries the hindrance {hindrance!r}")

    def _break(self, actor: Crewmate, item: Gear, hindrance: str) -> list[Fact]:
        if item.harmless:
            if hindrance:
                raise Refusal(BREAKS_HARMLESSLY.format(name=item.name))
            item.broken_times += 1
            trace = f"{actor.mention} breaks {item.name}, harmlessly"
            return [actor.fact(trace, card=actor.card_line(f"{item.name} breaks"))]
        if not hindrance:
            raise Refusal("name the hindrance that the hit becomes")
        sheet = actor.require_sheet()
        sheet.hindrances = actor.changed_tags("hindrance", sheet.hindrances, (hindrance,), ())
        item.broken_times += 1
        card = actor.card_line(f"{item.name} breaks — {hindrance}")
        trace = f"{actor.mention} breaks {item.name} — {hindrance}"
        return [actor.fact(trace, card=card)]

    def hold_refusal(self) -> str:
        return "" if self.ship_here else SHIP_AWAY

    def upgrade_refusal(self, function: Gear) -> str:
        if refusal := self.hold_refusal():
            return refusal
        if function.upgraded:
            return f"{function.name} is already upgraded"
        if (credits := self.player.require_sheet().credits) < UPGRADE_COST:
            return f"{self.player.name} has only ₡{credits}, not ₡{UPGRADE_COST}"
        return ""

    def require_hold_item(self, item_id: Slug) -> Gear:
        item = self.hold.get(item_id)
        if item is None:
            raise Refusal(f"{item_id!r} is not in the ship's hold")
        return item

    def stow_item(self, actor: Crewmate, item_id: Slug) -> list[Fact]:
        if refusal := self.hold_refusal():
            raise Refusal(refusal)
        sheet = actor.require_sheet()
        item = sheet.require(item_id, actor.name)
        del sheet.items[item_id]
        self.hold[slug(item.name, self.hold)] = item
        trace = f"{actor.mention} stows {item.name} in the ship's hold"
        card = actor.card_line(f"Stowed {item.name}")
        return [actor.fact(trace, card=card)]

    def retrieve_item(self, actor: Crewmate, item_id: Slug) -> list[Fact]:
        if refusal := self.hold_refusal():
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

    def upgrade_ship(self, function_id: Slug) -> list[Fact]:
        function = self.ship.get(function_id)
        if function is None:
            raise Refusal(f"{function_id!r} is not a ship function")
        if refusal := self.upgrade_refusal(function):
            raise Refusal(refusal)
        self.player.pay(UPGRADE_COST)
        function.upgraded = True
        trace = f"the ship's {function.name} is upgraded (₡{UPGRADE_COST})"
        card = f"{function.name} upgraded — ₡{UPGRADE_COST}"
        return [self.player.fact(trace, card=card)]

    def take_lead(self, member_id: Slug) -> list[Fact]:
        dead = self.player
        if dead.alive:
            raise Refusal(f"{dead.name} lives and leads")
        member = self.require_actor(member_id)
        if member is dead:
            raise Refusal(f"{dead.name} is dead and cannot lead")
        dead.leads = False
        member.leads = True
        del self.cast[member.id]
        self.party.remove(member.id)
        self.scene.here.remove(member.id)
        self.player = member
        self.cast[dead.id] = dead
        self.scene.here.append(dead.id)
        trace = f"{member.tag} takes the lead; {dead.tag} is dead"
        return [member.fact(trace, card=f"{member.name} leads now")]

    def take_job(self, terms: str) -> list[Fact]:
        if self.job:
            raise Refusal(f"a job is open: {self.job}")
        self.job = terms
        return [self.player.fact(f"the job is taken: {terms}", card=f"Job taken\n{terms}")]

    def close_job(self) -> None:
        self.job = ""


TwentyFourXXGame = Game[TwentyFourXXWorld]
