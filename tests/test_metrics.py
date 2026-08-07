"""Tests for the /metrics endpoint and the tool-call middleware that feeds it.

`server.mcp.custom_route("/metrics", ...)` should render whatever's in the
default Prometheus registry without auth. The second test goes further and
proves the middleware actually fires on a real `tools/call`, not just that
the endpoint renders whatever counters happen to exist. The outbound-HTTP
tests below drive the real instrumentation in `HttpClient.get()` (via the
`github_transport` fixture's `httpx.MockTransport`, reused here since it's
just wiring the shared `HttpClient` singleton to a mock transport - nothing
about it is GitHub-specific) rather than poking the counters directly.
"""

import anyio
import httpx
import pytest
from starlette.testclient import TestClient

from demo_mcp import server
from demo_mcp.clients.base import HttpClient
from demo_mcp.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL, TOOL_CALLS_TOTAL

HOST = "example.test"
BASE_URL = f"https://{HOST}"


async def _instant_sleep(*_args: object, **_kwargs: object) -> None:
    """Replaces `asyncio.sleep` in retry tests so exhausting retries doesn't
    actually wait out the real backoff."""
    return None


def _histogram_observation_count(histogram: object, **labels: str) -> float:
    """`Histogram` child objects expose `_sum` but no public observation
    count; read it off the `_count` sample instead, the same way `/metrics`
    itself would render it."""
    for family in histogram.collect():  # type: ignore[attr-defined]
        for sample in family.samples:
            if sample.name.endswith("_count") and sample.labels == labels:
                return sample.value
    return 0.0


# --- /metrics endpoint ---------------------------------------------------


def test_metrics_endpoint_is_reachable_without_auth():
    """The whole point of custom_route for /metrics is that a Prometheus
    scraper, which has no bearer token, can still reach it."""
    app = server.mcp.streamable_http_app()
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_metrics_body_contains_the_demo_mcp_metric_families():
    app = server.mcp.streamable_http_app()
    with TestClient(app) as client:
        response = client.get("/metrics")

    body = response.text
    assert "demo_mcp_tool_calls_total" in body
    assert "demo_mcp_http_requests_total" in body


# --- middleware actually fires --------------------------------------------


async def test_a_real_tool_call_increments_the_tool_call_counter():
    """Drive a real tools/call through the MCP protocol (not the
    `MCPServer.call_tool()` convenience method, which bypasses the
    middleware chain) and confirm PrometheusMiddleware recorded it."""
    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams

    before = TOOL_CALLS_TOTAL.labels(tool="whoami", status="ok")._value.get()

    # Private, but it's the only way to drive the server over a raw stream pair
    # rather than a real transport.
    lowlevel = server.mcp._lowlevel_server

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def run_server() -> None:
                await lowlevel.run(
                    server_read, server_write, lowlevel.create_initialization_options()
                )

            tg.start_soon(run_server)

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                await session.call_tool("whoami", {})

            tg.cancel_scope.cancel()

    after = TOOL_CALLS_TOTAL.labels(tool="whoami", status="ok")._value.get()
    assert after == before + 1


# --- outbound HTTP metrics (HttpClient.get) --------------------------------


async def test_http_get_success_records_one_increment_and_one_observation(github_transport):
    """A plain 200 records exactly one counter increment, labeled with the
    real status code, and one duration observation."""
    github_transport(lambda request: httpx.Response(200, json={"ok": True}))
    client = HttpClient(base_url=BASE_URL)

    before_total = HTTP_REQUESTS_TOTAL.labels(host=HOST, status="200")._value.get()
    before_observations = _histogram_observation_count(HTTP_REQUEST_DURATION_SECONDS, host=HOST)

    await client.get("/thing")

    assert HTTP_REQUESTS_TOTAL.labels(host=HOST, status="200")._value.get() == before_total + 1
    assert (
        _histogram_observation_count(HTTP_REQUEST_DURATION_SECONDS, host=HOST)
        == before_observations + 1
    )


async def test_http_get_exhausted_5xx_retries_records_the_real_status_once(
    github_transport, monkeypatch
):
    """Every attempt gets a 500; once retries are exhausted the terminal
    status label is the real numeric status - not a generic "error", which
    is reserved for a transport-level failure that never got a response at
    all (see the next test). Despite three attempts, exactly one increment
    and one duration observation are recorded for the logical call."""
    monkeypatch.setattr("demo_mcp.clients.base.asyncio.sleep", _instant_sleep)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    github_transport(handler)
    client = HttpClient(base_url=BASE_URL)

    before_total = HTTP_REQUESTS_TOTAL.labels(host=HOST, status="500")._value.get()
    before_observations = _histogram_observation_count(HTTP_REQUEST_DURATION_SECONDS, host=HOST)

    await client.get("/thing")

    assert calls == client.retries + 1, "every attempt should have reached the transport"
    assert HTTP_REQUESTS_TOTAL.labels(host=HOST, status="500")._value.get() == before_total + 1
    assert (
        _histogram_observation_count(HTTP_REQUEST_DURATION_SECONDS, host=HOST)
        == before_observations + 1
    )


async def test_http_get_exhausted_transport_error_retries_records_error_once(
    github_transport, monkeypatch
):
    """Every attempt raises a transport-level error (no response ever
    received); the terminal status label is the literal "error" string, and
    - as above - retried attempts still add up to exactly one increment and
    one duration observation."""
    monkeypatch.setattr("demo_mcp.clients.base.asyncio.sleep", _instant_sleep)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom", request=request)

    github_transport(handler)
    client = HttpClient(base_url=BASE_URL)

    before_total = HTTP_REQUESTS_TOTAL.labels(host=HOST, status="error")._value.get()
    before_observations = _histogram_observation_count(HTTP_REQUEST_DURATION_SECONDS, host=HOST)

    with pytest.raises(httpx.TransportError):
        await client.get("/thing")

    assert calls == client.retries + 1, "every attempt should have reached the transport"
    assert HTTP_REQUESTS_TOTAL.labels(host=HOST, status="error")._value.get() == before_total + 1
    assert (
        _histogram_observation_count(HTTP_REQUEST_DURATION_SECONDS, host=HOST)
        == before_observations + 1
    )
