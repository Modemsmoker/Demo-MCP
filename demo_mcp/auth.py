"""Client -> server authentication.

A single static bearer token, supplied via MCP_AUTH_TOKEN, checked with a
constant-time comparison. This module is imported before the server is
constructed, so the startup guard below fires at import time — tests rely on
that contract (see tests/conftest.py).
"""

import hmac
import logging
import os

from mcp.server.auth.provider import AccessToken, TokenVerifier

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
