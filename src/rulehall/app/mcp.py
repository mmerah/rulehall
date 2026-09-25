import logging
from asyncio import Event, Lock, Task, create_task
from dataclasses import dataclass, field

import mcp_types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from rulehall.app.session import Gate
from rulehall.core.tools import schema_of
from rulehall.core.validation import Refusal

LOGGER = logging.getLogger(__name__)

SERVER_NAME = "rulehall"
MOUNT_PATH = "/mcp"
LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1"})


@dataclass(slots=True)
class MountedLifespan:
    """A mounted app lifespan never runs; anyio needs one task to enter and exit the manager."""

    manager: StreamableHTTPSessionManager
    _ready: Event = field(default_factory=Event)
    _stopping: Event = field(default_factory=Event)
    _serving: Task[None] | None = None

    async def start(self) -> None:
        self._serving = create_task(self._serve())
        await self._ready.wait()
        if self._serving.done():
            self._serving.result()

    async def stop(self) -> None:
        self._stopping.set()
        if self._serving is not None:
            await self._serving

    async def _serve(self) -> None:
        try:
            async with self.manager.run():
                self._ready.set()
                await self._stopping.wait()
        finally:
            # Set on failure too, or a manager that never started would hang the startup.
            self._ready.set()


@dataclass(frozen=True, slots=True)
class LoopbackOnly:
    """The roles run on this machine; a LAN client can forge the Host header."""

    inner: StreamableHTTPASGIApp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        client = scope.get("client")
        if client is None or client[0] not in LOOPBACK_CLIENTS:
            await Response(status_code=403)(scope, receive, send)
            return
        await self.inner(scope, receive, send)


def endpoint(gate: Gate) -> tuple[LoopbackOnly, StreamableHTTPSessionManager]:
    manager = StreamableHTTPSessionManager(
        app=_build_server(gate),
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )
    return LoopbackOnly(StreamableHTTPASGIApp(manager)), manager


def _build_server(gate: Gate) -> Server[dict[str, object]]:
    lock = Lock()

    async def on_list_tools(
        _ctx: ServerRequestContext[dict[str, object]],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        turn = gate.turn
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=schema_of(tool.args),
                )
                for tool in (() if turn is None else turn.published_tools())
            ]
        )

    async def on_call_tool(
        _ctx: ServerRequestContext[dict[str, object]], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        """The lock keeps the tools sequential: a CLI may call several tools at once."""
        async with lock:
            try:
                answered = gate.require_turn().call(params.name, params.arguments or {})
            except Refusal as refused:
                return _content(str(refused), error=True)
            except Exception:
                # The mcp framework would otherwise swallow this traceback.
                LOGGER.exception("tool %s failed", params.name)
                raise
        return _content(answered)

    return Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def _content(body: str, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=body)], is_error=error)
