"""Demo MCP server.

Runs over streamable HTTP so it can be hosted in a container and reached by any
MCP client at http://<host>:<port>/mcp
"""

__version__ = "0.1.0"

import hmac
import logging
import os
from datetime import datetime, timezone

from pydantic import AnyHttpUrl

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

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

AUTH_DISABLED = os.getenv("MCP_AUTH_DISABLED", "0") == "1"
AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")
PUBLIC_URL = os.getenv("MCP_PUBLIC_URL", "http://localhost:8000/mcp")

if not AUTH_DISABLED and not AUTH_TOKEN:
    raise RuntimeError(
        "MCP_AUTH_TOKEN is not set. Set it, or set MCP_AUTH_DISABLED=1 to run without auth."
    )

logger = logging.getLogger("demo-mcp")


class StaticTokenVerifier(TokenVerifier):
    """Accepts exactly one token, supplied via MCP_AUTH_TOKEN."""

    def __init__(
        self, token: str, client_id: str = "demo-client", scopes: list[str] | None = None
    ) -> None:
        self._token = token
        self._access = AccessToken(token=token, client_id=client_id, scopes=scopes or ["demo"])

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._access if hmac.compare_digest(token, self._token) else None


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


@mcp.tool()
def whoami() -> str:
    """Report which client is calling and what scopes it holds."""
    token = get_access_token()
    if token is None:
        return "anonymous (auth disabled)"
    return f"{token.client_id} (scopes: {', '.join(token.scopes)})"


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
