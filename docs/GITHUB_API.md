# Demo-MCP — GitHub API Tools

## Context

The server currently exposes toy tools (`add`, `save_note`) that prove transport, auth, and
release plumbing work. The next step is real functionality: read-only tools over the **GitHub
REST API v3**, chosen because it has genuine auth, real pagination, HTTP caching via ETags, and
notoriously verbose payloads — which makes it a good vehicle for the design constraint below.

**The constraint that drives every decision here: tool output must not bloat session context.**

A naive MCP server is a 1:1 wrapper around HTTP endpoints. That is the wrong shape. One
`GET /repos/{owner}/{repo}` response is ~4 KB of JSON, of which a model needs maybe eight
fields. One PR diff can exceed an entire context window. Thirty endpoints become thirty tool
schemas, and *every one of those schemas is re-sent on every single request* whether it is
called or not.

So the design rule is: **tools mirror user intent, not endpoints.** A small number of tools
return compact summaries carrying stable identifiers; separate tools expand a single
identifier into detail on demand. Search, then drill down.

## Non-goals

- **Write operations.** No creating issues, comments, PRs, or pushes. They double the auth
  surface, invite a "what are your safeguards" conversation, and add nothing to what this
  server demonstrates.
- **Generic OpenAPI ingestion.** Registering an arbitrary spec and generating tools from it
  produces exactly the bloat this design exists to avoid — one tool per endpoint, full
  parameter schemas inlined, raw passthrough responses. Extensibility is handled instead by
  the adapter seam described under *Extensibility*.
- **1:1 wrappers** for `/users`, `/orgs`, `/branches`, notifications, gists. Each costs schema
  tokens on every request for functionality nothing exercises.

## Tool surface

Seven tools. `repo` is always a single `"owner/name"` string, never two parameters.

### `github_repo_overview(repo)`

Composes several upstream calls into one response: description, stars, forks, primary
language, default branch, latest release tag and date, open issue count, open PR count, last
push. Highest-value tool in the set — it eliminates the four-round-trip warm-up that would
otherwise begin every session.

Note that open PR count is not on the repo object; GitHub's `open_issues_count` includes PRs.
Get the real split from the search API or accept the combined number and label it honestly.

### `github_search(type, query, repo=None, state=None, author=None, limit=20)`

One tool covering `issues`, `pulls`, `repos`, and `code` via a `type` discriminator. Returns
per item: number/id, title, state, author, `updated_at`, url. Nothing else.

Resist splitting this into four tools. The parameter schemas are near-identical, and four
copies is schema cost paid on every request forever.

### `github_get_issue(repo, number, include_comments=False)`

Body, labels, assignees, milestone, linked PRs. Comments are opt-in and capped (default 10,
newest first, each truncated) because a hot thread is thousands of tokens.

### `github_get_pull_request(repo, number, files=None)`

Metadata plus a **file-level** summary: path, additions, deletions, status. The actual patch
text is returned only for paths explicitly named in `files`. Never return a full diff
unprompted — that is the single fastest way to blow a context window on one call.

### `github_list_commits(repo, ref=None, path=None, since=None, limit=20)`

Short sha, first line of the commit message, author, date. Not the full body, not the changed
file list.

### `github_get_file(repo, path, ref=None, start_line=None, end_line=None)`

Hard byte cap (~8 KB). On truncation, return the content plus an explicit note stating the
total line count and how to request the remainder — the model can only self-correct if told
how.

### `github_list_releases(repo, limit=10)`

Tag, name, published date, prerelease flag, and the release body truncated to ~500 chars.
Directly relevant to this repo's own semantic-release setup.

## Shared conventions

Applied uniformly across all seven tools:

| Concern | Rule |
| --- | --- |
| Repo identifier | single `"owner/name"` string |
| Limits | capped server-side regardless of what the caller asks for |
| Pagination | opaque `cursor` + `has_more` in the response; GitHub's `Link` headers never leak out |
| Field selection | declarative allowlist per resource type, applied in one place |
| Truncation | always signalled explicitly, never silent |
| Errors | 404 / 403 / rate-limit mapped to short actionable messages, not raw JSON |
| Timestamps | passed through as ISO 8601 |

## Structure

`server.py` is currently flat and will not hold this. Promote to a package:

