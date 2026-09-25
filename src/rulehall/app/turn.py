from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from random import Random
from typing import Self

from pydantic import JsonValue

from rulehall.core.creation import option_of
from rulehall.core.facts import NOTHING, Fact, traced
from rulehall.core.model import AnyGame
from rulehall.core.play import Answer, Refused, SpokenLine
from rulehall.core.tools import MasterTool
from rulehall.core.validation import Refusal
from rulehall.engines.engine import AnyEngine

PAUSED_TO_ASK = 'The rules paused play to ask the player: "{prompt}" '
RULES_WAIT = "the rules now wait on the player's decision"
REQUEST_WAIT = "the worldsmith writes what you asked for once this turn ends. Stop here and exit."
DIRECTED_WAIT = "the narrator has your direction and the turn ends there. Stop here and exit."
ANSWERED_BY_OPTION = (
    "The player chose the option above and the rules applied the option. Tell what the option "
    "caused. Do not decide the option again."
)
NO_TURN = "no turn is open. The player starts a turn from the page. Wait until you start again."
BATTLE_WAIT = "a battle starts once this turn ends. Stop here and exit."
BATTLE_ON = "A battle is on. Finish it on the battle screen."
GAME_OVER = "The game is over. The player restarts from the page."
RESTART = "The game continues only after a restart."


@dataclass(slots=True, kw_only=True)
class Turn:
    engine: AnyEngine
    draft: AnyGame
    rng: Random
    facts: list[Fact] = field(default_factory=list)
    refused: list[Refused] = field(default_factory=list)
    words: str = ""
    # What the master reads as PLAYER ACTION: the words, or the marker for a chosen option.
    master_input: str = ""
    notes: list[str] = field(default_factory=list)
    # Whether the master plays: an answer that re-suspended leaves every tool refused.
    played: bool = True

    @classmethod
    def begin(cls, engine: AnyEngine, state: AnyGame, answer: Answer, rng: Random) -> Self:
        turn = cls(engine=engine, draft=state.draft(), rng=deepcopy(rng))
        turn.draft.directed = False
        turn._consume(answer)
        turn.played = turn.draft.pending is None
        # Notes are read once; a note a tool writes after this steers the next turn.
        if turn.played:
            turn.notes, turn.draft.notes = turn.draft.notes, []
        return turn

    def _consume(self, answer: Answer) -> None:
        engine, draft = self.engine, self.draft
        require_playable(engine, draft)
        # Any input consumes the decision, a revision included: it never survives its own answer.
        consumed, draft.pending = draft.pending, None
        chosen = answer.option_id
        if consumed is not None and not consumed.allows_text and chosen is None:
            raise Refusal(f"the {consumed.kind!r} decision takes one of its options, not words")
        if chosen is None:
            if consumed is not None:
                draft.note(
                    PAUSED_TO_ASK.format(prompt=consumed.prompt)
                    + "The PLAYER ACTION is the player's answer."
                )
            self.words = self.master_input = answer.text
            return
        if consumed is None:
            raise Refusal(f"no decision is open, so option {chosen!r} answers nothing")
        option = option_of(consumed.options, chosen)
        if option is None:
            raise Refusal(f"the {consumed.kind!r} decision offers no option {chosen!r}")
        # A refusal raises: the engine enumerated the option, so it is never model error.
        facts = self.apply(lambda copy, dice: engine.play_option(copy, option, dice))
        traces = traced(facts)
        # An answer that re-suspended has no tool answer to carry the wait, so the note says it.
        if self.draft.pending is not None:
            traces += f"\n- {RULES_WAIT}"
        self.draft.note(
            PAUSED_TO_ASK.format(prompt=consumed.prompt)
            + f"They chose: {option.name}. Already resolved:\n{traces}"
        )
        self.words, self.master_input = option.name, ANSWERED_BY_OPTION

    @property
    def narrates(self) -> bool:
        """A hand-over that told the player nothing gets no prose."""
        draft = self.draft
        waiting = (
            draft.pending is not None or draft.request is not None or self.engine.in_battle(draft)
        )
        return any(fact.told for fact in self.facts) or not waiting

    @property
    def landed(self) -> bool:
        return bool(self.facts) or self.draft.pending is not None

    def call(self, name: str, raw: JsonValue) -> str:
        try:
            return self._called(name, raw)
        except Refusal as refused:
            self.refused.append(
                Refused(tool=name, reason=str(refused), after_facts=len(self.facts))
            )
            raise

    def _called(self, name: str, raw: JsonValue) -> str:
        if (ended := self.engine.ending(self.draft)) is not None:
            raise Refusal(f"{ended} {GAME_OVER}")
        found = self.engine.require_tool(name)
        pending = self.draft.pending
        if pending is not None:
            # A plain answer, not a refusal: a retry prompt would tell the model to try again.
            return (
                f"the rules are waiting on the player: {pending.prompt}\n"
                "Stop here and exit; the player's answer opens the next turn."
            )
        if self.draft.request is not None:
            return REQUEST_WAIT
        if self.engine.in_battle(self.draft):
            return BATTLE_WAIT
        if self.draft.directed:
            return DIRECTED_WAIT
        notes_before = len(self.draft.notes)
        facts = self.apply(lambda draft, rng: found.call(draft, raw, rng))
        lines = [f"- {fact.trace}" for fact in facts]
        lines.extend(f"- {note}" for note in self.draft.notes[notes_before:])
        if self.draft.pending is not None:
            lines.append(f"- {RULES_WAIT}")
        return "\n".join(lines) or NOTHING

    def published_tools(self) -> tuple[MasterTool, ...]:
        return tuple(self.engine.tools.values())

    def finish(self, lines: tuple[SpokenLine, ...]) -> AnyGame:
        if self.played and self.facts:
            self.engine.count_turn(self.draft)
        return self.engine.record(
            self.draft, lines, tuple(self.facts), words=self.words, refused=tuple(self.refused)
        )

    def apply(self, play: Callable[[AnyGame, Random], tuple[Fact, ...]]) -> tuple[Fact, ...]:
        """One execution against a candidate; a refused call leaves the draft and the dice alone."""
        candidate, dice = self.draft.draft(), deepcopy(self.rng)
        facts = play(candidate, dice)
        self.draft = self.engine.accept(candidate)
        self.rng.setstate(dice.getstate())
        self.facts.extend(facts)
        return facts


def require_playable(engine: AnyEngine, state: AnyGame) -> None:
    if (ended := engine.ending(state)) is not None:
        raise Refusal(f"{ended} {RESTART}")
    if engine.in_battle(state):
        raise Refusal(BATTLE_ON)
