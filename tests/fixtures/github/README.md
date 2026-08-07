# GitHub API fixtures

Trimmed JSON payloads shaped like real GitHub REST v3 responses (repo,
issue, pull request, commits, releases, search), used to drive
`httpx.MockTransport` in `tests/test_github_tools.py`. No test in this suite
performs a live call — see `test_no_live_network_calls`.

Each file keeps only the fields the shaping layer reads, plus a couple of
neighbours to prove `apply_fields`/`get_path` ignore fields they don't ask
for. If GitHub changes a field name used here, the fixture will not tell
you — it was hand-trimmed against the documented schema, not captured from
a live response, since this environment has no network access. Treat a
suite failure against real traffic as a signal to re-check the fixture
against `https://docs.github.com/en/rest`, not just the test.
