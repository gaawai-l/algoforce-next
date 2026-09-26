# Wheelhouse Market Strategy Specification

Status: implementation specification

Version: 1.0

Verified: 2026-09-26

Scope: read-only market intelligence for the Wheelhouse dashboard

## 1. Purpose

This specification defines the complete strategy logic required to reproduce the observed AlphaBTC workflow while allowing Wheelhouse to use a different interface and information architecture.

The strategy has four engines:

1. **Market Regime Engine**: classifies the market environment and selects the appropriate playbook.
2. **DeMark Exhaustion Engine**: tracks trend formation, confirmation, exhaustion, and invalidation across multiple timeframes.
3. **Breakout Engine**: detects non-DeMark directional breakouts and distinguishes durable trend expansion from false breaks or short-lived squeezes.
4. **Strategy Router**: combines regime, DeMark, breakout, volatility, key levels, and portfolio context into an analytical signal.

The dashboard is read-only. It may display analytical signals, risk levels, proposed option-leg adjustments, and scenario outcomes. It must not place, modify, cancel, or unlock trades.

## 2. Source Boundary

### 2.1 Confirmed source behavior

The following behavior was observed directly on 2026-09-26:

- AlphaBTC Regime v2.95.0 decision workflow.
- TradingSignal TD Sequential detail view for BTC/USDT across 5m, 15m, 1h, 4h, and 1D.
- TradingSignal explanations for Setup, Countdown, TDST, Risk Level, Sequential, Combo, and qualified 13.
- AlphaBTC short-term and long-term regime calibration.
- AlphaBTC BUY 1, BUY 2, SELL 1, SELL 2 presentation.
- AlphaBTC new-trend monitoring and option-strategy presentation.
- AlphaBTC chain-based cycle dashboard and its visible cost-basis regime inputs.

### 2.2 Replicated versus formalized logic

This specification uses two labels:

- **Replicated**: behavior or fields directly visible in the inspected source interfaces.
- **Wheelhouse-defined**: a deterministic rule introduced here because the source interface exposes an output but not the complete internal formula.

Wheelhouse must not describe Wheelhouse-defined scoring as the original site's proprietary formula.

### 2.3 Known source limitations

The source interfaces do not publicly expose:

- The exact numeric formula mapping raw DeMark events to weak, medium, or strong confidence.
- The exact formula mapping Setup and Countdown events to BUY 1/2 and SELL 1/2 in every edge case.
- The complete event-driven Regime Plus data feeds.
- The exact weighting formula for the chain-based composite Cycle Index.

Wheelhouse therefore reproduces the visible state machine and defines its own transparent scoring layer.

## 3. Strategy Architecture

```text
Closed market bars
  -> indicator calculations
  -> raw DeMark sequences
  -> raw breakout observations
  -> market regime classification
  -> multi-timeframe context
  -> signal qualification and invalidation
  -> strategy routing
  -> read-only analytical recommendation
```

Every final signal must remain traceable to its source bars, calculation variant, timeframe, observation time, and ruleset version.

### 3.1 Top-level decision route

The inspected workflow begins by deciding whether a reliable cycle/regime view is available.

#### Model-driven route

Use this route when cycle and regime inputs are fresh enough to classify:

```text
strategic cycle regime
  -> short-term and long-term DeMark regimes
  -> raw DeMark and breakout evidence
  -> strategy router
  -> analytical signal and portfolio implications
```

#### Evidence-only route

Use this route when no reliable cycle view is available or the user explicitly disables it:

```text
manual market view by horizon
  -> support/resistance levels
  -> implied/realized volatility view
  -> technical, on-chain, and institutional-flow evidence
  -> evidence summary without regime-adjusted confidence
```

Required manual horizons:

| Horizon | Default interpretation |
|---|---|
| Short term | Intraday to one week |
| Medium term | Weekly to monthly |
| Cycle | Quarterly and longer |

Each horizon can be bullish, neutral, or bearish. Manual views must retain author, timestamp, rationale, and expiry. They must not overwrite calculated model state.

### 3.2 Evidence-only route inputs

#### Key levels

