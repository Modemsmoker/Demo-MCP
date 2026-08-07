"""Shared HTTP plumbing: a lazily-constructed, process-wide `httpx.AsyncClient`
(see decision D2 in `docs/GITHUB_API.md`) and a small ETag cache so repeat GETs
against an unchanged resource never cost a full download or an extra unit
against the upstream rate limit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, NamedTuple

import httpx

logger = logging.getLogger("demo-mcp.clients.http")

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the process-wide AsyncClient, constructing it on first use."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


def set_client(client: httpx.AsyncClient) -> None:
    """Install a client explicitly. Tests use this to inject a MockTransport
    so no `HttpClient` subclass ever reaches the real network."""
    global _client
    _client = client


async def aclose() -> None:
    """Close and drop the shared client. Call this in test teardown to avoid
    leaking open connections between test modules."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class HttpResponse(NamedTuple):
    status_code: int
    payload: Any
    headers: httpx.Headers


class HttpClient:
    """GET-only HTTP client with ETag revalidation and bounded retries.

    Subclasses set `base_url` and override `_headers()` to add auth. A
    resource fetched twice sends `If-None-Match` on the second call; a `304`
    response is served from the in-memory cache instead of being treated as
    empty. Retries use `asyncio.sleep` backoff, never `time.sleep` — this
    runs inside async tool handlers and must not stall the event loop.
    """

    def __init__(self, base_url: str, retries: int = 2) -> None:
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self._etag_cache: dict[str, tuple[str, Any]] = {}

    def _headers(self) -> dict[str, str]:
        """Override in subclasses to add auth/Accept headers."""
        return {}

    def _cache_key(self, url: str, params: dict[str, str | int] | None) -> str:
        return f"{url}?{sorted((params or {}).items())}"

    async def get(self, path: str, params: dict[str, str | int] | None = None) -> HttpResponse:
        """Perform a GET against `base_url + path`, transparently revalidating
        against the ETag cache and retrying transient failures."""
        url = f"{self.base_url}{path}"
        cache_key = self._cache_key(url, params)
        headers = self._headers()
        cached = self._etag_cache.get(cache_key)
        if cached is not None:
            headers["If-None-Match"] = cached[0]

        client = get_client()
        response: httpx.Response | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await client.get(url, headers=headers, params=params)
            except httpx.TransportError:
                if attempt < self.retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
            if response.status_code >= 500 and attempt < self.retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            break

        assert response is not None  # the loop above always assigns or raises

        if response.status_code == 304 and cached is not None:
            return HttpResponse(304, cached[1], response.headers)

        payload: Any = None
        if response.content:
            payload = response.json()

        etag = response.headers.get("ETag")
        if etag and response.status_code == 200:
            self._etag_cache[cache_key] = (etag, payload)

        return HttpResponse(response.status_code, payload, response.headers)
