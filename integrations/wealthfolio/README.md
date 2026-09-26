# Wealthfolio host extension

This directory contains the reproducible extension of the official Wealthfolio host. It is a host source extension, not a sandboxed addon. The addon network broker does not support loopback/private service connections.

- `upstream.json`: pinned source commit, official image digest and package manager.
- `patches/`: changes to upstream route, navigation and development build configuration.
- `overlay/`: new host files. Edit these, then run `make sync`.
- `openapi.json`: generated Python HTTP contract; refresh with `make contract`.

The upstream checkout lives in `.local/wealthfolio`; its package lock is installed without modification. `make sync` refuses unknown local edits to managed overlay files. Upstream AGPL-3.0 licensing applies to the modified host and must be preserved on distribution. The root MIT license does not relicense upstream code.
