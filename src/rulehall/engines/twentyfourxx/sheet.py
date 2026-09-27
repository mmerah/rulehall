from collections.abc import Sequence

from pydantic import Field

from rulehall.core.facts import DiceEvent, Fact
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, slug
from rulehall.core.views import Rows, filled, tag_of
from rulehall.engines.entities import Sheeted, Thing, changed_tags, tag_card
from rulehall.engines.twentyfourxx.rules import DEFAULT_DIE, SkillDie, brief_hindrance, raised

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
)
SHIP_IDS: tuple[Slug, ...] = tuple(slug(name, ()) for name in SHIP_FUNCTIONS)


class Kit(Frozen):
    name: str
    bulky: bool = False
    breaks: int = Field(default=1, ge=1)
    harmless: bool = False


class Gear(Mutable):
    name: str
    bulky: bool = False
    breaks: int = Field(default=1, ge=1)
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
    traits: tuple[str, ...] = ()
    skills: dict[str, SkillDie] = Field(default_factory=dict)
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
