from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import Fact
from rulehall.core.validation import Mutable, slug
from rulehall.core.views import Rows
from rulehall.engines.entities import PLAYER_ID, Gauge, Sheeted, joined
from rulehall.engines.rooms.world import Dweller, Prop

type Ability = Literal["brute", "skulker", "erudite"]
type AbilityScores = dict[Ability, Annotated[int, Field(ge=0)]]
type Boost = Literal["health", "inventory"]
ABILITIES: tuple[Ability, ...] = ("brute", "skulker", "erudite")
HP_START = 10
INVENTORY_START = 8
ABILITY_POINTS = 3
STARTING_ITEMS = 3


class GoonSheet(Mutable):
    abilities: AbilityScores = Field(
        default_factory=lambda: dict.fromkeys(ABILITIES, 0), min_length=3, max_length=3
    )
    inventory: int = Field(default=INVENTORY_START, ge=0)
    level: int = Field(default=1, ge=1)

    def rows(self, *, carried: int | None = None) -> Rows:
        held = str(self.inventory) if carried is None else f"{carried}/{self.inventory}"
        return (
            *((ability.capitalize(), str(self.abilities[ability])) for ability in ABILITIES),
            ("Inventory", held),
            ("Level", str(self.level)),
        )

    def level_up(self, ability: Ability, boost: Boost, hp: Gauge) -> str:
        self.abilities[ability] += 1
        if boost == "health":
            hp.maximum += 1
            hp.current += 1
        else:
            self.inventory += 1
        self.level += 1
        return f"Level {self.level}: {ability.capitalize()} +1, {boost.capitalize()} +1"


class Goon(Sheeted[GoonSheet], Dweller):
    """A character on the map, friend or enemy. Only a hired goon has dice. The player is one."""

    hp: Gauge
    kit: SkipJsonSchema[tuple[str, ...]] = ()

    def sign_on(self, abilities: AbilityScores) -> str:
        sheet = self.sheet = GoonSheet(abilities=dict(abilities))
        return ", ".join(
            f"{ability.capitalize()} {sheet.abilities[ability]}" for ability in ABILITIES
        )

    def rows(self, *, carried: int | None = None) -> Rows:
        if self.sheet is None:
            return (("Health", f"{self.hp} (its Difficulty Score)"),)
        return (("Health", str(self.hp)), *self.sheet.rows(carried=carried))

    def level(self, ability: Ability, boost: Boost) -> list[Fact]:
        card = self.card_line(self.require_sheet().level_up(ability, boost, self.hp))
        return [self.card_fact(card)]

    def required(self) -> str:
        return joined(
            super().required(),
            "no kit" if self.kit else "",
            "health above zero" if self.hp.current == 0 else "",
        )

    def unpack_kit(self, taken: Iterable[str]) -> tuple[Prop, ...]:
        made = [PLAYER_ID, *taken]
        items: list[Prop] = []
        for name in self.kit:
            item_id = slug(name, made)
            made.append(item_id)
            items.append(Prop(id=item_id, name=name, brief="", known=True, holder_id=PLAYER_ID))
        return tuple(items)
