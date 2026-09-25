from collections.abc import Sequence

from pydantic import Field

from rulehall.core.facts import Fact
from rulehall.core.model import Game
from rulehall.core.validation import Refusal
from rulehall.core.views import Rows, filled
from rulehall.engines.entities import Gauge, Person, joined
from rulehall.engines.loner3e.rules import LUCK_MAX, TIES_PER_TWIST, RollOutcome, TagKind
from rulehall.engines.scenes.world import SceneWorld


class Loner3eEntity(Person):
    """A character is a person, an object, a vehicle or a curse."""

    concept: str = ""
    tags: dict[TagKind, list[str]] = Field(default_factory=dict)
    # Living characters only; the SRD gives none to an object, a vehicle or a curse.
    goal: str = ""
    motive: str = ""
    nemesis: str = ""
    luck: Gauge = Field(default_factory=lambda: Gauge(current=LUCK_MAX, maximum=LUCK_MAX))
    defeated: bool = False

    def tagged(self, kind: TagKind) -> list[str]:
        return self.tags.get(kind, [])

    def rows(self) -> Rows:
        return filled(
            ("Concept", self.concept),
            ("Skills", ", ".join(self.tagged("skill"))),
            ("Frailties", ", ".join(self.tagged("frailty"))),
            ("Gear", ", ".join(self.tagged("gear"))),
            ("Conditions", ", ".join(self.tagged("condition"))),
            ("Goal", self.goal),
            ("Motive", self.motive),
            ("Nemesis", self.nemesis),
            ("Luck", str(self.luck)),
            ("Defeated", "yes" if self.defeated else ""),
        )

    def required(self) -> str:
        return joined(
            super().required(),
            "full luck" if self.luck.shortfall != 0 else "",
            "a luck pool of at least 1" if self.luck.maximum < 1 else "",
            "no defeat behind them" if self.defeated else "",
        )

    def change_tags(self, kind: TagKind, gained: Sequence[str], lost: Sequence[str]) -> list[Fact]:
        self.tags[kind] = self.changed_tags(kind, self.tagged(kind), gained, lost)
        trace = f"{self.mention} {kind} " + ", ".join(
            (*(f"+{tag}" for tag in gained), *(f"-{tag}" for tag in lost))
        )
        parts: list[str] = []
        if gained:
            took = ", ".join(gained)
            parts.append(f"Took {took}" if kind == "gear" else f"Now: {took}")
        if lost:
            lost_line = ", ".join(lost)
            parts.append(f"Lost {lost_line}" if kind == "gear" else f"No longer: {lost_line}")
        return [self.fact(trace, card=self.card_line("; ".join(parts)) if parts else "")]

    def drive(self, *, goal: str, motive: str, nemesis: str) -> list[Fact]:
        parts: list[str] = []
        if goal:
            self.goal = goal
            parts.append(f"goal: {goal}")
        if motive:
            self.motive = motive
            parts.append(f"motive: {motive}")
        if nemesis:
            self.nemesis = nemesis
            parts.append(f"nemesis: {nemesis}")
        trace = f"{self.mention} " + "; ".join(parts)
        card = self.card_line(goal) if goal else ""
        return [self.fact(trace, card=card)]

    def refill(self, why: str) -> list[Fact]:
        return self.change(self.luck, self.luck.shortfall, "Luck", why)

    def spend_luck(self, amount: int, why: str) -> list[Fact]:
        if self.defeated:
            raise Refusal(f"{self.name} lost their last conflict. They can spend no luck.")
        if amount > self.luck.current:
            raise Refusal(f"{self.name} has {self.luck.current} luck, not {amount}.")
        return self.change(self.luck, -amount, "Luck", why)

    def run_out_of_luck(self) -> list[Fact]:
        self.defeated = True
        trace = f"{self.mention} is out of luck"
        return [self.fact(trace, card=self.card_line("Out of luck"))]

    def recover(self, why: str) -> list[Fact]:
        facts = self.refill(why)
        if self.defeated:
            self.defeated = False
            trace = f"{self.mention} is no longer defeated ({why})"
            facts.append(self.fact(trace, card=self.card_line("No longer defeated")))
        return facts


class Loner3eWorld(SceneWorld[Loner3eEntity]):
    # The played character's tally paces the whole game, so no sheet carries one.
    twist: Gauge = Field(default_factory=lambda: Gauge(current=0, maximum=TIES_PER_TWIST))

    def tick_twist(self) -> bool:
        self.twist.current += 1
        if self.twist.shortfall == 0:
            self.twist.current = 0
            return True
        return False

    def conflict_prompt(self, actor: Loner3eEntity, opponent: Loner3eEntity) -> str:
        foe = actor if opponent.id == self.player.id else opponent
        return f"{foe.name} is still in the fight. Press on, change tack, or break away?"

    def strike(
        self, actor: Loner3eEntity, opponent: Loner3eEntity, outcome: RollOutcome
    ) -> tuple[list[Fact], str]:
        harm = outcome.harm
        hit, striker = (opponent, actor) if harm > 0 else (actor, opponent)
        why = f"{striker.name} gets the better of the exchange"
        facts = hit.change(hit.luck, -abs(harm), "Luck", why)
        if hit.luck.current != 0:
            return facts, ""
        facts.extend(hit.run_out_of_luck())
        # SRD: luck resets after conflicts, and a side at 0 is the only end the engine sees.
        facts.extend(hit.refill("the conflict is over"))
        facts.extend(striker.refill("the conflict is over"))
        return facts, hit.name

    def check_conflict(self, actor: Loner3eEntity, opponent: Loner3eEntity | None) -> None:
        if opponent is None:
            return
        if opponent.id == actor.id:
            raise Refusal(f"{actor.name} cannot be their own opposition in a conflict.")
        for side in (actor, opponent):
            if side.defeated:
                raise Refusal(
                    f"{side.name} lost their last conflict. That conflict is settled. Tell "
                    "what the defeat costs them. If this is a new contest, call "
                    "`restore_luck` first."
                )


Loner3eGame = Game[Loner3eWorld]
