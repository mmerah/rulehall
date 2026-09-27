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
DIRECTED_ONCE = "the turn already has its direction: `direct` runs once per turn"
HELD = (
    "Fixed before this turn, and told with it: never tell, roll or change them again. "
    "Interpret only the player's answer.\n{traces}"
)
UNDIRECTED = (
    "The turn has no `direct`, and no tool ended it. Call `direct` now with the notes for the "
    "narrator."
)
ANSWERED_BY_OPTION = (
    "The player chose the option above and the rules applied the option. Tell what the option "
    "caused. Do not decide the option again."
)
NO_TURN = "no turn is open. The player starts a turn from the page. Wait until you start again."
BATTLE_WAIT = "a battle starts once this turn ends. Stop here and exit."
BATTLE_ON = "A battle is on. Finish it on the battle screen."
GAME_OVER = "The game is over. The player restarts from the page."
RESTART = "The game continues only after a restart."
DIRECT = "direct"


@dataclass(slots=True, kw_only=True)
class Turn:
    engine: AnyEngine
    draft: AnyGame
    rng: Random
    facts: list[Fact] = field(default_factory=list)
    held: list[Fact] = field(default_factory=list)
    refused: list[Refused] = field(default_factory=list)
    words: str = ""
    by_option: bool = False
    master_input: str = ""
    notes: list[str] = field(default_factory=list)
    played: bool = True
    direction: Fact | None = None

    @classmethod
    def begin(cls, engine: AnyEngine, state: AnyGame, answer: Answer, rng: Random) -> Self:
        turn = cls(engine=engine, draft=state.draft(), rng=deepcopy(rng))
        turn.draft.directed = False
        turn.held, turn.draft.unnarrated = turn.draft.unnarrated, []
        turn._consume(answer)
        turn.played = turn.draft.pending is None and turn.draft.request is None
        if turn.played:
            held = [HELD.format(traces=traced(turn.held))] if turn.held else []
            turn.notes, turn.draft.notes = [*held, *turn.draft.notes], []
        return turn

    def _consume(self, answer: Answer) -> None:
        engine, draft = self.engine, self.draft
        require_playable(engine, draft)
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
        if self.draft.pending is not None:
            traces += f"\n- {RULES_WAIT}"
        self.draft.note(
            PAUSED_TO_ASK.format(prompt=consumed.prompt)
            + f"They chose: {option.name}. Already resolved:\n{traces}"
        )
        self.words, self.master_input = option.name, ANSWERED_BY_OPTION
        self.by_option = True

    @property
    def told(self) -> tuple[Fact, ...]:
        return tuple(fact for fact in (*self.held, *self.facts) if fact.told)

    @property
    def narrates(self) -> bool:
        draft = self.draft
        if draft.pending is not None:
            return False
        return bool(self.told) or (draft.request is None and not self.engine.in_battle(draft))

    @property
    def over(self) -> bool:
        draft, engine = self.draft, self.engine
        return (
            draft.directed
            or draft.pending is not None
            or draft.request is not None
            or engine.in_battle(draft)
            or engine.ending(draft) is not None
        )

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
        if self.draft.directed and name == DIRECT:
            raise Refusal(DIRECTED_ONCE)
        pending = self.draft.pending
        if pending is not None and name != DIRECT:
            # A plain answer, not a refusal: a retry prompt would tell the model to try again.
            return (
                f"the rules are waiting on the player: {pending.prompt}\n"
                "Stop here and exit; the player's answer opens the next turn."
            )
        if self.draft.request is not None:
            return REQUEST_WAIT
        if self.engine.in_battle(self.draft):
            return BATTLE_WAIT
        facts = self.apply(lambda draft, rng: found.call(draft, raw, rng))
        if name == DIRECT:
            self.direction = facts[-1]
        elif self.direction is not None:
            self.facts.remove(self.direction)
            self.facts.append(self.direction)
        notes, self.draft.notes = self.draft.notes, []
        lines = [f"- {line}" for line in (*(fact.trace for fact in facts), *notes)]
        if self.draft.pending is not None:
            lines.append(f"- {RULES_WAIT}")
        return "\n".join(lines) or NOTHING

    def published_tools(self) -> tuple[MasterTool, ...]:
        return self.engine.published(self.draft)

    def finish(self, lines: tuple[SpokenLine, ...]) -> AnyGame:
        if not self.narrates:
            self.draft.unnarrated = list(self.told)
        if self.played:
            self.engine.end_turn(self.draft, acted=bool(self.facts))
        return self.engine.record(
            self.draft,
            lines,
            tuple(self.facts),
            words=self.words,
            by_option=self.by_option,
            refused=tuple(self.refused),
        )

    def apply(self, play: Callable[[AnyGame, Random], tuple[Fact, ...]]) -> tuple[Fact, ...]:
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
