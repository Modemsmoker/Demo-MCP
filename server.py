"""Demo MCP server.

Runs over streamable HTTP so it can be hosted in a container and reached by any
MCP client at http://<host>:<port>/mcp
"""

import os
from datetime import datetime, timezone

# The SDK renamed FastMCP -> MCPServer. Support both so the image builds
# against either a pinned older release or the current one.
try:
    from mcp.server.mcpserver import Context, MCPServer

    _NEW_API = True
except ImportError:  # mcp < 1.13
    from mcp.server.fastmcp import Context
    from mcp.server.fastmcp import FastMCP as MCPServer

    _NEW_API = False

HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8000"))

mcp = MCPServer("Demo-MCP")

# In-memory store so there is something stateful to poke at from a client.
_NOTES: dict[str, str] = {}


# --- Tools -------------------------------------------------------------


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


@mcp.tool()
def server_time() -> str:
    """Return the server's current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@mcp.tool()
async def save_note(title: str, body: str, ctx: Context) -> str:
    """Save a note under the given title, overwriting any existing note."""
    existed = title in _NOTES
    _NOTES[title] = body
    await ctx.info(f"{'Updated' if existed else 'Created'} note {title!r}")
    return f"{'Updated' if existed else 'Saved'} note {title!r} ({len(body)} chars)."


@mcp.tool()
def list_notes() -> list[str]:
    """List the titles of all saved notes."""
    return sorted(_NOTES)


# --- Resources ---------------------------------------------------------


@mcp.resource("note://{title}")
def read_note(title: str) -> str:
    """Read the body of a saved note."""
    if title not in _NOTES:
        raise ValueError(f"No note titled {title!r}")
    return _NOTES[title]


# --- Prompts -----------------------------------------------------------


@mcp.prompt()
def summarize_note(title: str) -> str:
    """Ask the model to summarize a saved note."""
    return f"Read the resource note://{title} and summarize it in three bullets."


if __name__ == "__main__":
    if _NEW_API:
        mcp.run(transport="streamable-http", host=HOST, port=PORT)
    else:
        mcp.settings.host = HOST
        mcp.settings.port = PORT
        mcp.run(transport="streamable-http")
