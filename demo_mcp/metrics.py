"""Prometheus metric definitions and the tool-call middleware that populates
them. Kept in one module so both `server.py` (tool-call metrics, `/metrics`
route) and `clients/base.py` (outbound HTTP metrics) import from a single
place.
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import Counter, Histogram

# `ServerMiddleware` (and the `middleware=` constructor kwarg it powers) only
# exists on the new SDK generation (MCPServer). server.py only instantiates
# `PrometheusMiddleware` when `_NEW_API` is true, so on an old SDK this class
# is defined but never used; falling back to `object` keeps the module
# importable either way.
try:
    from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
except ImportError:  # mcp < 1.13, no middleware chain
    CallNext = HandlerResult = ServerRequestContext = Any
    ServerMiddleware = object

try:
    from mcp_types import CallToolResult
except ImportError:  # pragma: no cover - older SDKs ship this under mcp.types
    from mcp.types import CallToolResult

TOOL_CALLS_TOTAL = Counter(
    "demo_mcp_tool_calls_total",
    "Total number of MCP tool calls handled, labeled by tool name and outcome.",
    ["tool", "status"],
)
TOOL_CALL_DURATION_SECONDS = Histogram(
    "demo_mcp_tool_call_duration_seconds",
    "Duration of MCP tool calls in seconds, labeled by tool name.",
    ["tool"],
)
HTTP_REQUESTS_TOTAL = Counter(
    "demo_mcp_http_requests_total",
    "Total number of outbound HTTP requests made by the server, labeled by host and status.",
    ["host", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "demo_mcp_http_request_duration_seconds",
    "Duration of outbound HTTP requests in seconds, labeled by host.",
    ["host"],
)


_MiddlewareBase = ServerMiddleware[Any] if ServerMiddleware is not object else object


class PrometheusMiddleware(_MiddlewareBase):
    """Context-tier middleware that records Prometheus metrics for every
    `tools/call` request. Structurally mirrors the SDK's own
    `OpenTelemetryMiddleware` (`mcp/server/_otel.py`).
    """

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)

        name = ctx.params.get("name") if ctx.params else None
        tool = name if isinstance(name, str) else "unknown"

        start = time.monotonic()
        try:
            result = await call_next(ctx)
        except Exception:
            TOOL_CALL_DURATION_SECONDS.labels(tool=tool).observe(time.monotonic() - start)
            TOOL_CALLS_TOTAL.labels(tool=tool, status="error").inc()
            raise

        TOOL_CALL_DURATION_SECONDS.labels(tool=tool).observe(time.monotonic() - start)
        # Tool errors are detected pre-serialization, so only shapes that reach the wire as an
        # error count: the model, or the camelCase alias (mirrors OpenTelemetryMiddleware).
        match result:
            case CallToolResult(is_error=True) | {"isError": True}:
                status = "error"
            case _:
                status = "ok"
        TOOL_CALLS_TOTAL.labels(tool=tool, status=status).inc()
        return result
