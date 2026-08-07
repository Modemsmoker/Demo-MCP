"""HTTP client layer. `base.HttpClient` knows HTTP (auth headers, ETag
caching, retries); `github.GitHubClient` knows GitHub's endpoints. Neither
knows anything about MCP or shaping — that split is what makes a second API
addable later without touching this package's existing contents.
"""