```
demo_mcp/
  __init__.py
  server.py          # MCPServer construction, auth, run() — as today
  auth.py            # StaticTokenVerifier, moved out of server.py
  clients/
    base.py          # HttpClient: base URL, auth strategy, retry, ETag cache
    github.py        # GitHubClient(HttpClient) — endpoint methods only
  shaping.py         # field allowlists + apply_fields(); truncation helpers
  tools/
    __init__.py      # register_all(mcp)
    github.py        # the seven @mcp.tool() functions
```

The split that matters: **`clients/` knows HTTP, `shaping.py` knows what a model needs to see,
`tools/` knows intent.** A tool function should be short — call the client, apply a named
allowlist, return. If a tool function is doing JSON surgery inline, the allowlist is in the
wrong place.

`shaping.py` holds something like:

```python
FIELDS = {
    "issue_summary": ("number", "title", "state", "user.login", "updated_at", "html_url"),
    "issue_detail":  ("number", "title", "state", "body", "labels[].name", ...),
    "commit_summary": ("sha[:7]", "commit.message|first_line", "commit.author.name", ...),
}
```

Declarative, one dict, greppable. This is also the artifact that makes the extensibility
argument concrete in a walkthrough.

## Auth

GitHub PAT via `GH_API_TOKEN`, read from the environment exactly as `MCP_AUTH_TOKEN` is today.
Add to `.env.example` and document in `README.md`.

Two distinct auth layers now exist and the distinction is worth stating explicitly in the
README, because conflating them is an easy misread:

- `MCP_AUTH_TOKEN` — *client → this server*. Who may call the MCP server.
- `GH_API_TOKEN` — *this server → GitHub*. Which GitHub identity the server acts as.

Unauthenticated GitHub allows 60 requests/hour; a PAT gives 5,000. Degrade gracefully rather
than refusing to start when `GH_API_TOKEN` is absent — log a warning at startup and let the
lower limit apply. Never echo the token in tool output or error messages.

## Caching

`HttpClient` keeps an in-memory `{url: (etag, payload)}` map and sends `If-None-Match`. GitHub
returns `304` for unchanged resources and **a 304 does not count against the rate limit**, so
repeat calls become both free and fast. A dict is fine here; state resets on container
restart, which is consistent with how `_NOTES` already behaves.

Add a short TTL (~60s) on top so a tight loop of identical calls does not even reach the
network.

## Extensibility

The right seam is `HttpClient` — base URL, auth strategy, retry policy, cache — parameterized
rather than hardcoded. Adding a second API means a new subclass, a new entry in `FIELDS`, and
a new module under `tools/`. No refactor of anything existing.

Worth proving rather than asserting: **CISA KEV** is a single unauthenticated JSON endpoint,
roughly 30 lines, and demonstrates the seam is real. Optional, and only after GitHub works
end to end.

If an OpenAPI spec is wanted, the defensible use is at *build* time — generate types or a
client from the spec, commit the output, hand-curate the tool surface on top. That keeps a
spec parser out of the request path.

## Implementation order

1. Package restructure; existing toy tools keep working, container still comes up. Commit.
2. `clients/base.py` + `clients/github.py` with retry and ETag caching. Unit-test against
   recorded fixtures, no live calls in CI.
3. `shaping.py` with the allowlist map and `apply_fields()`.
4. Tools in dependency order: `github_repo_overview` → `github_search` →
   `github_get_issue` → `github_list_commits` → `github_get_file` →
   `github_list_releases` → `github_get_pull_request`.
5. Update `README.md`, `.env.example`, and add `make health-github`.

Conventional commits throughout — semantic-release parses them, so `feat:` on each tool
produces a sensible changelog on its own.

## Verification

- `make up` and `make ps` show the container healthy with the new package layout.
- Register from a second Claude Code session; all seven tools appear as
  `mcp__demo-mcp__github_*`.
- End-to-end against a known public repo: `github_repo_overview` →
  `github_search(type="issues")` → `github_get_issue` on a number from those results. That
  chain proves the summary-then-drill-down pattern actually round-trips, which is the whole
  design claim.
- Confirm ETag caching: call the same tool twice, check the logs for a `304`.
- Confirm truncation: `github_get_file` on a large file returns the cap plus an explicit
  truncation notice, not a silent cut.
