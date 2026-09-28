from collections.abc import Callable
from dataclasses import dataclass, field
from random import Random

import pytest
from support.game import initialized

from rulehall.app.roles import Debrief, RoleReply, ask, run_master
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.decisions import PlayerInput
from rulehall.core.log import Narration
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal


@dataclass(slots=True)
class _Replies:
    replies: list[str | Refusal] = field(default_factory=list)
    asked: list[tuple[str, str | None]] = field(default_factory=list)
    master_turns: int = 0

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        resume_id: str | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RoleReply:
        del role, heard
        self.asked.append((prompt.text, resume_id))
        reply = self.replies.pop(0)
        if isinstance(reply, Refusal):
            raise reply
        return RoleReply(reply, "abc-123")

    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None:
        del prompt, turn
        self.master_turns += 1
        raise Refusal("boom")


def _turn_of() -> Turn:
    engine, state = initialized()
    return Turn.begin(engine, state, PlayerInput(text="I wait."), Random(0))


async def test_a_master_that_lands_nothing_is_asked_once_not_retried() -> None:
    turn = _turn_of()
    roles = _Replies()

    with pytest.raises(Refusal, match="boom"):
        await run_master(roles, turn)

    assert roles.master_turns == 1


async def test_a_master_that_already_landed_facts_is_not_retried_and_does_not_raise() -> None:
    turn = _turn_of()
    _ = turn.call_tool(
        "change_tags", {"actor_id": "player", "kind": "condition", "gained": ["Listening"]}
    )
    roles = _Replies()

    await run_master(roles, turn)

    assert roles.master_turns == 1


async def test_a_retry_carries_on_the_refused_attempt_and_sends_only_the_error() -> None:
    roles = _Replies(["not json", '{"lines": []}'])

    brief = Prompt(system="", user="THE WHOLE BRIEF")
    _ = await ask(roles, "narrator", brief, Narration, lambda _: None)

    assert roles.asked[0] == ("THE WHOLE BRIEF", None)
    assert roles.asked[1][1] == "abc-123"
    assert "THE WHOLE BRIEF" not in roles.asked[1][0]


async def test_a_bad_answer_gets_one_retry_and_a_crash_gets_none() -> None:
    prompt = Prompt(system="", user="PROMPT")
    bad_then_good = _Replies(["not json", '{"lines": []}'])
    crashed = _Replies([Refusal("the narrator exited 1"), '{"lines": []}'])

    answer = await ask(bad_then_good, "narrator", prompt, Narration, lambda _: None)
    with pytest.raises(Refusal, match="exited 1"):
        _ = await ask(crashed, "narrator", prompt, Narration, lambda _: None)

    assert answer == Narration(lines=())
    assert len(bad_then_good.asked) == 2
    assert len(crashed.asked) == 1


async def test_answered_nothing_usable_does_not_quote_the_checks_message() -> None:
    roles = _Replies(['{"lines": []}', '{"lines": []}'])

    def _check(_: Narration) -> None:
        raise Refusal("a scene that does not name what is hidden: ['Bell']")

    prompt = Prompt(system="", user="PROMPT")
    with pytest.raises(Refusal, match="the narrator answered nothing usable") as failed:
        _ = await ask(roles, "narrator", prompt, Narration, _check)

    assert "Bell" not in str(failed.value)


def test_a_debrief_with_a_blank_field_is_refused() -> None:
    debrief = Debrief(
        story_so_far="You reached the vault.",
        current_aim=" ",
        open_threads=("You could open the door.",),
        last_beats=("You lit a torch.", ""),
    )

    with pytest.raises(Refusal, match="current_aim, last_beats"):
        debrief.check()
