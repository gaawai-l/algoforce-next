# AlgoForceNext

A personal, read-only investment workspace for stocks, options, Wheel strategy tracking, portfolio Greeks, and market analysis. The current prototype brand is **Wheelhouse**.

This repository currently contains research, interface prototypes, synthetic data embedded in those prototypes, and design/reference screenshots. No live brokerage connection or trade execution is implemented. The active engineering foundation now extends the Wealthfolio host and starts an independent local Python service.

## Wealthfolio + Python foundation

The active architecture uses the official Wealthfolio **v3.8.0** host with a small source extension and an independent Python service. The A0–A5 local architecture now includes versioned OHLCV storage, public spot/fixture adapters, durable jobs, schedules, snapshots and a shared live/replay calculation pipeline. Brokerage access and full strategy engines remain separate work.

Prerequisites: Git, Python 3.12+, Node.js 24, npm, and a running Docker engine with Compose.

```sh
make setup   # Pinned source, dependencies, extension and private local configuration
make dev     # Wealthfolio server + Python service + modified Wealthfolio frontend
make doctor  # Verify host, Python and the same-origin connection
make verify-a5 # Verify the running fixture/data/task chain and 1,000-bar benchmark
make check   # Python checks, host typechecking and extension contract tests
make build   # Build the modified Wealthfolio web frontend
```

Open <http://127.0.0.1:1420/market-intelligence>. Complete Wealthfolio's local onboarding on first launch; no brokerage credentials are needed. Ctrl+C stops this workspace's processes and container while preserving data. `make stop` stops only its Wealthfolio container.

The source pin, minimal patches and new host files are tracked in [`integrations/wealthfolio`](integrations/wealthfolio/README.md); the upstream checkout, runtime data and generated encryption key live under ignored `.local/`. Edit overlay files and run `make sync`. Architecture and milestones: [Wealthfolio + Python](docs/architecture/wealthfolio-python.md). Acceptance evidence: [A2–A5 results](docs/architecture/a2-a5-results.md).

Wealthfolio's AGPL-3.0 license applies to the modified host; the repository MIT license does not relicense upstream code. Native Tauri packaging and authenticated remote deployment are not implemented.

The earlier root `backend/` and `frontend/` directories are experimental companion-app work, preserved for reference. They are not used by `make dev`.

## Preview locally

From the repository root:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory prototypes/wheel-dashboard
```

- Portfolio overview: <http://127.0.0.1:8765/index.html?variant=A>
- Wheel cycles: <http://127.0.0.1:8765/index.html?variant=B>
- Portfolio risk: <http://127.0.0.1:8765/index.html?variant=C>
- Market intelligence: <http://127.0.0.1:8765/market-prototype.html?tab=td9>

All screens share a left sidebar and an English dark cyberpunk theme. Market intelligence uses TD Sequential, Key levels, and Fibonacci tabs, with one chart and the selected method's detail panel. Earlier layout explorations are retained for reference, not as accepted designs.

## Research and project guidance

- [Agent working agreements](AGENTS.md)
- [Trading dashboard / Wealthfolio research](research/trading-dashboard-research-2026-09-26.md)
- [Option-specific dashboard candidates](research/options-dashboard-candidates.md)
- [moomoo OpenD and read-only data access](research/moomoo-access-research-2026-09-26.md)
- [Community moomoo MCP source review](research/moomoo-mcp-candidates.md)
- [GPT-6 AGENTS.md writing guidance](research/gpt6-agents-md-guidance-2026-09-26.md)
- [AlphaBTC regime inventory](research/alphabtc-regime-inventory-2026-09-26.md)
- [DeMark model study](research/demark-completed-model-study-2026-09-26.md)
- [Portfolio prototype notes](prototypes/wheel-dashboard/README.md)
- [Market prototype notes and confirmed layout](prototypes/wheel-dashboard/MARKET-PROTOTYPE.md)

Research documents record dated observations of external products. Their claims, suggested features, and published signal statistics are not validated algorithms or commitments to implement them here; this project's scope remains read-only analysis.

## Data and assets

Prototype portfolio figures, candles, TD states, and S/R clusters are simulated. Fibonacci values are calculated from the selected demo anchors. Reference screenshots capture public website research; they are not personal account records. Other screenshots include earlier design iterations and may differ from the current UI.

Fonts are served locally, with their SIL Open Font License notices under [`prototypes/wheel-dashboard/fonts/`](prototypes/wheel-dashboard/fonts/). Third-party fonts and reference material retain their respective licenses and ownership; the repository MIT license does not relicense them.

Local browser logs, credentials, runtime databases, and private data directories are excluded by [`.gitignore`](.gitignore). No actual account statements or holdings are included in this initial project snapshot.
