"""Field selection and truncation helpers shared by every GitHub tool.

`FIELDS` is a small, declarative allowlist per resource type — dotted paths,
`[].name` list projection, and two transforms (`sha[:7]`, `|first_line`).
`apply_fields()` walks a raw GitHub payload against one of those allowlists
and returns a flat dict. This is the one place a tool's field selection is
declared; a tool body should never do inline JSON surgery (call the client,
apply a named allowlist, build the model, return).

`truncate_text()` is the other half of the design constraint this module
exists for: every truncation is signalled explicitly. Silent truncation is
the failure mode the whole tool surface is built to avoid.
"""

from __future__ import annotations

import json
from typing import Any

FIELDS: dict[str, tuple[str, ...]] = {
    "issue_summary": ("number", "title", "state", "user.login", "updated_at", "html_url"),
    "pull_summary": ("number", "title", "state", "user.login", "updated_at", "html_url"),
    "repo_summary": ("id", "full_name", "owner.login", "updated_at", "html_url"),
    "repo_detail": (
        "full_name",
        "description",
        "stargazers_count",
        "forks_count",
        "language",
        "default_branch",
        "open_issues_count",
        "pushed_at",
        "html_url",
    ),
    "issue_detail": (
        "number",
        "title",
        "state",
        "user.login",
        "body",
        "labels[].name",
        "assignees[].login",
        "updated_at",
        "html_url",
    ),
    "comment_detail": ("user.login", "created_at", "body"),
    "pull_detail": (
        "number",
        "title",
        "state",
        "user.login",
        "body",
        "base.ref",
        "head.ref",
        "additions",
        "deletions",
        "changed_files",
        "html_url",
    ),
    "commit_summary": (
        "sha[:7]",
        "commit.message|first_line",
        "commit.author.name",
        "commit.author.date",
        "html_url",
    ),
    "release_summary": ("tag_name", "name", "published_at", "prerelease", "body", "html_url"),
}


def get_path(payload: Any, path: str) -> Any:
    """Walk a dotted path through a nested dict/list payload.

    Supports plain dotted attribute access (`"user.login"`), a trailing
    slice on the final segment (`"sha[:7]"`), and `[]` list projection of a
    single field across every item (`"labels[].name"`). Missing keys at any
    point return `None` (or `[]` for a `[]` projection) rather than raising —
    GitHub payloads are optional-heavy and a shaping helper should not be the
    thing that turns a missing field into a 500.
    """
    if payload is None:
        return None

    if "[]" in path:
        head, _, tail = path.partition("[].")
        items = get_path(payload, head)
        if not isinstance(items, list):
            return []
        return [get_path(item, tail) for item in items]

    segment, _, rest = path.partition(".")
    slice_expr: str | None = None
    if "[" in segment and segment.endswith("]"):
        segment, _, slice_part = segment.partition("[")
        slice_expr = slice_part[:-1]

    if not isinstance(payload, dict):
        return None
    value = payload.get(segment)

    if slice_expr is not None and isinstance(value, str):
        start_s, _, end_s = slice_expr.partition(":")
        start = int(start_s) if start_s else None
        end = int(end_s) if end_s else None
        value = value[start:end]

    if rest:
        return get_path(value, rest)
    return value


def first_line(text: str | None) -> str:
    """Return only the first line of a possibly multi-line string."""
    if not text:
        return ""
    return text.splitlines()[0]


def _output_key(path: str) -> str:
    """Derive a flat dict key from a `FIELDS` path spec (transform already
    stripped by the caller).

    A `[]` list projection is keyed by its head segment — `"labels[].name"`
    becomes `"labels"`, holding the projected list. Everything else is every
    dotted segment joined with `_`, with any trailing `[slice]` stripped —
    `"user.login"` becomes `"user_login"`, `"sha[:7]"` becomes `"sha"`. This
    is what keeps `"user.login"` and `"assignees[].login"` from colliding on
    the same key in `issue_detail`.
    """
    if "[]" in path:
        return path.partition("[].")[0]
    segments = path.split(".")
    segments[-1] = segments[-1].split("[")[0]
    return "_".join(segments)


def apply_fields(payload: dict[str, Any], key: str) -> dict[str, Any]:
    """Extract the named allowlist of fields from a raw GitHub payload.

    Looks `key` up in `FIELDS`, walks each dotted path with `get_path`, and
    returns a flat dict keyed per `_output_key` (transforms and slice syntax
    stripped, dotted segments joined with `_`). This is the one place a
    tool's field selection is declared — a tool body should call this and
    build its result model from the returned dict, not walk the raw payload
    itself.
    """
    result: dict[str, Any] = {}
    for spec in FIELDS[key]:
        path, _, transform = spec.partition("|")
        value = get_path(payload, path)
        if transform == "first_line":
            value = first_line(value)
        result[_output_key(path)] = value
    return result


def truncate_text(text: str | None, limit: int) -> tuple[str, str | None]:
    """Truncate `text` to at most `limit` characters.

    Returns `(truncated_text, note)`. `note` is `None` when nothing was cut;
    otherwise it names how much was removed and how large the original was,
    so a caller can decide whether to ask for more.
    """
    if not text:
        return text or "", None
    if len(text) <= limit:
        return text, None
    cut = len(text) - limit
    note = f"truncated: {cut} of {len(text)} characters removed"
    return text[:limit], note


def approx_tokens(payload: Any) -> int:
    """Rough token-count estimate for logging/instrumentation, not billing:
    `len(json) // 4`."""
    return len(json.dumps(payload, default=str)) // 4
