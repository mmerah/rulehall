import asyncio
import json
from dataclasses import dataclass, field

import pytest

import rulehall.app.spawn as spawn
from rulehall.app.spawn import (
    ClaudeDriver,
    CodexDriver,
    RunResult,
    child_environment,
    final_message,
    run_cli,
)
from rulehall.config import Role, RoleConfig
from rulehall.core.io import decode
from rulehall.core.prompt import Prompt
from rulehall.core.validation import Refusal


@dataclass(frozen=True, slots=True)
class _StubDriver:
    argv: tuple[str, ...]
    secrets: tuple[str, ...] = ()

    def command(
        self, role: Role, config: RoleConfig, conversation: str | None, url: str
    ) -> tuple[str, ...]:
        del role, config, conversation, url
        return self.argv

    def delta(self, line: str) -> str:
        return line

    def read_result(self, output: str) -> RunResult:
        del output
        raise AssertionError("the run fails before there is a result to read")


@dataclass(slots=True)
class _Started:
    found: list[tuple[str, str | None]] = field(default_factory=list[tuple[str, str | None]])
    argv: tuple[str, ...] = ()
    stdin: list[bytes] = field(default_factory=list[bytes])
    closed: bool = False


CODEX_OUTPUT = "\n".join(
    (
        '{"type":"thread.started","thread_id":"abc-123"}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"lines\\": []}"}}',
        '{"type":"turn.completed","usage":{"input_tokens":900,"cached_input_tokens":700}}',
    )
)


def _delta(text: str) -> str:
    return json.dumps(
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
        }
    )


CLAUDE_OUTPUT = "\n".join(
    (
        '{"type":"system","subtype":"init","session_id":"abc-123"}',
        _delta('{"lines": '),
        '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"hm"}}}',
        _delta("[]}"),
        json.dumps({"type": "result", "result": "said", "session_id": "abc-123"}),
    )
)


def test_no_codex_role_gets_a_shell_and_only_the_master_reaches_the_tools() -> None:
    config = RoleConfig(provider="codex", model="gpt-5", effort="low")
    master = CodexDriver().command("master", config, None, "http://localhost:1/mcp/")
    narrator = CodexDriver().command("narrator", config, None, "")

    assert "mcp_servers.rulehall.url=http://localhost:1/mcp/" in master
    assert "mcp_servers.rulehall.default_tools_approval_mode=approve" in master
    assert not any(line.startswith("mcp_servers") for line in narrator)
    for argv in (master, narrator):
        # `resume` accepts no sandbox flag, so the box rides `-c`, which both forms accept.
        assert "--sandbox" not in argv and "--approve-for-me" not in argv
        assert "sandbox_mode=read-only" in argv and "approval_policy=never" in argv
        disabled = {argv[at + 1] for at, flag in enumerate(argv) if flag == "--disable"}
        # The read-only sandbox blocks writes only; these tools read any file on the host.
        assert {"shell_tool", "unified_exec", "view_image", "image_generation"} <= disabled
        # `--ignore-user-config` leaves the account's own MCP servers standing; this removes them.
        assert "apps" in disabled
        assert "--ignore-user-config" in argv
        assert "web_search=disabled" in argv
        assert argv[-1] == "-"


def test_a_resumed_codex_run_still_reads_its_prompt_from_stdin() -> None:
    config = RoleConfig(provider="codex", model="gpt-5", effort="low")

    argv = CodexDriver().command("narrator", config, "abc-123", "")

    assert argv[:4] == ["codex", "exec", "resume", "abc-123"]
    assert argv[-1] == "-"


def test_no_claude_role_keeps_a_built_in_tool_and_only_the_master_reaches_the_tools() -> None:
    config = RoleConfig(model="haiku", effort="low")
    master = ClaudeDriver().command("master", config, None, "http://localhost:1/mcp/")
    narrator = ClaudeDriver().command("narrator", config, None, "")

    assert "--mcp-config" in master and "--mcp-config" not in narrator
    for argv in (master, narrator):
        tools = argv.index("--tools")
        assert argv[tools + 1] == ""
        assert "--restricted" in argv and argv[-1] == "--strict-mcp-config"


def test_a_failed_claude_run_does_not_quote_its_raw_result() -> None:
    output = json.dumps(
        {"result": "HIDDEN HERE the arc", "session_id": "abc-123", "is_error": True}
    )

    with pytest.raises(Refusal, match="the run failed") as failed:
        _ = ClaudeDriver().read_result(output)

    assert "HIDDEN HERE" not in str(failed.value)


async def test_a_missing_cli_binary_is_a_refusal_not_a_crash() -> None:
    config = RoleConfig(model="opus", effort="high")

    prompt = Prompt(system="", user="PLAY")
    with pytest.raises(Refusal, match="could not be started: rulehall-no-such-binary"):
        _ = await run_cli(
            "master", config, _StubDriver(("rulehall-no-such-binary",)), 1, prompt, None
        )


