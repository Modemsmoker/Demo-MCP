# Demo-MCP

A minimal Model Context Protocol server in Python, served over streamable HTTP from a Docker container.

## What it exposes

| Kind | Name | Purpose |
| --- | --- | --- |
| tool | `add(a, b)` | adds two numbers |
| tool | `server_time()` | UTC time from inside the container |
| tool | `save_note(title, body)` | writes to an in-memory store |
| tool | `list_notes()` | lists saved note titles |
| resource | `note://{title}` | reads a saved note |
| prompt | `summarize_note(title)` | prompt template over a note |

State lives in process memory, so it resets whenever the container restarts.

## Run it

```bash
docker compose up --build
```

The endpoint is `http://localhost:8000/mcp`.

While iterating on `server.py`, this reloads the container on save:

```bash
docker compose watch
```

## Connect from another Claude Code session

```bash
claude mcp add --transport http demo-mcp http://localhost:8000/mcp
```

Then in that session, `/mcp` lists the connection and the tools show up as `mcp__demo-mcp__add`, etc.

To remove it later:

```bash
claude mcp remove demo-mcp
```

## Adding a tool

Add a decorated function in [server.py](server.py) — the type hints become the input schema and the docstring becomes the tool description, so both matter to the calling model:

```python
@mcp.tool()
def word_count(text: str) -> int:
    """Count whitespace-separated words in the given text."""
    return len(text.split())
```

Async functions work too, and adding a `ctx: Context` parameter gives you `await ctx.info(...)` for logging back to the client and `await ctx.report_progress(...)` for long operations. The parameter is injected by the SDK and is not part of the tool's schema.

## Makefile

Wraps the commands above. Run `make` (or `make help`) to list targets.

| Target | Does |
| --- | --- |
| `help` | List targets (default) |
| `build` | `docker compose build` |
| `up` | Build and start the container in the background |
| `down` | Stop and remove the container |
| `restart` | `down` then `up` |
| `logs` | Follow container logs |
| `ps` | Show container status |
| `watch` | `docker compose watch` — live reload on `server.py` edits |
| `shell` | Shell into the running container |
| `health` | Smoke-check `/mcp` responds |
| `register` | `claude mcp add --transport http demo-mcp http://localhost:8000/mcp` |
| `unregister` | `claude mcp remove demo-mcp` |
| `clean` | `docker compose down -v --rmi local` |

## Notes

- The server binds `0.0.0.0` inside the container so Docker can publish the port; only `8000` on the host is exposed.
- No auth is configured. Keep the published port on localhost — don't expose this to a network as-is.
- `server.py` imports `MCPServer` with a fallback to `FastMCP`, the SDK's older name for the same class, so it builds against either release line.
