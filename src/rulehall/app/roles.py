import json
import logging
from asyncio import timeout
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from functools import partial
from time import monotonic
from typing import Protocol

from pydantic import BaseModel

from rulehall.app.api_roles import converse, stream_answer
from rulehall.app.cli_roles import DRIVERS, McpAccess, run_cli
from rulehall.app.mcp import OpenToolProviders
from rulehall.app.submission import Submission
from rulehall.config import LiveSettings, Role, RoleConfig
from rulehall.core.answer_repair import parse_with_repairs
from rulehall.core.game import Check, RoleAnswer
from rulehall.core.prompt import Prompt
from rulehall.core.tools import ToolProvider
from rulehall.core.validation import Refusal, decode

LOGGER = logging.getLogger(__name__)

RETRIES = 1


class RoleRunner(Protocol):
    tool_providers: OpenToolProviders

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        heard: Callable[[str], None] | None = None,
    ) -> str: ...
    async def play_tools(self, role: Role, prompt: Prompt, provider: ToolProvider) -> None: ...


@dataclass(slots=True)
class ProviderRoleRunner:
    live_settings: LiveSettings
    tool_providers: OpenToolProviders = field(default_factory=OpenToolProviders)

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        heard: Callable[[str], None] | None = None,
    ) -> str:
        return await self._run(role, prompt, heard=heard) or ""

    async def play_tools(self, role: Role, prompt: Prompt, provider: ToolProvider) -> None:
        port = self.live_settings.current.server.port
        with self.tool_providers.open(provider) as token:
            mcp = McpAccess(f"http://localhost:{port}/mcp/", token)
            _ = await self._run(role, prompt, tools=provider, mcp=mcp)

    async def _run(
        self,
        role: Role,
        prompt: Prompt,
        *,
        heard: Callable[[str], None] | None = None,
        tools: ToolProvider | None = None,
        mcp: McpAccess | None = None,
    ) -> str | None:
        settings = self.live_settings.current
        config = settings.roles.for_name(role)
        match config.provider:
            case "claude" | "codex":
                driver = DRIVERS[config.provider]
                running = run_cli(role, config, driver, prompt, mcp=mcp, heard=heard)
                return await _within_budget(role, config, running, detail="over the CLI")
            case "openrouter" | "local":
                provider = settings.providers.for_name(config.provider)
                running = (
                    stream_answer(role, config, provider, prompt, heard)
                    if tools is None
                    else converse(role, config, provider, prompt, tools)
                )
                return await _within_budget(role, config, running, detail="over the API")


async def ask_by_submission[T: BaseModel](
    runner: RoleRunner, role: Role, prompt: Prompt, model: type[T], check: Check[T]
) -> T:
    submission = Submission(model, check)
    await runner.play_tools(role, prompt, submission)
    # Only a CLI run can stop unaccepted: a conversation over the API nudges within itself.
    if submission.accepted is None:
        nudged = replace(prompt, user=f"{prompt.user}\n\n{submission.nudge}")
        await runner.play_tools(role, nudged, submission)
    if submission.accepted is None:
        raise Refusal(f"the {role} answered nothing usable")
    return submission.accepted


async def ask_with_retry[T: BaseModel](
    runner: RoleRunner,
    role: Role,
    prompt: Prompt,
    model: type[T],
    check: Check[T],
    heard: Callable[[str], None] | None = None,
) -> T:
    asked, refused = prompt, ""
    for _ in range(RETRIES + 1):
        reply = await runner.answer(role, asked, heard=heard)
        try:
            answer = parse_with_repairs(model, decode(final_message(reply)))
            check(answer)
        except Refusal as invalid:
            refused = str(invalid)
        else:
            return answer
        correction = f"Your last answer was refused: {refused}\nAnswer again. Correct the error."
        asked = replace(prompt, user=f"{prompt.user}\n\n{correction}")
    LOGGER.warning("the %s answered nothing usable: %s", role, refused)
    raise Refusal(f"the {role} answered nothing usable")


def role_answer(runner: RoleRunner, role: Role) -> RoleAnswer:
    if role == "worldsmith":
        return partial(ask_by_submission, runner, role)
    return partial(ask_with_retry, runner, role)


def final_message(output: str) -> str:
    fenced = output.rsplit("```", 2)
    if len(fenced) == 3:
        body = fenced[1]
        if body.startswith("json") and "\n" in body:
            body = body.split("\n", 1)[1]
        else:
            body = body.removeprefix("json")
        with suppress(json.JSONDecodeError, RecursionError):
            json.loads(body)
            return body
    tail = output.rstrip()
    start = tail.find("{")
    if start != -1:
        try:
            _, end = json.JSONDecoder().raw_decode(tail, start)
        except (json.JSONDecodeError, RecursionError):
            pass
        else:
            if end == len(tail):
                return tail[start:]
    return output


async def _within_budget[T](
    role: Role, config: RoleConfig, running: Awaitable[T], *, detail: str
) -> T:
    started = monotonic()
    try:
        async with timeout(config.timeout):
            result = await running
    except TimeoutError:
        raise Refusal(f"the {role} answered nothing in {config.timeout:.0f}s") from None
    LOGGER.info(
        "%s answered: provider=%s model=%s effort=%s %s in %.1fs",
        role,
        config.provider,
        config.model,
        config.effort,
        detail,
        monotonic() - started,
    )
    return result
