from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager

from httpx import AsyncClient
from pydantic import JsonValue

from rulehall.config import ProviderConfig

_client: AsyncClient | None = None


def client() -> AsyncClient:
    """One pool for the process: a new client per call pays a new handshake."""
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
    provider: ProviderConfig, path: str, body: Mapping[str, JsonValue], timeout: float
) -> bytes:
    reply = await client().post(
        f"{provider.base_url}{path}", headers=_bearer(provider), json=body, timeout=timeout
    )
    reply.raise_for_status()
    return reply.content


@asynccontextmanager
async def stream_bearer(
    provider: ProviderConfig, path: str, body: Mapping[str, JsonValue], timeout: float
) -> AsyncGenerator[AsyncIterator[str]]:
    async with client().stream(
        "POST", f"{provider.base_url}{path}", headers=_bearer(provider), json=body, timeout=timeout
    ) as reply:
        if reply.is_error:
            await reply.aread()
        reply.raise_for_status()
        yield reply.aiter_lines()


def _bearer(provider: ProviderConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {provider.api_key.get_secret_value()}"}
