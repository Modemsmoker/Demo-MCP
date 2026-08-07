"""The five demo tools that prove transport, auth, and release plumbing work.

Plain, undecorated functions — `register()` binds them to the running
`MCPServer` instance. Keeping them undecorated here (rather than importing
`demo_mcp.server`) is what avoids a circular import: `demo_mcp.server`
constructs `mcp` and then calls `register_all(mcp)`, which imports this
module, which must therefore never import `demo_mcp.server` back.
"""

from datetime import UTC, datetime

from mcp.server.auth.middleware.auth_context import get_access_token

# The SDK renamed FastMCP -> MCPServer. Support both so this module works
# against either a pinned older release or the current one, without
# importing demo_mcp.server (see module docstring).
try:
    from mcp.server.mcpserver import Context, MCPServer
except ImportError:  # mcp < 1.13
    from mcp.server.fastmcp import Context
    from mcp.server.fastmcp import FastMCP as MCPServer

# In-memory store so there is something stateful to poke at from a client.
_NOTES: dict[str, str] = {}


def add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


def server_time() -> str:
    """Return the server's current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


async def save_note(title: str, body: str, ctx: Context) -> str:
    """Save a note under the given title, overwriting any existing note."""
    existed = title in _NOTES
    _NOTES[title] = body
    await ctx.info(f"{'Updated' if existed else 'Created'} note {title!r}")
    return f"{'Updated' if existed else 'Saved'} note {title!r} ({len(body)} chars)."


def list_notes() -> list[str]:
    """List the titles of all saved notes."""
    return sorted(_NOTES)


def whoami() -> str:
    """Report which client is calling and what scopes it holds."""
    token = get_access_token()
    if token is None:
        return "anonymous (auth disabled)"
    return f"{token.client_id} (scopes: {', '.join(token.scopes)})"


def read_note(title: str) -> str:
    """Read the body of a saved note."""
    if title not in _NOTES:
        raise ValueError(f"No note titled {title!r}")
    return _NOTES[title]


def summarize_note(title: str) -> str:
    """Ask the model to summarize a saved note."""
    return f"Read the resource note://{title} and summarize it in three bullets."


def register(mcp: MCPServer) -> None:
    """Register the five demo tools, the note resource, and the summarize prompt."""
    mcp.tool()(add)
    mcp.tool()(server_time)
    mcp.tool()(save_note)
    mcp.tool()(list_notes)
    mcp.tool()(whoami)
    mcp.resource("note://{title}")(read_note)
    mcp.prompt()(summarize_note)
