# Wheelhouse test deployment

Deploy the `codex/test-environment` branch with Coolify Docker Compose. Compose path: `/deploy/test/compose.yaml`; base directory `/`. Only the `web` service receives a public HTTPS domain. Internal Python and Wealthfolio services have no published ports.

Runtime variables:
- `TEST_AUTH_USER`: test access username.
- `TEST_AUTH_HASH`: Apache APR1 password hash (not the plaintext password).
- `WF_SECRET_KEY`: independent 32-byte encryption key, encoded as base64 or a 32-character ASCII value.

Store these in Coolify environment variables; never commit their values. Docker Compose interpolation must preserve dollar signs in the APR1 hash. Keep test credentials separate from brokerage credentials.

The web image compiles the pinned upstream Wealthfolio source with this repository's overlay. Python is installed from the local source tree. The image context is an allowlist, so local databases, `.env`, virtual environments and broker SDK/runtime files are excluded. There is no OpenD in this stack; public broker discovery/sync paths return 403.

Nginx protects static content and both API namespaces with test authentication, verifies browser Origin against Host, proxies the APIs to their internal services and serves the React SPA. `/healthz` is public and contains only `ok`. HTTPS is terminated by Coolify. This is a shared single-user test workspace, not a multi-tenant deployment.

Named volumes keep test data across redeploys. Real statements and account captures must not be imported into this environment. Rotate test credentials in Coolify when sharing ends. Database backup/restore and production authentication are separate release requirements.
