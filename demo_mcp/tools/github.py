"""Seven read-only tools over the GitHub REST API.

Tools mirror user intent, not endpoints: a small number of compact,
explicitly-truncated summaries, plus separate tools to expand a single
identifier into detail on demand. See `docs/GITHUB_API.md` for the design
rationale. Every tool body stays short — call the client, apply a named
allowlist or model, return; JSON surgery belongs in `demo_mcp/shaping.py`,
not here.

Like `demo_mcp/tools/demo.py`, these are plain undecorated functions bound
to the server by `register()`, so this module never imports
`demo_mcp.server`.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Literal

from demo_mcp.clients.github import get_github_client
from demo_mcp.models import (
    CommitPage,
    CommitSummary,
    FileContent,
    IssueComment,
    IssueDetail,
    PullRequestDetail,
    PullRequestFile,
    ReleasePage,
    ReleaseSummary,
    RepoOverview,
    SearchPage,
    SearchResult,
)
from demo_mcp.shaping import apply_fields, approx_tokens, truncate_text

# The SDK renamed FastMCP -> MCPServer. Support both so this module works
# against either a pinned older release or the current one, without
# importing demo_mcp.server (see demo_mcp/tools/demo.py).
try:
    from mcp.server.mcpserver import Context, MCPServer
except ImportError:  # mcp < 1.13
    from mcp.server.fastmcp import Context
    from mcp.server.fastmcp import FastMCP as MCPServer

logger = logging.getLogger("demo-mcp.tools.github")

_SEARCH_LIMIT_CAP = 50
_SEARCH_FIELD_KEYS: dict[str, str] = {
    "issues": "issue_summary",
    "pulls": "pull_summary",
    "repos": "repo_summary",
}
_FILE_BYTE_CAP = 8 * 1024
_ISSUE_COMMENT_BODY_CAP = 1000
_ISSUE_BODY_CAP = 4000
_PR_BODY_CAP = 4000
_RELEASE_BODY_CAP = 500

# In-memory TTL cache for github_repo_overview only. It is the likely first
# call of every session, so a short cache pays for itself; the other six
# tools stay uncached per-request by design.
_REPO_OVERVIEW_CACHE: dict[str, tuple[float, RepoOverview]] = {}
_REPO_OVERVIEW_TTL_SECONDS = 60.0


def _split_repo(repo: str) -> tuple[str, str]:
    """Validate and split an `"owner/name"` identifier. Every GitHub tool
    takes `repo` as a single string, never separate `owner`/`name` args."""
    owner, sep, name = repo.partition("/")
    if not sep or not owner or not name:
        raise ValueError(f'repo must be "owner/name", got {repo!r}')
    return owner, name


def _log_tokens(tool_name: str, model: Any) -> None:
    logger.info("%s: ~%d tokens", tool_name, approx_tokens(model.model_dump()))


async def github_repo_overview(ctx: Context, repo: str) -> RepoOverview:
    """Get a compact overview of a GitHub repository: description, stars, forks,
    primary language, default branch, latest release, open issue and pull request
    counts, and when it was last pushed to.

    Use this first for any question about a repository — it answers in one call what
    would otherwise take four. `repo` is "owner/name", e.g. "pydantic/pydantic".
    Results are cached in-process for 60 seconds per repo.
    """
    _split_repo(repo)

    cached = _REPO_OVERVIEW_CACHE.get(repo)
    if cached is not None and (time.monotonic() - cached[0]) < _REPO_OVERVIEW_TTL_SECONDS:
        return cached[1]

    client = get_github_client()
    repo_payload = await client.get_repo(repo)
    fields = apply_fields(repo_payload, "repo_detail")

    releases, _, _ = await client.list_releases(repo, per_page=1, cursor=None)
    latest_fields = apply_fields(releases[0], "release_summary") if releases else None

    _, open_pr_total, _, _ = await client.search(
        "pulls", f"repo:{repo} is:pr is:open", per_page=1, cursor=None
    )
    combined_open = fields.get("open_issues_count", 0)
    open_issues = max(combined_open - open_pr_total, 0)

    result = RepoOverview(
        full_name=fields.get("full_name", repo),
        description=fields.get("description"),
        stars=fields.get("stargazers_count", 0),
        forks=fields.get("forks_count", 0),
        language=fields.get("language"),
        default_branch=fields.get("default_branch", "main"),
        latest_release_tag=latest_fields.get("tag_name") if latest_fields else None,
        latest_release_published_at=(latest_fields.get("published_at") if latest_fields else None),
        open_issues=open_issues,
        open_pull_requests=open_pr_total,
        last_pushed_at=fields.get("pushed_at", ""),
        html_url=fields.get("html_url", ""),
    )
    _REPO_OVERVIEW_CACHE[repo] = (time.monotonic(), result)
    _log_tokens("github_repo_overview", result)
    return result


async def github_search(
    ctx: Context,
    query: str,
    type: Literal["issues", "pulls", "repos"] = "issues",
    repo: str | None = None,
    state: Literal["open", "closed"] | None = None,
    author: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> SearchPage:
    """Search GitHub for issues, pull requests, or repositories.

    Returns a compact list — number, title, state, author, last-updated, url — suitable
    for choosing something to look at in detail. Follow up with github_get_issue or
    github_get_pull_request using a number from these results. `repo`, `state` and
    `author` narrow the search; `limit` is capped server-side at 50.
    """
    if repo is not None:
        _split_repo(repo)
    per_page = min(max(limit, 1), _SEARCH_LIMIT_CAP)

    qualifiers = [query]
    if type in ("issues", "pulls"):
        qualifiers.append("is:pr" if type == "pulls" else "is:issue")
    if repo:
        qualifiers.append(f"repo:{repo}")
    if state:
        qualifiers.append(f"state:{state}")
    if author:
        qualifiers.append(f"author:{author}")
    full_query = " ".join(qualifiers)

    client = get_github_client()
    items, _total_count, has_more, next_cursor = await client.search(
        type, full_query, per_page, cursor
    )

    field_key = _SEARCH_FIELD_KEYS[type]
    results = []
    for item in items:
        fields = apply_fields(item, field_key)
        if type == "repos":
            results.append(
                SearchResult(
                    number=fields.get("id", 0),
                    title=fields.get("full_name", ""),
                    state="",
                    author=fields.get("owner_login"),
                    updated_at=fields.get("updated_at", ""),
                    url=fields.get("html_url", ""),
                )
            )
        else:
            results.append(
                SearchResult(
                    number=fields.get("number", 0),
                    title=fields.get("title", ""),
                    state=fields.get("state", ""),
                    author=fields.get("user_login"),
                    updated_at=fields.get("updated_at", ""),
                    url=fields.get("html_url", ""),
                )
            )
    result = SearchPage(items=results, has_more=has_more, cursor=next_cursor)
    _log_tokens("github_search", result)
    return result


async def github_get_issue(
    ctx: Context,
    repo: str,
    number: int,
    include_comments: bool = False,
    comment_limit: int = 10,
) -> IssueDetail:
    """Get the full detail of a single GitHub issue: title, body, state, labels,
    assignees, and when it was last updated.

    Comments are excluded by default — a hot thread can be thousands of tokens.
    Pass include_comments=True to include up to comment_limit comments (newest
    first, each body truncated).
    """
    _split_repo(repo)
    client = get_github_client()
    payload = await client.get_issue(repo, number)
    fields = apply_fields(payload, "issue_detail")

    comments: list[IssueComment] = []
    if include_comments:
        capped_limit = min(max(comment_limit, 1), 50)
        raw_comments = await client.list_issue_comments(repo, number, capped_limit)
        raw_comments = sorted(raw_comments, key=lambda c: c.get("created_at", ""), reverse=True)
        for c in raw_comments[:capped_limit]:
            comment_fields = apply_fields(c, "comment_detail")
            body, note = truncate_text(comment_fields.get("body"), _ISSUE_COMMENT_BODY_CAP)
            comments.append(
                IssueComment(
                    author=comment_fields.get("user_login"),
                    created_at=comment_fields.get("created_at", ""),
                    body=body,
                    truncation_note=note,
                )
            )

    body, _ = truncate_text(fields.get("body"), _ISSUE_BODY_CAP)
    result = IssueDetail(
        number=fields.get("number", number),
        title=fields.get("title", ""),
        state=fields.get("state", ""),
        author=fields.get("user_login"),
        body=body,
        labels=fields.get("labels") or [],
        assignees=fields.get("assignees") or [],
        updated_at=fields.get("updated_at", ""),
        html_url=fields.get("html_url", ""),
        comments=comments,
    )
    _log_tokens("github_get_issue", result)
    return result


async def github_list_commits(
    ctx: Context,
    repo: str,
    ref: str | None = None,
    path: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> CommitPage:
    """List recent commits on a GitHub repository.

    Returns short sha, the first line only of each commit message, author, and
    date — not the full message body and not the changed file list. `ref` selects
    a branch, tag, or sha (defaults to the default branch); `path` filters to
    commits touching a given file or directory; `since` is an ISO 8601 timestamp.
    """
    _split_repo(repo)
    per_page = min(max(limit, 1), 100)
    client = get_github_client()
    items, has_more, cursor = await client.list_commits(repo, ref, path, since, per_page, None)

    summaries = []
    for c in items:
        fields = apply_fields(c, "commit_summary")
        summaries.append(
            CommitSummary(
                sha=fields.get("sha", ""),
                message=fields.get("commit_message", ""),
                author=fields.get("commit_author_name"),
                date=fields.get("commit_author_date", ""),
                html_url=fields.get("html_url", ""),
            )
        )
    result = CommitPage(items=summaries, has_more=has_more, cursor=cursor)
    _log_tokens("github_list_commits", result)
    return result


async def github_get_file(
    ctx: Context,
    repo: str,
    path: str,
    ref: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> FileContent:
    """Read a file's content from a GitHub repository.

    Content is capped at ~8 KB. If the file is larger than that (and no
    start_line/end_line slice was requested), the response is truncated and
    carries the total line count plus an explicit instruction to re-request
    with start_line/end_line to see the rest. Raises for directories and
    submodules rather than returning a confusing payload.
    """
    _split_repo(repo)
    client = get_github_client()
    payload = await client.get_contents(repo, path, ref)

    if isinstance(payload, list):
        raise ValueError(f"{path!r} is a directory, not a file")
    if payload.get("type") == "submodule":
        raise ValueError(f"{path!r} is a submodule, not a file")
    if payload.get("encoding") != "base64" or "content" not in payload:
        raise ValueError(f"cannot read {path!r}: not a plain file")

    raw = base64.b64decode(payload["content"])
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)

    if start_line is not None or end_line is not None:
        start = max((start_line or 1) - 1, 0)
        end = end_line if end_line is not None else total_lines
        text = "\n".join(lines[start:end])

    truncated = False
    note = None
    encoded = text.encode("utf-8")
    if len(encoded) > _FILE_BYTE_CAP:
        text = encoded[:_FILE_BYTE_CAP].decode("utf-8", errors="ignore")
        truncated = True
        note = (
            f"truncated at {_FILE_BYTE_CAP} bytes; file has {total_lines} lines total. "
            "Re-request with start_line/end_line to see the rest."
        )

    result = FileContent(
        path=path,
        content=text,
        total_lines=total_lines,
        truncated=truncated,
        truncation_note=note,
    )
    _log_tokens("github_get_file", result)
    return result


async def github_list_releases(ctx: Context, repo: str, limit: int = 10) -> ReleasePage:
    """List recent releases of a GitHub repository.

    Returns tag, name, published date, prerelease flag, and the release body
    truncated to ~500 characters (truncation is always signalled explicitly).
    """
    _split_repo(repo)
    per_page = min(max(limit, 1), 100)
    client = get_github_client()
    items, has_more, cursor = await client.list_releases(repo, per_page, None)

    summaries = []
    for r in items:
        fields = apply_fields(r, "release_summary")
        body, note = truncate_text(fields.get("body"), _RELEASE_BODY_CAP)
        summaries.append(
            ReleaseSummary(
                tag_name=fields.get("tag_name", ""),
                name=fields.get("name"),
                published_at=fields.get("published_at"),
                prerelease=fields.get("prerelease", False),
                body=body,
                truncation_note=note,
                html_url=fields.get("html_url", ""),
            )
        )
    result = ReleasePage(items=summaries, has_more=has_more, cursor=cursor)
    _log_tokens("github_list_releases", result)
    return result


async def github_get_pull_request(
    ctx: Context, repo: str, number: int, files: list[str] | None = None
) -> PullRequestDetail:
    """Get the full detail of a single GitHub pull request: title, body, state,
    branches, and a per-file summary (path, additions, deletions, status).

    Diff text is opt-in per file: pass a list of file paths in `files` to get
    the patch text for exactly those paths. With files=None (the default), no
    patch text is returned at all — a full diff can easily exceed a context
    window, so it is never returned unprompted.
    """
    _split_repo(repo)
    client = get_github_client()
    payload = await client.get_pull(repo, number)
    fields = apply_fields(payload, "pull_detail")
    raw_files = await client.list_pull_files(repo, number)

    # Per-file patch inclusion is opt-in behaviour, not field selection —
    # it stays bespoke rather than being forced into the FIELDS allowlist.
    wanted = set(files or [])
    file_models = [
        PullRequestFile(
            path=f.get("filename", ""),
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
            status=f.get("status", ""),
            patch=f.get("patch") if f.get("filename") in wanted else None,
        )
        for f in raw_files
    ]

    body, _ = truncate_text(fields.get("body"), _PR_BODY_CAP)
    result = PullRequestDetail(
        number=fields.get("number", number),
        title=fields.get("title", ""),
        state=fields.get("state", ""),
        author=fields.get("user_login"),
        body=body,
        base=fields.get("base_ref", ""),
        head=fields.get("head_ref", ""),
        additions=fields.get("additions", 0),
        deletions=fields.get("deletions", 0),
        changed_files=fields.get("changed_files", 0),
        html_url=fields.get("html_url", ""),
        files=file_models,
    )
    _log_tokens("github_get_pull_request", result)
    return result


def register(mcp: MCPServer) -> None:
    """Register the seven read-only GitHub tools."""
    mcp.tool()(github_repo_overview)
    mcp.tool()(github_search)
    mcp.tool()(github_get_issue)
    mcp.tool()(github_list_commits)
    mcp.tool()(github_get_file)
    mcp.tool()(github_list_releases)
    mcp.tool()(github_get_pull_request)
