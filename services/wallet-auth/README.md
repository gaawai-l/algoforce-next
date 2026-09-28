# Wallet authentication

Base (8453) SIWE authentication for the shared Wheelhouse workspace. RainbowKit connects browser wallets; the server enforces the configured address allowlist. A connection alone never authorizes requests.

- `npm ci`, `npm test`, `npm run build`.
- Runtime: `WALLET_AUTH_ORIGIN` (exact HTTPS origin), `WALLET_AUTH_ADDRESSES` (comma-separated addresses), `WALLET_AUTH_DATA_DIR` (default `/data`), optional `BASE_RPC_URL` and `PORT`.
- Optional build argument `VITE_WALLETCONNECT_PROJECT_ID` enables WalletConnect QR connections. Without a real ID, only injected/EIP-6963 browser wallets are offered.
- Challenge: 5 minutes, browser-bound HttpOnly cookie, consumed before signature verification.
- Session: 30 days, Secure/HttpOnly/SameSite=Lax cookie, SHA-256 token hash persisted atomically. Removing an address from the allowlist invalidates its sessions on service restart. This file store is for one service replica.
- `/login/?manage=1` shows the current session and sign-out action. Disconnecting the wallet extension alone does not revoke a server session; use Sign out.
- EOA verification is local. Contract signatures use viem's Base RPC verification; deployed and counterfactual wallet support depends on the wallet signature format and RPC availability. No real wallet signature is performed by automated tests.
- nginx must protect both API namespaces and the application with `auth_request`. Only nginx is published; the auth service is internal. Only nginx may supply `X-Real-IP` for rate limiting.
- Session files are secrets and must not enter source control or release records.
