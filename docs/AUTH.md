# Demo-MCP — Adding Token Authentication

> This document covers only the *client → this server* auth layer
> (`MCP_AUTH_TOKEN`). The GitHub tools add a second, unrelated layer —
> *this server → GitHub* (`GH_API_TOKEN`) — documented in
> [`docs/GITHUB_API.md`](GITHUB_API.md). Do not conflate the two.

## Context

The server currently accepts any request that reaches `http://localhost:8000/mcp`. We want a shared secret: a token supplied to the container as an environment variable, which clients must present as `Authorization: Bearer <token>`. The `register` Make target must pass that header so a second Claude Code session can still connect.

This is deliberately not OAuth. It is a single static token, appropriate for a demo on localhost and for a service reachable only inside a trusted network.

## Approach

The MCP Python SDK (installed version: **2.0.0**) already models this. Over streamable HTTP the server acts as an OAuth 2.1 *resource server*: it verifies tokens but never issues them. The entire integration surface is one protocol:

```python
class TokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None: ...
```

Returning `None` rejects the request with 401. So a static-token implementation is a dict lookup, and we get the SDK's auth middleware, 401 handling, and `get_access_token()` inside tools for free.

Passing `auth=AuthSettings(...)` is required alongside the verifier — it declares the public face of the resource server (`issuer_url`, `resource_server_url`, `required_scopes`) and drives the RFC 9728 metadata document at `/.well-known/oauth-protected-resource`. Since we are not running an authorization server, `issuer_url` is a placeholder that no real client will exercise as long as it presents a valid token. Call this out in the README so nobody mistakes it for a working OAuth deployment.

*Alternative considered:* a plain Starlette middleware checking the header, with no `AuthSettings` and no placeholder issuer. Simpler and more honest about not being OAuth, but it gives up `get_access_token()` and the SDK's standards-compliant 401 responses. Prefer the SDK path; fall back to middleware only if `AuthSettings` proves awkward.

## Changes

### 1. `server.py`

Add above the tool definitions:

```python
from pydantic import AnyHttpUrl

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
```

Read config from the environment, next to the existing `HOST`/`PORT` block:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | *(none)* | the shared secret; required unless auth is disabled |
| `MCP_AUTH_DISABLED` | `0` | set to `1` to run without auth (local debugging only) |
| `MCP_PUBLIC_URL` | `http://localhost:8000/mcp` | public URL of the endpoint, for `resource_server_url` |

Fail fast rather than starting open by accident: if `MCP_AUTH_DISABLED` is not set and `MCP_AUTH_TOKEN` is empty, raise `RuntimeError` at import with a message naming both variables. If auth *is* disabled, log a clear warning at startup.

The verifier — compare with `hmac.compare_digest` so token checking is constant-time:

```python
class StaticTokenVerifier(TokenVerifier):
    """Accepts exactly one token, supplied via MCP_AUTH_TOKEN."""

    def __init__(self, token: str, client_id: str = "demo-client",
                 scopes: list[str] | None = None) -> None:
        self._token = token
        self._access = AccessToken(token=token, client_id=client_id,
                                   scopes=scopes or ["demo"])

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._access if hmac.compare_digest(token, self._token) else None
```

Construct the server conditionally so the disabled path stays working:

```python
if AUTH_DISABLED:
    mcp = MCPServer("Demo-MCP")
else:
    mcp = MCPServer(
        "Demo-MCP",
        token_verifier=StaticTokenVerifier(AUTH_TOKEN),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.invalid"),
            resource_server_url=AnyHttpUrl(PUBLIC_URL),
            required_scopes=["demo"],
        ),
    )
```

Add one tool that proves auth is wired, mirroring the SDK's own example:

```python
@mcp.tool()
def whoami() -> str:
    """Report which client is calling and what scopes it holds."""
    token = get_access_token()
    if token is None:
        return "anonymous (auth disabled)"
    return f"{token.client_id} (scopes: {', '.join(token.scopes)})"
```

`get_access_token()` reads a context var set by the auth middleware, so it works in sync tools and needs no `ctx` parameter.

### 2. `.env.example` (new) and `.env` (gitignored)

```
MCP_AUTH_TOKEN=replace-me
```

Add `.env` to `.gitignore` **and** to `.dockerignore` — the token must reach the container through Compose's environment, never baked into an image layer.

### 3. `docker-compose.yml`

Add to the `environment` block:

```yaml
      MCP_AUTH_TOKEN: ${MCP_AUTH_TOKEN:?set MCP_AUTH_TOKEN in .env}
      MCP_AUTH_DISABLED: ${MCP_AUTH_DISABLED:-0}
      MCP_PUBLIC_URL: ${MCP_PUBLIC_URL:-http://localhost:8000/mcp}
```

Compose reads `.env` from the project directory automatically, so `make up` picks up the token with no extra flags. The `:?` form makes a missing token a startup error with a readable message instead of a confusing 401 later.

### 4. `Makefile`

Near the top, so targets can use the token:

```make
-include .env
export
```

Then update and add targets:

| Target | Change |
| --- | --- |
| `token` | **new** — `@openssl rand -hex 32`, to generate a value for `.env` |
| `health` | add `-H "Authorization: Bearer $(MCP_AUTH_TOKEN)"` |
| `health-unauth` | **new** — same curl without the header; expect `401` |
| `register` | add `--header "Authorization: Bearer $(MCP_AUTH_TOKEN)"` |

The register command becomes:

```
claude mcp add --transport http demo-mcp http://localhost:8000/mcp \
  --header "Authorization: Bearer $(MCP_AUTH_TOKEN)"
```

Guard `register` so it errors clearly when `MCP_AUTH_TOKEN` is empty rather than registering a server with a literal empty bearer token.

### 5. Healthcheck

The `Dockerfile` healthcheck opens a TCP socket and does not speak HTTP, so it is unaffected by auth. Leave it alone.

### 6. `README.md`

- Replace the "No auth is configured" bullet in **Notes**.
- Add a **Setup** step before "Run it": `make token`, then put the value in `.env`.
- Update the register snippet to include `--header`.
- Add `token`, `health-unauth` to the Makefile table; note that `health` now sends the token.
- State plainly that this is a shared static secret, not OAuth, and that `issuer_url` is a placeholder.

## Verification

1. `make token`, write the value into `.env`, then `make up`.
2. `make health` → `200`-class response (or a normal MCP protocol error about headers/session, not `401`).
3. `make health-unauth` → `401`, with a `WWW-Authenticate` header.
4. `curl` with a deliberately wrong bearer token → `401`.
5. Unset the token and run the container → it exits at startup with the `RuntimeError`, not silently open.
6. `make unregister && make register`, then from another Claude Code session: `/mcp` shows the server connected, and `mcp__demo-mcp__whoami` returns `demo-client (scopes: demo)` — which is only reachable if the header authenticated.
7. Re-run `mcp__demo-mcp__github_repo_overview` (also what `make health-github` exercises, e.g. on `octocat/Hello-World`) to confirm auth did not break the tools. This no longer proves in-process state or resources round-trip, because the server has neither.

## Constraints and follow-ups

- One shared token, no rotation, no per-client identity. Everyone holding it is `demo-client`.
- The token appears in the Make target's process arguments and in Claude Code's MCP config on disk. Fine for a local demo; not fine for a real deployment.
- No TLS. Over plain HTTP a bearer token is exposed to anything on the path — keep the published port on localhost.
- Natural next step once this works: multiple tokens mapped to distinct `client_id`s and scopes, then per-tool scope checks via `get_access_token()`.
