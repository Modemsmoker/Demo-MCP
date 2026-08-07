"""Demo MCP server.

Runs over streamable HTTP so it can be hosted in a container and reached by
any MCP client at http://<host>:<port>/mcp
"""

import logging
import os

from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from demo_mcp import __version__
from demo_mcp.auth import AUTH_DISABLED, AUTH_TOKEN, PUBLIC_URL, StaticTokenVerifier
from demo_mcp.tools import register_all

# The SDK renamed FastMCP -> MCPServer. Support both so the image builds
# against either a pinned older release or the current one.
try:
    from mcp.server.mcpserver import MCPServer

    _NEW_API = True
except ImportError:  # mcp < 1.13
    from mcp.server.fastmcp import FastMCP as MCPServer

    _NEW_API = False

HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8000"))

logger = logging.getLogger("demo-mcp")

if AUTH_DISABLED:
    logger.warning("MCP_AUTH_DISABLED=1: server is running without authentication.")
    mcp = MCPServer("Demo-MCP", version=__version__)
else:
    mcp = MCPServer(
        "Demo-MCP",
        version=__version__,
        token_verifier=StaticTokenVerifier(AUTH_TOKEN),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.invalid"),
            resource_server_url=AnyHttpUrl(PUBLIC_URL),
            required_scopes=["demo"],
        ),
    )

register_all(mcp)


if __name__ == "__main__":
    if _NEW_API:
        mcp.run(transport="streamable-http", host=HOST, port=PORT)
    else:
        mcp.settings.host = HOST
        mcp.settings.port = PORT
        mcp.run(transport="streamable-http")
