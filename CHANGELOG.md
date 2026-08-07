# CHANGELOG

<!-- version list -->

## v0.4.0 (2026-08-07)

### Features

- **metrics**: Version bump
  ([`9df9943`](https://github.com/Modemsmoker/Demo-MCP/commit/9df99435df5cce7a1520c651ad7eeda01995d716))


## v0.3.0 (2026-08-07)

### Features

- **tools**: Remove the add, server_time, save_note, and list_notes tools
  ([`a4fb529`](https://github.com/Modemsmoker/Demo-MCP/commit/a4fb52931e5d469aa6e7b7601e9379d572bffa6a))

### Breaking Changes

- **tools**: The add, server_time, save_note, and list_notes tools, the note://{title} resource, and
  the summarize_note prompt have been removed. whoami was kept as the sole in-band auth-verification
  tool. The server now exposes whoami plus the seven github_* tools. Clients calling any removed
  name will error.


## v0.2.0 (2026-08-07)


## v0.1.0 (2026-08-06)

- Initial Release
