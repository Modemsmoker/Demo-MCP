# Demo-MCP — Semantic Releases via GitHub Actions

## Context

The repo has no tags, no `.github/` directory, and no version recorded anywhere. Commits so far already follow Conventional Commits (`chore: add in baseline MCP functionality`), so the history is the right shape to drive versioning from.

Goal: pushing to `main` should determine the next version from the commit messages since the last tag, bump it, update a changelog, tag the commit, and publish a GitHub Release — with no manual version editing.

Remote: `https://github.com/Modemsmoker/Demo-MCP.git`.

## Approach

Use **python-semantic-release** (PSR) via its official GitHub Action. It's the natural fit for a Python repo — the alternatives (JS `semantic-release`, `release-please`) would drag in a Node toolchain or a release-PR workflow this project doesn't need.

PSR needs two things this repo currently lacks:

1. **A config home.** PSR reads `[tool.semantic_release]` from `pyproject.toml`. Adding one is worth it regardless — it also gives the project a declared name and version.
2. **A version to stamp.** `pyproject.toml`'s `project.version`, plus `__version__` in `server.py` so a running container can report what it is.

The project is not a distributable package and nothing gets published to PyPI, so no build step. Leave `build_command` unset; if the action still attempts a build on the first run, pass `build: false` to the action (equivalent to `--skip-build`).

## Changes

### 1. `pyproject.toml` (new)

```toml
[project]
name = "demo-mcp"
version = "0.0.0"          # PSR owns this from here on
description = "A demo Model Context Protocol server."
requires-python = ">=3.12"

[tool.semantic_release]
tag_format = "v{version}"
version_toml = ["pyproject.toml:project.version"]
version_variables = ["server.py:__version__"]
commit_message = "chore(release): v{version} [skip ci]"
allow_zero_version = true
major_on_zero = false

[tool.semantic_release.commit_parser_options]
minor_tags = ["feat"]
patch_tags = ["fix", "perf"]
parse_squash_commits = true
ignore_merge_commits = true

[tool.semantic_release.changelog.default_templates]
changelog_file = "CHANGELOG.md"
output_format = "md"
```

`allow_zero_version` with `major_on_zero = false` keeps the project in `0.x` until you deliberately cut `1.0.0` — a breaking change bumps the minor instead of jumping to `1.0.0`. `parse_squash_commits` matters if you merge PRs with squash, which is where conventional commits usually get mangled.

Leave `requirements.txt` as the runtime dependency source; the Dockerfile keeps using it. `pyproject.toml` here is metadata and tool config, not a packaging migration.

### 2. `server.py`

Add near the top, after the docstring:

```python
__version__ = "0.0.0"
```

PSR rewrites this line on every release, so it must stay a plain literal assignment. Pass it to the constructor if the SDK accepts a version argument — check `MCPServer`'s signature first and skip it if not; the module attribute alone satisfies PSR.

### 3. `.github/workflows/release.yml` (new)

```yaml
name: Release

on:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  release:
    runs-on: ubuntu-latest
    concurrency:
      group: ${{ github.workflow }}-release-${{ github.ref_name }}
      cancel-in-progress: false
    permissions:
      contents: write       # create the tag, commit, and release
      packages: write       # only if publishing the image (step 4)

    steps:
      - name: Checkout repository on release branch
        uses: actions/checkout@v4
        with:
          ref: ${{ github.ref_name }}
          fetch-depth: 0

      - name: Force release branch to workflow sha
        run: git reset --hard ${{ github.sha }}

      - name: Semantic version release
        id: release
        uses: python-semantic-release/python-semantic-release@v10
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          git_committer_name: "github-actions"
          git_committer_email: "actions@users.noreply.github.com"
```

Notes on the details, each of which is load-bearing:

- `fetch-depth: 0` — PSR walks history back to the last tag; a shallow clone can't see it.
- The `git reset --hard` guards against someone pushing to `main` while the job is in flight, which would otherwise release un-evaluated commits.
- `concurrency` with `cancel-in-progress: false` serializes releases instead of killing one mid-tag.
- Pin the action to a commit SHA rather than `@v10` once this is working — a floating major tag on an action that holds a write token is worth tightening.

### 4. Publish the Docker image (same job, optional but recommended)

Append to the same job — **not** a separate `on: release` workflow. Tags and releases created with `GITHUB_TOKEN` do not trigger other workflows, so a separate release-triggered workflow would silently never fire.

```yaml
      - name: Log in to GHCR
        if: steps.release.outputs.released == 'true'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        if: steps.release.outputs.released == 'true'
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/modemsmoker/demo-mcp:${{ steps.release.outputs.version }}
            ghcr.io/modemsmoker/demo-mcp:latest
```

Do not wrap the `if:` conditions in `${{ }}` — a wrapped string is always truthy, and every step would run on no-release pushes.

### 5. CI checks on pull requests (new, `.github/workflows/ci.yml`)

Releasing off `main` is only safe if `main` is known-good. A minimal PR workflow:

- `docker compose build` (or `docker build .`) — catches a broken image before it ships.
- A commit-message lint so non-conventional commits don't land and silently produce no release. `wagoid/commitlint-github-action` with `@commitlint/config-conventional` is the least-effort option. If the repo uses squash merges, lint the **PR title** instead, since that becomes the commit subject.

Keep this separate from the release workflow so a failing lint never blocks a release of already-merged code.

### 6. `README.md`

Add a short **Releasing** section: commits follow Conventional Commits; `feat:` → minor, `fix:`/`perf:` → patch, `!`/`BREAKING CHANGE:` → major (minor while in 0.x); merging to `main` releases automatically; the changelog lives in `CHANGELOG.md`.

## Verification

1. **Dry run locally first**, before pushing any workflow:
   ```bash
   pipx run python-semantic-release version --print
   ```
   With the current two commits and no tags, this should report the first version it would cut. `--noop` on the full command shows the whole plan without touching anything.
2. Merge a `fix:` commit to `main`. Expect: a `chore(release):` commit on `main`, a `vX.Y.Z` tag, a GitHub Release with generated notes, and `CHANGELOG.md` created.
3. Confirm `pyproject.toml` and `server.py` both show the new version in that release commit — proof `version_variables` is pointed at the right line.
4. Push a `docs:`-only commit. Expect **no** release and a clean, non-failing workflow run.
5. Push a commit with `feat!:` or a `BREAKING CHANGE:` footer. In 0.x with `major_on_zero = false`, expect a minor bump, not `1.0.0`.
6. If the image publish step is included: `docker pull ghcr.io/modemsmoker/demo-mcp:<version>` and run it against the same `.env` to confirm the published image works.

## Gotchas to expect

- **Branch protection.** If `main` requires PRs or status checks, the default `GITHUB_TOKEN` cannot push PSR's version commit and the job fails. Options: allow the GitHub Actions bot to bypass protection, or swap in a GitHub App token (`actions/create-github-app-token`) with bypass rights. A classic PAT works too but is the worst of the three for credential hygiene.
- **`[skip ci]` in the release commit message** prevents the release commit from re-triggering the workflow. Keep it in `commit_message`.
- **The first run has no baseline tag**, so PSR versions from the whole history. Sanity-check what step 1 prints before letting it run in CI.
- **Squash merges** discard individual commit subjects. Decide now whether the PR title or the commit list is the source of truth, and lint whichever one it is.
- `GITHUB_TOKEN`-created tags don't trigger workflows — hence keeping the image publish in the same job.
