from collections.abc import Mapping, Sequence
from random import Random
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from rulehall.core.facts import DiceEvent, Fact, Rolled, roll
from rulehall.core.game import Game
from rulehall.core.validation import Frozen, Mutable, Refusal, Slug, as_tuple
from rulehall.core.views import Rows
from rulehall.engines.args import BE_SHORT
from rulehall.engines.loner4e.rules import (
    DIE_FACE,
    DOUBLES_PER_TWIST,
    MEANWHILE_QUESTION,
    SCENE_ID,
    TWIST_ACTIONS,
    TWIST_SUBJECTS,
    UNTRAINED,
    ClosedBy,
    Position,
    RollOutcome,
    SceneKind,
    TagKind,
    faces_for,
    outcome_for,
    transition_for,
)
from rulehall.engines.loner4e.sheet import Loner4eEntity, StatusTrack, TagName, Tags
from rulehall.engines.scenes.world import NextProposal, SceneProposal, SceneWorld
from rulehall.engines.sheet import Gauge, changed_tags, tag_card, tag_delta
from rulehall.engines.world import IS_DEAD

SCENE_CLOSED = "the scene has closed: change nothing more in it; call `direct` now"
NO_SUCH_TAG = (
    "no such tag here: {missing}; cite exact tags from SCENE, the sheet or who is here, or cite "
    "none"
)
ENDING_ASKS_NOTHING = "the adventure is ending: ask nothing; write the growth"
FILED = (
    "{name}[{entity_id}] is new to the cast, which also holds: {others}. Use one of those ids "
    "when you mean them"
)
OFF_SCREEN = "the world moves off screen"
DETAILS_KEPT = 6
MEANWHILE_HINT = (
    ". First the world moves while you are away: the question below is about people "
    "elsewhere, not this scene"
)


class Framing(Frozen):
    goal: str = Field(
        min_length=1,
        description="What the protagonist is here for in this scene, in one line the player "
        "reads. Name nothing the player has not met.",
    )
    details: tuple[TagName, ...] = Field(
        min_length=1,
        max_length=4,
        description="Two to four tags on the place, such as `Slick Cobbles` or `Crowded "
        f"Market`. The player reads them. {BE_SHORT}",
    )
    hidden_ids: SkipJsonSchema[tuple[()]] = ()


class Loner4eOpeningProposal(Framing, SceneProposal[Loner4eEntity]):
    @model_validator(mode="after")
    def _scene_id_unfiled(self) -> Self:
        _check_scene_id_unfiled(self.cast)
        return self


class Loner4eNextProposal(Framing, NextProposal[Loner4eEntity]):
    @model_validator(mode="after")
    def _scene_id_unfiled(self) -> Self:
        _check_scene_id_unfiled(self.cast)
        return self


class TagChange(Frozen):
    gained: Annotated[tuple[TagName, ...], BeforeValidator(as_tuple)] = Field(
        default=(), description=f"Tags gained, in title case, such as `Rusty Key`. {BE_SHORT}"
    )
    lost: Tags = Field(default=(), description="Exact tags lost, removed, or used up.")

    @model_validator(mode="after")
    def _a_change(self) -> Self:
        if not self.gained and not self.lost:
            raise ValueError("give at least one gained tag or one lost tag")
        return self


class CastUpdate(TagChange):
    entity_id: Slug = Field(
        description="Exact id of a cast member off screen: never the player or who travels with "
        "them. The scene just left is off screen now."
    )
    kind: TagKind = Field(
        description="`condition` for what they are doing now, such as `Searching for the "
        "Protagonist`; `gear` for a thing taken or lost; `relationship` for what the bond with "
        "the protagonist has become."
    )


