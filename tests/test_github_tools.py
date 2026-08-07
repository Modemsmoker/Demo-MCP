"""Behavioural tests for the GitHub tools: caching, truncation, pagination,
error mapping, and the no-secret-leakage guarantees. Every test drives
`httpx.MockTransport` through the `github_transport` fixture in
`conftest.py` — no test here may reach the real network (enforced by
`test_no_live_network_calls`).
"""

import base64
import logging
from datetime import UTC, datetime

import httpx
import pytest

from demo_mcp.clients.github import get_github_client, reset_github_client
from demo_mcp.tools.github import (
    _REPO_OVERVIEW_CACHE,
    github_get_file,
    github_get_pull_request,
    github_list_commits,
    github_repo_overview,
    github_search,
)
from tests.conftest import load_fixture

REPO = "octocat/Hello-World"


def _overview_handler(request: httpx.Request) -> httpx.Response:
    """Serves get_repo / releases / open-PR-search for github_repo_overview."""
    path = request.url.path
    if "/search/issues" in path:
        return httpx.Response(200, json=load_fixture("search_pulls_open.json"))
    if path.endswith("/releases"):
        return httpx.Response(200, json=load_fixture("releases.json"))
    return httpx.Response(200, json=load_fixture("repo.json"))


# --- ETag caching (HTTP layer) ------------------------------------------


async def test_etag_second_call_is_served_from_cache(github_transport):
    """A second identical call sends If-None-Match and gets back the same
    payload the first call cached — the caching claim this design rests on."""
    etag = 'W/"etag-1"'
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304, headers={"ETag": etag})
        return httpx.Response(200, json=load_fixture("repo.json"), headers={"ETag": etag})

    github_transport(handler)
    client = get_github_client()

    first = await client.get_repo(REPO)
    second = await client.get_repo(REPO)

    assert first == second == load_fixture("repo.json")
    assert len(calls) == 2
    assert "If-None-Match" not in calls[0].headers
    assert calls[1].headers.get("If-None-Match") == etag


async def test_304_returns_the_cached_payload(github_transport):
    """A 304 has an empty body; the client must still return the full
    content it cached from the earlier 200, not an empty result."""
    payload = load_fixture("repo.json")
    etag = 'W/"etag-1"'
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json=payload, headers={"ETag": etag})
        return httpx.Response(304, headers={"ETag": etag})

    github_transport(handler)
    client = get_github_client()

    await client.get_repo(REPO)
    second = await client.get_repo(REPO)

    assert second == payload
    assert second != {}


# --- github_repo_overview TTL cache (amendment) --------------------------


async def test_repo_overview_cache_hit_within_ttl(github_transport):
    """Two calls inside the 60s TTL: the second is served from the
    in-process cache and never reaches the HTTP layer at all."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _overview_handler(request)

    github_transport(handler)

    first = await github_repo_overview(None, REPO)
    calls_after_first = len(calls)
    second = await github_repo_overview(None, REPO)

    assert second == first
    assert len(calls) == calls_after_first, "second call within TTL must not hit the HTTP layer"


async def test_repo_overview_cache_expires_after_ttl(github_transport):
    """Once the cached entry is older than the TTL, the next call must go
    back to the HTTP layer rather than serving stale data forever."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _overview_handler(request)

    github_transport(handler)

    await github_repo_overview(None, REPO)
    calls_after_first = len(calls)

    fetched_at, cached_value = _REPO_OVERVIEW_CACHE[REPO]
    _REPO_OVERVIEW_CACHE[REPO] = (fetched_at - 61, cached_value)

    await github_repo_overview(None, REPO)

    assert len(calls) > calls_after_first, "expired cache entry must trigger a fresh HTTP call"


# --- limits and pagination ------------------------------------------------


async def test_limits_are_clamped_server_side(github_transport):
    """A caller-supplied limit is untrusted input; github_search must never
    ask the client for more than the server-side cap."""
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["per_page"] = request.url.params.get("per_page")
        return httpx.Response(200, json=load_fixture("search_issues.json"))

    github_transport(handler)

    await github_search(None, "bug", limit=10_000)

    assert captured["per_page"] == "50"