- Confirm no token leakage: force a 401 from GitHub with a bad `GH_API_TOKEN` and check the
  error surfaced to the client contains no secret.

### Instrumentation

Log an approximate token count for every tool response (`len(json) / 4` is close enough).
Then capture a before/after comparing raw passthrough against shaped output for the same call.

This turns the central architectural claim into a number, and a number is what makes the
argument in a code walkthrough.

## Open questions

- Rate-limit behaviour when exhausted: fail fast with the reset time, or block and retry?
  Fail fast is more honest to a calling model, which can decide whether to wait.
- Should `github_search(type="code")` ship at all? Code search has its own auth requirements
  and quirkier rate limits than the rest. Reasonable to defer.
- Whether `github_repo_overview` should cache more aggressively than the other tools, since
  it is the likely first call in every session.

## As built

Decisions the implementation landed on, where they diverged from or resolved something left
open in this spec:

- **Explicit `httpx` dependency (D1).** `httpx>=0.27` is declared directly in
  `requirements.txt` rather than relied on transitively. The `mcp` SDK's own HTTP dependency
  (`httpx2` on the 2.x line installed in this repo) is a separate module and coexists without
  conflict; `demo_mcp` only ever imports plain `httpx`.
- **Singleton over lifespan (D2).** `demo_mcp/clients/base.py` holds a lazily-constructed,
  process-wide `httpx.AsyncClient` with `set_client()`/`aclose()` for tests, rather than using
  `MCPServer`'s `lifespan` hook. Same lifetime model `_NOTES` already uses.
- **Pydantic returns (D3).** Every tool returns a pydantic model (`demo_mcp/models.py`), not a
  bare `dict`, so CLAUDE.md's return-annotation rule holds and the output schema is real.
  `shaping.apply_fields()` does the raw JSON extraction as a flat dict, keyed by a
  collision-safe derivation of each `FIELDS` path (`"user.login"` → `user_login`,
  `"labels[].name"` → `labels`); every tool that is fundamentally a field-selection problem —
  `github_repo_overview`, `github_search`, `github_get_issue` (including comments),
  `github_list_commits`, `github_list_releases`, and the top-level fields of
  `github_get_pull_request` — calls it and builds its result model from the returned dict, not
  from the raw payload. `github_get_pull_request`'s per-file patch opt-in and
  `github_get_file`'s base64-decode/line-slice/byte-cap logic are left as direct payload
  access: they are behavioural (conditional inclusion, decoding, slicing), not a "pick these
  N fields" problem, so forcing them through the allowlist would be the DSL creep risk item 6
  warns against, not a reconciliation of it.
- **`code` search deferred (D4).** `github_search`'s `type` is `Literal["issues", "pulls",
  "repos"]`. Widening it later (adding `"code"`) is additive; ship without it for now.
- **Fail-fast on rate limit (D5).** Exhausting the core rate limit raises `ValueError` naming
  the `X-RateLimit-Reset` time in ISO 8601, rather than blocking and retrying.
- **`GH_API_TOKEN`, not `GITHUB_TOKEN`.** This spec's examples use `GITHUB_TOKEN`, but the
  implementation uses `GH_API_TOKEN` everywhere — env var, `.env.example`, Compose,
  `tests/conftest.py`. `GITHUB_TOKEN` is a name GitHub Actions auto-injects into every
  workflow's environment; using it here would risk the CI-provided token leaking into this
  server's GitHub calls, or the test suite silently picking one up depending on how a future
  CI job is wired. This is exactly the risk flagged in the "Risks / open questions" section
  above — `tests/conftest.py` hard-assigns `GH_API_TOKEN`, not `GITHUB_TOKEN`, so there is
  nothing named that a workflow would collide with.
- **Caching scope narrowed to `github_repo_overview` only.** Rather than the generic ~60s TTL
  short-circuit this spec describes at the `HttpClient` level, the TTL cache (60s, in-process,
  keyed by repo identifier) lives specifically in `demo_mcp/tools/github.py` and applies only
  to `github_repo_overview` — answering the "cache more aggressively" open question above in
  the affirmative, but scoped rather than blanket. `HttpClient` still does ETag/`If-None-Match`
  revalidation for every GitHub call, so a `304` never re-downloads a payload, but the other
  six tools otherwise hit the HTTP layer on every call.
