"""Contract tests for the Demo-MCP server.

These assert on the *protocol surface* a client sees, not on internals. A tool
losing its description or an argument changing name is a breaking API change
for every MCP client, so those are the things worth pinning.
"""

import pytest

from demo_mcp import server
from demo_mcp.auth import StaticTokenVerifier
from demo_mcp.tools import demo

EXPECTED_TOOLS = {
    "whoami",
    "github_repo_overview",
    "github_search",
    "github_get_issue",
    "github_list_commits",
    "github_get_file",
    "github_list_releases",
    "github_get_pull_request",
}


def schema_of(tool):
    """The SDK renamed inputSchema -> input_schema. server.py supports both
    generations, so the tests have to as well."""
    return getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)


# --- Protocol surface --------------------------------------------------


async def test_all_tools_are_registered():
    names = {t.name for t in await server.mcp.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_every_tool_has_a_description():
    """Tool descriptions are the prompt the model reads. Empty ones are bugs."""
    for tool in await server.mcp.list_tools():
        assert tool.description, f"tool {tool.name!r} has no description"
        assert schema_of(tool) is not None


async def test_ctx_is_not_exposed_as_a_tool_argument():
    """Context is injected by the framework and must not leak into the schema.

    Pins the ctx-first, single-required-argument, no-optionals case.
    """
    tool = next(t for t in await server.mcp.list_tools() if t.name == "github_repo_overview")
    assert set(schema_of(tool).get("properties", {})) == {"repo"}


async def test_ctx_first_with_optional_args_is_not_exposed_either():
    """Pins the many-optional-arguments path of the SDK's schema derivation —
    a different code path than the single-required-argument case above.

    Note: no tool in this codebase currently puts ctx *last* (the shape
    save_note used to cover before it was removed); if a future tool does,
    nothing here will catch a ctx leak into its schema.
    """
    tool = next(t for t in await server.mcp.list_tools() if t.name == "github_search")
    assert set(schema_of(tool).get("properties", {})) == {
        "query",
        "type",
        "repo",
        "state",
        "author",
        "limit",
        "cursor",
    }


async def test_search_type_is_an_enum_in_the_schema():
    """Pins decision D4: `type` is a Literal, which must render as a JSON
    Schema enum of exactly the three supported search kinds."""
    tool = next(t for t in await server.mcp.list_tools() if t.name == "github_search")
    assert schema_of(tool)["properties"]["type"]["enum"] == ["issues", "pulls", "repos"]


async def test_repo_identifier_is_a_single_string():
    """No github_* tool exposes separate owner/name properties — repo is
    always a single "owner/name" string."""
    github_tools = [t for t in await server.mcp.list_tools() if t.name.startswith("github_")]
    assert github_tools
    for tool in github_tools:
        properties = set(schema_of(tool).get("properties", {}))
        assert "owner" not in properties
        assert "name" not in properties


async def test_no_prompts_are_registered():
    """The summarize_note prompt was removed along with the note resource;
    no prompt should be exposed."""
    assert {p.name for p in await server.mcp.list_prompts()} == set()


async def test_no_note_resource_is_registered():
    """note://{title} was a templated resource, so it was exposed via
    list_resource_templates(), not list_resources(). Assert neither
    accessor still advertises a note:// URI."""
    templates = await server.mcp.list_resource_templates()
    assert not any(t.uri_template.startswith("note://") for t in templates)
    resources = await server.mcp.list_resources()
    assert not any(str(r.uri).startswith("note://") for r in resources)


# --- Auth --------------------------------------------------------------


async def test_verifier_accepts_the_configured_token():
    verifier = StaticTokenVerifier("s3cret")
    token = await verifier.verify_token("s3cret")
    assert token is not None
    assert "demo" in token.scopes


@pytest.mark.parametrize("bad", ["", "wrong", "s3cre", "s3cret "])
async def test_verifier_rejects_everything_else(bad):
    assert await StaticTokenVerifier("s3cret").verify_token(bad) is None


# --- Tool behaviour ----------------------------------------------------


def test_whoami_reports_anonymous_outside_request_context():
    """Outside an active MCP request, the auth middleware has not set the
    access-token context var, so get_access_token() returns None and whoami
    degrades gracefully rather than raising."""
    assert demo.whoami() == "anonymous (auth disabled)"
