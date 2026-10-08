import logging
from asyncio import Event, Task, create_task
from dataclasses import dataclass, field

import mcp_types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from rulehall.app.cli_roles import SUBMISSION_HEADER
from rulehall.app.game_session import Gate
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
    async def on_list_tools(
        ctx: ServerRequestContext[dict[str, object], Request],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        token = _submission_token(ctx)
        surface = gate.turn if token is None else gate.submissions.find(token)
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.schema,
                )
                for tool in (() if surface is None else surface.published_tools())
            ]
        )

    async def on_call_tool(
        ctx: ServerRequestContext[dict[str, object], Request],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        token = _submission_token(ctx)
        try:
            surface = gate.require_turn() if token is None else gate.submissions.require(token)
            answered = surface.call_tool(params.name, params.arguments or {})
        except Refusal as refused:
            return _content(str(refused), error=True)
        except Exception:
            # The mcp framework would otherwise swallow this traceback.
            LOGGER.exception("tool %s failed", params.name)
            raise
        return _content(answered)

    return Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def _submission_token(ctx: ServerRequestContext[dict[str, object], Request]) -> str | None:
    return None if ctx.request is None else ctx.request.headers.get(SUBMISSION_HEADER)


def _content(body: str, *, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=body)], is_error=error)