- At least three resistance and three support levels may be recorded.
- Every level stores price, contributing method, contributing timeframe, confidence method, observation time, and invalidation condition.
- Confidence is a qualitative evidence grade unless statistically calibrated.
- S/R clusters must retain their contributing levels rather than only a merged number.

#### Volatility view

- Implied volatility direction: rising, falling, or stable.
- Realized volatility direction: rising, falling, or stable.
- When available, store current value, percentile, tenor, term-structure context, and observation time.
- Direction-only manual views must remain visibly different from measured live values.

#### Research evidence

- Technical structure and indicators.
- On-chain selling, profitability, and cost-basis evidence.
- Institutional or fund-flow evidence.

Research evidence supports a view but does not automatically become a trade signal. Each item must identify its source and freshness.

### 3.3 Route selection rules

```text
if required regime inputs are fresh and classification is valid:
    route = model_driven
else:
    route = evidence_only
```

The UI may show both routes for comparison, but the strategy decision must identify which route generated it. Missing regime data must not silently fall back to a fabricated neutral regime.

## 4. Timeframe Roles

The default crypto configuration uses:

| Timeframe | Role |
|---|---|
| 1D | Strategic market direction and late-cycle context |
| 4h | Primary swing direction and cross-day regime |
| 1h | Intraday regime and trade setup context |
| 15m | Confirmation and entry preparation |
| 5m | Execution timing and early failure detection |

The roles are defaults, not hard-coded assumptions. Other assets may use a different hierarchy, but the relative structure must remain: strategic, primary, setup, confirmation, execution.

## 5. Closed-Bar Policy

- Strategy state must be calculated from closed bars by default.
- A forming bar may be displayed separately but must not silently overwrite closed-bar state.
- Each snapshot must identify `closed_bar_time`, `forming_bar_time`, and `calculated_at`.
- Historical views must use information available at that historical timestamp and must not look ahead.
- The market session and timezone must be explicit for every provider and instrument.

## 6. DeMark Exhaustion Engine

### 6.1 Supported variants

The first production implementation must support **TD Sequential** because the inspected integration used `td:sequential`.

The data model must reserve a variant field for:

- `sequential`
- `combo`
- `combo_relaxed`
- `both`

Combo calculations must not be approximated using Sequential rules. They should remain unsupported until separately validated.

### 6.2 Direction terminology

The UI must distinguish the direction of the observed trend from the direction of the possible reversal:

| Raw structure | Observed move | Possible reversal |
|---|---|---|
| Buy Setup / Buy Countdown | Downward trend | Bullish reversal |
| Sell Setup / Sell Countdown | Upward trend | Bearish reversal |

The UI must not label a Buy Setup as an established uptrend.

### 6.3 Setup state machine

Replicated meaning:

- Setup 1-8: trend forming.
- Setup 9: trend established and potentially tiring.
- Setup 9 is a warning, not a completed reversal signal.

Implementation requirements:

```text
idle
  -> forming(1..8)
  -> established(9)
  -> countdown_active
  -> cancelled | qualified13
```

The engine must track buy-side and sell-side structures independently. A timeframe may contain multiple relevant historical sequences at the same time.

### 6.4 Setup calculation contract

The initial calculation adapter must use the validated provider's exact TD Sequential output when available.

If Wheelhouse calculates the common Sequential Setup locally, the variant must be declared explicitly:

- Buy Setup condition: close lower than the close four bars earlier.
- Sell Setup condition: close higher than the close four bars earlier.
- Setup requires nine consecutive qualifying bars.
- A price-flip requirement, cancellation behavior, perfection rules, equal-price handling, and recycling rules must be configured and tested as separate parameters rather than assumed.

The dashboard must show the selected variant and provider. Two providers with different variants must not be merged into one sequence.

### 6.5 Setup perfection

The model must reserve:

```text
setup_perfected: true | false | unknown
setup_perfected_at: timestamp | null
```

If the provider does not expose perfection, the value must remain `unknown`. Wheelhouse must not infer a perfected Setup from only a displayed 9.

### 6.6 TDST

Replicated meaning:

- TDST is derived from the completed Setup structure.
- It evaluates whether the Setup 9 structure remains intact during the subsequent phase.
- The inspected interface states that an entire candle crossing TDST, not merely a close crossing it, may cancel the active count under its chosen interpretation.

