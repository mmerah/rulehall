import json
import logging
import os
import shutil
import signal
import sys
from asyncio import StreamReader, shield, subprocess, timeout
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from subprocess import DEVNULL, run
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Annotated, Protocol

from pydantic import Field, ValidationError

from rulehall.app.api_roles import run_over_api
from rulehall.app.turn import Turn
from rulehall.config import CliProvider, Role, RoleConfig, Settings
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Loose, Refusal, parse_json

LOGGER = logging.getLogger(__name__)

# The child gets nothing else: the parent shell may hold keys no role may see.
# The names past TERM are Windows ones: the CLIs need them to start and to find their logins.
KEPT_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "TERM",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
)
OUTPUT_MAX_BYTES = 4_194_304  # a role answer is kilobytes; a runaway CLI streams without end
# The id goes back as an argv element; a leading `-` must not parse as a flag.
ConversationId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]


@dataclass(frozen=True, slots=True)
class RunResult:
    text: str
    conversation: str | None


class Driver(Protocol):
    """A driver never starts a process."""

    @property
    def secrets(self) -> tuple[str, ...]: ...

    def command(
        self, role: Role, config: RoleConfig, conversation: str | None, url: str
    ) -> Sequence[str]: ...
    def delta(self, line: str) -> str: ...
    def read_result(self, output: str) -> RunResult: ...


