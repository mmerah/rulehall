import json
import logging
from asyncio import StreamReader, subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Annotated, NamedTuple, Protocol

from pydantic import Field

from rulehall.app.processes import start_child, stop_process
from rulehall.config import CliProvider, Role, RoleConfig
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Loose, Refusal, parse_json

LOGGER = logging.getLogger(__name__)

OUTPUT_MAX_BYTES = 4_194_304
# The id goes back as an argv element; a leading `-` must not parse as a flag.
ResumeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]


class CliReply(NamedTuple):
    text: str
    resume_id: str | None


class Driver(Protocol):
    @property
    def secrets(self) -> tuple[str, ...]: ...

    def command(
        self, config: RoleConfig, resume_id: str | None, mcp_url: str | None
    ) -> Sequence[str]: ...
    def delta(self, line: str) -> str: ...
    def read_result(self, output: str) -> CliReply: ...


class _ClaudeResult(Loose):
    result: str
    session_id: ResumeId
    # A failed run can still exit 0 and put its error where the answer goes.
    is_error: bool = False


class _ClaudeDelta(Loose):
    text: str = ""


class _ClaudeStreamEvent(Loose):
    delta: _ClaudeDelta | None = None


class _ClaudeEvent(Loose):
    event: _ClaudeStreamEvent | None = None


class _CodexItem(Loose):
    type: str
    text: str = ""


class _CodexEvent(Loose):
    """`type` is required: a bare answer object must not parse as an event."""

    type: str
    thread_id: ResumeId | None = None
    item: _CodexItem | None = None


@dataclass(frozen=True, slots=True)
class ClaudeDriver:
    secrets: tuple[str, ...] = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

    def command(
        self, config: RoleConfig, resume_id: str | None, mcp_url: str | None
    ) -> Sequence[str]:
        argv = [
            "claude",
            "-p",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--model",
            config.model,
            "--effort",
            config.effort,
            *(() if resume_id is None else ("--resume", resume_id)),
            "--restricted",
            "--tools",
            "",
        ]
        if mcp_url is not None:
            argv += ["--allowed-tools", "mcp__rulehall", "--mcp-config", _claude_mcp(mcp_url)]
        return (*argv, "--strict-mcp-config")

    def delta(self, line: str) -> str:
        with suppress(Refusal):
            event = parse_json(_ClaudeEvent, line).event
            if event is not None and event.delta is not None:
                return event.delta.text
        return ""

    def read_result(self, output: str) -> CliReply:
        for line in reversed(output.splitlines()):
            with suppress(Refusal):
                result = parse_json(_ClaudeResult, line)
                break
        else:
            LOGGER.warning("claude printed no JSON result: %s", output[-500:])
            raise Refusal("claude printed no JSON result")
        if result.is_error:
            LOGGER.warning("the run failed: %s", result.result[-500:])
            raise Refusal("the run failed")
        return CliReply(result.result, result.session_id)


@dataclass(frozen=True, slots=True)
class CodexDriver:
    secrets: tuple[str, ...] = ("OPENAI_API_KEY",)

    def command(
        self, config: RoleConfig, resume_id: str | None, mcp_url: str | None
    ) -> Sequence[str]:
        argv = ["codex", "exec", *(() if resume_id is None else ("resume", resume_id))]
        argv += [
            "--json",
            "--model",
            config.model,
            "-c",
            f"model_reasoning_effort={config.effort}",
            "-c",
            "web_search=disabled",
            "--disable",
            "apps",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            # `resume` takes no `--sandbox`; `-c` works in both forms.
            "-c",
            "sandbox_mode=read-only",
            "-c",
            "approval_policy=never",
            # Measured: the read-only sandbox still lets these tools read any file.
            "--disable",
            "shell_tool",
            "--disable",
            "unified_exec",
            "--disable",
            "view_image",
            "--disable",
            "image_generation",
        ]
        if mcp_url is not None:
            # Measured: under `approval_policy=never` an MCP call is refused without this.
            argv += ["-c", "mcp_servers.rulehall.default_tools_approval_mode=approve"]
            argv += ["-c", f"mcp_servers.rulehall.url={mcp_url}"]
        # `resume` reads the prompt from stdin only when told so by `-`.
        return [*argv, "-"]

    def delta(self, line: str) -> str:
        del line
        return ""

    def read_result(self, output: str) -> CliReply:
        events = _codex_events(output)
        thread = next((event.thread_id for event in events if event.thread_id is not None), None)
        return CliReply(_said(events) or output, thread)


DRIVERS: Mapping[CliProvider, Driver] = {"claude": ClaudeDriver(), "codex": CodexDriver()}


async def run_cli(
    role: Role,
    config: RoleConfig,
    driver: Driver,
    prompt: Prompt,
    *,
    resume_id: str | None = None,
    mcp_url: str | None = None,
    heard: Callable[[str], None] | None = None,
) -> CliReply:
    argv = driver.command(config, resume_id, mcp_url)
    said = ""

    def heard_line(line: str) -> None:
        nonlocal said
        if heard is not None and (piece := driver.delta(line)):
            said += piece
            heard(said)

    # An empty working directory, so a role cannot read this repository even if it tries.
    with TemporaryDirectory(prefix=f"rulehall-{role}-") as empty:
        output = await _spawn(role, argv, prompt.text, driver.secrets, empty, heard_line)
    return driver.read_result(output)


async def _spawn(
    role: Role,
    argv: Sequence[str],
    prompt: str,
    secrets: Sequence[str],
    cwd: str,
    heard_line: Callable[[str], None],
) -> str:
    process = await start_child(
        argv, secrets=secrets, cwd=cwd, stderr=subprocess.STDOUT, limit=OUTPUT_MAX_BYTES
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        # Not argv: Windows caps a command line near 32 KB, and a `.cmd` shim near 8 KB.
        process.stdin.write(prompt.encode())
        process.stdin.close()
        output = await _capped(role, process.stdout, heard_line)
        _ = await process.wait()
    finally:
        await stop_process(process)
    if process.returncode != 0:
        LOGGER.warning("the %s exited %s: %s", role, process.returncode, output[-500:])
        raise Refusal(f"the {role} exited {process.returncode}")
    return output


def _claude_mcp(url: str) -> str:
    return json.dumps({"mcpServers": {"rulehall": {"type": "http", "url": url}}})


def _codex_events(output: str) -> list[_CodexEvent]:
    events: list[_CodexEvent] = []
    for line in output.splitlines():
        with suppress(Refusal):
            events.append(parse_json(_CodexEvent, line))
    return events


def _said(events: Sequence[_CodexEvent]) -> str | None:
    """The last agent message is the answer; a resumed thread holds earlier ones."""
    spoken = (
        event.item.text
        for event in reversed(events)
        if event.item is not None and event.item.type == "agent_message" and event.item.text
    )
    return next(spoken, None)


async def _capped(role: Role, stdout: StreamReader, heard_line: Callable[[str], None]) -> str:
    read: list[str] = []
    size = 0
    overflow = f"the {role} printed more than {OUTPUT_MAX_BYTES} bytes"
    try:
        async for raw in stdout:
            size += len(raw)
            if size > OUTPUT_MAX_BYTES:
                raise Refusal(overflow)
            line = raw.decode(errors="replace")
            read.append(line)
            heard_line(line)
    except ValueError as overlong:
        raise Refusal(overflow) from overlong
    return "".join(read)
