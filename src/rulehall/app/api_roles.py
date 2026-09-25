import logging
from collections.abc import Callable
from typing import Literal

from httpx import HTTPError, HTTPStatusError
from pydantic import BaseModel, ConfigDict, JsonValue

from rulehall.app.providers import post_bearer, stream_bearer
from rulehall.app.turn import Turn
from rulehall.config import ProviderConfig, Role, RoleConfig
from rulehall.core.io import decode
from rulehall.core.prompt import Prompt
from rulehall.core.tools import MasterTool, schema_of
from rulehall.core.validation import Loose, Refusal, parse_json

LOGGER = logging.getLogger(__name__)


class _Echoed(BaseModel):
    """Kept whole: a reply goes back in the next request, with its reasoning."""

    model_config = ConfigDict(extra="allow", frozen=True, strict=True)


class _Function(_Echoed):
    name: str
    arguments: str


class _ToolCall(_Echoed):
    id: str
    type: Literal["function"]
    function: _Function


class _Said(_Echoed):
    role: Literal["assistant"]
    content: str | None = None
    tool_calls: tuple[_ToolCall, ...] | None = None


class _Choice(Loose):
    message: _Said


class _Error(Loose):
    message: str


class _Completion(Loose):
    choices: tuple[_Choice, ...] = ()
    error: _Error | None = None


class _Delta(Loose):
    content: str | None = None
    tool_calls: tuple[_ToolCall, ...] | None = None


class _ChunkChoice(Loose):
    delta: _Delta


class _Chunk(Loose):
    choices: tuple[_ChunkChoice, ...] = ()
    error: _Error | None = None


async def run_over_api(
    role: Role,
    config: RoleConfig,
    provider: ProviderConfig,
    prompt: Prompt,
    turn: Turn | None,
    heard: Callable[[str], None] | None,
) -> str:
    """Stateless: nothing resumes, and a retry sends the whole prompt again."""
    messages: list[JsonValue] = [
        {"role": "system", "content": prompt.system},
        {"role": "user", "content": prompt.user},
    ]
    try:
        if turn is None:
            return await _stream(role, config, provider, messages, heard)
        return await _converse(role, config, provider, messages, turn)
    except HTTPError as failed:
        raise Refusal(f"the {role}'s provider failed: {_detail(failed)}") from failed


async def _stream(
    role: Role,
    config: RoleConfig,
    provider: ProviderConfig,
    messages: list[JsonValue],
    heard: Callable[[str], None] | None,
) -> str:
    body = _request(config, messages) | {"stream": True}
    said = ""
    async with stream_bearer(provider, "/chat/completions", body, config.timeout) as lines:
        async for line in lines:
            data = line.removeprefix("data:").strip()
            if not line.startswith("data:") or data == "[DONE]":
                continue
            chunk = parse_json(_Chunk, data)
            if chunk.error is not None:
                raise Refusal(f"the provider answered an error: {chunk.error.message}")
            for choice in chunk.choices:
                if choice.delta.tool_calls:
                    called = choice.delta.tool_calls[0].function.name
                    raise Refusal(f"the {role} has no tools, yet called {called!r}")
                if choice.delta.content:
                    said += choice.delta.content
                    if heard is not None:
                        heard(said)
    return said


async def _converse(
    role: Role,
    config: RoleConfig,
    provider: ProviderConfig,
    messages: list[JsonValue],
    turn: Turn,
) -> str:
    published: list[JsonValue] = [_declared(tool) for tool in turn.published_tools()]
    for rounds in range(1, config.max_rounds + 1):
        said = await _complete(config, provider, messages, published)
        messages.append(said.model_dump(mode="json", exclude_none=True))
        if not said.tool_calls:
            LOGGER.info("the %s ended its turn after %d rounds", role, rounds)
            return said.content or ""
        messages.extend(
            {"role": "tool", "tool_call_id": call.id, "content": _answer(turn, call)}
            for call in said.tool_calls
        )
    raise Refusal(
        f"the {role} made {config.max_rounds} rounds of tool calls without ending the turn"
    )


def _answer(turn: Turn, call: _ToolCall) -> str:
    """A refusal is a result the model reads and continues from, not an error."""
    try:
        return turn.call(call.function.name, decode(call.function.arguments))
    except Refusal as refused:
        return str(refused)


async def _complete(
    config: RoleConfig, provider: ProviderConfig, messages: list[JsonValue], tools: list[JsonValue]
) -> _Said:
    body = _request(config, messages)
    if tools:
        body["tools"] = tools
    raw = await post_bearer(provider, "/chat/completions", body, config.timeout)
    reply = parse_json(_Completion, raw)
    if reply.error is not None:
        raise Refusal(f"the provider answered an error: {reply.error.message}")
    if not reply.choices:
        raise Refusal("the provider answered no choices")
    return reply.choices[0].message


def _request(config: RoleConfig, messages: list[JsonValue]) -> dict[str, JsonValue]:
    return {"model": config.model, "messages": messages, "reasoning_effort": config.effort}


def _declared(tool: MasterTool) -> JsonValue:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema_of(tool.args),
        },
    }


def _detail(failed: HTTPError) -> str:
    if isinstance(failed, HTTPStatusError):
        status, body = failed.response.status_code, failed.response.text.strip()
        LOGGER.warning("the provider answered %s: %s", status, body)
        first = next(iter(body.splitlines()), "")[:120]
        return f"{status} {first}".strip()
    return str(failed)
