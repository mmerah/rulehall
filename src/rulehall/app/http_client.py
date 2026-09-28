import logging
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager

from httpx import AsyncClient, HTTPError, HTTPStatusError
from pydantic import JsonValue

from rulehall.config import ProviderConfig
from rulehall.core.validation import Refusal

LOGGER = logging.getLogger(__name__)

_client: AsyncClient | None = None


def client() -> AsyncClient:
    global _client
    if _client is None:
        _client = AsyncClient()
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def post_bearer(
    provider: ProviderConfig, path: str, body: Mapping[str, JsonValue], timeout: float | None
) -> bytes:
    try:
        reply = await client().post(
            f"{provider.base_url}{path}", headers=_bearer(provider), json=body, timeout=timeout
        )
        reply.raise_for_status()
    except HTTPError as failed:
        raise Refusal(f"the provider failed: {_detail(failed)}") from failed
    return reply.content


@asynccontextmanager
async def stream_bearer(
    provider: ProviderConfig, path: str, body: Mapping[str, JsonValue], timeout: float | None
) -> AsyncGenerator[AsyncIterator[str]]:
    try:
        async with client().stream(
            "POST",
            f"{provider.base_url}{path}",
            headers=_bearer(provider),
            json=body,
            timeout=timeout,
        ) as reply:
            if reply.is_error:
                await reply.aread()
            reply.raise_for_status()
            yield reply.aiter_lines()
    except HTTPError as failed:
        raise Refusal(f"the provider failed: {_detail(failed)}") from failed


def _bearer(provider: ProviderConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {provider.api_key.get_secret_value()}"}


def _detail(failed: HTTPError) -> str:
    if isinstance(failed, HTTPStatusError):
        status, body = failed.response.status_code, failed.response.text.strip()
        LOGGER.warning("the provider answered %s: %s", status, body)
        first = next(iter(body.splitlines()), "")[:120]
        return f"{status} {first}".strip()
    return str(failed)
