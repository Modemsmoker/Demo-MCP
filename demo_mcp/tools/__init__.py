"""Tool registration.

`register_all(mcp)` calls each domain module's own `register()`. Adding a new
tool domain later means one import and one line here — the domain module
itself is what stays free of a `demo_mcp.server` import (see
`demo_mcp/tools/demo.py`).
"""

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp < 1.13
    from mcp.server.fastmcp import FastMCP as MCPServer

from demo_mcp.tools import demo, github


def register_all(mcp: MCPServer) -> None:
    """Register every tool, resource, and prompt domain with the server."""
    demo.register(mcp)
    github.register(mcp)
