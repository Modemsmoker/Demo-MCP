"""Read-only GitHub REST v3 client.

Endpoint methods only — no field shaping (that lives in `demo_mcp/shaping.py`)
and no MCP concepts. Reads a personal access token from `GH_API_TOKEN`; when
absent, GitHub's unauthenticated 60 requests/hour limit applies and a warning
is logged once, at construction. This client never raises for a missing
token — see decision D5 in `docs/GITHUB_API.md` for why the server degrades
instead of refusing to start, unlike `MCP_AUTH_TOKEN`.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from demo_mcp.clients.base import HttpClient, HttpResponse

logger = logging.getLogger("demo-mcp.clients.github")


def _parse_link_header(link_header: str | None) -> dict[str, str]:
    """Parse a GitHub `Link` header into `{rel: url}`.

    Internal only: the raw header value and the URLs inside it must never
    reach a tool's output, per the pagination convention in
    `docs/GITHUB_API.md`.
    """
    links: dict[str, str] = {}
    if not link_header:
        return links
    for part in link_header.split(","):
        url_part, _, rel_part = part.strip().partition(";")
        url = url_part.strip("<> ")
        rel = rel_part.split("=")[-1].strip('" ')
        if url and rel:
            links[rel] = url
    return links


def _next_page_cursor(headers: Any) -> str | None:
    """Extract an opaque next-page cursor (the next page number, nothing
    else) from a `Link` header, or `None` when there is no next page."""
    links = _parse_link_header(headers.get("Link"))
    next_url = links.get("next")
    if not next_url:
        return None
    values = parse_qs(urlparse(next_url).query).get("page", [None])
    return values[0]


class GitHubClient(HttpClient):
    """Thin wrapper over `api.github.com`. Endpoint methods return raw
    GitHub JSON; shaping and MCP-facing pydantic models live elsewhere."""

    def __init__(self) -> None:
        super().__init__(base_url="https://api.github.com")
        self.token = os.getenv("GH_API_TOKEN", "")
        if not self.token:
            logger.warning(
                "GH_API_TOKEN is not set; GitHub calls fall back to the "
                "60 requests/hour unauthenticated rate limit."
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> tuple[Any, Any]:
        """GET `path`, mapping GitHub's error responses to short, actionable
        `ValueError`s in one place. Never includes the token, a header dump,
        or a request repr in the raised message."""
        result: HttpResponse = await self.get(path, params)
        if result.status_code == 404:
            raise ValueError(f"repository or resource not found: {path}")
        if result.status_code == 403:
            if result.headers.get("X-RateLimit-Remaining") == "0":
                reset = result.headers.get("X-RateLimit-Reset")
                reset_iso = (
                    datetime.fromtimestamp(int(reset), tz=UTC).isoformat() if reset else "unknown"
                )
                raise ValueError(f"GitHub rate limit exhausted; resets at {reset_iso}")
            raise ValueError("GitHub rejected the request: insufficient permissions")
        if result.status_code == 401:
            raise ValueError("GitHub rejected the configured credentials")
        if result.status_code >= 400:
            raise ValueError(f"GitHub API error: HTTP {result.status_code}")
        return result.payload, result.headers

    async def get_repo(self, repo: str) -> dict[str, Any]:
        payload, _ = await self._request(f"/repos/{repo}")
        return payload

    async def search(
        self, kind: str, query: str, per_page: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], int, bool, str | None]:
        endpoint = "/search/repositories" if kind == "repos" else "/search/issues"
        params: dict[str, str | int] = {
            "q": query,
            "per_page": per_page,
            "page": int(cursor) if cursor else 1,
        }
        payload, headers = await self._request(endpoint, params)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        total_count = payload.get("total_count", len(items)) if isinstance(payload, dict) else 0
        next_cursor = _next_page_cursor(headers)
        return items, total_count, next_cursor is not None, next_cursor

    async def get_issue(self, repo: str, number: int) -> dict[str, Any]:
        payload, _ = await self._request(f"/repos/{repo}/issues/{number}")
        return payload

    async def list_issue_comments(
        self, repo: str, number: int, per_page: int
    ) -> list[dict[str, Any]]:
        payload, _ = await self._request(
            f"/repos/{repo}/issues/{number}/comments", {"per_page": per_page}
        )
        return payload if isinstance(payload, list) else []

    async def get_pull(self, repo: str, number: int) -> dict[str, Any]:
        payload, _ = await self._request(f"/repos/{repo}/pulls/{number}")
        return payload

    async def list_pull_files(self, repo: str, number: int) -> list[dict[str, Any]]:
        payload, _ = await self._request(f"/repos/{repo}/pulls/{number}/files")
        return payload if isinstance(payload, list) else []

    async def list_commits(
        self,
        repo: str,
        ref: str | None,
        path: str | None,
        since: str | None,
        per_page: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        params: dict[str, str | int] = {
            "per_page": per_page,
            "page": int(cursor) if cursor else 1,
        }
        if ref:
            params["sha"] = ref
        if path:
            params["path"] = path
        if since:
            params["since"] = since
        payload, headers = await self._request(f"/repos/{repo}/commits", params)
        items = payload if isinstance(payload, list) else []
        next_cursor = _next_page_cursor(headers)
        return items, next_cursor is not None, next_cursor

    async def get_contents(self, repo: str, path: str, ref: str | None) -> Any:
        params = {"ref": ref} if ref else None
        payload, _ = await self._request(f"/repos/{repo}/contents/{path}", params)
        return payload

    async def list_releases(
        self, repo: str, per_page: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        params: dict[str, str | int] = {
            "per_page": per_page,
            "page": int(cursor) if cursor else 1,
        }
        payload, headers = await self._request(f"/repos/{repo}/releases", params)
        items = payload if isinstance(payload, list) else []
        next_cursor = _next_page_cursor(headers)
        return items, next_cursor is not None, next_cursor


_github_client: GitHubClient | None = None


def get_github_client() -> GitHubClient:
    """Return the process-wide GitHubClient, constructing it on first use
    (see D2 in `docs/GITHUB_API.md`)."""
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client


def reset_github_client() -> None:
    """Drop the cached client. Tests use this to reconstruct a client under a
    fresh `GH_API_TOKEN` or a newly-installed mock transport."""
    global _github_client
    _github_client = None
