# Demo-MCP — Observability

Prometheus metrics and a Grafana dashboard ship alongside the server so its
usage and performance are visible without extra setup.

## `/metrics`

The server exposes Prometheus text-format metrics at
`http://localhost:8000/metrics`. This route is registered with
`MCPServer.custom_route()`, which the SDK documents as bypassing auth — it is
not wrapped by `RequireAuthMiddleware`. That is deliberate: a Prometheus
scraper has no bearer token and no way to acquire one, and metrics data is not
sensitive in the way tool responses can be. `MCP_AUTH_TOKEN` still protects
every `/mcp` tool call; `/metrics` is a separate, intentionally public route,
the same way it would be behind a health-check endpoint in most services.

## Metric names and labels

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `demo_mcp_tool_calls_total` | Counter | `tool`, `status` (`ok`/`error`) | Every `tools/call` request handled, by tool name and outcome. |
| `demo_mcp_tool_call_duration_seconds` | Histogram | `tool` | Wall-clock time spent inside a tool call. |
| `demo_mcp_http_requests_total` | Counter | `host`, `status` | Outbound HTTP GETs made by `HttpClient` (e.g. to the GitHub API), by target host and terminal outcome. `status` is the real numeric HTTP status code of the last response received — including a `5xx` that exhausted retries. It is only the literal string `error` when every retry raised a transport-level failure (connection error, timeout) and no response was ever received. |
| `demo_mcp_http_request_duration_seconds` | Histogram | `host` | Time spent per logical `HttpClient.get()` call, including any retries — one observation per call, not per attempt. |

Standard `prometheus_client` process metrics (`process_*`, `python_gc_*`, etc.)
are also present, since they come free with the default registry.

## How it's wired

- **Tool-call metrics** (`demo_mcp_tool_calls_total`,
  `demo_mcp_tool_call_duration_seconds`) are recorded by
  `PrometheusMiddleware` in `demo_mcp/metrics.py`, which hooks into the SDK's
  `ServerMiddleware` chain — the same mechanism the SDK itself uses for
  `OpenTelemetryMiddleware`. It wraps every `tools/call` without touching any
  individual tool function.
- **Outbound HTTP metrics** (`demo_mcp_http_requests_total`,
  `demo_mcp_http_request_duration_seconds`) are recorded in
  `HttpClient.get()` (`demo_mcp/clients/base.py`), the single choke point for
  every outbound call the server makes (currently, GitHub's API).
- **`_NEW_API`-only caveat**: the SDK renamed `FastMCP` → `MCPServer`, and the
  `middleware=` constructor kwarg that powers tool-call metrics only exists on
  the new generation (`_NEW_API` in `demo_mcp/server.py`). On an old SDK,
  `PrometheusMiddleware` is never instantiated, so
  `demo_mcp_tool_calls_total`/`demo_mcp_tool_call_duration_seconds` stay at
  zero. `/metrics` and the outbound-HTTP metrics are unaffected — both SDK
  generations support `custom_route()`, and `HttpClient.get()` doesn't touch
  the middleware chain at all.

## Prometheus and Grafana in Compose

`docker-compose.yml` starts two extra services automatically with `make up` —
no profile flag needed:

- **`prometheus`** (`prom/prometheus:v2.55.1`) scrapes `demo-mcp:8000/metrics`
  every 15s, per `observability/prometheus/prometheus.yml`. Reachable at
  `http://localhost:9090`; check `/targets` to confirm the `demo-mcp` job is
  `UP`.
- **`grafana`** (`grafana/grafana:11.3.0`) is pre-provisioned with a
  `Prometheus` datasource (`observability/grafana/provisioning/datasources/`)
  and a "Demo-MCP" dashboard (`observability/grafana/dashboards/demo-mcp.json`)
  that is auto-loaded via
  `observability/grafana/provisioning/dashboards/dashboards.yml`.

  Anonymous **Viewer** access is enabled, so `http://localhost:3000` shows the
  dashboard immediately with no login. Admin login (`admin` /
  `$GRAFANA_ADMIN_PASSWORD`, default `admin`) is still available for editing —
  set `GRAFANA_ADMIN_PASSWORD` in `.env` to change it. Grafana's own state
  (users, edits) persists in the `grafana-data` named volume, which survives
  `make restart` but is removed by `make clean`.

The dashboard has five panels: tool call rate by tool, tool call error rate,
p95 tool call duration, outbound HTTP request rate by host/status, and p95
outbound HTTP duration.

## Makefile targets

| Target | What it does |
| --- | --- |
| `make metrics` | `curl` the running server's `/metrics` output |
| `make dashboard` | Print the Grafana dashboard URL (`http://localhost:3000`) |

## Verification

1. `make up` — starts `demo-mcp`, `prometheus`, `grafana`.
2. `make metrics` (or `curl -sS http://localhost:8000/metrics | grep demo_mcp_`)
   — confirms metric families are exposed.
3. Call a tool (e.g. `make health`, or an actual MCP client call), then
   re-check `/metrics` — `demo_mcp_tool_calls_total` should have incremented.
4. `http://localhost:9090/targets` — the `demo-mcp` scrape target is `UP`.
5. `make dashboard` and open the URL — the "Demo-MCP" dashboard loads with
   live panels, no login prompt.