Required fields:

```text
tdst_price
tdst_side
tdst_source_sequence_id
tdst_breach_policy
tdst_breached_at
```

The breach policy must identify whether the provider uses full-bar, close-only, or another rule.

### 6.7 Countdown state machine

Replicated meaning:

- Countdown begins after an established Setup under Sequential.
- Countdown bars do not need to be consecutive.
- Countdown 1-12 measures progress toward exhaustion.
- Countdown 13 is an exhaustion candidate, not automatically a qualified signal.

Required states:

```text
inactive
active
cancelled
count13_unqualified
qualified13
invalidated
expired
```

### 6.8 Qualified 13

The dashboard must separate numeric count from qualification:

```text
countdown_count: 13
countdown_status: qualified13
```

Sequential qualification may require the 13th bar to satisfy the provider's comparison with Countdown bar 8. Store the referenced bar and threshold explicitly:

```text
countdown_bar8_close
countdown_13_qualification_threshold
countdown_13_qualified_at
```

If those details are unavailable, display `13 unverified`, not `qualified13`.

### 6.9 Risk Level

Replicated meaning:

- A qualified 13 produces a reversal thesis.
- Risk Level is the invalidation boundary for that thesis.
- Crossing the Risk Level in the invalidating direction cancels the reversal argument.

Required fields:

```text
risk_level
risk_level_direction
risk_level_breach_policy
risk_level_valid
risk_level_invalidated_at
```

Risk Level must not be displayed as active when its source 13 has already failed, expired, or been superseded.

### 6.10 Signal recency

Every sequence must store:

- Bars since Setup 9.
- Bars since latest qualified 13.
- Signal confirmation close.
- Confirmation timestamp.
- Historical qualified 13 count for the selected lookback.

Recency must be expressed in both bars and elapsed time. Elapsed time alone is misleading across timeframes.

### 6.11 Multiple simultaneous sequences

The engine must support all of these on one timeframe:

- An older qualified 13 that is still valid.
- A newer active Countdown in the same direction.
- A forming Setup in the opposite direction.
- A cancelled sequence retained for audit and chart reconstruction.

The implementation must never reduce a timeframe to one mutable `td_count` field.

## 7. DeMark Analytical Signal Mapping

### 7.1 Signal stages

Wheelhouse defines four transparent stages:

| Stage | Trigger | Meaning |
|---|---|---|
| Watch | Setup 7-8 | Trend has persisted; prepare monitoring |
| Warning | Setup 9 | Trend established and tiring |
| Armed | Countdown 10-12 | Exhaustion is approaching |
| Candidate | Qualified 13 | Reversal thesis may be acted on analytically |

### 7.2 Directional mapping

```text
Buy Setup 9          -> bullish reversal warning
Buy qualified13      -> bullish reversal candidate
Sell Setup 9         -> bearish reversal warning
Sell qualified13     -> bearish reversal candidate
```

To resemble the inspected source presentation:

```text
BUY_1  ~= valid Buy Setup 9 warning
BUY_2  ~= valid Buy qualified13 candidate
SELL_1 ~= valid Sell Setup 9 warning
SELL_2 ~= valid Sell qualified13 candidate
```

This mapping is Wheelhouse-defined because the source's complete internal mapping was not exposed. The UI must not claim it is the proprietary AlphaBTC formula.

### 7.3 Raw DeMark strength

Wheelhouse uses an explainable point system rather than fabricated probabilities:

| Condition | Points |
|---|---:|
| Setup 9 completed | 20 |
| Setup perfected | 5 |
| Countdown 10-12 | 10 |
| Qualified 13 | 35 |
| Risk Level remains valid | 15 |
| Opposite-direction Setup begins after 13 | 10 |
| Signal still within configured validity window | 5 |

Penalties:

| Condition | Points |
|---|---:|
| TDST cancellation | -35 |
| Risk Level invalidated | -100 and signal invalid |
| Signal expired | -100 and signal invalid |
| Strategic timeframe strongly opposes candidate | -20 |
| Breakout Engine confirms continuation against candidate | -30 |

The result is a **strength score**, not a probability or expected return.

Default labels:

