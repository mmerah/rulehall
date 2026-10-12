"""The master's tools over the MCP endpoint, driven in process through httpx's ASGI transport."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from httpx import ASGITransport, AsyncClient
from support.table import NO_PACKS, narrated, offline_settings

from rulehall.app.catalog import SavedGameKey
from rulehall.app.mcp import NO_TOOLS, TOOLS_HEADER, MountedLifespan, OpenToolProviders, endpoint
from rulehall.app.role_prompts import Debrief
from rulehall.app.runtime import Runtime
from rulehall.app.submission import SUBMIT, Submission
from rulehall.config import Role
from rulehall.core.decisions import PlayerInput
from rulehall.core.prompt import Prompt
from rulehall.core.tools import ToolProvider
from rulehall.core.validation import EngineId
from rulehall.engines.loner4e.engine import Loner4eEngine

BASE_URL = "http://localhost:8123"
ENTER_TOMAS: dict[str, object] = {"name": "enter", "arguments": {"target_id": "tomas"}}


class Tool(TypedDict):
    name: str


class Content(TypedDict):
    text: str


class Result(TypedDict, total=False):
    tools: list[Tool]
    content: list[Content]
    isError: bool


class Reply(TypedDict, total=False):
    result: Result


@dataclass(slots=True)
class HttpMaster:
    """The narrator answers directly; the master calls tools over the mounted MCP endpoint."""

    client: AsyncClient | None = None
    tool_providers: OpenToolProviders = field(default_factory=OpenToolProviders)
    tools_seen: list[str] = field(default_factory=list)
    change_result: Result | None = None

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        heard: Callable[[str], None] | None = None,
    ) -> str:
        del role, prompt, heard
        return narrated("You wait.")

    async def play_tools(self, role: Role, prompt: Prompt, provider: ToolProvider) -> None:
        del role, prompt
        assert self.client is not None
        with self.tool_providers.open(provider) as token:
            listed = await rpc(self.client, "tools/list", {}, token)
            self.tools_seen = [tool["name"] for tool in listed.get("result", {}).get("tools", [])]
            called = await rpc(self.client, "tools/call", ENTER_TOMAS, token)
        self.change_result = called.get("result")


async def rpc(
    client: AsyncClient, method: str, params: dict[str, object], token: str = ""
) -> Reply:
    routed = {TOOLS_HEADER: token} if token else {}
    reply = await client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **routed,
        },
    )
    return reply.json()


async def test_master_tools_over_the_mcp_endpoint(tmp_path: Path) -> None:
    master = HttpMaster()
    runtime = Runtime(offline_settings(tmp_path), roles=master)
    asgi, manager = endpoint(runtime.roles.tool_providers)
    lifespan = MountedLifespan(manager)
    await lifespan.start()
    try:
        async with AsyncClient(transport=ASGITransport(app=asgi), base_url=BASE_URL) as client:
            master.client = client

            # First of the installed engines, so reading the engines instead would show it.
            toolless = Loner4eEngine(NO_PACKS)
            toolless.id = EngineId("mirror")
            toolless.tools = {}
            runtime.engines = {toolless.id: toolless, **runtime.engines}

            # Mid-turn: the engine's tools are published, and a landed call carries no error.
            service = runtime.session_for(
                SavedGameKey(scenario_id="whispering-vault", character_id="kael")
            )
            await service.choose(PlayerInput(text="I search the vault."))
            assert "ask" in master.tools_seen
            assert "enter" in master.tools_seen
            change_result = master.change_result
            assert change_result is not None
            assert change_result.get("isError") is not True

            facts = service.state.log_entries()[-1].facts
            assert any("tomas" in fact.trace for fact in facts)
    finally:
        await lifespan.stop()


async def test_a_lan_client_is_refused_at_the_mcp_endpoint() -> None:
    asgi, _ = endpoint(OpenToolProviders())
    lan = ASGITransport(app=asgi, client=("192.168.1.20", 50000))
    async with AsyncClient(transport=lan, base_url=BASE_URL) as client:
        reply = await client.post("/mcp/", json={})
    assert reply.status_code == 403


async def test_a_submission_token_routes_to_submit_alone() -> None:
    tool_providers = OpenToolProviders()
    asgi, manager = endpoint(tool_providers)
    lifespan = MountedLifespan(manager)
    submission = Submission(Debrief, Debrief.check)
    debrief = {
        "story_so_far": "You reached the vault.",
        "current_aim": "Open the vault.",
        "open_threads": ["You could open the door."],
        "last_beats": ["You lit a torch."],
    }
    await lifespan.start()
    try:
        async with AsyncClient(transport=ASGITransport(app=asgi), base_url=BASE_URL) as client:
            with tool_providers.open(submission) as token:
                routed = await rpc(client, "tools/list", {}, token)
                unrouted = await rpc(client, "tools/list", {})
                called = await rpc(
                    client, "tools/call", {"name": SUBMIT, "arguments": debrief}, token
                )
            closed = await rpc(client, "tools/list", {}, token)
    finally:
        await lifespan.stop()

    assert [tool["name"] for tool in routed.get("result", {}).get("tools", [])] == [SUBMIT]
    assert unrouted.get("result", {}).get("tools") == []
    assert called.get("result", {}).get("isError") is not True
    assert submission.accepted is not None
    assert closed.get("result", {}).get("tools") == []


async def test_a_tool_call_without_a_token_is_refused() -> None:
    tool_providers = OpenToolProviders()
    asgi, manager = endpoint(tool_providers)
    lifespan = MountedLifespan(manager)
    await lifespan.start()
    try:
        async with AsyncClient(transport=ASGITransport(app=asgi), base_url=BASE_URL) as client:
            with tool_providers.open(Submission(Debrief, Debrief.check)):
                listed = await rpc(client, "tools/list", {})
                called = await rpc(client, "tools/call", {"name": SUBMIT, "arguments": {}})
    finally:
        await lifespan.stop()

    assert listed.get("result", {}).get("tools") == []
    result = called.get("result", {})
    assert result.get("isError") is True
    content = result.get("content")
    assert content is not None and content[0]["text"] == NO_TOOLS
