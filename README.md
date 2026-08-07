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
| tool | `github_repo_overview(repo)` | compact repo summary: stars, language, latest release, open issue/PR counts |
| tool | `github_search(query, type, repo, state, author, limit, cursor)` | search GitHub issues, pull requests, or repositories |
| tool | `github_get_issue(repo, number, include_comments, comment_limit)` | full detail of one issue, comments opt-in |
| tool | `github_list_commits(repo, ref, path, since, limit)` | recent commits: short sha, first line of message, author, date |
| tool | `github_get_file(repo, path, ref, start_line, end_line)` | read a file's content, capped at ~8 KB |
| tool | `github_list_releases(repo, limit)` | recent releases with truncated release notes |
| tool | `github_get_pull_request(repo, number, files)` | PR detail with per-file diff stats; patch text opt-in per file |

State lives in process memory, so it resets whenever the container restarts.

## Setup

The server requires a shared bearer token. Generate one and put it in `.env`:

```bash
make token          # prints a random token
cp .env.example .env
# paste the token as MCP_AUTH_TOKEN in .env
```

The GitHub tools work without any further setup, limited to GitHub's
unauthenticated rate limit (60 requests/hour). To raise that limit, add a
personal access token as `GH_API_TOKEN` in `.env` — see **Two tokens** below.

`docker compose` reads `.env` automatically, so `make up` picks it up with no extra flags.

## Run it

```bash
docker compose up --build
```

The endpoint is `http://localhost:8000/mcp`.

While iterating on the `demo_mcp/` package, this reloads the container on save:

```bash
docker compose watch
```

## Connect from another Claude Code session

```bash
claude mcp add --transport http demo-mcp http://localhost:8000/mcp \
  --header "Authorization: Bearer $MCP_AUTH_TOKEN"
```

Then in that session, `/mcp` lists the connection and the tools show up as `mcp__demo-mcp__add`, etc.

To remove it later:

```bash
claude mcp remove demo-mcp
```

## Two tokens

There are two distinct auth layers, and conflating them is an easy misread:

| Variable | Direction | Meaning |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | client → this server | who may call this MCP server |
| `GH_API_TOKEN` | this server → GitHub | which GitHub identity the server acts as when calling the GitHub tools |

`MCP_AUTH_TOKEN` is required; the server refuses to start without it (or without
`MCP_AUTH_DISABLED=1`). `GH_API_TOKEN` is optional — its absence degrades to
GitHub's 60 requests/hour unauthenticated limit rather than refusing to start,
and a warning is logged once when the GitHub client is first used. The token is
never echoed in tool output, error messages, or logs.

## Adding a tool

Add a plain, undecorated function to the relevant module under
[`demo_mcp/tools/`](demo_mcp/tools/) (e.g. `demo_mcp/tools/demo.py`), then bind it
in that module's `register()` — the type hints become the input schema and the
docstring becomes the tool description, so both matter to the calling model:

```python
def word_count(text: str) -> int:
    """Count whitespace-separated words in the given text."""
    return len(text.split())


def register(mcp: MCPServer) -> None:
    ...
    mcp.tool()(word_count)
```

Async functions work too, and adding a `ctx: Context` parameter gives you `await ctx.info(...)` for logging back to the client and `await ctx.report_progress(...)` for long operations. The parameter is injected by the SDK and is not part of the tool's schema.

A new tool *domain* (a new file under `demo_mcp/tools/`) needs one more line: call its
`register()` from `register_all()` in `demo_mcp/tools/__init__.py`.

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
| `watch` | `docker compose watch` — live reload on `demo_mcp/` edits |
| `shell` | Shell into the running container |
| `health` | Smoke-check `/mcp` responds, with the bearer token attached |
| `health-unauth` | Same, without a token — expect `401` |
| `health-github` | Call `github_repo_overview` against a known public repo through the running container |
| `token` | Generate a random value for `MCP_AUTH_TOKEN` |
| `env` | Create `.env` with a generated `MCP_AUTH_TOKEN` if one doesn't exist yet (used by CI) |
| `register` | `claude mcp add --transport http demo-mcp http://localhost:8000/mcp --header "Authorization: Bearer $MCP_AUTH_TOKEN"` |
| `unregister` | `claude mcp remove demo-mcp` |
| `clean` | `docker compose down -v --rmi local` |

## Releasing

Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:` bumps the minor version, `fix:`/`perf:` bumps patch, and a `!` or `BREAKING CHANGE:` footer bumps major (minor, while the project is still `0.x`). Merging to `main` runs [python-semantic-release](https://python-semantic-release.readthedocs.io/) automatically — it computes the next version from commit history, updates `pyproject.toml` and `__version__` in `demo_mcp/__init__.py`, tags the commit, generates `CHANGELOG.md`, and publishes a GitHub Release. PRs are squash-merged, so the **PR title** is what gets parsed — it must itself be a valid Conventional Commit, and CI lints it.

## Notes

- The server binds `0.0.0.0` inside the container so Docker can publish the port; only `8000` on the host is exposed.
- Auth is a single shared static bearer token (`MCP_AUTH_TOKEN`), not OAuth. There's no rotation and no per-client identity — everyone holding the token is `demo-client`. The `issuer_url` set in `server.py` is a placeholder; no authorization server actually runs. This is appropriate for a localhost demo only — keep the published port off any untrusted network, and note there's no TLS, so the token is exposed to anything on the network path.
- `demo_mcp/server.py` imports `MCPServer` with a fallback to `FastMCP`, the SDK's older name for the same class, so it builds against either release line.
