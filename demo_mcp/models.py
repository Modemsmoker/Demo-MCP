"""Pydantic result models for the GitHub tools.

CLAUDE.md rule 2 forbids a bare `dict` return annotation because MCP derives
each tool's output schema from it. `shaping.apply_fields()` still does the
raw JSON extraction as a flat dict; every tool wraps that dict in one of
these models before returning, so the allowlist stays declarative *and* the
client gets a real, described output schema (decision D3).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepoOverview(BaseModel):
    full_name: str = Field(description='"owner/name"')
    description: str | None = Field(description="Repository description, if set")
    stars: int = Field(description="Star count")
    forks: int = Field(description="Fork count")
    language: str | None = Field(description="Primary language GitHub detected")
    default_branch: str = Field(description="Default branch name")
    latest_release_tag: str | None = Field(
        description="Tag of the most recent release, or null if none has been published"
    )
    latest_release_published_at: str | None = Field(
        description="ISO 8601 publish date of the latest release, or null"
    )
    open_issues: int = Field(description="Open issues only — pull requests are excluded")
    open_pull_requests: int = Field(description="Open pull request count, counted separately")
    last_pushed_at: str = Field(description="ISO 8601 timestamp of the last push")
    html_url: str = Field(description="Web URL of the repository")


class SearchResult(BaseModel):
    number: int = Field(description="Issue/PR number, or repository id for repo search")
    title: str = Field(description="Title (or full_name for a repository result)")
    state: str = Field(description="open or closed; empty for repository results")
    author: str | None = Field(description="Login of the author or owner")
    updated_at: str = Field(description="ISO 8601 last-updated timestamp")
    url: str = Field(description="Web URL")


class SearchPage(BaseModel):
    items: list[SearchResult] = Field(description="Matching results, most relevant first")
    has_more: bool = Field(description="Whether more results exist beyond this page")
    cursor: str | None = Field(description="Opaque cursor; pass back in to fetch the next page")


class IssueComment(BaseModel):
    author: str | None = Field(description="Login of the commenter")
    created_at: str = Field(description="ISO 8601 timestamp")
    body: str = Field(description="Comment body, possibly truncated")
    truncation_note: str | None = Field(description="Present only if the body was cut")


class IssueDetail(BaseModel):
    number: int = Field(description="Issue number")
    title: str = Field(description="Issue title")
    state: str = Field(description="open or closed")
    author: str | None = Field(description="Login of the issue author")
    body: str | None = Field(description="Issue body, possibly truncated")
    labels: list[str] = Field(description="Label names")
    assignees: list[str] = Field(description="Assignee logins")
    updated_at: str = Field(description="ISO 8601 last-updated timestamp")
    html_url: str = Field(description="Web URL")
    comments: list[IssueComment] = Field(
        description="Empty unless include_comments=True was passed"
    )


class PullRequestFile(BaseModel):
    path: str = Field(description="File path in the repository")
    additions: int = Field(description="Lines added")
    deletions: int = Field(description="Lines deleted")
    status: str = Field(description="added, modified, removed, or renamed")
    patch: str | None = Field(
        default=None, description="Diff text — only populated for paths explicitly requested"
    )


class PullRequestDetail(BaseModel):
    number: int = Field(description="Pull request number")
    title: str = Field(description="Pull request title")
    state: str = Field(description="open, closed, or merged")
    author: str | None = Field(description="Login of the PR author")
    body: str | None = Field(description="PR description, possibly truncated")
    base: str = Field(description="Base branch name")
    head: str = Field(description="Head branch name")
    additions: int = Field(description="Total lines added across all files")
    deletions: int = Field(description="Total lines deleted across all files")
    changed_files: int = Field(description="Number of files changed")
    html_url: str = Field(description="Web URL")
    files: list[PullRequestFile] = Field(
        description="Per-file summary; patch text only for paths passed in `files`"
    )


class CommitSummary(BaseModel):
    sha: str = Field(description="Short (7-character) commit sha")
    message: str = Field(description="First line of the commit message only")
    author: str | None = Field(description="Commit author name")
    date: str = Field(description="ISO 8601 author date")
    html_url: str = Field(description="Web URL")


class CommitPage(BaseModel):
    items: list[CommitSummary] = Field(description="Commits, newest first")
    has_more: bool = Field(description="Whether more commits exist beyond this page")
    cursor: str | None = Field(description="Opaque cursor for the next page, if any")


class FileContent(BaseModel):
    path: str = Field(description="File path that was read")
    content: str = Field(description="File content, possibly truncated or line-sliced")
    total_lines: int = Field(description="Total line count of the full file")
    truncated: bool = Field(description="Whether the returned content was cut short")
    truncation_note: str | None = Field(description="Present only if content was truncated")


class ReleaseSummary(BaseModel):
    tag_name: str = Field(description="Release tag")
    name: str | None = Field(description="Release title, if set")
    published_at: str | None = Field(description="ISO 8601 publish date")
    prerelease: bool = Field(description="Whether this is marked as a prerelease")
    body: str | None = Field(description="Release notes, truncated to ~500 characters")
    truncation_note: str | None = Field(description="Present only if the body was truncated")
    html_url: str = Field(description="Web URL")


class ReleasePage(BaseModel):
    items: list[ReleaseSummary] = Field(description="Releases, newest first")
    has_more: bool = Field(description="Whether more releases exist beyond this page")
    cursor: str | None = Field(description="Opaque cursor for the next page, if any")