| Score | Label |
|---:|---|
| 0-24 | Informational |
| 25-44 | Weak |
| 45-64 | Moderate |
| 65-79 | Strong |
| 80-100 | Very strong |

All point values are configurable and require historical validation before production use.

## 8. Multi-Timeframe DeMark Logic

### 8.1 No majority voting

The model must not count bullish versus bearish timeframes and choose the majority. Timeframes have different roles.

### 8.2 Default hierarchy

For an intraday bullish reversal candidate:

1. 1D must not contain an uninvalidated strong bearish continuation state.
2. 4h defines whether the move is a countertrend bounce or a primary reversal.
3. 1h should contain Buy Setup 9, Buy Countdown 10-13, or a valid Buy qualified13.
4. 15m should show an opposite-direction Setup forming or a reclaimed local structure.
5. 5m supplies timing and detects immediate failure.

The bearish case is symmetrical.

### 8.3 Alignment labels

```text
aligned
partially_aligned
conflicted
countertrend
```

The dashboard must show which timeframe creates the signal, which confirms it, and which conflicts with it.

### 8.4 Cross-timeframe adjustment

Wheelhouse-defined default adjustment:

| Context | Adjustment |
|---|---:|
| Primary and strategic timeframes align | +15 |
| Setup timeframe and confirmation timeframe align | +10 |
| Execution timeframe confirms structure break | +5 |
| One higher timeframe conflicts | -15 |
| Both higher timeframes conflict | -30 |

Again, this is a strength adjustment, not probability calibration.

## 9. Market Regime Engine

### 9.1 Meaning of regime

A regime is the current market operating state. It determines which strategy family is permitted, emphasized, reduced, or disabled.

Regime must remain separate from signal:

```text
regime = what kind of market is this?
signal = what event has occurred?
strategy = what analytical response is appropriate?
```

### 9.2 Three regime layers

#### Strategic cycle regime

The inspected chain dashboard visibly used:

- Spot price.
- True Market Mean cost basis.
- Short-Term Holder cost basis.
- 1 Day-1 Week holder cost basis.
- Depth: `ln(1D-1W cost basis / True Market Mean)`.
- Spread: `ln(Short-Term Holder cost basis / True Market Mean)`.
- Deadband corridors to reduce state flipping.
- Four percentile-like component scores: unrealized P&L, realized P&L, supply in profit/loss, and young-capital/long-capital ratio.

It exposed six states:

```text
advance
breakout
pressure
repair
breakdown
capitulation
```

The exact composite weighting was not exposed. Wheelhouse may display provider-supplied state or implement its own documented classifier, but must not claim an unknown weighting was reproduced.

#### Short-term DeMark regime

- Anchor timeframe: 1h.
- Applies to: 5m, 15m, 1h.

#### Long-term DeMark regime

- Anchor timeframe: 4h.
- Applies to: 4h, 1D.

### 9.3 Business regime labels

The inspected AlphaBTC interface compressed raw DeMark state into three business labels. Wheelhouse maps them deterministically:

#### Reversal Fade

Meaning: Setup 9 has warned of exhaustion, but qualified 13 has not confirmed a reversal.

```text
setup_count == 9
and qualified13 == false
and trend has begun to lose continuation quality
```

#### Breakout Decay

Meaning: an upward or downward breakout has completed Setup 9 and Countdown is progressing, so trend continuation remains possible but exhaustion risk is increasing.

```text
setup_count == 9
and countdown_status == active
and countdown_count between 1 and 12
```

#### Compression Reversal

Meaning: a prior directional move has reached qualified 13 and the opposite direction has begun to form.

```text
countdown_status == qualified13
and risk_level_valid == true
and opposite_setup_count >= 1
```

The product UI should use clear English labels and show the raw state beneath them. Business labels must never replace raw Setup and Countdown data.

### 9.4 Strategy permission matrix

| Regime | DeMark reversal | Breakout following | Grid/mean reversion | Short volatility |
|---|---|---|---|---|
| Compression/range | Allowed after confirmation | Armed, not triggered | Preferred | Allowed with risk limits |
| Breakout | Reduced | Preferred | Disabled or reduced | Reduced |
| Trend advance | Exit/tighten first; reverse only on confirmation | Preferred | Disabled | Reduced |
| Exhaustion | Preferred after qualified13 | Reduce new entries | Conditional | Conditional |
| Breakdown/capitulation | Bullish reversal watch | Short continuation until failure | Disabled initially | Avoid until volatility stabilizes |