async def test_the_cli_is_found_on_the_childs_path_and_reads_its_prompt_from_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _faked(monkeypatch, b"said", 3)
    config = RoleConfig(model="opus", effort="high")
    monkeypatch.setenv("PATH", "/opt/cli")
    prompt = Prompt(system="", user="x" * 200_000)

    with pytest.raises(Refusal, match="exited 3"):
        _ = await run_cli("narrator", config, _StubDriver(("rulehall-cli", "-p")), 1, prompt, None)

    assert started.found == [("rulehall-cli", "/opt/cli")]
    assert started.argv == ("/opt/cli/rulehall-cli", "-p")
    assert started.stdin == [prompt.text.encode()] and started.closed


def _faked(monkeypatch: pytest.MonkeyPatch, output: bytes, returncode: int) -> _Started:
    started = _Started()

    def fake_which(name: str, path: str | None) -> str:
        started.found.append((name, path))
        return f"{path}/{name}"

    class FakeStdin:
        def write(self, data: bytes) -> None:
            started.stdin.append(data)

        def close(self) -> None:
            started.closed = True

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdin = FakeStdin()
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(output)
            self.stdout.feed_eof()

        async def wait(self) -> int:
            return returncode

    async def fake_create(*argv: str, **_kwargs: object) -> FakeProcess:
        started.argv = argv
        return FakeProcess()

    monkeypatch.setattr(spawn.shutil, "which", fake_which)
    monkeypatch.setattr(spawn.subprocess, "create_subprocess_exec", fake_create)
    return started


async def test_a_crashed_roles_raw_output_never_reaches_the_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = _faked(monkeypatch, b"HIDDEN HERE the arc", 3)
    config = RoleConfig(model="opus", effort="high")
    prompt = Prompt(system="", user="PLAY")

    with pytest.raises(Refusal, match="master exited 3") as failed:
        _ = await run_cli("master", config, _StubDriver(("rulehall-crashing",)), 1, prompt, None)

    assert "HIDDEN HERE" not in str(failed.value)


@pytest.mark.parametrize(
    ("driver", "output", "streamed"),
    ((ClaudeDriver(), CLAUDE_OUTPUT, '{"lines": []}'), (CodexDriver(), CODEX_OUTPUT, "")),
    ids=("claude", "codex"),
)
def test_a_driver_reads_the_conversation_its_cli_reported_and_streams_only_the_answers_text(
    driver: ClaudeDriver | CodexDriver, output: str, streamed: str
) -> None:
    assert driver.read_result(output).conversation == "abc-123"
    assert "".join(driver.delta(line) for line in output.splitlines()) == streamed


def test_a_deeply_nested_answer_is_refused_not_a_bare_recursion_error() -> None:
    depth = 12000
    nested = '{"lines": ' + "[" * depth + "]" * depth + "}"

    assert final_message(nested) == nested
    assert final_message(f"```json\n{nested}\n```") is not None
    with pytest.raises(Refusal, match="not JSON"):
        _ = decode(nested)


def test_the_child_environment_holds_nothing_but_the_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("A_KEY_NO_ROLE_SHOULD_SEE", "secret")
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    env = child_environment(ClaudeDriver().secrets)

    assert "A_KEY_NO_ROLE_SHOULD_SEE" not in env
    assert env["PATH"] == "/bin"
    assert env["ANTHROPIC_API_KEY"] == "k"


def test_the_child_keeps_what_windows_needs_to_start_a_cli_and_find_its_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = ("SYSTEMROOT", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
    for name in windows:
        monkeypatch.setenv(name, name.lower())
    monkeypatch.delenv("TEMP", raising=False)

    env = child_environment(())

    assert all(env[name] == name.lower() for name in windows)
    assert "TEMP" not in env


async def test_a_role_that_floods_its_output_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spawn, "OUTPUT_MAX_BYTES", 16)
    _ = _faked(monkeypatch, b"x" * 64, 0)
    config = RoleConfig(model="opus", effort="high")
    prompt = Prompt(system="", user="PLAY")

    with pytest.raises(Refusal, match="master printed more than 16 bytes"):
        _ = await run_cli("master", config, _StubDriver(("rulehall-flooding",)), 1, prompt, None)


async def test_a_listener_hears_the_text_so_far_line_by_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = _faked(monkeypatch, b"a\nb\n", 3)
    config = RoleConfig(model="opus", effort="high")
    heard: list[str] = []

    with pytest.raises(Refusal, match="exited 3"):
        _ = await run_cli(
            "narrator",
            config,
            _StubDriver(("rulehall-talking",)),
            1,
            Prompt(system="", user="PLAY"),
            None,
            heard.append,
        )

    assert heard == ["a\n", "a\nb\n"]
