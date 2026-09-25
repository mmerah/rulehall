from pathlib import Path
from random import Random

import pytest
from pydantic import Field
from support.game import open_game
from support.table import NO_PACKS, Table, narrowed, play_turn, tool_call

from rulehall.app.turn import RULES_WAIT
from rulehall.core.facts import Fact
from rulehall.core.model import AnyGame
from rulehall.core.play import Answer, PendingDecision, PendingOption
from rulehall.core.tools import NoArgs, action, actions_of, tool, tools_of
from rulehall.core.validation import Frozen, Refusal
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner3e.engine import Loner3eEngine
from rulehall.engines.loner3e.world import Loner3eGame


class Broken(Frozen):
    item: str = Field(description="What breaks to turn the hit.")


def _turned(item: str) -> tuple[Fact, ...]:
    return (Fact(trace=f"{item} broke to turn the hit", told=True),)


class Deciding:
    def __init__(self, *, told: bool) -> None:
        self.told = told

    @tool
    def strike(self, draft: AnyGame, _args: NoArgs, _rng: Random) -> tuple[Fact, ...]:
        """Take a hit the player may turn by breaking something of theirs."""
        _loner(draft).pending = DECISION
        return (Fact(trace="the blow reaches the player", told=self.told),)

    @action
    def turn_the_hit(self, _draft: AnyGame, args: Broken, _rng: Random) -> tuple[Fact, ...]:
        return _turned(args.item)

    @action
    def chain_the_hit(self, draft: AnyGame, args: Broken, _rng: Random) -> tuple[Fact, ...]:
        _loner(draft).pending = DECISION
        return _turned(args.item)


def _decision(resolver_name: str) -> PendingDecision:
    return PendingDecision(
        kind="defence",
        prompt="The blow lands unless something of yours breaks. What gives?",
        options=(
            PendingOption(
                id="lantern",
                name="Break the lantern",
                brief="Its glass shatters.",
                action_name=resolver_name,
                args={"item": "lantern"},
            ),
        ),
        allows_text=True,
    )


DECISION = _decision("turn_the_hit")
CHAINING = _decision("chain_the_hit")


def _engine(*, told: bool = True) -> AnyEngine:
    engine = Loner3eEngine(NO_PACKS)
    deciding = Deciding(told=told)
    engine.tools = tools_of(deciding, lambda draft, texts: draft.world.check_unnamed(*texts))
    engine.actions = actions_of(deciding)
    return engine


def _deciding(saves: Path, *, told: bool = True) -> Table[Loner3eGame]:
    return open_game(saves, engine=_engine(told=told))


def _suspend(table: Table[Loner3eGame], decision: PendingDecision = DECISION) -> None:
    table.service.save(_pending(table.service.state, decision))


async def test_a_suspending_resolver_ends_the_run_and_records_the_pause(tmp_path: Path) -> None:
    table = _deciding(tmp_path)

    state = await play_turn(table, "I charge the guard.", tool_call("strike"))

    assert any(RULES_WAIT in answer for answer in table.answers)
    assert state.pending == DECISION
    assert state.exchanges()[-1].decision == DECISION.prompt
    assert [role for role, _ in table.spawner.prompts] == ["master", "narrator"]


async def test_a_closed_answer_resolves_in_engine_code_before_the_master_continues(
    tmp_path: Path,
) -> None:
    table = _deciding(tmp_path)
    _suspend(table)

    state = await play_turn(table, Answer(option_id="lantern"))

    assert [fact.trace for fact in table.facts] == ["lantern broke to turn the hit"]
    assert "lantern broke to turn the hit" in table.spawner.prompt("master")
    assert state.exchanges()[-1].words == "Break the lantern"
    assert state.pending is None


async def test_an_answer_that_re_suspends_spawns_no_master(tmp_path: Path) -> None:
    """Every tool would be refused while the rules wait, so the spawn would play nothing."""
    table = _deciding(tmp_path)
    _suspend(table, CHAINING)

    state = await play_turn(table, Answer(option_id="lantern"))

    assert state.pending == DECISION
    assert [role for role, _ in table.spawner.prompts] == ["narrator"]


async def test_an_option_the_decision_never_offered_raises(tmp_path: Path) -> None:
    table = _deciding(tmp_path)
    _suspend(table)

    with pytest.raises(Refusal, match="offers no option 'vest'"):
        _ = await play_turn(table, Answer(option_id="vest"))


def _option(**changes: object) -> PendingOption:
    return PendingOption.model_validate(
        {"id": "lantern", "name": "Break the lantern", "action_name": "turn_the_hit"} | changes
    )


def test_an_option_that_names_no_action_or_carries_args_it_rejects_is_refused(
    tmp_path: Path,
) -> None:
    engine, suspended = _engine(), _pending(open_game(tmp_path).service.state)
    draft = suspended.draft()

    assert engine.restore(suspended.model_dump_json()).pending == DECISION

    with pytest.raises(Refusal, match="'spend_momentum' is not an action of the"):
        _ = engine.play_option(draft, _option(action_name="spend_momentum"), Random(0))
    with pytest.raises(Refusal, match="Extra inputs are not permitted"):
        _ = engine.play_option(draft, _option(args={"nothing": "of theirs"}), Random(0))


def _pending(state: AnyGame, decision: PendingDecision = DECISION) -> Loner3eGame:
    draft = _loner(state).draft()
    draft.pending = decision
    return draft.commit()


def _loner(state: AnyGame) -> Loner3eGame:
    return narrowed(state, Loner3eGame)