## 10. Non-DeMark Breakout Engine

### 10.1 Purpose

DeMark is optimized for persistence and exhaustion. It must not be used as the only detector for a new directional breakout. The Breakout Engine independently evaluates price acceptance, volatility expansion, participation, and derivative positioning.

### 10.2 Breakout state machine

```text
neutral
  -> compression
  -> armed
  -> triggered
  -> confirmed
  -> trending
  -> exhausted | failed
```

### 10.3 Compression detection

Wheelhouse-defined default requirements; at least two must be true:

- ATR percentile over the configured lookback is at or below 25.
- Realized-volatility percentile is at or below 25.
- Bollinger Band Width percentile is at or below 25.
- High-low range has contracted for at least three evaluation bars.
- Volume is below its rolling median while price remains inside a defined range.

Defaults are configuration, not universal constants.

### 10.4 Structural breakout level

Eligible levels:

- Rolling N-bar high or low.
- Validated support/resistance cluster.
- Session or weekly high/low.
- User-selected structural level.
- Fibonacci anchor level when explicitly selected by the user.

The contributing method and timeframe must be retained. A confluence count must not be presented as a probability.

### 10.5 Trigger

Long trigger:

```text
closed_bar.close > breakout_level + breakout_buffer
```

Short trigger:

```text
closed_bar.close < breakout_level - breakout_buffer
```

Default `breakout_buffer`:

```text
max(min_tick_buffer, ATR * 0.10)
```

The trigger requires a close outside the level. A wick-only breach is not sufficient.

### 10.6 Confirmation families

To avoid double-counting correlated indicators, confirmation should require evidence from at least three independent families.

#### Price acceptance

- Two consecutive closes outside the level; or
- One close outside followed by a successful retest; or
- One wide-range close with close location in the outer 20% of the candle.

#### Volatility expansion

- ATR or realized volatility rises from the compression state.
- Candle true range exceeds its rolling median by a configurable factor.

#### Participation

- Volume or turnover z-score exceeds the configured threshold.
- Spot CVD agrees with the breakout direction when available.
- More than one venue confirms the move when multi-venue data is available.

#### Derivatives health

- Open interest behavior is classified rather than treated as universally bullish or bearish.
- Price and OI rising together suggests new directional positioning.
- Price rising while OI falls is classified as possible short covering.
- Price falling while OI falls is classified as possible long liquidation.
- Funding and basis must be checked for immediate crowding.

#### Higher-timeframe structure

- Primary timeframe closes outside its structural boundary.
- Strategic timeframe does not strongly oppose the direction.

### 10.7 Breakout confidence score

Wheelhouse-defined score:

| Evidence | Points |
|---|---:|
| Valid close outside structural level | 25 |
| Successful retest or second confirming close | 15 |
| Volatility expansion | 15 |
| Participation confirmation | 15 |
| Derivatives confirmation | 10 |
| Higher-timeframe alignment | 15 |
| Clean distance from opposing key level | 5 |

Penalties:

| Condition | Points |
|---|---:|
| Wick-only break | -25 |
| Close returns inside range | -40 |
| Immediate engulfing reversal | -30 |
| No participation expansion | -15 |
| Move appears liquidation-only | -10 |
| Active opposing qualified13 with valid Risk Level | -20 |
| Entry is already excessively extended from level | -15 |

Default interpretation:

| Score | State |
|---:|---|
| Below 40 | Unconfirmed |
| 40-59 | Triggered |
| 60-74 | Confirmed |
| 75-100 | Strongly confirmed |

### 10.8 Breakout failure

A confirmed breakout becomes failed when any configured failure rule occurs:

- Close returns into the prior range.
- Retest breaks through the opposite side of the breakout level.
- Participation disappears while price stalls.
- Higher-timeframe close rejects the breakout.
- Opposite DeMark reversal becomes qualified and price breaks the relevant local structure.

Failure must be recorded as a state transition, not by deleting the original signal.

