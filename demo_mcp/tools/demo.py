"""The `whoami` tool, the in-band proof that bearer-token auth is wired up.

Plain, undecorated function — `register()` binds it to the running
`MCPServer` instance. Keeping it undecorated here (rather than importing
`demo_mcp.server`) is what avoids a circular import: `demo_mcp.server`
constructs `mcp` and then calls `register_all(mcp)`, which imports this
module, which must therefore never import `demo_mcp.server` back.
"""

from mcp.server.auth.middleware.auth_context import get_access_token

# The SDK renamed FastMCP -> MCPServer. Support both so this module works
# against either a pinned older release or the current one, without
# importing demo_mcp.server (see module docstring).
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp < 1.13
    from mcp.server.fastmcp import FastMCP as MCPServer


def whoami() -> str:
    """Report which client is calling and what scopes it holds.

    The only in-band way for a client to confirm which identity and scopes a
    bearer token resolved to — call this to verify auth is working end to end.
    """
    token = get_access_token()
    if token is None:
        return "anonymous (auth disabled)"
    return f"{token.client_id} (scopes: {', '.join(token.scopes)})"


def register(mcp: MCPServer) -> None:
    """Register the whoami tool."""
    mcp.tool()(whoami)
