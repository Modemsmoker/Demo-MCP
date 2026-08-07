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
    "add",
    "server_time",
    "save_note",
    "list_notes",
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
    """Context is injected by the framework and must not leak into the schema."""
    tool = next(t for t in await server.mcp.list_tools() if t.name == "save_note")
    assert set(schema_of(tool).get("properties", {})) == {"title", "body"}


async def test_ctx_first_with_optional_args_is_not_exposed_either():
    """save_note only covers ctx-last-with-no-defaults. The GitHub tools put
    ctx first and have optional arguments, a different code path through the
    SDK's schema derivation — pin it separately."""
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


async def test_prompts_are_registered():
    assert {p.name for p in await server.mcp.list_prompts()} == {"summarize_note"}


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


def test_add():
    assert demo.add(2, 3) == 5
    assert demo.add(-1.5, 1.5) == 0


def test_server_time_is_iso_utc():
    from datetime import datetime

    parsed = datetime.fromisoformat(demo.server_time())
    assert parsed.tzinfo is not None


def test_notes_roundtrip():
    demo._NOTES.clear()
    demo._NOTES["alpha"] = "body"
    assert demo.list_notes() == ["alpha"]
    assert demo.read_note("alpha") == "body"


def test_read_note_rejects_unknown_title():
    demo._NOTES.clear()
    with pytest.raises(ValueError):
        demo.read_note("nope")
