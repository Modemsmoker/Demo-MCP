# Demo-MCP — Implementation Plan

## Context

`Demo-MCP` is a near-empty repo. The goal is a basic Python MCP server that runs in a Docker container via Docker Compose, so a separate Claude Code session can connect to it over the network and exercise real tools, resources, and prompts.

Transport matters here: `stdio` only works when the client launches the server as a subprocess. Since the server lives in a container, it must use **streamable HTTP** and expose `/mcp` on a published port.

SDK notes (verified against current MCP Python SDK docs):

- The SDK renamed `FastMCP` → `MCPServer`, now at `mcp.server.mcpserver`. The old import path still works on older releases.
- Transport configuration (`host`, `port`, `stateless_http`, `json_response`) belongs on `run()`, **not** the constructor, in the current SDK. On older releases it lives on `mcp.settings`.
- A tool gets the request context by declaring a `ctx: Context` parameter. The SDK injects it; it is not part of the tool's input schema.

## Current state

These files are already written and unverified — nothing has been built or run:

- `server.py`
- `requirements.txt`
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `README.md`

Review them against the descriptions below before changing anything.

## Files

### `server.py`

Imports `MCPServer` with a fallback to `FastMCP` so it builds against either SDK line. Reads `MCP_HOST`/`MCP_PORT` (default `0.0.0.0:8000`) and runs with `transport="streamable-http"`.

- tools: `add(a, b)`, `server_time()`, `save_note(title, body, ctx)`, `list_notes()`
- resource: `note://{title}`
- prompt: `summarize_note(title)`

`save_note` takes a `ctx: Context` parameter to demonstrate `await ctx.info(...)`. Notes live in a module-level dict, so state resets on container restart — that is intentional for a demo.

### `requirements.txt`

`mcp>=1.12`, `uvicorn>=0.30`.

### `Dockerfile`

`python:3.12-slim`, non-root uid 10001, `EXPOSE 8000`, TCP-socket healthcheck. An HTTP healthcheck against `/mcp` is unreliable without a session header, so the healthcheck opens a socket instead.

### `docker-compose.yml`

Publishes `8000:8000`, `restart: unless-stopped`, and `develop.watch` with `sync+restart` on `server.py`.

## Remaining work

### 1. `Makefile` (to write)

Wraps the commands used day to day. `.PHONY` on every target; `help` is the default goal and self-documents via `##` comments.

| Target | Command |
| --- | --- |
| `help` | list targets (default goal) |
| `build` | `docker compose build` |
| `up` | `docker compose up -d --build` |
| `down` | `docker compose down` |
| `restart` | `down` then `up` |
| `logs` | `docker compose logs -f demo-mcp` |
| `ps` | `docker compose ps` |
| `watch` | `docker compose watch` (live reload on `server.py` edits) |
| `shell` | `docker compose exec demo-mcp /bin/bash` |
| `health` | `curl -isS -X POST http://localhost:8000/mcp` — smoke-check the endpoint answers |
| `register` | `claude mcp add --transport http demo-mcp http://localhost:8000/mcp` |
| `unregister` | `claude mcp remove demo-mcp` |
| `clean` | `docker compose down -v --rmi local` |

### 2. Build and fix

1. `make up`
2. Fix whatever the first build/run surfaces — most likely the `mcp` version resolved by pip vs. the `MCPServer`/`FastMCP` import path, or `run()` rejecting `host`/`port` kwargs on an older release. If pip pulls a version where only `FastMCP` exists, the fallback branch sets `mcp.settings.host/port` instead; verify which branch actually executes rather than assuming.
3. Confirm the endpoint answers on `http://localhost:8000/mcp`.

### 3. Document

Add a Makefile section to `README.md` once the targets are confirmed working.

## Verification

- `make ps` shows the container healthy.
- `make logs` shows uvicorn bound to `0.0.0.0:8000`.
- `make health` returns an HTTP response from `/mcp`. A 4xx about a missing session or accept header still proves the server is live; a connection refused does not.
- From another Claude Code session:
  ```
  claude mcp add --transport http demo-mcp http://localhost:8000/mcp
  ```
  Then `/mcp` in that session lists the server, and its tools appear as `mcp__demo-mcp__add` and so on.
- End-to-end check in that session: call `add`, then `save_note` followed by `list_notes` and reading `note://<title>`. That proves tools, in-process state, and resources all round-trip.

## Constraints

- No auth is configured. Keep the published port on localhost; this is not safe to expose to a network as-is.
- Adding a tool is one decorated function. Type hints become the input schema and the docstring becomes the description the calling model reads, so both are load-bearing.
