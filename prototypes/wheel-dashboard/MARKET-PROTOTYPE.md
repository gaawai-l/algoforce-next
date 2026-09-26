# Market intelligence — throwaway UI prototype

Question: should market assessment start with a full chart plus inspector (A), parallel method evidence (B), or an evidence-based market brief (C)?

Open `http://127.0.0.1:8765/market-prototype.html?variant=A` using the existing prototype server. Same command as README; no new dependencies or production app.

References inspected on 2026-09-26:
- https://tradingsignal.pro/app?market=crypto&symbol=BTC%2FUSDT&timeframe=4h&tab=td9&opts=td%3Asequential
- https://tradingsignal.pro/app?market=crypto&symbol=BTC%2FUSDT&timeframe=4h&tab=levels
- https://tradingsignal.pro/app?market=crypto&symbol=BTC%2FUSDT&timeframe=4h&tab=fib&fib=retrace

User URLs at root showed a landing page; followed its public `/app` link to inspect the actual tools. First link label said indicators but href was TD9: TD Sequential is primary, with an Indicators subview in A to expose that distinction.

Observed reference concepts: setup/countdown/TDST/risk levels, multi-timeframe TD matrix; S/R price clusters with contributing methods and timeframes; manual A/B anchors for Fibonacci retracement. The prototype reinterprets these concepts within the existing English cyberpunk Wheelhouse shell, not a replica or live integration.

Mock boundaries: synthetic OHLC, static illustrative per-timeframe TD states and S/R method attribution. No validated DeMark algorithm, no real market feed, no external account, no AI-generated summary. Timeframe switching changes fixtures/context, not a full resampling engine. Fibonacci values are calculated as high - ratio × (high - low); input and chart-click anchors recompute values. Chart price history is the same illustrative shape across timeframes. Market brief is hand-authored, no probability or investment recommendation.

Interactions: A/B/C variants; symbol BTC/USDT, SPY, NVDA; 1h/4h/1d; method tabs; TD/Indicators subview; multi-timeframe row selection; S/R isolate/reset; Fibonacci input anchors and chart clicks; zoom; accessible OHLC table; explanatory dialog. URL stores layout, symbol, timeframe, and method. Other state is in memory and surfaced in footer.

This directory remains a throwaway prototype. No real app route exists yet, no Git repository/issue has been established, and user has not selected a winner; branch capture is pending that decision.

Browser verification: 1440px desktop and 390px mobile; A/B/C have no document overflow. Verified S1 isolation, Fibonacci anchors 80,000→90,000 producing 0.500=85,000 and 0.618=83,820, variant switching, symbol change resetting anchors, timeframe/URL updates, and no console errors.

## Confirmed navigation / information hierarchy

User rejected the parallel card layout and requested the reference site's method tabs. Current market page is now one workspace: shared left navigation → market/symbol → TD Sequential / Key levels / Fibonacci tabs → timeframe controls → large chart with only the selected method's detail inspector. Removed active layout switcher, parallel charts, summary cards, and briefing variant. Previous explorations are preserved in `market-layout-explorations.html`. Method tabs support arrow keys/Home/End; selection stays in the URL.
