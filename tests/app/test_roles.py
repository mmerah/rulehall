from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from pydantic import BaseModel, JsonValue
from support.table import offline_settings

from rulehall.app.cli_roles import Driver
from rulehall.app.role_prompts import Debrief
from rulehall.app.roles import ProviderRoleRunner, ask
from rulehall.app.submission import SUBMIT, UNSUBMITTED, Submission, Submissions
from rulehall.app.turn import Turn
from rulehall.config import LiveSettings, Role, RoleConfig
from rulehall.core.log import Narration
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal


@dataclass(slots=True)
class _Replies:
    replies: list[str | Refusal] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        heard: Callable[[str], None] | None = None,
    ) -> str:
        del role, heard
        self.asked.append(prompt.text)
        reply = self.replies.pop(0)
        if isinstance(reply, Refusal):
            raise reply
        return reply

    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None:
        del prompt, turn
        raise AssertionError("no master turn is asked here")

    async def submit_answer[T: BaseModel](
        self, role: Role, prompt: Prompt, submission: Submission[T]
    ) -> None:
        del role, prompt, submission
        raise AssertionError("no submission is asked here")


async def test_a_retry_resends_the_whole_prompt_with_the_error() -> None:
    roles = _Replies(["not json", '{"lines": []}'])

    brief = Prompt(system="", user="THE WHOLE BRIEF")
    _ = await ask(roles, "narrator", brief, Narration, lambda _: None)

    assert roles.asked[0] == "THE WHOLE BRIEF"
    assert roles.asked[1].startswith("THE WHOLE BRIEF") and "refused" in roles.asked[1]


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


def test_a_refused_submission_stays_open_and_a_valid_one_is_accepted() -> None:
    submission = Submission(Debrief, Debrief.check)
    blank: dict[str, JsonValue] = {
        "story_so_far": "You reached the vault.",
        "current_aim": " ",
        "open_threads": ["You could open the door."],
        "last_beats": ["You lit a torch."],
    }

    with pytest.raises(Refusal, match="current_aim"):
        _ = submission.call_tool(SUBMIT, blank)
    assert not submission.must_stop
    answered = submission.call_tool(SUBMIT, blank | {"current_aim": "Open the vault."})

    assert "accepted" in answered
    assert submission.accepted is not None
    assert submission.accepted.current_aim == "Open the vault."
    assert submission.must_stop


async def test_a_cli_worldsmith_that_ends_unsubmitted_is_run_once_more_with_the_nudge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submissions = Submissions()
    prompts: list[str] = []
    debrief: dict[str, JsonValue] = {
        "story_so_far": "You reached the vault.",
        "current_aim": "Open the vault.",
        "open_threads": ["You could open the door."],
        "last_beats": ["You lit a torch."],
    }

    async def run_cli(
        role: Role,
        config: RoleConfig,
        driver: Driver,
        prompt: Prompt,
        *,
        mcp_url: str | None,
        mcp_token: str | None,
    ) -> str:
        del role, config, driver, mcp_url
        prompts.append(prompt.user)
        if len(prompts) == 2 and mcp_token is not None:
            _ = submissions.require(mcp_token).call_tool(SUBMIT, debrief)
        return "done"

    monkeypatch.setattr("rulehall.app.roles.run_cli", run_cli)
    runner = ProviderRoleRunner(LiveSettings(offline_settings()), submissions)

    answer = await ask(
        runner, "worldsmith", Prompt(system="", user="WRITE"), Debrief, Debrief.check
    )

    assert answer.current_aim == "Open the vault."
    assert prompts == ["WRITE", f"WRITE\n\n{UNSUBMITTED}"]
