"""The master's tools over the MCP endpoint, driven in process through httpx's ASGI transport."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from httpx import ASGITransport, AsyncClient
from support.table import NO_PACKS, narrated, offline_settings

from rulehall.app.catalog import SavedGameKey
from rulehall.app.mcp import MountedLifespan, endpoint
from rulehall.app.roles import RoleReply
from rulehall.app.runtime import Runtime
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.decisions import PlayerInput
from rulehall.core.prompt import Prompt
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
    tools_seen: list[str] = field(default_factory=list)
    change_result: Result | None = None

    async def answer(
        self,
        role: Role,
        prompt: Prompt,
        *,
        resume_id: str | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RoleReply:
        del role, prompt, resume_id, heard
        return RoleReply(narrated("You wait."), None)

    async def play_master_turn(self, prompt: Prompt, turn: Turn) -> None:
        del prompt, turn
        assert self.client is not None
        listed = await rpc(self.client, "tools/list", {})
        self.tools_seen = [tool["name"] for tool in listed.get("result", {}).get("tools", [])]
        called = await rpc(self.client, "tools/call", ENTER_TOMAS)
        self.change_result = called.get("result")


async def rpc(client: AsyncClient, method: str, params: dict[str, object]) -> Reply:
    reply = await client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    return reply.json()


async def test_master_tools_over_the_mcp_endpoint(tmp_path: Path) -> None:
    master = HttpMaster()
    runtime = Runtime(offline_settings(tmp_path), roles=master)
    asgi, manager = endpoint(runtime.gate)
    lifespan = MountedLifespan(manager)
    await lifespan.start()
    try:
        async with AsyncClient(transport=ASGITransport(app=asgi), base_url=BASE_URL) as client:
            master.client = client

            # Between turns: no tools are published, and a call is refused with the wait line.
            listed = await rpc(client, "tools/list", {})
            assert listed.get("result", {}).get("tools") == []
            called = await rpc(client, "tools/call", {"name": "ask", "arguments": {}})
            result = called.get("result", {})
            assert result.get("isError") is True
            content = result.get("content")
            assert content is not None and "no turn is open" in content[0]["text"]

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


async def test_a_lan_client_is_refused_at_the_mcp_endpoint(tmp_path: Path) -> None:
    runtime = Runtime(offline_settings(tmp_path), roles=HttpMaster())
    asgi, _ = endpoint(runtime.gate)
    lan = ASGITransport(app=asgi, client=("192.168.1.20", 50000))
    async with AsyncClient(transport=lan, base_url=BASE_URL) as client:
        reply = await client.post("/mcp/", json={})
    assert reply.status_code == 403