async def test_link_header_does_not_leak(github_transport):
    """Pagination is exposed as an opaque cursor/has_more pair; the raw Link
    header and any api.github.com pagination URL must never appear in a
    tool's output."""

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {
            "Link": (
                '<https://api.github.com/repos/octocat/Hello-World/commits?page=2>; rel="next"'
            )
        }
        return httpx.Response(200, json=load_fixture("commits.json"), headers=headers)

    github_transport(handler)

    result = await github_list_commits(None, REPO)

    assert result.has_more is True
    assert result.cursor == "2"
    dumped = result.model_dump_json()
    assert "Link" not in dumped
    assert "api.github.com" not in dumped


# --- truncation -------------------------------------------------------


async def test_file_truncation_is_explicit(github_transport):
    """A file over the byte cap must come back with content plus a notice
    naming the total line count — silent truncation is the failure mode
    this whole design targets."""
    big_text = "line of text\n" * 1500  # comfortably over the 8 KB cap
    content_b64 = base64.b64encode(big_text.encode()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"type": "file", "encoding": "base64", "content": content_b64}
        )

    github_transport(handler)

    result = await github_get_file(None, REPO, "big.txt")

    assert result.truncated is True
    assert result.truncation_note is not None
    assert str(result.total_lines) in result.truncation_note
    assert len(result.content.encode()) <= 8 * 1024


# --- pull request patches ----------------------------------------------


async def test_pull_request_omits_patches_unless_requested(github_transport):
    """No patch text without an explicit `files` list; patch text present
    only for the paths named. The highest-consequence assertion in the
    suite — a full diff can blow a context window on one call."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=load_fixture("pull_files.json"))
        return httpx.Response(200, json=load_fixture("pull.json"))

    github_transport(handler)

    no_files = await github_get_pull_request(None, REPO, 7)
    assert all(f.patch is None for f in no_files.files)

    with_files = await github_get_pull_request(None, REPO, 7, files=["README.md"])
    patches = {f.path: f.patch for f in with_files.files}
    assert patches["README.md"] is not None
    assert patches["src/app.py"] is None


# --- errors --------------------------------------------------------------


async def test_rate_limit_error_reports_reset_time(github_transport):
    reset_ts = 1_700_000_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "rate limited"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_ts)},
        )

    github_transport(handler)
    client = get_github_client()

    with pytest.raises(ValueError) as exc_info:
        await client.get_repo(REPO)

    expected_iso = datetime.fromtimestamp(reset_ts, tz=UTC).isoformat()
    assert expected_iso in str(exc_info.value)


async def test_errors_never_contain_the_token(github_transport, caplog, monkeypatch):
    """Force 401 and 403 with a sentinel GH_API_TOKEN; the sentinel must
    appear in neither the raised message nor any captured log record."""
    sentinel = "sentinel-secret-token-xyz"
    monkeypatch.setenv("GH_API_TOKEN", sentinel)
    reset_github_client()

    responses = iter(
        [
            httpx.Response(401, json={"message": "Bad credentials"}),
            httpx.Response(
                403, json={"message": "Forbidden"}, headers={"X-RateLimit-Remaining": "5"}
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    github_transport(handler)
    client = get_github_client()

    caplog.set_level(logging.DEBUG)
    for _ in range(2):
        with pytest.raises(ValueError) as exc_info:
            await client.get_repo(REPO)
        assert sentinel not in str(exc_info.value)

    for record in caplog.records:
        assert sentinel not in record.getMessage()


async def test_missing_github_token_warns_but_does_not_raise(monkeypatch, caplog):
    """Pins the 'degrade, don't refuse' rule: absence of GH_API_TOKEN must
    log a warning and construct successfully, never raise like
    MCP_AUTH_TOKEN's startup guard does."""
    monkeypatch.delenv("GH_API_TOKEN", raising=False)
    reset_github_client()

    with caplog.at_level(logging.WARNING):
        client = get_github_client()

    assert client.token == ""
    assert any("GH_API_TOKEN" in record.getMessage() for record in caplog.records)

    reset_github_client()


async def test_no_live_network_calls(github_transport, no_network_transport):
    """A session-scoped-style transport that raises on any request: cheap
    insurance the suite stays deterministic even if a future change
    forgets to mock a call."""
    github_transport(no_network_transport)

    with pytest.raises(AssertionError):
        await get_github_client().get_repo(REPO)
