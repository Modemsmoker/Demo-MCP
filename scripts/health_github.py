"""Exercise `github_repo_overview` against the running container.

Used by `make health-github`: a real MCP client round-trip (initialize, then
call the tool) proves the whole path — auth, transport, and the GitHub tool
itself — works end to end, not just that the port is open.
"""

import asyncio
import json
import os
import sys

from mcp import ClientSession

try:
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
except ImportError:  # mcp < 1.13 named it streamablehttp_client
    from mcp.client.streamable_http import create_mcp_http_client
    from mcp.client.streamable_http import streamablehttp_client as streamable_http_client


async def main() -> None:
    url = os.environ.get("MCP_PUBLIC_URL", "http://localhost:8000/mcp")
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    repo = sys.argv[1] if len(sys.argv) > 1 else "octocat/Hello-World"

    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("github_repo_overview", {"repo": repo})
                for block in result.content:
                    if hasattr(block, "text"):
                        print(block.text)
                    else:
                        print(json.dumps(block, default=str))


if __name__ == "__main__":
    asyncio.run(main())
