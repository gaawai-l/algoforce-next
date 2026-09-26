# Wheel dashboard — throwaway UI prototype

Question: should the personal Wheel portfolio prioritize assets (A), strategy cycles (B), or Greeks/risk (C)? All three share fictional data, on one route selected by `?variant=A|B|C`.

Run from the workspace root:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory prototypes/wheel-dashboard
```

Open http://127.0.0.1:8765/?variant=A. The standalone HTML also works by opening it directly. No dependencies, backend, persistence, real accounts, or trade operations. The whole directory is prototype-only; the design switcher is never intended for a production build.

Interactions: bottom variant switcher / left-right arrow keys; period buttons; strategy filter; position/cycle detail modal; risk scenario sliders and reset. State is surfaced in the footer and logged on variant changes. Native sliders retain arrow-key control.

Mock data: $128,190 NAV = $65,690 securities net value + $62,500 cash; $25,000 earmarked for NVDA puts, leaving $37,500 available. Stock quantities AAPL 100 and MSFT 100; short calls -1 each; NVDA short puts -2. Multiplier 100 throughout. Dollar Delta $54,990; daily Theta $23.50; Vega -$58 per one volatility percentage point. Gamma remains per underlying. Scenario uses local delta-gamma-vega approximation, not full repricing or margin modelling. NAV chart is illustrative, not a return calculation.

Status: awaiting user design feedback. This workspace has no Git repository or implementation issue. No branch/issue capture or production implementation has been performed; preserve these files until a winning direction is confirmed and a real repository is selected.

Browser verification: desktop 1440px and mobile 390px; all three variants fit the viewport after fixing risk-grid intrinsic sizing. Exercised URL/keyboard variant switching, strategy filtering, detail modal and Escape, risk slider keyboard control (−5% gives approximately −$3,255), and reset. No brokerage data or trades involved.

## Art direction update

All variants now use English copy and a dark cyberpunk theme. Typography: Orbitron 600/700 for brand and display headings; Inter 400/500/600 for interface copy; JetBrains Mono 400/500 for amounts, Greeks and telemetry labels. Fonts are served locally from `fonts/` (Google Fonts sources) through `fonts.css`; no runtime font CDN requests. Theme tokens and responsive overrides live in `cyberpunk.css`. Cyan is the primary signal; violet separates secondary exposure, amber flags attention, and rose indicates negative sensitivity. No flashing or glitch animations.
