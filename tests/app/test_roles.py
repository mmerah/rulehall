from collections.abc import Callable
from dataclasses import dataclass
from random import Random

import pytest
from support.game import initialized

from rulehall.app.roles import ask, run_master
from rulehall.app.spawn import RunResult
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.play import Answer, Narration
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal


@dataclass(slots=True)
class _AlwaysRefuses:
    calls: int = 0

    async def run(
        self,
        role: Role,
        prompt: Prompt,
        conversation: str | None,
        turn: Turn | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RunResult:

        del heard, role, prompt, conversation, turn
        self.calls += 1
        raise Refusal("boom")


def _turn_of() -> Turn:
    engine, state = initialized()
    return Turn.begin(engine, state, Answer(text="I wait."), Random(0))


async def test_a_master_that_lands_nothing_is_asked_once_not_retried() -> None:
    turn = _turn_of()
    spawner = _AlwaysRefuses()

    with pytest.raises(Refusal, match="boom"):
        await run_master(spawner, turn)

    assert spawner.calls == 1


async def test_a_master_that_already_landed_facts_is_not_retried_and_does_not_raise() -> None:
    turn = _turn_of()
    _ = turn.call(
        "change_tags", {"actor_id": "player", "kind": "condition", "gained": ["Listening"]}
    )
    spawner = _AlwaysRefuses()

    await run_master(spawner, turn)

    assert spawner.calls == 1


async def test_a_retry_carries_on_the_refused_attempt_and_sends_only_the_error() -> None:
    asked: list[tuple[str, str | None]] = []

    class _Spawner:
        async def run(
            self,
            role: Role,
            prompt: Prompt,
            conversation: str | None,
            turn: Turn | None = None,
            heard: Callable[[str], None] | None = None,
        ) -> RunResult:
            del heard, role, turn
            asked.append((prompt.text, conversation))
            return RunResult('{"lines": []}' if conversation else "not json", "abc-123")

    brief = Prompt(system="", user="THE WHOLE BRIEF")
    _ = await ask(_Spawner(), "narrator", brief, Narration, lambda _: None)

    assert asked[0] == ("THE WHOLE BRIEF", None)
    assert asked[1][1] == "abc-123"
    assert "THE WHOLE BRIEF" not in asked[1][0]


async def test_a_spawn_that_refuses_once_still_gets_its_one_retry() -> None:
    attempts: list[str | None] = []

    class _Spawner:
        async def run(
            self,
            role: Role,
            prompt: Prompt,
            conversation: str | None,
            turn: Turn | None = None,
            heard: Callable[[str], None] | None = None,
        ) -> RunResult:
            del heard, role, prompt, turn
            attempts.append(conversation)
            if len(attempts) == 1:
                raise Refusal("the narrator exited 1")
            return RunResult('{"lines": []}', "abc-123")

    prompt = Prompt(system="", user="PROMPT")
    answer = await ask(_Spawner(), "narrator", prompt, Narration, lambda _: None)

    assert answer == Narration(lines=())
    assert attempts == [None, None]


async def test_answered_nothing_usable_does_not_quote_the_checks_message() -> None:
    class _Spawner:
        async def run(
            self,
            role: Role,
            prompt: Prompt,
            conversation: str | None,
            turn: Turn | None = None,
            heard: Callable[[str], None] | None = None,
        ) -> RunResult:
            del heard, role, prompt, turn
            return RunResult('{"lines": []}', conversation or "abc-123")

    def _check(_: Narration) -> None:
        raise Refusal("a scene that does not name what is hidden: ['Bell']")

    prompt = Prompt(system="", user="PROMPT")
    with pytest.raises(Refusal, match="the narrator answered nothing usable") as failed:
        _ = await ask(_Spawner(), "narrator", prompt, Narration, _check)

    assert "Bell" not in str(failed.value)
