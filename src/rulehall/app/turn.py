from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from random import Random
from typing import Self

from pydantic import JsonValue

from rulehall.core.creation import find_option
from rulehall.core.decisions import Decision, PlayerInput
from rulehall.core.facts import NOTHING, Fact, render_traces
from rulehall.core.game import AnyGame
from rulehall.core.log import RefusedCall, SpokenLine
from rulehall.core.tools import MasterTool
from rulehall.core.validation import Refusal, Slug, decode
from rulehall.engines.engine import AnyEngine

PAUSED_TO_ASK = 'The rules paused play to ask the player: "{prompt}" '
RULES_WAIT = "the rules now wait on the player's decision"
REQUEST_WAIT = "the worldsmith writes what you asked for once this turn ends: stop here and exit"
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
BATTLE_WAIT = "a battle starts once this turn ends: stop here and exit"
GAME_OVER = "the game is over ({ending}): the player restarts from the page"
DIRECT = "direct"


@dataclass(slots=True, kw_only=True)
class Turn:
    engine: AnyEngine
    draft: AnyGame
    rng: Random
    facts: list[Fact] = field(default_factory=list)
    facts_carried_from_last_turn: list[Fact] = field(default_factory=list)
    refused: list[RefusedCall] = field(default_factory=list)
    logged_words: str = ""
    by_option: bool = False
    master_action_text: str = ""
    notes: list[str] = field(default_factory=list)
    master_plays_this_turn: bool = True
    direct_fact: Fact | None = None

    @classmethod
    def begin(
        cls,
        engine: AnyEngine,
        state: AnyGame,
        answer: PlayerInput,
        rng: Random,
        played: tuple[Fact, ...] = (),
    ) -> Self:
        turn = cls(engine=engine, draft=state.draft(), rng=deepcopy(rng), facts=list(played))
        turn.facts_carried_from_last_turn, turn.draft.unnarrated = turn.draft.unnarrated, []
        consumed, turn.draft.pending = turn.draft.pending, None
        if answer.option_id is None:
            turn._answer_with_words(consumed, answer.text)
        else:
            turn._answer_with_option(consumed, answer.option_id, answer.text)
        turn.master_plays_this_turn = turn.draft.pending is None and turn.draft.request is None
        if turn.master_plays_this_turn:
            fixed = (*turn.facts_carried_from_last_turn, *played)
            held = [HELD.format(traces=render_traces(fixed))] if fixed else []
            turn.notes, turn.draft.notes = [*held, *turn.draft.notes], []
        return turn

    def _answer_with_words(self, consumed: Decision | None, text: str) -> None:
        if consumed is not None:
            if not consumed.allows_text:
                raise Refusal(f"the {consumed.kind!r} decision takes one of its options, not words")
            self.draft.note(
                PAUSED_TO_ASK.format(prompt=consumed.prompt)
                + "The PLAYER ACTION is the player's answer."
            )
        self.logged_words = self.master_action_text = text

    def _answer_with_option(self, consumed: Decision | None, option_id: Slug, text: str) -> None:
        if consumed is None:
            raise Refusal(f"no decision is open, so option {option_id!r} answers nothing")
        offered = find_option(consumed.options, option_id)
        if offered is None:
            raise Refusal(f"the {consumed.kind!r} decision offers no option {option_id!r}")
        option = offered.with_words(text)
        # A refusal raises: the engine enumerated the option, so it is never model error.
        facts = self._apply(lambda draft, rng: self.engine.play_option(draft, option, rng))
        traces = render_traces(facts)
        if self.draft.pending is not None:
            traces += f"\n- {RULES_WAIT}"
        self.draft.note(
            PAUSED_TO_ASK.format(prompt=consumed.prompt)
            + f"They chose: {option.name}. Already resolved:\n{traces}"
        )
        self.logged_words, self.master_action_text = option.name, ANSWERED_BY_OPTION
        self.by_option = True

    @property
    def told(self) -> tuple[Fact, ...]:
        return tuple(
            fact for fact in (*self.facts_carried_from_last_turn, *self.facts) if fact.told
        )

    @property
    def needs_narration(self) -> bool:
        draft = self.draft
        if draft.pending is not None:
            return False
        return bool(self.told) or (draft.request is None and not self.engine.in_battle(draft))

    @property
    def master_must_stop(self) -> bool:
        draft, engine = self.draft, self.engine
        return (
            self.direct_fact is not None
            or draft.pending is not None
            or draft.request is not None
            or engine.in_battle(draft)
            or engine.ending(draft) is not None
        )

    @property
    def state_changed(self) -> bool:
        return bool(self.facts) or self.draft.pending is not None

    def call_tool(self, name: str, arguments: str | dict[str, JsonValue]) -> str:
        try:
            return self._call_tool(
                name, decode(arguments) if isinstance(arguments, str) else arguments
            )
        except Refusal as refused:
            self.refused.append(
                RefusedCall(tool=name, reason=str(refused), after_facts=len(self.facts))
            )
            raise

    def _call_tool(self, name: str, raw: JsonValue) -> str:
        if (ended := self.engine.ending(self.draft)) is not None:
            raise Refusal(GAME_OVER.format(ending=ended.rstrip(".")))
        if name == DIRECT and self.direct_fact is not None:
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
        facts = self._apply(lambda draft, rng: self.engine.call_tool(draft, name, raw, rng))
        if name == DIRECT:
            self.direct_fact = facts[-1]
        elif self.direct_fact is not None:
            self.facts.remove(self.direct_fact)
            self.facts.append(self.direct_fact)
        notes, self.draft.notes = self.draft.notes, []
        lines = [f"- {line}" for line in (*(fact.trace for fact in facts), *notes)]
        if self.draft.pending is not None:
            lines.append(f"- {RULES_WAIT}")
        return "\n".join(lines) or NOTHING

    def published_tools(self) -> tuple[MasterTool, ...]:
        return self.engine.published(self.draft)

    def finish(self, lines: tuple[SpokenLine, ...]) -> AnyGame:
        if not self.needs_narration:
            self.draft.unnarrated = list(self.told)
        if self.master_plays_this_turn:
            self.engine.end_turn(self.draft, acted=bool(self.facts))
        return self.engine.record(
            self.draft,
            lines,
            tuple(self.facts),
            words=self.logged_words,
            by_option=self.by_option,
            refused=tuple(self.refused),
        )

    def _apply(self, play: Callable[[AnyGame, Random], tuple[Fact, ...]]) -> tuple[Fact, ...]:
        candidate, dice = self.draft.draft(), deepcopy(self.rng)
        facts = play(candidate, dice)
        self.draft = self.engine.accept(candidate)
        self.rng.setstate(dice.getstate())
        self.facts.extend(facts)
        return facts
