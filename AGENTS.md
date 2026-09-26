# AlgoForceNext

## Purpose and current state

Build a personal, read-only investment workspace for a moomoo Singapore account: stock and option portfolio tracking, Wheel strategy accounting, portfolio Greeks, and market analysis. The prototype brand is **Wheelhouse**.

This workspace currently contains research and disposable HTML/CSS/JavaScript prototypes. It is not a deployed product or a Wealthfolio checkout. Wealthfolio is the preferred reuse candidate, but an addon, fork, or separate companion app has not been selected. Prefer extending existing software and data libraries over rebuilding them; validate integration seams before committing to an architecture.

## Working agreements

- Communicate with the user in Chinese. Write product UI, code, and code comments in English.
- Carry authorized local work through implementation and relevant verification. Resolve routine choices using established context; ask only when missing information materially changes scope, correctness, or an external commitment.
- Treat the latest explicit user direction as authoritative over earlier prototypes and skill suggestions, subject to system and developer instructions. A design correction should apply across the shared app shell, not just the visible page.
- Use relevant installed skills when their triggers match. Do not invoke Superpowers skills. If a skill would block authorized work, identify the exact instruction and explain why it applies rather than inventing an approval requirement.
- Preserve files and directories. Do not delete them or use destructive deletion commands. If removal is necessary, ask the user to do it manually. Preserve superseded prototypes as clearly labeled references.
- Report the concrete result, verification performed, and remaining limitations. Separate implemented behavior, observed external capabilities, and unverified assumptions.

## Brokerage boundary

- Account access is **read-only analytics**. Do not implement or expose order placement, modification, cancellation, trade unlocking, or automated execution as part of this project.
- Target the user's Singapore entity, `SecurityFirm.FUTUSG`, independently of the traded market. Select the actual account by `acc_id`; `REAL` means real account data, not permission to trade.
- Prefer official moomoo OpenD and SDK query interfaces. The user signs in through official OpenD; local readers connect to the loopback gateway. Keep login credentials out of the app, chat, repository, and logs. Do not request or store a trading password for a read-only workflow.
- Keep account collection separate from UI and analytics. A community MCP is optional and must be inspected for write tools, automatic unlocking, and account-region assumptions before adoption.
- Read orders, executions, positions, cash flows, and fees as distinct records. Orders are not fills; positions are snapshots. Make repeated imports idempotent and preserve broker identifiers, currencies, timestamps, and source provenance.
- Validate real account availability, historical coverage, and quote entitlements before claiming a working integration. Missing or stale data must remain visible rather than silently becoming zero or fabricated live values.
- Keep real statements, holdings, screenshots, and credentials out of public artifacts and demo fixtures. Account connection does not authorize publishing financial data or sending it to unrelated external services.

## Financial correctness

- A Wheel cycle links short puts, assignment into stock, covered calls, and eventual closure; rolls retain their transaction history. Allow explicit cycle assignment when grouping is ambiguous.
- Distinguish premiums received, realized P&L, unrealized P&L, and cash movement. Reconcile fees, assignment, exercise, and expiration without counting premiums twice. State the cost-basis method used.
- Preserve currency, timezone, contract identity, signed position quantity, and the actual contract multiplier. The prototype's multiplier of 100 is a fixture, not a universal production rule. Use appropriate decimal precision for accounting.
- Normalize provider Greeks before aggregation: sign, per-share versus per-contract units, multiplier, Theta time basis, and Vega per volatility percentage point. Display source and timestamp; distinguish quoted Greeks from model estimates.
- Aggregate share-equivalent Delta and Gamma **per underlying**. Portfolio dollar Delta is the sum of each underlying's net Delta × spot price, converted to a common currency. Label beta-weighted exposure separately. Theta is sensitivity, not guaranteed income.
- Label scenario assumptions and approximation limits. For production indicators, specify the actual calculation variant, input bars, market session, timezone, closed/forming-bar policy, and Fibonacci anchors; avoid look-ahead in historical views.

## UI decisions already made

- Use an English, dark cyberpunk interface: near-black surfaces, cyan primary accents, violet secondary accents, restrained glow, readable data, and visible keyboard focus. Use Orbitron for display headings, Inter for interface copy, and JetBrains Mono for financial values and telemetry.
- Use **one shared left sidebar** for Overview, Wheel cycles, Risk exposure, and Market intelligence. On small screens, collapse that same navigation. Do not add a competing top-level page navigation.
- Market intelligence follows the reference workflow: market/symbol selection → **TD Sequential / Key levels / Fibonacci tabs** → timeframe controls → one large chart with the selected method's details. Keep method tabs distinct from application navigation.
- Do not restore the rejected three-method card grid, parallel charts, or market briefing layout. Use cards only where the information benefits from grouping; they are not the default container for every section.
- Retain clear distinctions between Setup and Countdown, S/R clusters and their contributing methods/timeframes, and user-selected Fibonacci anchors. Do not present invented confluence scores as probabilities or fabricated summaries as live AI analysis.
- Prototypes must clearly identify simulated data and unimplemented integrations. Prototype artifacts are design references, not production-ready accounting or indicator engines.

## Workflows and completion

- **Prototype/UI changes:** reuse the shared shell and established styles; inspect the changed screen in a browser, exercise the affected controls, and check a narrow viewport. Deliver a runnable preview and state what remains simulated. A request for design review is complete at a usable, reviewable prototype.
- **Accounting, import, or risk changes:** use sanitized fixtures and independently check expected results for affected cases, such as partial fills, repeat imports, short options, assignment, fees, nonstandard multipliers, and cross-currency values. Reconcile against broker records when authorized data is available.
- **Production changes:** inspect the actual stack and task scripts when they exist; run the relevant checks. The current prototype has no package-based test suite. Avoid inventing commands or adding tests that merely duplicate presentation code. Broaden checks only when changes or failures justify it.
- **Research/integration choices:** follow claims to official docs, source, or releases and record the verification date. README claims, stale roadmaps, and a repository name alone do not establish support. Prefer existing libraries and official data over implementing pricing engines from scratch.

Run the current prototype from this workspace root:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory prototypes/wheel-dashboard
```

Portfolio: `http://127.0.0.1:8765/index.html?variant=A`.
Market: `http://127.0.0.1:8765/market-prototype.html?tab=td9`.
Reuse an existing running server when available.

## Read when relevant

- **Selecting the application base or a Wealthfolio extension:** [dashboard research](research/trading-dashboard-research-2026-09-26.md); use [option-specific candidates](research/options-dashboard-candidates.md) when comparing Wheel tools.
- **Connecting moomoo or evaluating a broker MCP:** [official access research](research/moomoo-access-research-2026-09-26.md) and [MCP source review](research/moomoo-mcp-candidates.md). Recheck version-sensitive claims before implementation.
- **Changing portfolio screens or demo calculations:** [prototype README](prototypes/wheel-dashboard/README.md). The active shared navigation is in `app-shell.js` and `app-shell.css` in that directory.
- **Changing market analysis screens:** [market prototype notes](prototypes/wheel-dashboard/MARKET-PROTOTYPE.md), especially its final confirmed information hierarchy. Earlier variants and `market-layout-explorations.html` are historical references, not accepted designs.
- **Revising these instructions:** [GPT-6 instruction-writing notes and official sources](research/gpt6-agents-md-guidance-2026-09-26.md). Keep stable project constraints here and task-specific detail in linked documents; do not require all documents to be read for every edit.