class Loner4eMeanwhileProposal(Frozen):
    power: tuple[CastUpdate, ...] = Field(
        default=(),
        description="The new tags of whoever holds power over the situation: the antagonist, a "
        "rival, an organisation, or the cast entry acting for it. Never an ally or anyone on the "
        "protagonist's side.",
    )
    ally: CastUpdate | None = Field(
        description="On a yes only: the new tags of the NPC most affected by recent events, an "
        "ally or a wildcard. Null on a no: allies hold."
    )
    scene: Loner4eNextProposal | None = Field(
        description="The next scene when the request asks for a dramatic one; null when it asks "
        "for no scene."
    )

    @property
    def updates(self) -> tuple[CastUpdate, ...]:
        return (*self.power, *(() if self.ally is None else (self.ally,)))


class Fate(Frozen):
    entity_id: Slug = Field(description="Exact id of an NPC the player has met.")
    line: str = Field(
        min_length=1,
        description="How the relationship stands, what they want now, gone or still in play. "
        "Leave out their name: the engine writes it.",
    )


class LivingWorldProposal(Frozen):
    people: tuple[Fate, ...] = Field(description="For each NPC who mattered, one entry.")
    places: tuple[str, ...] = Field(
        description="For each location that featured, one line: what changed there, and "
        "whether it stays accessible, dangerous or relevant."
    )
    events: tuple[str, ...] = Field(
        description="For each event, thread or faction that mattered, one line: settled or "
        "still hanging, and the pressure it keeps on the world."
    )

    @model_validator(mode="after")
    def _one_line_at_least(self) -> Self:
        if not (self.people or self.places or self.events):
            raise ValueError("write at least one line")
        return self


class OracleRoll(Frozen):
    question: str
    position: Position
    outcome: RollOutcome
    chance: Rolled
    risk: Rolled
    twist_count: int = 0

    @property
    def twist_due(self) -> bool:
        return self.twist_count == DOUBLES_PER_TWIST

    def facts(self, *lines: str, hoped: bool = True) -> list[Fact]:
        return [self.chance.fact, self.risk.fact, self._card(*lines, hoped=hoped)]

    def _card(self, *lines: str, hoped: bool) -> Fact:
        outcome = self.outcome
        reading = f": {outcome.reading}" if hoped else ""
        return Fact(
            trace=f"oracle, {self.position}: {self.question} {outcome.wording}{reading}",
            told=True,
            card="\n".join((self.question, self.outcome.wording, *lines, *self._counted())),
            dice=(self.chance.event, self.risk.event),
        )

    def _counted(self) -> tuple[str, ...]:
        return (f"+1 Twist ({self.twist_count}/{DOUBLES_PER_TWIST})",) if self.twist_count else ()


class Frame(Mutable):
    kind: SceneKind = "dramatic"
    goal: str = ""
    details: list[str] = Field(default_factory=list)
    next: SceneKind | None = None
    meanwhile: bool = False
    closed_by: ClosedBy | None = None
    ally: str = ""
    offscreen: str = ""
    twist: str = ""

    @property
    def open(self) -> bool:
        return self.next is None

    @property
    def breather(self) -> bool:
        return self.next == "quiet" and not self.meanwhile

    @property
    def coming(self) -> SceneKind:
        return self.next or "dramatic"

    @property
    def handover(self) -> str:
        return f"meanwhile, then {self.next}" if self.meanwhile else f"{self.next}"

    def rewrite_goal(self, goal: str) -> list[Fact]:
        self.goal = goal
        return [Fact(trace=f"the scene goal is now: {goal}", told=True, card=f"Goal: {goal}")]

    def change_details(self, gained: Sequence[str], lost: Sequence[str]) -> list[Fact]:
        details = changed_tags("The scene", "detail", self.details, gained, lost)
        stale, self.details = details[:-DETAILS_KEPT], details[-DETAILS_KEPT:]
        card = tag_card(gained, lost, "Here now: ", "No longer: ")
        facts = [Fact(trace=f"the scene detail {tag_delta(gained, lost)}", told=True, card=card)]
        if stale:
            facts.append(Fact(trace=f"the oldest details give way: {', '.join(stale)}"))
        return facts

    def lines(self) -> str:
        return f"kind: {self.kind}\ngoal: {self.goal}\ndetails: {', '.join(self.details)}"

    def phase(self) -> str:
        if self.open:
            return "open"
        if self.breather:
            return "breather: the player chooses the aim of a quiet scene"
        return f"closing: next {self.handover}"