class Spawner(Protocol):
    async def run(
        self,
        role: Role,
        prompt: Prompt,
        conversation: str | None,
        turn: Turn | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RunResult: ...


class _ClaudeResult(Loose):
    result: str
    session_id: ConversationId
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
    thread_id: ConversationId | None = None
    item: _CodexItem | None = None


@dataclass(frozen=True, slots=True)
class ClaudeDriver:
    secrets: tuple[str, ...] = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

    def command(
        self, role: Role, config: RoleConfig, conversation: str | None, url: str
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
            *(() if conversation is None else ("--resume", conversation)),
            "--restricted",
            # Measured on 2.1.282: no built-in tool is left; the MCP tools stay.
            "--tools",
            "",
        ]
        if role == "master":
            argv += ["--allowed-tools", "mcp__rulehall", "--mcp-config", _claude_mcp(url)]
        return (*argv, "--strict-mcp-config")

    def delta(self, line: str) -> str:
        with suppress(ValidationError):
            event = _ClaudeEvent.model_validate_json(line).event
            if event is not None and event.delta is not None:
                return event.delta.text
        return ""

    def read_result(self, output: str) -> RunResult:
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
        return RunResult(final_message(result.result), result.session_id)


@dataclass(frozen=True, slots=True)
class CodexDriver:
    secrets: tuple[str, ...] = ("OPENAI_API_KEY",)

    def command(
        self, role: Role, config: RoleConfig, conversation: str | None, url: str
    ) -> Sequence[str]:
        argv = ["codex", "exec", *(() if conversation is None else ("resume", conversation))]
        argv += [
            "--json",
            "--model",
            config.model,
            "-c",
            f"model_reasoning_effort={config.effort}",
            "-c",
            "web_search=disabled",
            # The account's own MCP servers, which `--ignore-user-config` keeps.
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
        if role == "master":
            # Measured: under `approval_policy=never` an MCP call is refused without this.
            argv += ["-c", "mcp_servers.rulehall.default_tools_approval_mode=approve"]
            argv += ["-c", f"mcp_servers.rulehall.url={url}"]
        # `resume` reads the prompt from stdin only when told so by `-`.
        return [*argv, "-"]

    def delta(self, line: str) -> str:
        # `codex exec --json` prints a message only once it is complete: nothing to stream.
        del line
        return ""

    def read_result(self, output: str) -> RunResult:
        events = _codex_events(output)
        thread = next((event.thread_id for event in events if event.thread_id is not None), None)
        return RunResult(_said(events) or final_message(output), thread)


DRIVERS: Mapping[CliProvider, Driver] = {"claude": ClaudeDriver(), "codex": CodexDriver()}


@dataclass(slots=True)
class RoleRunner:
    settings: Settings

    async def run(
        self,
        role: Role,
        prompt: Prompt,
        conversation: str | None,
        turn: Turn | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RunResult:
        config = self.settings.roles.for_name(role)
        started = monotonic()
        try:
            async with timeout(config.timeout):
                match config.provider:
                    case "claude" | "codex":
                        driver = DRIVERS[config.provider]
                        port = self.settings.server.port
                        result = await run_cli(
                            role, config, driver, port, prompt, conversation, heard
                        )
                        detail = "resumed" if conversation is not None else "cold"
                    case "openrouter" | "local":
                        provider = self.settings.providers.for_name(config.provider)
                        text = await run_over_api(role, config, provider, prompt, turn, heard)
                        result = RunResult(final_message(text), None)
                        detail = "over the API"
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


async def run_cli(
    role: Role,
    config: RoleConfig,
    driver: Driver,
    port: int,
    prompt: Prompt,
    conversation: str | None,
    heard: Callable[[str], None] | None = None,
) -> RunResult:
    """One of the two places that start a process; `line_process.start_process` is the other."""
    url = f"http://localhost:{port}/mcp/"
    argv = driver.command(role, config, conversation, url)
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


def final_message(output: str) -> str:
    fenced = output.rsplit("```", 2)
    if len(fenced) == 3:
        body = fenced[1]
        if body.startswith("json") and "\n" in body:
            body = body.split("\n", 1)[1]
        else:
            body = body.removeprefix("json")
        # A fence holding something else is prose about the answer, not the answer.
        with suppress(json.JSONDecodeError, RecursionError):
            json.loads(body)
            return body
    tail = output.rstrip()
    # Only the first `{`: digging past a broken one costs a whole re-prompt on a chatty answer.
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


def child_environment(secrets: Sequence[str]) -> dict[str, str]:
    return {name: os.environ[name] for name in (*KEPT_ENV, *secrets) if name in os.environ}


async def stop_process(process: subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        _kill_tree(process.pid)
    # Shielded: a second cancel would abandon the wait mid-reap.
    await shield(process.wait())


async def _spawn(
    role: Role,
    argv: Sequence[str],
    prompt: str,
    secrets: Sequence[str],
    cwd: str,
    heard_line: Callable[[str], None],
) -> str:
    env = child_environment(secrets)
    # PATHEXT finds the `.cmd` shim npm installs on Windows, which a bare name misses.
    executable = shutil.which(argv[0], path=env.get("PATH"))
    if executable is None:
        raise Refusal(f"the {role} could not be started: {argv[0]} is not on the PATH")
    try:
        process = await subprocess.create_subprocess_exec(
            executable,
            *argv[1:],
            # Not argv: Windows caps a command line near 32 KB, and a `.cmd` shim near 8 KB.
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=env,
            # Its own group, so an abandoned spawn leaves no child process running.
            start_new_session=True,
            limit=OUTPUT_MAX_BYTES,
        )
    except OSError as failed:
        raise Refusal(f"the {role} could not be started: {failed}") from failed
    try:
        assert process.stdin is not None and process.stdout is not None
        # No drain: the pipe flushes while the output is read, so a full pipe cannot deadlock.
        process.stdin.write(prompt.encode())
        process.stdin.close()
        output = await _capped(role, process.stdout, heard_line)
        _ = await process.wait()
    finally:
        # Does nothing once it exited; an abandoned or timed-out spawn dies with its children.
        await stop_process(process)
    if process.returncode != 0:
        LOGGER.warning("the %s exited %s: %s", role, process.returncode, output[-500:])
        raise Refusal(f"the {role} exited {process.returncode}")
    return output


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        # Windows has no process groups; `/T` also kills the child a `.cmd` shim started.
        _ = run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=DEVNULL, stderr=DEVNULL)
    else:
        os.killpg(pid, signal.SIGKILL)


def _claude_mcp(url: str) -> str:
    """A string, not a file: `--mcp-config` takes either, and a string needs no cleanup."""
    return json.dumps({"mcpServers": {"rulehall": {"type": "http", "url": url}}})


def _codex_events(output: str) -> list[_CodexEvent]:
    events: list[_CodexEvent] = []
    for line in output.splitlines():
        with suppress(ValidationError):
            events.append(_CodexEvent.model_validate_json(line))
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
    """Stderr is merged into stdout, so the cap covers both."""
    read: list[str] = []
    size = 0
    try:
        async for raw in stdout:
            size += len(raw)
            if size > OUTPUT_MAX_BYTES:
                break
            line = raw.decode(errors="replace")
            read.append(line)
            heard_line(line)
        else:
            return "".join(read)
    except ValueError:
        pass
    raise Refusal(f"the {role} printed more than {OUTPUT_MAX_BYTES} bytes")
