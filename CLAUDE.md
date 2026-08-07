# Demo-MCP — working agreement

A Model Context Protocol server over streamable HTTP, containerised, released by
`python-semantic-release` from conventional commits.

## Stack

| Concern    | Choice                                              |
| ---------- | --------------------------------------------------- |
| Language   | Python 3.12+ (`requires-python = ">=3.12"`)          |
| Framework  | `mcp` SDK (FastMCP / MCPServer), pydantic, uvicorn   |
| Transport  | streamable HTTP at `/mcp`, port 8000                 |
| Lint/format| ruff (line length 100)                               |
| Tests      | pytest + pytest-asyncio (`asyncio_mode = "auto"`)    |
| Runtime    | Docker Compose; `make watch` live-reloads `demo_mcp/` |
| CI/Release | GitHub Actions + python-semantic-release             |

## The one command that matters

```bash
make check          # ruff check + ruff format --check + pytest
```

Nothing is "done" until `make check` is green. Use `make fmt` to auto-fix
formatting and lint violations rather than hand-editing style.

## MCP-specific rules

These are the ones that get broken most often. Read them before touching
`demo_mcp/`.

1. **Docstrings are the public API.** A tool's docstring is injected into the
   client model's prompt — it is the entire basis on which a model decides to
   call it. Write it for a model that has never seen this codebase: say what the
   tool does, and when to use it. Never ship a tool without one.
2. **Type annotations are the schema.** `mcp` derives each tool's JSON Schema
   from its signature. Missing or loose annotations (`Any`, bare `dict`) produce
   a useless schema. Ruff's `ANN201` enforces return annotations for this reason.
3. **`ctx: Context` is framework-injected.** It must not appear in the tool's
   input schema. `tests/test_server.py` pins this.
4. **Renaming a tool or an argument is a breaking change** for every connected
   client. It warrants `feat!:` or a `BREAKING CHANGE:` trailer.
5. **Support both SDK generations.** The SDK renamed `FastMCP` → `MCPServer` and
   `inputSchema` → `input_schema`. `demo_mcp/server.py`, the tool modules, and the
   tests all handle either; preserve that when adding code that touches SDK types.
6. **Don't block the event loop.** Tool handlers are async. Use async I/O; ruff's
   `ASYNC` rules catch the common mistakes.
7. **Errors belong in exceptions.** Raise `ValueError` with a useful message
   (see `read_note`); the framework turns it into a proper MCP error response.

## Auth

Single static bearer token via `MCP_AUTH_TOKEN`, compared with
`hmac.compare_digest` — constant-time, keep it that way. `MCP_AUTH_DISABLED=1`
bypasses auth for local work only. The server refuses to start if neither is set;
that is deliberate, don't soften it.

Never commit `.env` or a real token. Never log token values.

## Commits

Conventional Commits are **load-bearing** — python-semantic-release parses them
to compute the next version and write `CHANGELOG.md`. A wrong prefix means a
wrong release.

- `feat:` → minor
- `fix:` / `perf:` → patch
- `feat!:` or `BREAKING CHANGE:` trailer → major
- `chore:` / `docs:` / `test:` / `refactor:` → no release

Scope with the area touched, e.g. `feat(tools): add fetch_issue tool`.

## Where things live

```
demo_mcp/__init__.py      package docstring, __version__ (PSR rewrites this)
demo_mcp/auth.py          StaticTokenVerifier, auth env reads, startup guard
demo_mcp/server.py        MCPServer construction, run() — no tool bodies
demo_mcp/clients/base.py  HttpClient: base URL, auth strategy, retry, ETag cache
demo_mcp/clients/github.py GitHubClient(HttpClient) — endpoint methods only
demo_mcp/shaping.py       field allowlists, apply_fields(), truncation helpers
demo_mcp/models.py        pydantic result models returned by tools
demo_mcp/tools/__init__.py register_all(mcp) — one line per tool domain
demo_mcp/tools/demo.py    the five demo tools, note resource, summarize prompt
demo_mcp/tools/github.py  the seven read-only GitHub tools
tests/test_server.py      protocol-surface contract tests
tests/conftest.py         sets auth env before server import — required
tests/fixtures/github/    recorded GitHub API fixtures for offline tests
docs/                     AUTH, RELEASES, GITHUB_API, base_implementation
Makefile                  every workflow; `make help` lists them
.claude/agents/           planner -> implementer -> reviewer pipeline
.claude/handoff/          agent handoff artifacts (gitignored)
```

Tool modules never import `demo_mcp.server` — that would be circular, since
`demo_mcp.server` calls `register_all()`. A tool domain module exposes only a
`register(mcp)` function.

## Definition of done

- [ ] `make check` green
- [ ] New tools have docstring + full annotations + a test
- [ ] `docs/` updated if behaviour or config changed
- [ ] Conventional Commit prefix chosen deliberately