## 11. Regime Plus Confirmation Layer

### 11.1 Standard versus advanced model

In the inspected product, “standard” and “advanced” refer to two layers around the same DeMark source data:

| Capability | Standard: DeMark Regime | Advanced: Regime Plus |
|---|---|---|
| Core question | Is the trend forming, established, or exhausted? | Will the warning resolve as reversal, durable breakout, or squeeze? |
| Primary inputs | OHLC, Setup, Countdown, TDST, Risk Level | Standard output plus divergence, participation/order-book, volatility, positioning, and event evidence |
| Main output | BUY/SELL warning or reversal candidate | Confirmation, rejection, squeeze classification, or continued scanning |
| Typical horizon | 5m through 1D sequence state | Faster confirmation after a warning or trigger |
| Failure mode | Reversing too early against a persistent trend | Treating a temporary squeeze or noisy feed as durable trend confirmation |

Regime Plus is not a different Setup/Countdown formula. It is a confirmation layer applied after a DeMark warning or breakout trigger.

The observed advanced interface used three stages:

```text
warning
confirmation_scan
high_frequency_monitoring
```

Wheelhouse implements this as a generic confirmation layer, not a separate DeMark calculation.

Supported completed categories:

- Market divergence.
- Order-book or participation fuel when a reliable feed is available.
- Volatility squeeze.
- Directional squeeze classification.

Event or sentiment modules without a verified data source must remain visibly unavailable. They must not be represented by simulated live states.

Possible squeeze classifications:

```text
durable_breakout
short_squeeze
long_liquidation
unconfirmed_expansion
```

These are classifications, not probabilities unless the model has been statistically calibrated.

## 12. Strategy Router

### 12.1 Inputs

- Strategic cycle regime.
- Short-term and long-term DeMark regimes.
- All active DeMark sequences.
- Breakout state and score.
- Key support/resistance levels.
- Volatility state.
- Market participation and derivatives data.
- Current read-only portfolio exposure when available.

### 12.2 Precedence rules

1. Invalid or stale data cannot produce an actionable analytical signal.
2. Risk Level invalidation overrides an older DeMark reversal candidate.
3. Breakout failure overrides a prior breakout confirmation.
4. Strategic and primary timeframes define whether a lower-timeframe signal is primary or countertrend.
5. Qualified 13 does not automatically reverse a confirmed breakout.
6. Setup 9 never overrides a confirmed higher-timeframe trend by itself.

### 12.3 Routing table

| Regime and evidence | Analytical output |
|---|---|
| Compression + breakout armed | Wait for directional trigger |
| Confirmed breakout + no opposing valid 13 | Trend-following signal |
| Confirmed breakout + opposing valid 13 | Reduced-strength trend signal; tighten invalidation monitoring |
| Qualified 13 + Risk Level valid + lower-timeframe reversal confirmation | Reversal candidate |
| Qualified 13 without confirmation | Watch/armed, not entry |
| Setup 9 only | Exhaustion warning |
| Conflicting primary and strategic timeframes | Countertrend or no-signal classification |
| Stale/missing inputs | Data unavailable |

### 12.4 Final analytical signal schema

```text
signal_id
symbol
strategy_family          # demark_reversal | breakout | range
direction                # long | short | neutral
stage                    # watch | warning | armed | candidate | confirmed | failed
strength_score           # 0..100, not probability
primary_timeframe
confirmation_timeframes
regime_context
trigger_price
invalidation_price
target_reference_levels
source_sequence_ids
evidence[]
conflicts[]
created_at
updated_at
expires_at
ruleset_version
data_freshness
```

### 12.5 Explanation contract

Every signal must answer:

1. What happened?
2. Which timeframe generated it?
3. Which timeframes confirmed or opposed it?
4. Which regime is active?
5. What invalidates the thesis?
6. Which data is stale or unavailable?
7. Is the signal primary-trend or countertrend?

The explanation must be generated from structured evidence. It must not fabricate live AI insight.

## 13. Option Strategy Translation

The inspected source translated market state into near/far Call and Put adjustments. Wheelhouse will present equivalent analytical actions without order execution.

Supported leg dimensions:

```text
option_type: call | put
tenor: near | far
action: hold | roll_up | roll_down | buy_back | cover | reduce
reason
source_signal_id
```

### 13.1 Directional translation

Default Wheelhouse-defined guidance:

| Market output | Short Call analytical action | Short Put analytical action |
|---|---|---|
| Bullish breakout | Roll Call up/reduce Call risk | Hold or roll Put up only within risk limits |
| Bearish breakout | Hold or roll Call down cautiously | Buy back/reduce Put risk |
| Bullish DeMark reversal | Reduce bearish exposure; avoid adding aggressive Calls | Consider Put risk only after confirmation |
| Bearish DeMark reversal | Reduce bullish exposure; avoid adding aggressive Puts | Consider Call risk only after confirmation |
| Range | Maintain range strategy subject to Greeks and margin | Maintain range strategy subject to Greeks and margin |

This table is analytical guidance. Portfolio Greeks, assignment risk, days to expiry, liquidity, transaction cost, and account constraints must be evaluated separately.

### 13.2 Backtest separation

Historical holding-period tables must remain separate from live signal strength.

- Historical win rate is not a current probability.
- Regime-adjusted and non-regime backtests must not be mixed.
- Sample period, sample size, fees, slippage, strike-selection rule, expiry rule, and contract multiplier must be visible.
- A signal may reference historical evidence but must not inherit a probability without calibration.

## 14. Data Model

### 14.1 Market bars

```text
market_bar
  provider
  symbol
  timeframe
  market_session
  timezone
  open_time
  close_time
  open
  high
  low
  close
  volume
  turnover
  is_closed
  fetched_at
```

### 14.2 DeMark sequence

```text
demark_sequence
  sequence_id
  provider
  variant
  ruleset_version
  symbol
  timeframe
  side
  setup_count
  setup_status
  setup_perfected
  setup_started_at
  setup_confirmed_at
  countdown_count
  countdown_status
  countdown_bar8_close
  countdown_13_threshold
  countdown_confirmed_at
  confirmation_close
  tdst_price
  tdst_breach_policy
  risk_level
  risk_level_breach_policy
  risk_level_valid
  next_count_condition
  bars_since_setup9
  bars_since_qualified13
  observed_at
```

### 14.3 Regime snapshot

```text
regime_snapshot
  regime_id
  symbol
  layer                    # strategic | short_term | long_term
  regime
  source_timeframe
  affected_timeframes[]
  source_sequence_ids[]
  component_values
  confidence_method
  observed_at
  expires_at
```

### 14.4 Breakout signal

```text
breakout_signal
  breakout_id
  symbol
  direction
  timeframe
  state
  structural_level
  structural_level_source
  breakout_buffer
  trigger_close
  retest_status
  volatility_evidence
  participation_evidence
  derivatives_evidence
  higher_timeframe_context
  score
  invalidation_price
  observed_at
```

### 14.5 Strategy decision

```text
strategy_decision
  decision_id
  signal_ids[]
  strategy_family
  direction
  stage
  strength_score
  trigger_price
  invalidation_price
  evidence[]
  conflicts[]
  explanation
  ruleset_version
  generated_at
```

### 14.6 Audit and provenance

```text
analysis_audit_log
  event_id
  entity_type
  entity_id
  action
  previous_value
  new_value
  actor                    # engine | user override
  reason
  timestamp
```

Manual overrides must never overwrite raw provider state. They create a new audited overlay.

## 15. Freshness and Degraded States

Each panel and signal must show:

- Observation time.
- Fetch time.
- Expected next refresh.
- Provider.
- Closed/forming bar status.
- Fresh, delayed, stale, unavailable, or simulated state.

Rules:

- Delayed or stale inputs reduce signal strength or prevent confirmation.
- Missing values remain missing; they must not become zero.
- A derived signal is no fresher than its stalest required input.
- Demo fixtures must be marked simulated in the UI.

## 16. UI Information Requirements

The final UI may differ visually from the reference, but it must preserve the strategy hierarchy:

```text
market and symbol
  -> method: TD Sequential | Key levels | Fibonacci
  -> timeframe
  -> primary chart
  -> current method details
```

For TD Sequential, the detail inspector must include:

- Setup and Countdown as separate progress indicators.
- Side and observed trend direction.
- Lifecycle status.
- TDST.
- Risk Level and validity.
- Countdown bar 8 qualification threshold.
- Next-bar condition.
- Multi-timeframe context.
- Regime adjustment.
- Source and freshness.

For the combined market-strategy view, include:

- Active strategic, short-term, and long-term regimes.
- DeMark reversal candidates.
- Breakout candidates.
- Conflicts and invalidations.
- Read-only option-leg implications.

Do not show a generated probability unless a calibrated probability model exists.

## 17. Acceptance Criteria

### 17.1 DeMark state

- Setup and Countdown cannot be conflated.
- Count 13 cannot be treated as qualified without qualification metadata.
- Active, cancelled, qualified, invalidated, and expired states remain distinguishable.
- More than one sequence can be retained per timeframe.
- Risk Level disappears or becomes explicitly inactive when its source signal is invalid.
- Closed and forming bars are visibly distinct.

### 17.2 Multi-timeframe logic

- A lower-timeframe candidate can be labelled countertrend rather than silently suppressed.
- Conflicting timeframes are displayed explicitly.
- Higher-timeframe conflict reduces strength according to a versioned rule.
- No majority-vote shortcut is used.

### 17.3 Breakout logic

- Wick-only breaks do not confirm.
- Price acceptance, volatility, and participation are separate evidence families.
- A return into the prior range records a failed breakout.
- Liquidation-driven moves can be classified separately from durable positioning.
- An opposing qualified13 is a penalty, not an automatic veto.

### 17.4 Read-only boundary

- No control sends, modifies, cancels, or unlocks an order.
- Proposed option actions remain analytical annotations.
- Broker positions and orders, when integrated, are read-only inputs.

### 17.5 Historical correctness

- Historical snapshots do not use future bars.
- Signal state transitions can be replayed.
- Provider, variant, parameters, and ruleset version are stored.
- Backtests include fees, slippage, sample metadata, and explicit holding rules.

## 18. Initial Implementation Order

### Phase 1: deterministic state display

- Provider-normalized OHLCV.
- TD Sequential provider adapter.
- Multi-sequence persistence.
- Setup, Countdown, TDST, Risk Level, and lifecycle UI.
- Data freshness and simulated-data labels.

### Phase 2: transparent analytical signals

- Wheelhouse DeMark strength score.
- Multi-timeframe alignment.
- Short-term and long-term regime classification.
- Structured explanations.

### Phase 3: non-DeMark breakout engine

- Compression detector.
- Structural breakout trigger.
- Price, volatility, and participation confirmation.
- Breakout failure transitions.

### Phase 4: portfolio-aware interpretation

- Read-only holdings and option exposure.
- Per-underlying Greeks.
- Strategy-to-position gap.
- Read-only roll, cover, reduce, or hold implications.

### Phase 5: validation

- Historical replay.
- Provider comparison.
- Out-of-sample evaluation.
- Regime-specific performance.
- Model drift and ruleset version comparison.

## 19. References

Verified on 2026-09-26:

- AlphaBTC Regime internal research interface: `https://alphabtc-regime.vercel.app/`
- AlphaBTC cycle dashboard: `https://alphabtc-regime.vercel.app/onchain/cycle-dashboard`
- TradingSignal TD Sequential view: `https://www.tradingsignal.pro/app?market=crypto&symbol=BTC%2FUSDT&timeframe=4h&tab=td9&opts=td%3Asequential`
- DeMARK TD Sequential overview: `https://demark.com/sequential-indicator/`
- DeMARK indicator list and simplified 9-13 description: `https://demark.com/indicators-list/`
- Existing research: `research/demark-completed-model-study-2026-09-26.md`
- Existing inventory: `research/alphabtc-regime-inventory-2026-09-26.md`

## 20. Final Design Principle

The implementation must preserve four independent questions:

1. **Regime**: what kind of market is operating?
2. **DeMark**: is the current move forming, established, or exhausted?
3. **Breakout**: has price been accepted outside a meaningful boundary with real participation?
4. **Risk**: what invalidates the analytical thesis, and what does it imply for existing exposure?

No single count, score, color, or label may replace these four questions.