class Loner4eWorld(SceneWorld[Loner4eEntity]):
    twist: Gauge = Field(default_factory=lambda: Gauge(current=0, maximum=DOUBLES_PER_TWIST))
    frame: Frame = Field(default_factory=Frame)
    opponent_ids: list[Slug] = Field(default_factory=list)
    player_question: str = ""
    status: StatusTrack = Field(default_factory=StatusTrack)
    end_why: str = ""
    ended: bool = False
    grown: bool = Field(default=False, exclude=True)

    @model_validator(mode="after")
    def _scene_id_unfiled(self) -> Self:
        _check_scene_id_unfiled(self.cast)
        return self

    def apply_proposal_extras(self, proposal: Framing) -> None:
        self.frame = Frame(
            kind=self.frame.coming, goal=proposal.goal, details=list(proposal.details)
        )

    def close(self, reason: ClosedBy, rng: Random) -> list[Fact]:
        frame = self.frame
        if self.end_why:
            raise Refusal(ENDING_ASKS_NOTHING)
        self.require_open()
        facts = self.end_conflict("the scene closes") if self.opponent_ids else []
        frame.next = "dramatic"
        dice: list[DiceEvent] = []
        meanwhile: list[Fact] = []
        if reason != "turning_point":
            rolled = roll((DIE_FACE,), "scene transition", rng, label="Transition")
            facts.append(rolled.fact)
            dice.append(rolled.event)
            transition = transition_for(rolled.face)
            if transition == "meanwhile":
                ally = self._roll_oracle(MEANWHILE_QUESTION, "neutral", rng, settle=False)
                frame.ally = ally.outcome.wording
                meanwhile = ally.facts()
                if (twisted := self.roll_twist(ally, rng)) is not None:
                    pair, twist_facts = twisted
                    frame.twist = " / ".join(pair)
                    meanwhile += twist_facts
                follow = roll((DIE_FACE,), "meanwhile follow-up", rng, label="Transition")
                facts.append(follow.fact)
                dice.append(follow.event)
                quiet = transition_for(follow.face) == "quiet"
                frame.meanwhile = True
                frame.next = "quiet" if quiet else "dramatic"
            else:
                frame.next = transition
        frame.closed_by = reason
        card = f"Scene closes: {reason.replace('_', ' ')}. Next: {frame.handover}"
        if frame.meanwhile:
            card += MEANWHILE_HINT
        facts.append(Fact(trace=card, told=True, card=card, dice=tuple(dice)))
        return [
            *facts,
            *(fact.model_copy(update={"trace": OFF_SCREEN}) for fact in meanwhile if fact.told),
        ]

    def consult(
        self,
        question: str,
        position: Position,
        rng: Random,
        *,
        settle: bool = True,
    ) -> OracleRoll:
        if self.end_why:
            raise Refusal(ENDING_ASKS_NOTHING)
        self.require_open()
        return self._roll_oracle(question, position, rng, settle=settle)

    def _roll_oracle(
        self, question: str, position: Position, rng: Random, *, settle: bool = True
    ) -> OracleRoll:
        chance_faces, risk_faces = faces_for(position)
        chance = roll(
            chance_faces, f"{question} — chance", rng, label="Chance", highlight_kept=True
        )
        risk = roll(risk_faces, f"{question} — risk", rng, label="Risk", highlight_kept=True)
        outcome = outcome_for(chance.kept, risk.kept)
        if settle:
            self.settle(question, outcome.wording)
        counted = outcome.doubles and not self.opponent_ids
        return OracleRoll(
            question=question,
            position=position,
            outcome=outcome,
            chance=chance,
            risk=risk,
            twist_count=self.tick_twist() if counted else 0,
        )

    def roll_twist(
        self, consulted: OracleRoll, rng: Random
    ) -> tuple[tuple[str, str], list[Fact]] | None:
        if not consulted.twist_due:
            return None
        rolled = roll((DIE_FACE, DIE_FACE), "twist — subject, action", rng, label="Twist")
        subject_face, action_face = rolled.event.rolled
        subject, action = TWIST_SUBJECTS[subject_face - 1], TWIST_ACTIONS[action_face - 1]
        card = Fact(
            trace=f"a twist interrupts the scene: {subject} / {action}",
            told=True,
            card=f"Twist — {subject} / {action}",
            dice=(rolled.event,),
        )
        return (subject, action), [rolled.fact, card]

    def apply_offscreen_update(self, update: CastUpdate) -> list[Fact]:
        entity = self.require(update.entity_id)
        if entity is self.player or entity.id in self.party_ids:
            raise Refusal(f"{entity.name} is the protagonist or travels with them, not off screen")
        if not entity.alive:
            raise Refusal(IS_DEAD.format(name=entity.name))
        return entity.change_tags(update.kind, update.gained, update.lost)

    def apply_offscreen_updates(self, updates: Sequence[CastUpdate]) -> list[Fact]:
        facts = [fact for update in updates for fact in self.apply_offscreen_update(update)]
        self.frame.offscreen = "; ".join(fact.card for fact in facts)
        if not facts:
            return []
        card = "\n".join(f"Meanwhile: {fact.card}" for fact in facts)
        shown = Fact(trace=f"off screen: {self.frame.offscreen}", told=True, card=card)
        return [*(fact.model_copy(update={"card": ""}) for fact in facts), shown]

    def scene_lines(self) -> str:
        return f"{super().scene_lines()}\n{self.frame.lines()}"

    def require_open(self) -> None:
        if not self.frame.open:
            raise Refusal(SCENE_CLOSED)

    def check_cited(self, helps: Sequence[str], hinders: Sequence[str]) -> None:
        carried = {
            tag.casefold()
            for tag in (
                *self.frame.details,
                *((self.status.active, self.status.line()) if self.status.boxes else ()),
                UNTRAINED,
                *(tag for member in self.here() for tags in member.tags.values() for tag in tags),
            )
        }
        if missing := [tag for tag in (*helps, *hinders) if tag.casefold() not in carried]:
            raise Refusal(NO_SUCH_TAG.format(missing=missing))

    def living_world_lines(self, living_world: LivingWorldProposal) -> tuple[str, ...]:
        people = (
            f"{self.require(fate.entity_id).name}: {fate.line}" for fate in living_world.people
        )
        return (*people, *living_world.places, *living_world.events)

    def pop_player_question(self) -> str:
        question, self.player_question = self.player_question, ""
        return question

    def here_or_entering(self, entity_id: Slug) -> tuple[Loner4eEntity, list[Fact]]:
        known = self._find_known_id(entity_id)
        if known is not None and (known == self.player.id or known in self.scene.here_ids):
            return self.require_living_here(known), []
        facts = self.enter(entity_id)
        return self.require_living_here(entity_id if known is None else known), facts

    def conflict_lines(self) -> str:
        if not self.opponent_ids:
            return ""
        lines = [f"- {self.player.tag}: luck {self.player.luck}"]
        for opponent in map(self.require, self.opponent_ids):
            edge = ", ".join((*opponent.tagged("skill"), *opponent.tagged("gear")))
            lines.append(
                f"- {opponent.tag}: luck {opponent.luck}" + (f"; hinders: {edge}" if edge else "")
            )
        return "\n".join(lines)

    def elsewhere_lines(self) -> str:
        return "\n".join(
            f"- {entry.tag}" + (f" — {entry.concept}" if entry.concept else "")
            for entry in self.cast.values()
            if entry.alive and entry.id not in self.scene.here_ids
        )

    def sheet_rows(self) -> Rows:
        rows = self.player.rows()
        return (*rows, ("Status", self.status.line())) if self.status.boxes else rows

    def tick_twist(self) -> int:
        reached = self.twist.current + 1
        self.twist.current = 0 if reached == DOUBLES_PER_TWIST else reached
        return reached

    def engage(self, opponent: Loner4eEntity) -> list[Fact]:
        if opponent.id in self.opponent_ids:
            # Last in the list is the one fought last: an `ask` with no `opponent_id` engages them.
            self.opponent_ids.remove(opponent.id)
            self.opponent_ids.append(opponent.id)
            return []
        opened = [] if self.opponent_ids else self.player.refill("a conflict begins")
        self.opponent_ids.append(opponent.id)
        return [*opened, *opponent.refill("the conflict begins")]

    def strike(
        self, opponent: Loner4eEntity, outcome: RollOutcome
    ) -> tuple[list[Fact], Loner4eEntity | None]:
        hit, striker = (opponent, self.player) if outcome.harm > 0 else (self.player, opponent)
        why = f"{striker.name} gets the better of the exchange"
        facts = hit.change(hit.luck, -abs(outcome.harm), "Luck", why)
        if hit.luck.current != 0:
            return facts, None
        return [*facts, *self.knock_out(hit)], hit

    def spend(
        self, spender: Loner4eEntity, amount: int, why: str
    ) -> tuple[list[Fact], Loner4eEntity | None]:
        facts = spender.spend_luck(amount, why)
        fighting = spender.id in self.opponent_ids or (
            spender is self.player and bool(self.opponent_ids)
        )
        if spender.luck.current != 0 or not fighting:
            return facts, None
        return [*facts, *self.knock_out(spender)], spender

    def knock_out(self, loser: Loner4eEntity) -> list[Fact]:
        if loser is self.player:
            return self.end_conflict(f"{loser.name} is out of luck")
        return self.drop_opponent(loser.id)

    def drop_opponent(self, entity_id: Slug) -> list[Fact]:
        if entity_id not in self.opponent_ids:
            return []
        if self.opponent_ids == [entity_id]:
            return self.end_conflict("the last opponent is out")
        self.opponent_ids.remove(entity_id)
        leaver = self.require(entity_id)
        return leaver.refill("out of the conflict") if leaver.alive else []

    def end_conflict(self, why: str) -> list[Fact]:
        sides = [self.player, *(self.require(entity_id) for entity_id in self.opponent_ids)]
        self.opponent_ids.clear()
        return [
            fact
            for side in sides
            if side.alive
            for fact in side.refill(f"the conflict is over: {why}")
        ]

    def enter(self, entity_id: Slug) -> list[Fact]:
        self.require_open()
        known = self._find_known_id(entity_id)
        if known is not None:
            return super().enter(known)
        others = ", ".join(entry.tag for entry in self.cast.values() if entry.alive)
        name = self.file_stranger(entity_id, "").name
        filed = FILED.format(name=name, entity_id=entity_id, others=others or "(no one)")
        return [Fact(trace=filed), *super().enter(entity_id)]

    def leave(self, entity_id: Slug) -> list[Fact]:
        self.require_open()
        known = self._find_known_id(entity_id) or entity_id
        if known not in self.scene.here_ids:
            return []
        return [*super().leave(known), *self.drop_opponent(known)]

    def _find_known_id(self, entity_id: Slug) -> Slug | None:
        if entity_id in self.cast or entity_id == self.player.id:
            return entity_id
        found = [key for key in self.cast if f"-{entity_id}-" in f"-{key}-"]
        return found[0] if len(found) == 1 else None

    def kill(self, entity_id: Slug) -> list[Fact]:
        return [*super().kill(entity_id), *self.drop_opponent(entity_id)]


Loner4eGame = Game[Loner4eWorld]


def _check_scene_id_unfiled(cast: Mapping[Slug, Loner4eEntity]) -> None:
    if SCENE_ID in cast:
        raise ValueError(f"no cast entry filed under `{SCENE_ID}`: that id names the scene")
