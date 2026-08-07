"""Test bootstrap.

server.py raises at import time if no auth token is configured, so the
environment has to be set before the module is ever imported.
"""

import os

os.environ.setdefault("MCP_AUTH_TOKEN", "test-token-do-not-use-in-production")
os.environ.setdefault("MCP_AUTH_DISABLED", "0")
os.environ.setdefault("MCP_PUBLIC_URL", "http://localhost:8000/mcp")

# Hard assignment, not setdefault: a developer's real PAT, or a token CI
# injects into the workflow environment, must never be reachable from the
# test suite. Combined with the mocked transport in the GitHub tests, this
# makes a live call impossible rather than merely unlikely.
os.environ["GH_API_TOKEN"] = "test-github-token"

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from demo_mcp.clients import base as http_base  # noqa: E402
from demo_mcp.clients.github import reset_github_client  # noqa: E402
from demo_mcp.tools.github import _REPO_OVERVIEW_CACHE  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "github"


def load_fixture(name: str):
    """Load a trimmed GitHub API JSON fixture by filename (see
    tests/fixtures/github/README.md)."""
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
async def github_transport():
    """Install a `httpx.MockTransport` as the shared HTTP client for the
    duration of a test, and reset every piece of GitHub-related module state
    (the singleton `GitHubClient`, the `github_repo_overview` TTL cache)
    before and after so tests never leak into one another.

    Yields a function the test calls with `handler(request) -> Response` to
    install its own routing.
    """
    reset_github_client()
    _REPO_OVERVIEW_CACHE.clear()

    def _install(handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        http_base.set_client(client)
        return client

    yield _install

    reset_github_client()
    _REPO_OVERVIEW_CACHE.clear()
    await http_base.aclose()


@pytest.fixture
def no_network_transport():
    """A transport that raises on any request, for
    `test_no_live_network_calls`: cheap insurance that a bug can never make a
    test reach the real network, mocked or not."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected live network call: {request.method} {request.url}")

    return handler
