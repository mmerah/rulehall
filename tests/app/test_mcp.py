"""The master's tools over the MCP endpoint, driven in process through httpx's ASGI transport."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from httpx import ASGITransport, AsyncClient
from support.table import NO_PACKS, narrated, offline_settings

from rulehall.app.launch import LaunchTarget
from rulehall.app.mcp import MountedLifespan, endpoint
from rulehall.app.runtime import Runtime
from rulehall.app.spawn import RunResult
from rulehall.app.turn import Turn
from rulehall.config import Role
from rulehall.core.play import Answer
from rulehall.core.prompt import Prompt
from rulehall.core.validation import EngineId
from rulehall.engines.loner3e.engine import Loner3eEngine

BASE_URL = "http://localhost:8123"
REVEAL_VAULT_MAP: dict[str, object] = {"name": "reveal", "arguments": {"target_id": "vault-map"}}


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

    async def run(
        self,
        role: Role,
        prompt: Prompt,
        conversation: str | None,
        turn: Turn | None = None,
        heard: Callable[[str], None] | None = None,
    ) -> RunResult:

        del heard, prompt, conversation, turn
        if role != "master":
            return RunResult(narrated("You wait."), None)
        assert self.client is not None
        listed = await rpc(self.client, "tools/list", {})
        self.tools_seen = [tool["name"] for tool in listed.get("result", {}).get("tools", [])]
        called = await rpc(self.client, "tools/call", REVEAL_VAULT_MAP)
        self.change_result = called.get("result")
        return RunResult("done", None)


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
    runtime = Runtime(offline_settings(tmp_path), spawner=master)
    asgi, manager = endpoint(runtime.gate)
    lifespan = MountedLifespan(manager)
    await lifespan.start()
    try:
        async with AsyncClient(transport=ASGITransport(app=asgi), base_url=BASE_URL) as client:
            master.client = client

            # Between turns: no tools are published, and a call is refused with the wait line.
            listed = await rpc(client, "tools/list", {})
            assert listed.get("result", {}).get("tools") == []
            called = await rpc(client, "tools/call", {"name": "roll", "arguments": {}})
            result = called.get("result", {})
            assert result.get("isError") is True
            content = result.get("content")
            assert content is not None and "no turn is open" in content[0]["text"]

            # First of the installed engines, so reading the engines instead would show it.
            toolless = Loner3eEngine(NO_PACKS)
            toolless.id = EngineId("mirror")
            toolless.tools = {}
            runtime.engines = {toolless.id: toolless, **runtime.engines}

            # Mid-turn: the engine's tools are published, and a landed call carries no error.
            service = runtime.session(
                LaunchTarget(scenario_id="whispering-vault", character_id="kael")
            )
            await service.play(Answer(text="I search the vault."))
            assert "roll" in master.tools_seen
            assert "reveal" in master.tools_seen
            change_result = master.change_result
            assert change_result is not None
            assert change_result.get("isError") is not True

            facts = service.state.exchanges()[-1].facts
            assert any("vault-map" in fact.trace for fact in facts)
    finally:
        await lifespan.stop()


async def test_a_lan_client_is_refused_at_the_mcp_endpoint(tmp_path: Path) -> None:
    runtime = Runtime(offline_settings(tmp_path), spawner=HttpMaster())
    asgi, _ = endpoint(runtime.gate)
    lan = ASGITransport(app=asgi, client=("192.168.1.20", 50000))
    async with AsyncClient(transport=lan, base_url=BASE_URL) as client:
        reply = await client.post("/mcp/", json={})
    assert reply.status_code == 403
