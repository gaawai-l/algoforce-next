# Wheelhouse test deployment

Deploy `codex/test-environment` through Coolify Docker Compose. Compose path: `/deploy/test/compose.yaml`; base directory `/`. Only `web` has a public HTTPS domain. Python, Wealthfolio and wallet-auth have internal ports only.

Authentication uses RainbowKit and Base SIWE. Basic Auth is disabled. The server permits only the configured wallet addresses and issues a 30-day HttpOnly/Secure session cookie. Visit `/login/?manage=1` to sign out. See [wallet authentication](../../services/wallet-auth/README.md).

Runtime configuration:

- `WF_SECRET_KEY`: independent Wealthfolio encryption key; preserve it across deployments.
- `WALLET_AUTH_ORIGIN`: exact public HTTPS origin. The Compose default is this test environment's existing domain; update it when the domain changes.
- `WALLET_AUTH_ADDRESSES`: comma-separated address allowlist. Defaults to the two Base addresses provided by the owner.
- `BASE_RPC_URL`: Base JSON-RPC endpoint for contract-wallet signature verification; defaults to Base's public endpoint.
- Optional build argument `VITE_WALLETCONNECT_PROJECT_ID`: real WalletConnect project ID for QR connections. Without it, RainbowKit discovers installed browser wallets.

`TEST_AUTH_USER` and `TEST_AUTH_HASH` are obsolete and ignored. `web-entrypoint.sh` is retained as historical material but is no longer copied into images.

The web image compiles pinned Wealthfolio source with this repository's overlay plus the independent login page. The Python image installs our analytics package, including DeMark. Coolify builds these and the wallet-auth image on the server; no custom registry is used.

Nginx authorizes the application and both API namespaces via wallet-auth. The login resources and `/healthz` are public. Anonymous APIs return 401 without a Basic challenge. Browser Origin checks remain active. Broker discovery/sync return 403 and the broker worker stays disabled.

Separate named volumes preserve test analytics, Wealthfolio data and hashed wallet sessions. Use public market data and fixtures only. Session data and credentials never enter Git. Production authentication, backup policy and brokerage connectivity remain separate decisions.

Anonymous acceptance: `python deploy/test/verify.py https://<test-domain>`. Full acceptance additionally accepts `--session-file /absolute/private/session.json`, containing `session_cookie` from a legitimate wallet session; the script never prints its value. Do not provide a wallet private key.
