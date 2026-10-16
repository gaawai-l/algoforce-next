# DeMark Regime 数据层实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 用本地 DeMark 引擎算出 AlphaBTC「Demark Regime」区块的全部数据，并在 1420 的 TD tab 上提供一张核对表。

**架构：**
- 新增三个模块：
  - `summary.py`：把 `DemarkResult` 投影成与 TradingSignal across 等价的主序列摘要；
  - `alphabtc.py`：照搬 AlphaBTC 的 9/13 状态、Regime 和置信度规则；
  - `context.py`：读取 5 个周期各自最近 499 根已收盘 K 线，现场计算并组装结果。
- 通过 `GET /market-context` 只读返回，不新建表。
- 前端新增一个可折叠核对区块，与 AlphaBTC 并排对照。

**技术栈：**
- 后端：Python 3.14、FastAPI、Pydantic v2、pytest、ruff、mypy strict；
- 前端：React、TanStack Query、Zod、Vitest；
- 契约：`make contract`，即 openapi-typescript。

**Spec：** [SPEC.md](SPEC.md)。依据：[AlphaBTC 规则核验](../../../research/alphabtc-regime-cycle-source-2026-09-28.md)、[主序列映射](../demark/ACROSS-PRIMARY-SEQUENCE.md)。

## 全局约束

- 代码、标识符和注释用英文；文档用中文；UI 文案走 `i18n.ts`，en 与 zh 两套键必须一致。
- 只读分析：不下单、不写账户；新接口只有 GET，不写库。
- 线上只用已收盘 K 线；未收盘那根只在核对脚本的回放中使用。
- 窗口固定为 `WINDOW = 499` 根已收盘 K 线。
- DeMark 配置固定为 v2：`ruleset_version="wheelhouse-sequential-2"`、`same_side_policy="retain_active"`、`perfection_policy="strict_at_nine"`。
- 数据缺失或过期时显示 unavailable，不给默认 Regime（不照搬 AlphaBTC 无数据时显示「突破减弱」的行为）。
- 只在用户要求时 commit；当前在 main 分支，而且工作区有大量未提交的 DeMark 改动。本计划**不含 commit 步骤**，每个任务结束于一个检查点。
- 后端测试命令在 `services/analytics` 下执行：`../../.venv-foundation/bin/python -m pytest …`。
- 前端测试需要先执行 `make sync`，把 overlay 复制到 `.local/wealthfolio`，再运行 `pnpm --filter frontend exec vitest run …`。`make check` 会跑全套。

## 评审重点（Review Focus）

以下是 spec 隐含、但最容易在使用中出问题的输入，每条都在对应任务里有测试：

1. **某周期从未刷新过（库里 0 根 K 线）：** 接口仍返回 200；该周期 `status=unavailable`，`summary`/`state` 为 null；以它为锚点的 Regime 为 `unavailable`。放在 Task 4。
2. **窗口内没有任何完整序列（刚开始积累数据，或断档后 continuity 全部 lost）：** `summarize` 返回 None，不能在 `seqs[-1]` 处抛出 IndexError。放在 Task 2。
3. **13 延期期间（`count13_unqualified`）：** `step` 为 12，`s13` 为 false，不能提前显示反转。放在 Task 2 和 Task 3。
4. **回放参数不完整或指向未来：** 只给 `market_at` 或 `knowledge_at` 之一、带未来时间、或不带时区时，返回 422。放在 Task 4。
5. **fixture 数据源、ETHUSDT：** 状态为 `simulated`，Regime 仍可用（spec §3.3 已写明，界面标「模拟」）；ETH 与 BTC 走同一路径，不报错。放在 Task 4。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `services/analytics/src/wheelhouse_service/indicators/demark/summary.py`（新建） | `DemarkResult` → `DemarkSummary`（TradingSignal across 等价）；`as_tradingsignal()` 转成 TS 字段名，供核对使用 |
| `services/analytics/src/wheelhouse_service/indicators/regime/__init__.py`（新建） | 包标记 |
| `services/analytics/src/wheelhouse_service/indicators/regime/alphabtc.py`（新建） | AlphaBTC 规则：`derive_state`、`regime_of`、`signals`、`new_trend`、`adjust` |
| `services/analytics/src/wheelhouse_service/context.py`（新建） | 读取窗口、判断新鲜度、组装 `MarketContext` |
| `services/analytics/src/wheelhouse_service/http.py`（修改） | 新增 `GET /market-context`，capabilities 增加 `market_context` |
| `services/analytics/tests/regime/regime_fixture.py`（新建） | 加载黄金样本，构造回放 Dataset |
| `services/analytics/tests/regime/fixtures/alphabtc-td9-2026-09-27T162832Z.json`（新建） | 5 个周期各 500 根 K 线，外加 TS 的 across/risk |
| `services/analytics/tests/regime/test_regime_summary.py`（新建） | 摘要与 TS 的一致性，以及边界情况 |
| `services/analytics/tests/regime/test_regime_rules.py`（新建） | AlphaBTC 规则表 |
| `services/analytics/tests/regime/test_regime_context.py`（新建） | 窗口、新鲜度、组装、HTTP |
| `integrations/wealthfolio/openapi.json`、`…/wheelhouse/api-schema.d.ts`（由 `make contract` 重新生成） | 契约 |
| `…/wheelhouse/regime-contract.ts` 与 `.test.ts`（新建） | Zod schema 与类型 |
| `…/wheelhouse/client.ts`（修改） | `getMarketContext()` |
| `…/wheelhouse/regime-board.ts` 与 `.test.ts`（新建） | 看板映射、档位选择、时长格式 |
| `…/wheelhouse/regime-check.tsx` 与 `.test.tsx`（新建） | 核对区块组件 |
| `…/wheelhouse/i18n.ts`、`market.css`、`market-page.tsx`（修改） | 文案、样式、挂载位置 |
| `scripts/verification/compare_alphabtc_context.py`（新建） | 用新快照回放对照 |
| `docs/features/demark-regime/PARITY-LOG.md`（新建） | 每次对照的结果记录 |
| `prototypes/wheel-dashboard/MARKET-STRATEGY-SPEC.md`（修改 §9.3） | 改为指向 AlphaBTC 实际规则 |

`…/wheelhouse/` 指 `integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/`。

---

### Task 1：黄金样本

**文件：**
- 新建：`services/analytics/tests/regime/fixtures/alphabtc-td9-2026-09-27T162832Z.json`
- 新建：`services/analytics/tests/regime/regime_fixture.py`

**接口：**
- 产出：
  - `load_fixture() -> dict`
  - `replay_dataset(tf: str) -> tuple[Dataset, datetime]`：返回 500 根 K 线（最后一根是重建的未收盘 bar，这里按已收盘处理）和 TS 的 asOf，即最后一根的开盘时间。
  - `V2: DemarkConfig`
  - `TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")`

- [ ] **Step 1：生成样本文件（一次性）**

输入来自研究阶段的临时目录：
- `/private/tmp/claude-501/-Users-gary-code-AlgoForceNext/766fdf7e-1bf6-49dd-af42-f417d07fde53/scratchpad/across/`（`binance_raw.json`、`ts_snapshot.json`、`harness.py`）
- 15m 的前 499 根使用仓库中的 TradingSignal 导出行情，与研究时一致。

在仓库根目录运行：

```bash
.venv-foundation/bin/python - <<'EOF'
import json, os, sys
SCR = "/private/tmp/claude-501/-Users-gary-code-AlgoForceNext/766fdf7e-1bf6-49dd-af42-f417d07fde53/scratchpad/across"
for name in ("harness.py", "binance_raw.json", "ts_snapshot.json"):
    if not os.path.exists(f"{SCR}/{name}"):
        sys.exit(f"missing research input {SCR}/{name}; rerun the across research before Task 1")
sys.path.insert(0, SCR)
sys.path.insert(0, "services/analytics/src")
from harness import AS_OF, FETCH, rows_for

FIX = json.load(open("services/analytics/tests/demark/fixtures/tradingsignal-btcusdt-15m-candles.json"))["candles"]
TS = json.load(open(f"{SCR}/ts_snapshot.json"))

def rows(tf):
    if tf == "15m":
        head = [[x["t"] * 1000, str(x["o"]), str(x["h"]), str(x["l"]), str(x["c"])] for x in FIX[:-1]]
        tail = [r for r in rows_for("15m", "forming") if r[0] // 1000 >= 1790523000]
        return head + tail
    return rows_for(tf, "forming")

out = {
    "captured_at": FETCH,
    "note": "AlphaBTC /api/td9 (TradingSignal across) at 2026-09-27T16:28:32Z. "
            "Last bar of each timeframe is the forming bar rebuilt from Binance 1m/1s klines. "
            "15m bars before 15:30 UTC come from the user's TradingSignal export.",
    "timeframes": {},
}
for tf in ("5m", "15m", "1h", "4h", "1d"):
    rs = rows(tf)[-500:]
    assert len(rs) == 500 and rs[-1][0] // 1000 == AS_OF[tf], tf
    out["timeframes"][tf] = {
        "as_of": AS_OF[tf],
        "bars": [[r[0] // 1000, str(r[1]), str(r[2]), str(r[3]), str(r[4])] for r in rs],
        "across": TS["across"][tf],
        "risk": TS["risk"][tf],
    }
dest = "services/analytics/tests/regime/fixtures/alphabtc-td9-2026-09-27T162832Z.json"
import os; os.makedirs(os.path.dirname(dest), exist_ok=True)
json.dump(out, open(dest, "w"), indent=1)
print("wrote", dest)
EOF
```

预期输出：`wrote services/analytics/tests/regime/fixtures/alphabtc-td9-2026-09-27T162832Z.json`。

然后检查：
- 文件里没有 `read`、AI 解读或任何账户字段：`grep -c '"read"' <file>` 应为 0。
- 文件大小在 1 MB 以内。

- [ ] **Step 2：写加载器 `regime_fixture.py`**

```python
"""Replay inputs for the 2026-09-27T16:28:32Z AlphaBTC / TradingSignal snapshot."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wheelhouse_service.indicators.demark import DemarkConfig
from wheelhouse_service.market import DURATIONS, Bar, Dataset, StoredBar, Stream

FIXTURE = Path(__file__).parent / "fixtures" / "alphabtc-td9-2026-09-27T162832Z.json"
TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
V2 = DemarkConfig(
    ruleset_version="wheelhouse-sequential-2",
    same_side_policy="retain_active",
    perfection_policy="strict_at_nine",
)


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def replay_dataset(tf: str) -> tuple[Dataset, datetime]:
    """All 500 bars as closed input, matching how TradingSignal counted its forming bar."""
    entry = load_fixture()["timeframes"][tf]
    step = timedelta(seconds=DURATIONS[tf])
    bars = []
    for t, o, h, low, c in entry["bars"]:
        opened = datetime.fromtimestamp(t, UTC)
        bars.append(
            StoredBar(
                revision_id=f"fx:{tf}:{t}",
                revision=1,
                fetched_at=opened + step,
                bar=Bar(
                    open_time=opened,
                    close_time=opened + step,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    is_closed=True,
                ),
            )
        )
    end = bars[-1].bar.close_time
    stream = Stream(source="binance", symbol="BTCUSDT", timeframe=tf)  # type: ignore[arg-type]
    dataset = Dataset(
        stream=stream, market_at=end, knowledge_at=end, fetched_at=end, bars=bars, forming=[]
    )
    return dataset, datetime.fromtimestamp(entry["as_of"], UTC)
```

- [ ] **Step 3：确认可以加载**

在 `services/analytics` 下运行：

```bash
../../.venv-foundation/bin/python -c "import sys; sys.path[:0]=['tests/regime','src']; from regime_fixture import *; d,a=replay_dataset('1h'); print(len(d.bars), a)"
```

预期：`500 2026-09-27 16:00:00+00:00`

检查点：样本在 JSON 与 Python 两侧都能正确读出。

---

### Task 2：主序列摘要 `summary.py`

**文件：**
- 新建：`services/analytics/src/wheelhouse_service/indicators/demark/summary.py`
- 测试：`services/analytics/tests/regime/test_regime_summary.py`

**接口：**
- 使用：
  - `DemarkResult`、`DemarkSequence`、`Model`、`Side`（来自 `indicators/demark/models.py`）
  - `text(value: Decimal) -> str`（来自 `indicators/demark/engine.py`）
  - `Bar`（来自 `market.py`）
- 产出：
  - `summarize(result: DemarkResult, bars: list[Bar], as_of: datetime) -> DemarkSummary | None`
  - `as_tradingsignal(summary: DemarkSummary) -> tuple[dict[str, Any], dict[str, Any]]`，返回 `(across, risk)`，字段名与 TS 相同。
  - 模型：`DemarkSummary`、`Round`、`SignalRef`、`PrevCountdown`、`SecondSetup`、`SetupRun`、`NextBarNeeds`、`SummaryRisk`。
  - 类型别名：`Trend = Literal["up", "down"]`。

- [ ] **Step 1：写失败的测试**

```python
"""TradingSignal-equivalent primary-sequence summary, pinned to the 2026-09-27 snapshot."""

from decimal import Decimal

import pytest
from regime_fixture import TIMEFRAMES, V2, load_fixture, replay_dataset
from test_sequential import BUY, dataset

from wheelhouse_service.indicators.demark import evaluate_demark
from wheelhouse_service.indicators.demark.summary import as_tradingsignal, summarize

STRUCTURAL = (
    "side", "regime", "phase", "step", "target", "setupStep", "countdownStep",
    "barsSinceQualified13", "lastSignal", "prev", "second", "rounds",
)
# 5m's previous SELL 13 sits 2-7 USDT from its thresholds; the feeds disagree there.
FEED_SENSITIVE = {"5m": {"prev", "barsSinceQualified13"}}
PRICES = ("riskLevel", "risk9", "setupClose", "close13", "tdst")


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "strong"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _replay(tf):
    data, as_of = replay_dataset(tf)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], as_of)
    assert summary is not None
    return as_tradingsignal(summary)


@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_structure_matches_tradingsignal(tf):
    expected = load_fixture()["timeframes"][tf]
    across, risk = _replay(tf)
    for key in STRUCTURAL:
        if key in FEED_SENSITIVE.get(tf, set()):
            continue
        assert _strip(across.get(key)) == _strip(expected["across"].get(key)), key
    for key in ("provisional", "risk13Ts", "risk9Ts", "side", "setupRun"):
        assert risk[key] == expected["risk"][key], key
    assert risk["nextBarNeeds"]["direction"] == expected["risk"]["nextBarNeeds"]["direction"]


@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_prices_differ_only_by_feed(tf):
    expected = load_fixture()["timeframes"][tf]["risk"]
    _, risk = _replay(tf)
    for key in PRICES:
        assert (risk[key] is None) == (expected[key] is None), key
        if risk[key] is not None:
            # Binance vs TradingSignal's feed: largest observed gap is 64.54 (4h risk9).
            assert abs(Decimal(risk[key]) - Decimal(str(expected[key]))) <= 70, key


def test_15m_prices_are_exact_on_tradingsignal_candles():
    expected = load_fixture()["timeframes"]["15m"]["risk"]
    _, risk = _replay("15m")
    for key in ("risk9", "setupClose", "riskLevel", "tdst"):
        assert abs(Decimal(risk[key]) - Decimal(str(expected[key]))) < Decimal("1e-6"), key


def test_5m_previous_thirteen_is_the_locally_observed_one():
    across, _ = _replay("5m")
    assert across["prev"] == {"side": "SELL", "countdown": 13, "qualified": True, "barsAgo": 35}


def test_no_observed_sequence_returns_none():
    data = dataset([100, 101, 102])
    result = evaluate_demark(data, V2)
    assert summarize(result, [b.bar for b in data.bars], data.market_at) is None


def test_deferred_thirteen_reports_twelve_in_countdown():
    closes = BUY + [90, 89, 88, 87, 86, 85, 84, 94, 94, 93, 92, 91, 90, 89]
    data = dataset(closes)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], data.market_at)
    assert summary is not None
    assert summary.phase == "countdown"
    assert summary.step == 12
    assert summary.countdown_step == 12
```

`test_sequential` 位于 `tests/demark/`。pytest 默认的 `prepend` 导入模式只把当前测试文件所在目录加入 `sys.path`，因此需要在同一目录新建 `tests/regime/conftest.py`，内容如下：

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demark"))
```

- [ ] **Step 2：确认测试失败**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m pytest tests/regime/test_regime_summary.py -q`

预期：`ModuleNotFoundError: No module named 'wheelhouse_service.indicators.demark.summary'`

- [ ] **Step 3：实现 `summary.py`**

```python
"""Primary-sequence summary equivalent to TradingSignal's multi-timeframe `across` view.

Mapping evidence: docs/features/demark/ACROSS-PRIMARY-SEQUENCE.md (verified 2026-09-28).
Open questions keep their documented defaults: rounds rule B, deferred 13 stays at 12,
setup-phase lastSignal falls back to the previous countdown, `strong` is not produced.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from ...market import Bar
from .engine import text
from .models import DemarkResult, DemarkSequence, Model, Side

Trend = Literal["up", "down"]
TREND: dict[str, Trend] = {"buy": "down", "sell": "up"}
ACTIVE = ("active", "count13_unqualified")
ENDED = ("qualified13", "cancelled", "recycled")


class Round(Model):
    side: Side
    trend: Trend
    setup: int
    countdown: int
    setup9_at: datetime | None
    qualified13_at: datetime | None


class SignalRef(Model):
    kind: Literal[9, 13]
    at: datetime
    side: Side


class PrevCountdown(Model):
    side: Side
    countdown: int
    qualified: bool
    bars_ago: int


class SecondSetup(Model):
    side: Side
    trend: Trend
    step: int
    setup9_at: datetime | None


class SetupRun(Model):
    start: datetime
    side: Side
    count: int
    active: bool
    completed: bool


class NextBarNeeds(Model):
    direction: Literal["above", "below"]
    price: str


class SummaryRisk(Model):
    risk9: str | None
    risk9_at: datetime | None
    setup_close: str | None
    risk_level: str | None
    risk13_at: datetime | None
    provisional: bool
    close13: str | None
    tdst: str | None
    next_bar_needs: NextBarNeeds | None


class DemarkSummary(Model):
    side: Side
    trend: Trend
    phase: Literal["setup", "countdown"]
    step: int
    target: Literal[9, 13]
    setup_step: int
    countdown_step: int
    rounds: list[Round]
    last_signal: SignalRef | None
    prev: PrevCountdown | None
    second: SecondSetup | None
    bars_since_qualified13: int | None
    setup_run: SetupRun
    risk: SummaryRisk
    as_of: datetime
    close: str


def _t9(seq: DemarkSequence) -> datetime:
    return seq.setup_bars[8].open_time


def _t13(seq: DemarkSequence) -> datetime:
    return seq.countdown_bars[-1].open_time


def summarize(result: DemarkResult, bars: list[Bar], as_of: datetime) -> DemarkSummary | None:
    """Project `result` (computed on `bars`) onto one primary sequence per timeframe."""
    seqs = sorted(
        (s for s in result.sequences if s.continuity == "observed" and s.setup_bars),
        key=lambda s: s.setup_bars[0].open_time,
    )
    if not seqs or not bars:
        return None
    index = {bar.open_time: i for i, bar in enumerate(bars)}
    last = len(bars) - 1

    def true_high(i: int) -> Decimal:
        high = Decimal(bars[i].high)
        return max(high, Decimal(bars[i - 1].close)) if i else high

    def true_low(i: int) -> Decimal:
        low = Decimal(bars[i].low)
        return min(low, Decimal(bars[i - 1].close)) if i else low

    done = [s for s in seqs if s.setup_status == "completed"]
    run = seqs[-1]
    active = [s for s in seqs if s.countdown_status in ACTIVE]
    if active:
        primary = active[0]
        phase: Literal["setup", "countdown"] = "countdown"
        step = countdown_step = primary.countdown_count
        same_run = run is not primary and run.side == primary.side
        setup_step = run.setup_count if same_run else primary.setup_count
    else:
        primary = run
        phase = "setup"
        step = setup_step = run.setup_count
        countdown_step = 0
    side = primary.side

    # Rounds, rule B: a same-side chain that restarts on an opposite 9 or on a new 9
    # after any chain round already reached qualified 13.
    chain: list[DemarkSequence] = []
    for seq in done:
        if chain and (
            seq.side != chain[0].side
            or any(
                c.countdown_status == "qualified13"
                and index[c.countdown_bars[-1].open_time] < index[seq.setup_bars[8].open_time]
                for c in chain
            )
        ):
            chain = []
        chain.append(seq)
    if not active and chain and chain[0].side != run.side:
        chain = []
    if not any(c is run for c in chain):
        chain.append(run)
    rounds = [
        Round(
            side=s.side,
            trend=TREND[s.side],
            setup=s.setup_count,
            countdown=s.countdown_count,
            setup9_at=_t9(s) if s.setup_status == "completed" else None,
            qualified13_at=_t13(s) if s.countdown_status == "qualified13" else None,
        )
        for s in chain
    ]

    ended = [
        s
        for s in seqs
        if s is not primary and s.countdown_status in ENDED and s.countdown_count > 0
    ]
    prev_seq = max(ended, key=lambda s: index[s.countdown_bars[-1].open_time], default=None)
    prev = (
        PrevCountdown(
            side=prev_seq.side,
            countdown=prev_seq.countdown_count,
            qualified=prev_seq.countdown_status == "qualified13",
            bars_ago=last - index[prev_seq.countdown_bars[-1].open_time],
        )
        if prev_seq
        else None
    )

    first = chain[0]
    last_signal: SignalRef | None
    if first.countdown_status == "qualified13":
        last_signal = SignalRef(kind=13, at=_t13(first), side=first.side)
    elif first.setup_status == "completed":
        last_signal = SignalRef(kind=9, at=_t9(first), side=first.side)
    elif prev_seq is not None and prev is not None:
        last_signal = SignalRef(
            kind=13 if prev.qualified else 9,
            at=_t13(prev_seq) if prev.qualified else _t9(prev_seq),
            side=prev_seq.side,
        )
    else:
        last_signal = None

    second = (
        SecondSetup(
            side=run.side,
            trend=TREND[run.side],
            step=run.setup_count,
            setup9_at=_t9(run) if run.setup_status == "completed" else None,
        )
        if phase == "countdown" and run is not primary
        else None
    )
    since13 = [s.bars_since_qualified13 for s in seqs if s.bars_since_qualified13 is not None]

    same_done = [s for s in done if s.side == side]
    setup9 = same_done[-1] if same_done else None
    risk9: Decimal | None = None
    if setup9 is not None:
        positions = [index[b.open_time] for b in setup9.setup_bars]
        if side == "buy":
            j = min(positions, key=lambda i: (true_low(i), i))
            risk9 = true_low(j) - (true_high(j) - true_low(j))
        else:
            # Ties take the earliest bar, as in the mapping note §5 and the engine's risk rule.
            j = max(positions, key=lambda i: (true_high(i), -i))
            risk9 = true_high(j) + (true_high(j) - true_low(j))
    same13 = [s for s in seqs if s.side == side and s.countdown_status == "qualified13"]
    risk13 = max(same13, key=_t13, default=None)
    close13 = (
        prev_seq.confirmation_close
        if prev_seq is not None and prev is not None and prev.qualified and prev_seq.side == side
        else None
    )
    if phase == "countdown":
        tdst = primary.tdst
        need = next((c for c in primary.next_conditions if c.purpose == "countdown"), None)
    else:
        tdst = done[-1].tdst if done else None
        need = next((c for c in run.next_conditions if c.purpose == "setup"), None)

    return DemarkSummary(
        side=side,
        trend=TREND[side],
        phase=phase,
        step=step,
        target=13 if phase == "countdown" else 9,
        setup_step=setup_step,
        countdown_step=countdown_step,
        rounds=rounds,
        last_signal=last_signal,
        prev=prev,
        second=second,
        bars_since_qualified13=min(since13) if since13 else None,
        setup_run=SetupRun(
            start=run.setup_bars[0].open_time,
            side=run.side,
            count=run.setup_count,
            active=run.setup_status == "forming",
            completed=run.setup_status == "completed",
        ),
        risk=SummaryRisk(
            risk9=text(risk9) if risk9 is not None else None,
            risk9_at=_t9(setup9) if setup9 is not None else None,
            setup_close=setup9.setup_bars[8].close if setup9 is not None else None,
            risk_level=risk13.risk_level if risk13 is not None else None,
            risk13_at=_t13(risk13) if risk13 is not None else None,
            provisional=not (risk13 is not None and first is risk13),
            close13=close13,
            tdst=tdst,
            next_bar_needs=(
                NextBarNeeds(
                    direction="below" if need.operator in ("<", "<=") else "above",
                    price=need.threshold,
                )
                if need is not None
                else None
            ),
        ),
        as_of=as_of,
        close=bars[-1].close,
    )


def as_tradingsignal(summary: DemarkSummary) -> tuple[dict[str, Any], dict[str, Any]]:
    """Field names and encodings of TradingSignal's across/risk payload, for parity checks."""

    def ts(value: datetime | None) -> int | None:
        return int(value.timestamp()) if value else None

    def signal(kind: int, at: datetime, side: str) -> dict[str, Any]:
        return {"kind": kind, "ts": ts(at), "side": side.upper()}

    rounds = []
    for r in summary.rounds:
        item: dict[str, Any] = {
            "side": r.side.upper(), "regime": r.trend, "setup": r.setup, "countdown": r.countdown
        }
        if r.setup9_at:
            item["establishedTs"] = ts(r.setup9_at)
        if r.qualified13_at:
            item["exhaustedTs"] = ts(r.qualified13_at)
        rounds.append(item)
    ls = summary.last_signal
    prev = summary.prev
    across: dict[str, Any] = {
        "side": summary.side.upper(),
        "rounds": rounds,
        "lastSignal": signal(ls.kind, ls.at, ls.side) if ls else None,
        "prev": (
            {"side": prev.side.upper(), "countdown": prev.countdown,
             "qualified": prev.qualified, "barsAgo": prev.bars_ago}
            if prev else None
        ),
        "barsSinceQualified13": summary.bars_since_qualified13,
        "regime": summary.trend,
        "phase": summary.phase,
        "step": summary.step,
        "target": summary.target,
        "setupStep": summary.setup_step,
        "countdownStep": summary.countdown_step,
        "asOf": ts(summary.as_of),
        "close": summary.close,
    }
    if summary.second:
        second: dict[str, Any] = {
            "phase": "setup",
            "side": summary.second.side.upper(),
            "regime": summary.second.trend,
            "step": summary.second.step,
            "target": 9,
        }
        if summary.second.setup9_at:
            second["lastSignal"] = signal(9, summary.second.setup9_at, summary.second.side)
        across["second"] = second
    risk = summary.risk
    run = summary.setup_run
    return across, {
        "riskLevel": risk.risk_level,
        "provisional": risk.provisional,
        "risk13Ts": ts(risk.risk13_at),
        "risk9": risk.risk9,
        "risk9Ts": ts(risk.risk9_at),
        "setupClose": risk.setup_close,
        "close13": risk.close13,
        "side": summary.side.upper(),
        "tdst": risk.tdst,
        "nextBarNeeds": (
            {"direction": risk.next_bar_needs.direction, "price": risk.next_bar_needs.price}
            if risk.next_bar_needs else None
        ),
        "setupRun": {"start": ts(run.start), "side": run.side.upper(), "n": run.count,
                     "active": run.active, "completed": run.completed},
    }
```

- [ ] **Step 4：运行测试，确认通过**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m pytest tests/regime/test_regime_summary.py -q`

预期：14 passed（结构 5 + 价格 5 + 其余 4）。

**如果失败：**
- 结构测试失败时，逐字段对照研究笔记 §3，以及研究脚本 `across.py` 的行为；**不要改测试期望去迁就代码**。
- 如果只有 4h 的 `risk9` 超出容差：检查并列极值是否取了最早的一根（研究残差为 −64.54）。

- [ ] **Step 5：静态检查**

在 `services/analytics` 下运行：

```bash
../../.venv-foundation/bin/python -m ruff check src tests/regime
../../.venv-foundation/bin/python -m mypy src/wheelhouse_service
```

预期：无错误。

检查点：黄金样本的结构字段对齐。

---

### Task 3：AlphaBTC 规则 `alphabtc.py`

**文件：**
- 新建：`services/analytics/src/wheelhouse_service/indicators/regime/__init__.py`
- 新建：`services/analytics/src/wheelhouse_service/indicators/regime/alphabtc.py`
- 测试：`services/analytics/tests/regime/test_regime_rules.py`

**接口：**
- 使用：Task 2 的 `DemarkSummary`、`Trend`，以及 `models.py` 的 `Model`、`Side`。
- 产出：
  - `S9 = Literal["up", "down", "none"]`
  - `RegimeValue = Literal["decay", "rev", "pump", "none", "unavailable"]`
  - `USABLE_STATUS = ("fresh", "delayed", "simulated")`
  - 模型 `TimeframeState`、`Signal`、`NewTrend`
  - `derive_state(summary: DemarkSummary) -> TimeframeState`
  - `regime_of(state: TimeframeState | None, status: str) -> RegimeValue`
  - `adjust(level: int, side: Side, regime: RegimeValue) -> int`
  - `signals(state: TimeframeState, summary: DemarkSummary, intraday: RegimeValue, swing: RegimeValue) -> list[Signal]`
  - `new_trend(summary: DemarkSummary) -> NewTrend`

- [ ] **Step 1：写失败的测试**

```python
"""AlphaBTC v2.95.0 regime rules (research/alphabtc-regime-cycle-source-2026-09-28.md §2)."""

import pytest
from regime_fixture import V2, replay_dataset

from wheelhouse_service.indicators.demark import evaluate_demark
from wheelhouse_service.indicators.demark.summary import summarize
from wheelhouse_service.indicators.regime.alphabtc import (
    TimeframeState,
    adjust,
    derive_state,
    new_trend,
    regime_of,
    signals,
)


def _summary(tf):
    data, as_of = replay_dataset(tf)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], as_of)
    assert summary is not None
    return summary


# Expected values were read from the AlphaBTC page for the same TD data.
@pytest.mark.parametrize(
    ("tf", "s9", "s13", "carry13", "countdown"),
    [
        ("5m", "down", False, False, 3),
        ("15m", "up", True, True, 13),
        ("1h", "down", True, True, 13),
        ("4h", "up", False, False, 8),
        ("1d", "up", False, False, 9),
    ],
)
def test_state_matches_alphabtc(tf, s9, s13, carry13, countdown):
    state = derive_state(_summary(tf))
    assert (state.s9, state.s13, state.carry13, state.countdown) == (s9, s13, carry13, countdown)


def test_anchor_regimes_match_alphabtc():
    assert regime_of(derive_state(_summary("1h")), "fresh") == "pump"
    assert regime_of(derive_state(_summary("4h")), "fresh") == "decay"


def _state(s9, s13):
    return TimeframeState(
        s9=s9, s13=s13, carry13=False, countdown=13 if s13 else 0,
        setup9_at=None, qualified13_at=None, setup9_seconds_ago=None,
        qualified13_seconds_ago=None, beyond_risk9=None,
    )


@pytest.mark.parametrize(
    ("s9", "s13", "expected"),
    [("up", False, "decay"), ("up", True, "rev"), ("down", False, "rev"),
     ("down", True, "pump"), ("none", False, "none")],
)
def test_regime_table(s9, s13, expected):
    assert regime_of(_state(s9, s13), "fresh") == expected


@pytest.mark.parametrize("status", ["stale", "unavailable"])
def test_regime_is_unavailable_without_usable_anchor_data(status):
    assert regime_of(_state("down", True), status) == "unavailable"
    assert regime_of(None, "fresh") == "unavailable"


@pytest.mark.parametrize("status", ["fresh", "delayed", "simulated"])
def test_regime_uses_fresh_delayed_or_simulated_anchor(status):
    assert regime_of(_state("down", True), status) == "pump"


@pytest.mark.parametrize(
    ("level", "side", "regime", "expected"),
    [(2, "buy", "pump", 3), (2, "sell", "pump", 1), (3, "buy", "rev", 2),
     (3, "sell", "rev", 4), (2, "buy", "decay", 2), (5, "buy", "pump", 5),
     (1, "sell", "pump", 1), (3, "sell", "unavailable", 3), (3, "buy", "none", 3)],
)
def test_adjust_clamps_and_follows_regime(level, side, regime, expected):
    assert adjust(level, side, regime) == expected


# Confidence words shown on AlphaBTC (board "日内网格", intraday regime = pump):
# 5m BUY1 中等(3); 15m SELL1 弱(1), SELL2 中等偏弱(2); 1h BUY1 中等(3), BUY2 中等偏强(4);
# 4h SELL1 弱(1); 1d SELL1 弱(1).
@pytest.mark.parametrize(
    ("tf", "expected"),
    [
        ("5m", [("buy", True, 3), ("buy", False, None)]),
        ("15m", [("sell", True, 1), ("sell", True, 2)]),
        ("1h", [("buy", True, 3), ("buy", True, 4)]),
        ("4h", [("sell", True, 1), ("sell", False, None)]),
        ("1d", [("sell", True, 1), ("sell", False, None)]),
    ],
)
def test_intraday_levels_match_alphabtc_page(tf, expected):
    summary = _summary(tf)
    got = signals(derive_state(summary), summary, "pump", "decay")
    assert [(s.side, s.active, s.intraday_level) for s in got] == expected


def test_signal_prices_come_from_setup_and_thirteen_closes():
    summary = _summary("1h")
    one, two = signals(derive_state(summary), summary, "pump", "decay")
    assert one.price == summary.risk.setup_close
    assert two.price == summary.risk.close13
    assert (one.base_level, two.base_level) == (2, 3)
    assert (one.swing_level, two.swing_level) == (2, 3)


def test_new_trend_follows_second_setup_during_countdown():
    trend = new_trend(_summary("4h"))
    assert (trend.present, trend.trend, trend.step, trend.confirmed) == (True, "up", 9, True)
    idle = new_trend(_summary("5m"))
    assert (idle.present, idle.trend, idle.step) == (True, "up", 6)


def test_deferred_thirteen_is_not_a_reversal():
    from test_sequential import BUY, dataset

    closes = BUY + [90, 89, 88, 87, 86, 85, 84, 94, 94, 93, 92, 91, 90, 89]
    data = dataset(closes)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], data.market_at)
    state = derive_state(summary)
    assert (state.s9, state.s13, state.countdown) == ("down", False, 12)
    assert regime_of(state, "simulated") == "rev"
```

- [ ] **Step 2：确认测试失败**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m pytest tests/regime/test_regime_rules.py -q`

预期：`ModuleNotFoundError: No module named 'wheelhouse_service.indicators.regime'`

- [ ] **Step 3：实现**

`indicators/regime/__init__.py`：

```python
"""Market regime interpretations layered on indicator results; never alter raw counts."""
```

`indicators/regime/alphabtc.py`：

```python
"""AlphaBTC's DeMark Regime interpretation, ported from its client (v2.95.0, 2026-09-28).

Source notes: research/alphabtc-regime-cycle-source-2026-09-28.md §2. Deliberate deviation:
missing or stale anchor data yields "unavailable" instead of AlphaBTC's default "decay".
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from ..demark.models import Model, Side
from ..demark.summary import DemarkSummary, Trend

S9 = Literal["up", "down", "none"]
RegimeValue = Literal["decay", "rev", "pump", "none", "unavailable"]
USABLE_STATUS = ("fresh", "delayed", "simulated")
BASE_LEVEL = {1: 2, 2: 3}


class TimeframeState(Model):
    s9: S9
    s13: bool
    carry13: bool
    countdown: int
    setup9_at: datetime | None
    qualified13_at: datetime | None
    setup9_seconds_ago: int | None
    qualified13_seconds_ago: int | None
    beyond_risk9: bool | None


class Signal(Model):
    n: Literal[1, 2]
    side: Side
    active: bool
    price: str | None
    base_level: int | None
    intraday_level: int | None
    swing_level: int | None


class NewTrend(Model):
    present: bool
    trend: Trend
    step: int
    confirmed: bool
    seconds: int | None


def _ago(as_of: datetime, at: datetime | None) -> int | None:
    return int((as_of - at).total_seconds()) if at is not None and as_of >= at else None


def derive_state(summary: DemarkSummary) -> TimeframeState:
    """AlphaBTC `dmkLive`: 9/13 status, keeping a just-finished 13 until a new 9 confirms."""
    prev = summary.prev
    prev_q13 = bool(prev and prev.qualified and prev.countdown >= 13)
    exhausted = [r.qualified13_at for r in summary.rounds if r.qualified13_at and r.countdown >= 13]
    last_ex13 = exhausted[-1] if exhausted else None
    ls = summary.last_signal
    last9 = ls.at if ls is not None and ls.kind == 9 else None
    last_is_13 = bool(
        (ls is not None and ls.kind == 13)
        or (last_ex13 is not None and (last9 is None or last_ex13 > last9))
    )
    carry13 = (
        last_is_13
        and summary.phase != "countdown"
        and summary.setup_step < 9
        and (prev_q13 or summary.countdown_step >= 13)
    )
    if carry13 and prev is not None:
        up = prev.side == "sell"
    elif carry13:
        finished = [r for r in summary.rounds if r.qualified13_at]
        up = (finished[-1].trend if finished else summary.trend) == "up"
    else:
        up = summary.trend == "up"
    setup_done = carry13 or summary.phase == "countdown" or summary.setup_step >= 9
    countdown = 13 if carry13 else (summary.step if summary.phase == "countdown" else 0)

    setup9_at: datetime | None = None
    if ls is not None and ls.kind == 9:
        setup9_at = ls.at
    elif carry13:
        rounds = [r for r in summary.rounds if r.setup9_at and r.qualified13_at] or [
            r for r in summary.rounds if r.setup9_at
        ]
        setup9_at = rounds[-1].setup9_at if rounds else summary.risk.risk9_at
    if ls is not None and ls.kind == 13:
        qualified13_at: datetime | None = ls.at
    elif carry13 and last_ex13 is not None:
        qualified13_at = last_ex13
    elif summary.risk.risk13_at is not None and not summary.risk.provisional:
        qualified13_at = summary.risk.risk13_at
    else:
        qualified13_at = None

    # risk9 belongs to the primary sequence's side, so compare in that direction. AlphaBTC uses the
    # carried round's direction here (only for bar tint); that contradicts the displayed "<"/">".
    risk9 = summary.risk.risk9
    close = Decimal(summary.close)
    rising = summary.trend == "up"
    beyond = (
        None if risk9 is None else (close > Decimal(risk9) if rising else close < Decimal(risk9))
    )
    return TimeframeState(
        s9=("up" if up else "down") if setup_done else "none",
        s13=countdown >= 13,
        carry13=carry13,
        countdown=countdown,
        setup9_at=setup9_at,
        qualified13_at=qualified13_at,
        setup9_seconds_ago=_ago(summary.as_of, setup9_at),
        qualified13_seconds_ago=_ago(summary.as_of, qualified13_at),
        beyond_risk9=beyond,
    )


def regime_of(state: TimeframeState | None, status: str) -> RegimeValue:
    """AlphaBTC `cycAuto` for an anchor timeframe (1h intraday, 4h swing)."""
    if state is None or status not in USABLE_STATUS:
        return "unavailable"
    if state.s9 == "none":
        return "none"
    if state.s9 == "down":
        return "pump" if state.s13 else "rev"
    return "rev" if state.s13 else "decay"


def adjust(level: int, side: Side, regime: RegimeValue) -> int:
    """AlphaBTC `regimeDelta`: pump favours BUY, rev favours SELL, one level, clamped 1..5."""
    delta = {"pump": 1, "rev": -1}.get(regime, 0) * (1 if side == "buy" else -1)
    return max(1, min(5, level + delta))


def signals(
    state: TimeframeState, summary: DemarkSummary, intraday: RegimeValue, swing: RegimeValue
) -> list[Signal]:
    """AlphaBTC `sigBlock`: signal 1 at a confirmed 9, signal 2 at 13."""
    side: Side = "buy" if state.s9 == "down" else "sell"
    out = []
    for n, active, price in (
        (1, state.s9 != "none", summary.risk.setup_close),
        (2, state.s13, summary.risk.close13),
    ):
        base = BASE_LEVEL[n]
        out.append(
            Signal(
                n=n,  # type: ignore[arg-type]
                side=side,
                active=active,
                price=price,
                base_level=base if active else None,
                intraday_level=adjust(base, side, intraday) if active else None,
                swing_level=adjust(base, side, swing) if active else None,
            )
        )
    return out


def new_trend(summary: DemarkSummary) -> NewTrend:
    """AlphaBTC `tdNew`: the setup forming beside an old countdown, or the setup itself."""
    if summary.second is not None:
        side, trend, step = summary.second.side, summary.second.trend, summary.second.step
        setup9_at = summary.second.setup9_at
    elif summary.phase == "setup":
        side, trend, step = summary.side, summary.trend, summary.step
        ls = summary.last_signal
        setup9_at = ls.at if ls is not None and ls.kind == 9 else None
    else:
        return NewTrend(present=False, trend=summary.trend, step=0, confirmed=False, seconds=None)
    confirmed = step >= 9
    run = summary.setup_run
    start = run.start if run.side == side else None
    return NewTrend(
        present=True,
        trend=trend,
        step=step,
        confirmed=confirmed,
        seconds=_ago(summary.as_of, setup9_at if confirmed else start),
    )
```

- [ ] **Step 4：运行测试，确认通过**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m pytest tests/regime -q`

预期：两个测试文件全部通过。

**如果 `test_new_trend_follows_second_setup_during_countdown` 的 5m 断言失败：** 快照中 5m 的 `second` 为 SELL 6，对应 trend `up`、step 6，以此为准。

- [ ] **Step 5：静态检查**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m ruff check src tests/regime && ../../.venv-foundation/bin/python -m mypy src/wheelhouse_service`

预期：无错误。

检查点：AlphaBTC 页面上的 regime 与置信度 5/5 复现。

---

### Task 4：`context.py` 与 `GET /market-context`

**文件：**
- 新建：`services/analytics/src/wheelhouse_service/context.py`
- 修改：`services/analytics/src/wheelhouse_service/http.py`（import、新 route、capabilities）
- 测试：`services/analytics/tests/regime/test_regime_context.py`

**接口：**
- 使用：
  - `Repository.read(stream, *, market_at, knowledge_at, limit)`
  - `data_state(source, closed_at, at, interval)`（来自 `calculation.py`）
  - `evaluate_demark`、Task 2 的 `summarize`，以及 Task 3 的全部函数
- 产出：
  - `WINDOW = 499`
  - `TIMEFRAMES`
  - `CONFIG: DemarkConfig`（v2）
  - `load_window(repository, stream, *, market_at, knowledge_at) -> tuple[DataStatus, Dataset]`：返回的 Dataset 只含最近 `WINDOW` 根已收盘 K 线，`forming=[]`
  - `compose(source, symbol, windows: dict[Timeframe, WindowResult], *, checked_at, market_at, knowledge_at) -> MarketContext`
  - `build_context(repository, source, symbol, *, market_at, knowledge_at, checked_at) -> MarketContext`
  - 模型：`WindowResult`、`TimeframeContext`、`RegimeState`、`MarketContext`
  - HTTP：`GET /api/wheelhouse/v1/market-context?source=&symbol=[&market_at=&knowledge_at=]`

- [ ] **Step 1：写失败的测试**

```python
"""Cross-timeframe context: windows, freshness, composition and the read-only endpoint."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from regime_fixture import TIMEFRAMES, V2, replay_dataset

from wheelhouse_service.context import (
    WINDOW,
    WindowResult,
    build_context,
    compose,
    load_window,
)
from wheelhouse_service.http import create_app
from wheelhouse_service.indicators.demark import evaluate_demark
from wheelhouse_service.indicators.demark.summary import summarize
from wheelhouse_service.market import DURATIONS, Bar, Batch, Stream
from wheelhouse_service.repository import Repository

START = datetime(2026, 1, 1, tzinfo=UTC)


def _ingest(repo, source, tf, count=None, *, symbol="BTCUSDT", closes=None, forming=False):
    closes = closes or [100 + i % 7 for i in range(count)]
    step = timedelta(seconds=DURATIONS[tf])
    bars = [
        Bar(open_time=START + step * i, close_time=START + step * (i + 1),
            open=str(c), high=str(c + 1), low=str(c - 1), close=str(c), is_closed=True)
        for i, c in enumerate(closes)
    ]
    if forming:  # an unfinished bar at the fetch moment must never enter the window
        opened = bars[-1].close_time
        bars.append(Bar(open_time=opened, close_time=opened + step, open="100", high="101",
                        low="99", close="100", is_closed=False))
    stream = Stream(source=source, symbol=symbol, timeframe=tf)
    end = max(b.close_time for b in bars if b.is_closed)
    repo.ingest(Batch(stream=stream, fetched_at=end, bars=bars, raw_payload={}))
    return stream, end


def test_window_takes_last_499_closed_bars_and_flags_short_history(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    stream, end = _ingest(repo, "fixture", "1h", 520, forming=True)
    status, window = load_window(repo, stream, market_at=end, knowledge_at=end)
    assert status == "simulated"
    assert len(window.bars) == WINDOW and window.forming == []
    assert window.bars[-1].bar.close_time == end
    short, _ = _ingest(repo, "fixture", "4h", 30)
    _, few = load_window(repo, short, market_at=end + timedelta(days=5), knowledge_at=end)
    assert len(few.bars) == 30


def test_replay_cutoff_excludes_later_bars(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    stream, end = _ingest(repo, "fixture", "1h", 100)
    cut = end - timedelta(hours=10)
    _, window = load_window(repo, stream, market_at=cut, knowledge_at=end)
    assert window.bars[-1].bar.close_time == cut


def test_empty_repository_is_unavailable_not_an_error(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    now = datetime(2026, 9, 28, tzinfo=UTC)
    ctx = build_context(repo, "binance", "BTCUSDT", market_at=now, knowledge_at=now, checked_at=now)
    assert [tf.status for tf in ctx.timeframes] == ["unavailable"] * 5
    assert all(
        tf.summary is None and tf.state is None and tf.signals == [] for tf in ctx.timeframes
    )
    assert (ctx.intraday.value, ctx.swing.value) == ("unavailable", "unavailable")


def test_stale_binance_anchor_makes_regime_unavailable(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    _, end = _ingest(repo, "binance", "1h", 60)
    later = end + timedelta(hours=5)
    ctx = build_context(repo, "binance", "BTCUSDT", market_at=later, knowledge_at=later,
                        checked_at=later)
    hour = next(tf for tf in ctx.timeframes if tf.timeframe == "1h")
    assert hour.status == "stale"
    assert hour.summary is None and hour.state is None and hour.signals == []
    assert hour.new_trend is None and hour.bars_used == 60
    assert ctx.intraday.value == "unavailable"


def test_eth_fixture_source_is_simulated_and_usable(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    # Buy Setup 9 followed by a qualified 13 (same pattern as tests/demark/test_sequential.py).
    closes = [100, 101, 102, 103, 104, 99, 98, 97, 96, 95, 94, 93, 92, 91, *range(90, 78, -1)]
    _, end = _ingest(repo, "fixture", "1h", symbol="ETHUSDT", closes=closes)
    ctx = build_context(repo, "fixture", "ETHUSDT", market_at=end, knowledge_at=end, checked_at=end)
    hour = next(tf for tf in ctx.timeframes if tf.timeframe == "1h")
    assert hour.status == "simulated"
    assert hour.summary is not None
    assert hour.history_complete is False and hour.bars_used == len(closes)
    assert ctx.intraday.value != "unavailable"


def _golden_windows():
    windows = {}
    for tf in TIMEFRAMES:
        data, as_of = replay_dataset(tf)
        summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], as_of)
        windows[tf] = WindowResult(status="fresh", bars_used=500, gapped=False,
                                   last_closed_at=data.bars[-1].bar.close_time, summary=summary)
    return windows


def test_compose_reproduces_alphabtc_regimes_and_levels():
    now = datetime(2026, 9, 27, 16, 30, tzinfo=UTC)
    ctx = compose("binance", "BTCUSDT", _golden_windows(), checked_at=now, market_at=now,
                  knowledge_at=now)
    assert (ctx.intraday.anchor, ctx.intraday.value) == ("1h", "pump")
    assert (ctx.swing.anchor, ctx.swing.value) == ("4h", "decay")
    five = next(tf for tf in ctx.timeframes if tf.timeframe == "5m")
    assert [(s.side, s.intraday_level) for s in five.signals] == [("buy", 3), ("buy", None)]


def test_compose_falls_back_to_base_levels_when_anchor_is_stale():
    windows = _golden_windows()
    windows["1h"] = windows["1h"].model_copy(update={"status": "stale"})
    now = datetime(2026, 9, 27, 16, 30, tzinfo=UTC)
    ctx = compose("binance", "BTCUSDT", windows, checked_at=now, market_at=now, knowledge_at=now)
    assert ctx.intraday.value == "unavailable"
    five = next(tf for tf in ctx.timeframes if tf.timeframe == "5m")
    assert five.signals[0].intraday_level == five.signals[0].base_level == 2


def test_endpoint_is_read_only_and_validates_replay_cutoffs(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite", start_worker=False)) as client:
        ok = client.get("/api/wheelhouse/v1/market-context?source=binance&symbol=BTCUSDT")
        assert ok.status_code == 200
        assert ok.json()["window"] == WINDOW
        assert len(ok.json()["timeframes"]) == 5
        base = "/api/wheelhouse/v1/market-context?source=binance&symbol=BTCUSDT"
        only_one = client.get(base + "&market_at=2026-09-01T00:00:00Z")
        assert only_one.status_code == 422
        future = client.get(
            base + "&market_at=2999-01-01T00:00:00Z&knowledge_at=2999-01-01T00:00:00Z"
        )
        assert future.status_code == 422
        naive = client.get(
            base + "&market_at=2026-09-01T00:00:00&knowledge_at=2026-09-01T00:00:00"
        )
        assert naive.status_code == 422
        assert client.get(base.replace("BTCUSDT", "SOLUSDT")).status_code == 422
        replay = client.get(
            base + "&market_at=2026-09-01T00:00:00Z&knowledge_at=2026-09-02T00:00:00Z"
        )
        assert replay.status_code == 200
        assert replay.json()["mode"] == "retrospective"
        assert client.post(base).status_code == 405
        status = client.get("/api/wheelhouse/v1/status").json()
        assert "market_context" in status["capabilities"]
```

- [ ] **Step 2：确认测试失败**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m pytest tests/regime/test_regime_context.py -q`

预期：`ModuleNotFoundError: No module named 'wheelhouse_service.context'`

- [ ] **Step 3：实现 `context.py`**

```python
"""Cross-timeframe DeMark context: TradingSignal-equivalent summaries plus AlphaBTC regime.

Read-only and computed on demand from stored closed bars; nothing is persisted.
"""

from datetime import datetime
from typing import Literal

from .calculation import data_state
from .indicators.demark import evaluate_demark
from .indicators.demark.models import DemarkConfig
from .indicators.demark.summary import DemarkSummary, summarize
from .indicators.regime.alphabtc import (
    USABLE_STATUS,
    NewTrend,
    RegimeValue,
    Signal,
    TimeframeState,
    derive_state,
    new_trend,
    regime_of,
    signals,
)
from .market import DURATIONS, Dataset, Model, Source, Stream, Timeframe
from .repository import Repository

# TradingSignal evaluates 500 bars including one forming bar; 499 closed bars keep the same start.
WINDOW = 499
TIMEFRAMES: tuple[Timeframe, ...] = ("5m", "15m", "1h", "4h", "1d")
CONFIG = DemarkConfig(
    ruleset_version="wheelhouse-sequential-2",
    same_side_policy="retain_active",
    perfection_policy="strict_at_nine",
)
DataStatus = Literal["fresh", "delayed", "stale", "unavailable", "simulated"]
Symbol = Literal["BTCUSDT", "ETHUSDT"]


class WindowResult(Model):
    status: DataStatus
    bars_used: int
    gapped: bool
    last_closed_at: datetime | None
    summary: DemarkSummary | None


class TimeframeContext(Model):
    timeframe: Timeframe
    status: DataStatus
    bars_used: int
    history_complete: bool
    history_gapped: bool
    last_closed_at: datetime | None
    summary: DemarkSummary | None
    state: TimeframeState | None
    signals: list[Signal]
    new_trend: NewTrend | None


class RegimeState(Model):
    anchor: Timeframe
    value: RegimeValue


class MarketContext(Model):
    source: Source
    symbol: Symbol
    checked_at: datetime
    market_at: datetime
    knowledge_at: datetime
    mode: Literal["as_known", "retrospective"]
    config: DemarkConfig
    window: int
    timeframes: list[TimeframeContext]
    intraday: RegimeState
    swing: RegimeState


def load_window(
    repository: Repository, stream: Stream, *, market_at: datetime, knowledge_at: datetime
) -> tuple[DataStatus, Dataset]:
    # A small margin covers forming rows that the SQL limit counts before closed filtering.
    dataset = repository.read(
        stream, market_at=market_at, knowledge_at=knowledge_at, limit=WINDOW + 20
    )
    window = dataset.model_copy(update={"bars": dataset.bars[-WINDOW:], "forming": []})
    last = window.bars[-1].bar.close_time if window.bars else None
    status = data_state(stream.source, last, market_at, DURATIONS[stream.timeframe])
    return status, window


def _window(
    repository: Repository, stream: Stream, *, market_at: datetime, knowledge_at: datetime
) -> WindowResult:
    status, window = load_window(
        repository, stream, market_at=market_at, knowledge_at=knowledge_at
    )
    if not window.bars:
        return WindowResult(
            status=status, bars_used=0, gapped=False, last_closed_at=None, summary=None
        )
    end = window.bars[-1].bar.close_time
    bars = [b.bar for b in window.bars]
    result = evaluate_demark(window, CONFIG)
    return WindowResult(
        status=status,
        bars_used=len(bars),
        gapped=result.history_status == "gapped",
        last_closed_at=end,
        summary=summarize(result, bars, end),
    )


def compose(
    source: Source,
    symbol: Symbol,
    windows: dict[Timeframe, WindowResult],
    *,
    checked_at: datetime,
    market_at: datetime,
    knowledge_at: datetime,
) -> MarketContext:
    states = {
        tf: derive_state(w.summary) if w.summary is not None else None for tf, w in windows.items()
    }
    intraday = regime_of(states["1h"], windows["1h"].status)
    swing = regime_of(states["4h"], windows["4h"].status)
    timeframes = []
    for tf in TIMEFRAMES:
        w = windows[tf]
        # Stale or missing data shows no values at all (spec §1.4), not yesterday's reading.
        usable = w.status in USABLE_STATUS
        summary = w.summary if usable else None
        state = states[tf] if usable else None
        timeframes.append(
            TimeframeContext(
                timeframe=tf,
                status=w.status,
                bars_used=w.bars_used,
                history_complete=w.bars_used >= WINDOW,
                history_gapped=w.gapped,
                last_closed_at=w.last_closed_at,
                summary=summary,
                state=state,
                signals=(
                    signals(state, summary, intraday, swing)
                    if state is not None and summary is not None
                    else []
                ),
                new_trend=new_trend(summary) if summary is not None else None,
            )
        )
    return MarketContext(
        source=source,
        symbol=symbol,
        checked_at=checked_at,
        market_at=market_at,
        knowledge_at=knowledge_at,
        mode="retrospective" if knowledge_at > market_at else "as_known",
        config=CONFIG,
        window=WINDOW,
        timeframes=timeframes,
        intraday=RegimeState(anchor="1h", value=intraday),
        swing=RegimeState(anchor="4h", value=swing),
    )


def build_context(
    repository: Repository,
    source: Source,
    symbol: Symbol,
    *,
    market_at: datetime,
    knowledge_at: datetime,
    checked_at: datetime,
) -> MarketContext:
    windows = {
        tf: _window(
            repository,
            Stream(source=source, symbol=symbol, timeframe=tf),
            market_at=market_at,
            knowledge_at=knowledge_at,
        )
        for tf in TIMEFRAMES
    }
    return compose(
        source,
        symbol,
        windows,
        checked_at=checked_at,
        market_at=market_at,
        knowledge_at=knowledge_at,
    )
```

- [ ] **Step 4：在 `http.py` 注册 route**

在 `http.py` 顶部 import 区加入：

```python
from .context import MarketContext, build_context
```

在 `@app.get(f"{PREFIX}/workspace", ...)` 那个 route 之前加入：

```python
    @app.get(f"{PREFIX}/market-context", response_model=MarketContext)
    def market_context(
        source: Source = "fixture",
        symbol: str = "BTCUSDT",
        market_at: datetime | None = None,
        knowledge_at: datetime | None = None,
    ) -> MarketContext:
        if symbol not in {"BTCUSDT", "ETHUSDT"}:
            raise APIException(422)
        if (market_at is None) != (knowledge_at is None):
            raise APIException(422)
        now = datetime.now(UTC)
        market = market_at or now
        knowledge = knowledge_at or now
        if market.tzinfo is None or knowledge.tzinfo is None or market > now or knowledge > now:
            raise APIException(422)
        return build_context(
            repo(),
            source,
            symbol,  # type: ignore[arg-type]
            market_at=market,
            knowledge_at=knowledge,
            checked_at=now,
        )
```

在 `status()` 的 `capabilities` 列表末尾加上 `"market_context",`。

如果 `http.py` 尚未导入 `datetime`、`UTC`、`Source`、`APIException`，则一并补上；它们在该文件已有使用，通常已经导入。

- [ ] **Step 5：运行测试，确认通过**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m pytest tests/regime -q && ../../.venv-foundation/bin/python -m pytest -q`

预期：`tests/regime` 全部通过，全量测试也没有回归。

- [ ] **Step 6：静态检查**

在 `services/analytics` 下运行：`../../.venv-foundation/bin/python -m ruff check . && ../../.venv-foundation/bin/python -m mypy src/wheelhouse_service`

预期：无错误。

检查点：接口可用，未刷新、过期、回放等边界都正确。

---

### Task 5：契约与前端 client

**文件：**
- 重新生成：`integrations/wealthfolio/openapi.json`、`…/wheelhouse/api-schema.d.ts`
- 新建：`…/wheelhouse/regime-contract.ts`、`…/wheelhouse/regime-contract.test.ts`、`…/wheelhouse/regime-sample.ts`（测试共用的样例 payload）
- 修改：`…/wheelhouse/client.ts`

**接口：**
- 使用：Task 4 的 JSON 形状，以及 `demark-contract.ts` 的 `demarkConfigSchema`。
- 产出：
  - `marketContextSchema`
  - `type MarketContext`
  - `getMarketContext(source: Stream["source"], symbol: Stream["symbol"], signal?: AbortSignal): Promise<MarketContext>`

- [ ] **Step 1：重新生成契约**

在仓库根目录运行：`make contract`

预期：
- `openapi.json` 中出现 `/api/wheelhouse/v1/market-context` 和 `MarketContext` schema；
- `api-schema.d.ts` 中出现 `MarketContext`。

用 `grep -c MarketContext integrations/wealthfolio/openapi.json` 确认计数大于 0。

- [ ] **Step 2：写样例 `regime-sample.ts` 和失败的测试 `regime-contract.test.ts`**

`regime-sample.ts`（非测试文件，Task 6 的组件测试也会导入它）：

```ts
import { defaultDemarkConfig } from "./demark-contract";

const empty = (timeframe: string) => ({
  timeframe,
  status: "unavailable",
  bars_used: 0,
  history_complete: false,
  history_gapped: false,
  last_closed_at: null,
  summary: null,
  state: null,
  signals: [],
  new_trend: null,
});

export const sampleContext = {
  source: "binance",
  symbol: "BTCUSDT",
  checked_at: "2026-09-27T16:30:00Z",
  market_at: "2026-09-27T16:30:00Z",
  knowledge_at: "2026-09-27T16:30:00Z",
  mode: "as_known",
  config: defaultDemarkConfig,
  window: 499,
  timeframes: [
    empty("5m"),
    empty("15m"),
    {
      ...empty("1h"),
      status: "fresh",
      bars_used: 499,
      history_complete: true,
      last_closed_at: "2026-09-27T16:00:00Z",
      summary: {
        side: "buy",
        trend: "down",
        phase: "setup",
        step: 3,
        target: 9,
        setup_step: 3,
        countdown_step: 0,
        rounds: [
          {
            side: "buy",
            trend: "down",
            setup: 9,
            countdown: 13,
            setup9_at: "2026-09-23T14:00:00Z",
            qualified13_at: "2026-09-25T21:00:00Z",
          },
        ],
        last_signal: { kind: 13, at: "2026-09-25T21:00:00Z", side: "buy" },
        prev: { side: "buy", countdown: 13, qualified: true, bars_ago: 43 },
        second: null,
        bars_since_qualified13: 43,
        setup_run: {
          start: "2026-09-27T14:00:00Z",
          side: "buy",
          count: 3,
          active: true,
          completed: false,
        },
        risk: {
          risk9: "81772.1",
          risk9_at: "2026-09-23T14:00:00Z",
          setup_close: "84537.5",
          risk_level: "81974.4",
          risk13_at: "2026-09-25T21:00:00Z",
          provisional: false,
          close13: "83788.6",
          tdst: "86625.8",
          next_bar_needs: { direction: "below", price: "85030.5" },
        },
        as_of: "2026-09-27T16:00:00Z",
        close: "84578.3",
      },
      state: {
        s9: "down",
        s13: true,
        carry13: true,
        countdown: 13,
        setup9_at: "2026-09-23T14:00:00Z",
        qualified13_at: "2026-09-25T21:00:00Z",
        setup9_seconds_ago: 353200,
        qualified13_seconds_ago: 154800,
        beyond_risk9: false,
      },
      signals: [
        { n: 1, side: "buy", active: true, price: "84537.5", base_level: 2, intraday_level: 3, swing_level: 2 },
        { n: 2, side: "buy", active: true, price: "83788.6", base_level: 3, intraday_level: 4, swing_level: 3 },
      ],
      new_trend: { present: true, trend: "down", step: 3, confirmed: false, seconds: 7200 },
    },
    empty("4h"),
    empty("1d"),
  ],
  intraday: { anchor: "1h", value: "pump" },
  swing: { anchor: "4h", value: "unavailable" },
};
```

`regime-contract.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { marketContextSchema } from "./regime-contract";
import { sampleContext } from "./regime-sample";

describe("market context contract", () => {
  it("accepts the service payload", () => {
    const parsed = marketContextSchema.parse(sampleContext);
    expect(parsed.intraday.value).toBe("pump");
    expect(parsed.timeframes[2].signals[1].intraday_level).toBe(4);
  });

  it("rejects an unknown regime instead of rendering a guess", () => {
    const bad = { ...sampleContext, intraday: { anchor: "1h", value: "bullish" } };
    expect(marketContextSchema.safeParse(bad).success).toBe(false);
  });
});
```

- [ ] **Step 3：实现 `regime-contract.ts`**

```ts
import { z } from "zod";
import type { components } from "./api-schema";
import { demarkConfigSchema } from "./demark-contract";

export type MarketContext = components["schemas"]["MarketContext"];
export type TimeframeContext = MarketContext["timeframes"][number];
export type RegimeValue = MarketContext["intraday"]["value"];

const time = z.string().datetime({ offset: true });
const price = z.string().regex(/^-?\d+(?:\.\d+)?$/);
const int = z.number().int();
const side = z.enum(["buy", "sell"]);
const trend = z.enum(["up", "down"]);
const level = int.min(1).max(5);
const timeframe = z.enum(["5m", "15m", "1h", "4h", "1d"]);
const regime = z.object({
  anchor: timeframe,
  value: z.enum(["decay", "rev", "pump", "none", "unavailable"]),
});
const summary = z.object({
  side,
  trend,
  phase: z.enum(["setup", "countdown"]),
  step: int,
  target: z.union([z.literal(9), z.literal(13)]),
  setup_step: int,
  countdown_step: int,
  rounds: z.array(
    z.object({
      side,
      trend,
      setup: int,
      countdown: int,
      setup9_at: time.nullable(),
      qualified13_at: time.nullable(),
    }),
  ),
  last_signal: z
    .object({ kind: z.union([z.literal(9), z.literal(13)]), at: time, side })
    .nullable(),
  prev: z
    .object({ side, countdown: int, qualified: z.boolean(), bars_ago: int })
    .nullable(),
  second: z
    .object({ side, trend, step: int, setup9_at: time.nullable() })
    .nullable(),
  bars_since_qualified13: int.nullable(),
  setup_run: z.object({
    start: time,
    side,
    count: int,
    active: z.boolean(),
    completed: z.boolean(),
  }),
  risk: z.object({
    risk9: price.nullable(),
    risk9_at: time.nullable(),
    setup_close: price.nullable(),
    risk_level: price.nullable(),
    risk13_at: time.nullable(),
    provisional: z.boolean(),
    close13: price.nullable(),
    tdst: price.nullable(),
    next_bar_needs: z
      .object({ direction: z.enum(["above", "below"]), price })
      .nullable(),
  }),
  as_of: time,
  close: price,
});

export const marketContextSchema: z.ZodType<
  MarketContext,
  z.ZodTypeDef,
  unknown
> = z.object({
  source: z.enum(["fixture", "binance"]),
  symbol: z.enum(["BTCUSDT", "ETHUSDT"]),
  checked_at: time,
  market_at: time,
  knowledge_at: time,
  mode: z.enum(["as_known", "retrospective"]),
  config: demarkConfigSchema,
  window: int,
  timeframes: z.array(
    z.object({
      timeframe,
      status: z.enum(["fresh", "delayed", "stale", "unavailable", "simulated"]),
      bars_used: int,
      history_complete: z.boolean(),
      history_gapped: z.boolean(),
      last_closed_at: time.nullable(),
      summary: summary.nullable(),
      state: z
        .object({
          s9: z.enum(["up", "down", "none"]),
          s13: z.boolean(),
          carry13: z.boolean(),
          countdown: int,
          setup9_at: time.nullable(),
          qualified13_at: time.nullable(),
          setup9_seconds_ago: int.nullable(),
          qualified13_seconds_ago: int.nullable(),
          beyond_risk9: z.boolean().nullable(),
        })
        .nullable(),
      signals: z.array(
        z.object({
          n: z.union([z.literal(1), z.literal(2)]),
          side,
          active: z.boolean(),
          price: price.nullable(),
          base_level: level.nullable(),
          intraday_level: level.nullable(),
          swing_level: level.nullable(),
        }),
      ),
      new_trend: z
        .object({
          present: z.boolean(),
          trend,
          step: int,
          confirmed: z.boolean(),
          seconds: int.nullable(),
        })
        .nullable(),
    }),
  ),
  intraday: regime,
  swing: regime,
});
```

**如果 type-check 报 `marketContextSchema` 与生成类型不兼容：** 以 `api-schema.d.ts` 为准修改 Zod（例如生成类型把某个 literal 表示成 number），不要改生成文件。

- [ ] **Step 4：在 `client.ts` 增加 `getMarketContext`**

在 `export const getSnapshot` 之后加入：

```ts
export const getMarketContext = (
  source: Stream["source"],
  symbol: Stream["symbol"],
  signal?: AbortSignal,
) =>
  query(
    `/market-context?${new URLSearchParams({ source, symbol })}`,
    marketContextSchema,
    { signal },
  );
```

并在文件顶部加上 `import { marketContextSchema } from "./regime-contract";`。

- [ ] **Step 5：运行前端测试**

在仓库根目录运行：`make sync`，然后执行：

```bash
npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend exec vitest run src/features/wheelhouse/regime-contract.test.ts
npx --yes pnpm@10.33.4 --dir .local/wealthfolio build:types
npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend type-check
```

（`pnpm@10.33.4` 以 `scripts/foundation.py` 的 `PIN["package_manager"]` 为准。）

预期：
- 测试 2 passed；
- type-check 无错误。

**如果 `make sync` 的实际行为与此不同：** 以 `scripts/foundation.py` 中 `sync_host` 的实现为准。

检查点：契约与 client 就绪。

---

### Task 6：核对区块 UI

**文件：**
- 新建：`…/wheelhouse/regime-board.ts`、`…/wheelhouse/regime-board.test.ts`
- 新建：`…/wheelhouse/regime-check.tsx`、`…/wheelhouse/regime-check.test.tsx`
- 修改：`…/wheelhouse/i18n.ts`（en 与 zh 各加同一组键）、`…/wheelhouse/market.css`、`…/wheelhouse/market-page.tsx`

**接口：**
- 使用：
  - Task 5 的 `getMarketContext`、`MarketContext`、`TimeframeContext`、`RegimeValue`
  - client 的 `submitJob`、`money`、`stamp`、`Stream`、`Rules`
- 产出：
  - `type Board = "cta" | "opt" | "all"`
  - `regimeSideFor(board, timeframe): "intraday" | "swing"`
  - `signalLevel(signal, side, calibrated): number | null`
  - `shortAge(seconds: number | null): string | null`
  - `<RegimeCheck stream={stream} rules={rules} />`

- [ ] **Step 1：写失败的测试 `regime-board.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { regimeSideFor, shortAge, signalLevel } from "./regime-board";

const signal = {
  n: 1 as const,
  side: "buy" as const,
  active: true,
  price: "1",
  base_level: 2,
  intraday_level: 3,
  swing_level: 1,
};

describe("AlphaBTC board mapping", () => {
  it("uses one regime per single board and splits the all board", () => {
    expect(regimeSideFor("cta", "4h")).toBe("intraday");
    expect(regimeSideFor("opt", "5m")).toBe("swing");
    expect(regimeSideFor("all", "1h")).toBe("intraday");
    expect(regimeSideFor("all", "4h")).toBe("swing");
  });

  it("returns the calibrated or base level and nothing for inactive signals", () => {
    expect(signalLevel(signal, "intraday", true)).toBe(3);
    expect(signalLevel(signal, "swing", true)).toBe(1);
    expect(signalLevel(signal, "intraday", false)).toBe(2);
    expect(signalLevel({ ...signal, active: false }, "intraday", true)).toBeNull();
  });

  it("formats ages like AlphaBTC's short clock", () => {
    expect(shortAge(1200)).toBe("<1h");
    expect(shortAge(12 * 3600)).toBe("12h");
    expect(shortAge(4 * 86400)).toBe("4D");
    expect(shortAge(null)).toBeNull();
  });
});
```

- [ ] **Step 2：实现 `regime-board.ts`**

```ts
import type { TimeframeContext } from "./regime-contract";

export type Board = "cta" | "opt" | "all";
export type RegimeSide = "intraday" | "swing";
type Signal = TimeframeContext["signals"][number];

/** AlphaBTC: grid board uses the 1h regime, option board the 4h, "all" splits by timeframe. */
export function regimeSideFor(
  board: Board,
  timeframe: TimeframeContext["timeframe"],
): RegimeSide {
  if (board === "cta") return "intraday";
  if (board === "opt") return "swing";
  return timeframe === "5m" || timeframe === "15m" || timeframe === "1h"
    ? "intraday"
    : "swing";
}

export function signalLevel(
  signal: Signal,
  side: RegimeSide,
  calibrated: boolean,
): number | null {
  if (!signal.active) return null;
  if (!calibrated) return signal.base_level;
  return side === "intraday" ? signal.intraday_level : signal.swing_level;
}

/** AlphaBTC `tdShort`: "<1h", hours below two days, then days. */
export function shortAge(seconds: number | null): string | null {
  if (seconds == null) return null;
  const hours = Math.round(seconds / 3600);
  if (hours < 1) return "<1h";
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}D`;
}
```

- [ ] **Step 3：在 `i18n.ts` 加文案**

在 `en` 对象的 `} as const;` 之前加入以下键；在 `zh` 对象的 `};` 之前加入相同的键，值取右侧中文。中文与 AlphaBTC 原文逐字一致，方便对照。

| 键 | en | zh |
|---|---|---|
| `regime.title` | `Cross-timeframe check · AlphaBTC parity` | `跨周期核对 · AlphaBTC 对照` |
| `regime.note` | `Closed bars only, last {{window}} per timeframe. AlphaBTC also counts the forming bar, so values can lag it by one bar.` | `只用已收盘 K 线，每个周期取最近 {{window}} 根。AlphaBTC 含未收盘 K 线，数值可能比它晚一根。` |
| `regime.intraday` | `Intraday regime · 1h` | `日内周期 · 1 小时线` |
| `regime.swing` | `Swing regime · 4h` | `跨天周期 · 4 小时线` |
| `regime.value.decay` | `Breakout decay (突破减弱)` | `突破减弱` |
| `regime.value.rev` | `Reversal fade (反转阴跌)` | `反转阴跌` |
| `regime.value.pump` | `Selloff exhausted (阴跌爆拉)` | `阴跌爆拉` |
| `regime.value.none` | `9 not confirmed` | `9 未确认 · 暂无状态` |
| `regime.value.unavailable` | `Unavailable · anchor data missing or stale` | `不可用 · 锚点数据缺失或过期` |
| `regime.board.cta` | `Intraday grid` | `日内网格趋势反转` |
| `regime.board.opt` | `Option strangle` | `期权双卖` |
| `regime.board.all` | `All` | `全部` |
| `regime.calibrate.intraday` | `Apply short-term regime` | `短期 regime 校准` |
| `regime.calibrate.swing` | `Apply long-term regime` | `长期 regime 校准` |
| `regime.refreshAll` | `Refresh all timeframes` | `全部刷新` |
| `regime.row.data` | `Data` | `数据` |
| `regime.row.nine` | `9` | `9` |
| `regime.row.thirteen` | `13 · Countdown` | `13 · 衰减计数` |
| `regime.row.setup` | `Setup run` | `Setup 进度` |
| `regime.row.since9` | `Since 9` | `9 距今` |
| `regime.row.since13` | `Since 13` | `13 距今` |
| `regime.row.risk9` | `Trend decay threshold` | `趋势衰退阈值` |
| `regime.row.risk13` | `Reversal level` | `反转位` |
| `regime.row.next` | `Next bar needs` | `下一根需` |
| `regime.row.signal1` | `Signal 1` | `信号 1` |
| `regime.row.signal2` | `Signal 2` | `信号 2` |
| `regime.row.newTrend` | `New trend` | `新趋势监测` |
| `regime.row.tdst` | `TDST` | `TDST` |
| `regime.row.window` | `Window` | `窗口` |
| `regime.s9.up` | `Uptrend confirmed` | `上升趋势确认` |
| `regime.s9.down` | `Downtrend confirmed` | `下跌趋势确认` |
| `regime.s9.none` | `{{trend}} {{count}}/9` | `{{trend}} {{count}}/9` |
| `regime.trend.up` | `Up` | `上升` |
| `regime.trend.down` | `Down` | `下降` |
| `regime.s13.upDone` | `Uptrend reversed 13/13` | `上涨趋势反转` |
| `regime.s13.downDone` | `Downtrend reversed 13/13` | `下降趋势反转` |
| `regime.s13.pending` | `No reversal {{count}}/13` | `反转未出 {{count}}/13` |
| `regime.beyond.yes` | `price beyond → trend continues` | `现价越过 → 趋势延续` |
| `regime.beyond.no` | `price inside → trend decaying` | `现价未越过 → 趋势衰退` |
| `regime.risk13.current` | `This round` | `本轮反转位` |
| `regime.risk13.previous` | `Previous round` | `上轮反转位` |
| `regime.level.1` | `Weak` | `弱` |
| `regime.level.2` | `Moderately weak` | `中等偏弱` |
| `regime.level.3` | `Moderate` | `中等` |
| `regime.level.4` | `Moderately strong` | `中等偏强` |
| `regime.level.5` | `Strong` | `强` |
| `regime.signal.none` | `——` | `——` |
| `regime.newTrend.none` | `No new trend` | `暂无新趋势` |
| `regime.newTrend.forming` | `{{trend}} {{count}}/9 forming` | `{{trend}} {{count}}/9 形成中` |
| `regime.newTrend.confirmed` | `{{trend}} confirmed` | `{{trend}} 已确认` |
| `regime.window.short` | `{{count}}/{{window}} · history short` | `{{count}}/{{window}} · 历史不足` |
| `regime.window.gapped` | `gap in window` | `窗口内有断档` |
| `regime.level.uncalibrated` | `base level · regime unavailable` | `基础档 · regime 不可用` |
| `regime.reason.stale` | `Data is stale; values are hidden until a fresh refresh.` | `数据已过期；刷新到最新前不显示数值。` |
| `regime.reason.unavailable` | `No stored bars for this timeframe yet.` | `该周期还没有已存 K 线。` |
| `regime.reason.short` | `Fewer than the window's closed bars; counts may differ from AlphaBTC.` | `已收盘 K 线不足窗口长度；计数可能与 AlphaBTC 不同。` |
| `regime.reason.gapped` | `The window has a gap; sequences after it restart.` | `窗口内有断档；断档后的序列会重新计数。` |
| `regime.status.fresh` | `Fresh` | `最新` |
| `regime.status.delayed` | `Delayed` | `延迟` |
| `regime.status.stale` | `Stale` | `过期` |
| `regime.status.unavailable` | `Unavailable` | `不可用` |
| `regime.status.simulated` | `Simulated` | `模拟` |

- [ ] **Step 4：写失败的组件测试 `regime-check.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Rules, Stream } from "./client";
import { defaultDemarkConfig } from "./demark-contract";
import { RegimeCheck } from "./regime-check";
import { sampleContext } from "./regime-sample";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const stream = {
  source: "binance",
  symbol: "BTCUSDT",
  timeframe: "5m",
  venue: "binance-spot",
  market_session: "24/7",
  timezone: "UTC",
  quote_currency: "USDT",
  base_currency: "BTC",
  price_encoding: "decimal_string_18_places",
} as Stream;
const rules: Rules = { engine_version: "baseline-v1", window: 20, demark: defaultDemarkConfig };

it("shows regimes, calibrated levels and unavailable timeframes without guessing", async () => {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) =>
    url.includes("/market-context")
      ? new Response(JSON.stringify(sampleContext))
      : new Response(JSON.stringify({}), { status: 500 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RegimeCheck stream={stream} rules={rules} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText(/Selloff exhausted/)).toBeTruthy());
  expect(screen.getByText(/Unavailable · anchor data/)).toBeTruthy();
  expect(screen.getByText(/BUY 2 · 83,788.60 · Moderately strong/)).toBeTruthy();
  expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
  // Auto refresh: non-fresh timeframes except the page's own 5m; the fresh 1h is left alone.
  await waitFor(() => {
    const posted = fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith("/jobs"))
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)).stream.timeframe);
    expect(posted.sort()).toEqual(["15m", "1d", "4h"]);
  });
  // Option board uses the swing regime, which is unavailable in the sample.
  fireEvent.click(screen.getByRole("radio", { name: "Option strangle" }));
  expect(
    screen.getByText(/BUY 2 · 83,788.60 · Moderate · base level · regime unavailable/),
  ).toBeTruthy();
});
```

- [ ] **Step 5：实现 `regime-check.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  getMarketContext,
  money,
  stamp,
  submitJob,
  type Rules,
  type Stream,
} from "./client";
import { useWheelhouseText, type MessageKey } from "./i18n";
import { regimeSideFor, shortAge, signalLevel, type Board } from "./regime-board";
import type { MarketContext, TimeframeContext } from "./regime-contract";

type Row = { key: MessageKey; cell: (tf: TimeframeContext) => string };

export function RegimeCheck({ stream, rules }: { stream: Stream; rules: Rules }) {
  const { text } = useWheelhouseText();
  const missing = text("missing");
  const cache = useQueryClient();
  const [board, setBoard] = useState<Board>("cta");
  const [calibrate, setCalibrate] = useState({ intraday: true, swing: true });
  const context = useQuery({
    queryKey: ["wh", "market-context", stream.source, stream.symbol],
    queryFn: ({ signal }) => getMarketContext(stream.source, stream.symbol, signal),
    refetchInterval: 30000,
  });
  const refresh = useMutation({
    // `skip` is the page's own timeframe on auto refresh: the page already refreshes it.
    mutationFn: async ({ data, skip }: { data: MarketContext; skip?: string }) => {
      const due = data.timeframes.filter(
        (tf) =>
          tf.status !== "fresh" && tf.status !== "simulated" && tf.timeframe !== skip,
      );
      await Promise.all(
        due.map((tf) =>
          submitJob(
            { kind: "refresh", stream: { ...stream, timeframe: tf.timeframe }, rules },
            crypto.randomUUID(),
          ),
        ),
      );
    },
    onSettled: () => cache.invalidateQueries({ queryKey: ["wh"] }),
  });
  const refreshedScope = useRef<string | null>(null);
  useEffect(() => {
    const scope = `${stream.source}:${stream.symbol}`;
    const current = context.data;
    if (!current || refreshedScope.current === scope) return;
    if (`${current.source}:${current.symbol}` !== scope) return;
    refreshedScope.current = scope;
    refresh.mutate({ data: current, skip: stream.timeframe });
  }, [context.data, refresh, stream.source, stream.symbol, stream.timeframe]);

  const data = context.data;
  // Keys built from payload enums; every combination exists in both catalogs (i18n.test.ts).
  const tk = (key: string, vars?: Parameters<typeof text>[1]) => text(key as MessageKey, vars);
  const trendWord = (trend: "up" | "down") => tk(`regime.trend.${trend}`);
  const signalCell = (tf: TimeframeContext, n: 1 | 2) => {
    const signal = tf.signals.find((s) => s.n === n);
    if (!signal) return missing;
    const side = regimeSideFor(board, tf.timeframe);
    const level = signalLevel(signal, side, calibrate[side]);
    const label = `${signal.side.toUpperCase()} ${n}`;
    const price = signal.price ? money(signal.price, missing) : text("regime.signal.none");
    if (level == null) return `${label} · ${text("regime.signal.none")}`;
    // Calibration requested but its regime is unavailable: the level is the base level.
    const uncalibrated =
      calibrate[side] && data?.[side].value === "unavailable"
        ? ` · ${text("regime.level.uncalibrated")}`
        : "";
    return `${label} · ${price} · ${tk(`regime.level.${level}`)}${uncalibrated}`;
  };
  const reason = (tf: TimeframeContext) =>
    tf.status === "stale" || tf.status === "unavailable"
      ? tk(`regime.reason.${tf.status}`)
      : tf.history_gapped
        ? text("regime.reason.gapped")
        : !tf.history_complete
          ? text("regime.reason.short")
          : undefined;
  const rows: Row[] = [
    {
      key: "regime.row.data",
      cell: (tf) =>
        `${tk(`regime.status.${tf.status}`)} · ${stamp(tf.last_closed_at, missing)}`,
    },
    {
      key: "regime.row.nine",
      cell: (tf) =>
        !tf.state || !tf.summary
          ? missing
          : tf.state.s9 === "none"
            ? text("regime.s9.none", {
                trend: trendWord(tf.summary.trend),
                count: tf.summary.setup_step,
              })
            : tk(`regime.s9.${tf.state.s9}`),
    },
    {
      key: "regime.row.thirteen",
      cell: (tf) =>
        !tf.state
          ? missing
          : tf.state.s9 === "none"
            ? "—"
            : tf.state.s13
              ? text(tf.state.s9 === "down" ? "regime.s13.downDone" : "regime.s13.upDone")
              : text("regime.s13.pending", { count: tf.state.countdown }),
    },
    {
      key: "regime.row.setup",
      cell: (tf) =>
        tf.summary
          ? `${tf.summary.setup_run.side.toUpperCase()} ${tf.summary.setup_run.count}/9`
          : missing,
    },
    {
      key: "regime.row.since9",
      cell: (tf) => shortAge(tf.state?.setup9_seconds_ago ?? null) ?? "—",
    },
    {
      key: "regime.row.since13",
      cell: (tf) => shortAge(tf.state?.qualified13_seconds_ago ?? null) ?? "—",
    },
    {
      key: "regime.row.risk9",
      cell: (tf) => {
        const risk9 = tf.summary?.risk.risk9;
        if (!tf.summary || !risk9) return missing;
        const sign = tf.summary.trend === "up" ? "<" : ">";
        const beyond = tf.state?.beyond_risk9;
        const note =
          beyond == null ? "" : ` · ${text(beyond ? "regime.beyond.yes" : "regime.beyond.no")}`;
        return `${sign} ${money(risk9, missing)}${note}`;
      },
    },
    {
      key: "regime.row.risk13",
      cell: (tf) => {
        const risk = tf.summary?.risk;
        if (!risk || !risk.risk_level) return missing;
        const label = text(
          risk.provisional ? "regime.risk13.previous" : "regime.risk13.current",
        );
        const sign = tf.summary?.trend === "up" ? "<" : ">";
        return `${label} ${sign} ${money(risk.risk_level, missing)}`;
      },
    },
    {
      key: "regime.row.next",
      cell: (tf) => {
        const need = tf.summary?.risk.next_bar_needs;
        return need
          ? `${need.direction === "below" ? "<" : ">"} ${money(need.price, missing)}`
          : missing;
      },
    },
    { key: "regime.row.signal1", cell: (tf) => signalCell(tf, 1) },
    { key: "regime.row.signal2", cell: (tf) => signalCell(tf, 2) },
    {
      key: "regime.row.newTrend",
      cell: (tf) => {
        const trend = tf.new_trend;
        if (!trend) return missing;
        if (!trend.present) return text("regime.newTrend.none");
        const vars = { trend: trendWord(trend.trend), count: trend.step };
        const body = text(
          trend.confirmed ? "regime.newTrend.confirmed" : "regime.newTrend.forming",
          vars,
        );
        const age = shortAge(trend.seconds);
        return age ? `${body} · ${age}` : body;
      },
    },
    {
      key: "regime.row.tdst",
      cell: (tf) => money(tf.summary?.risk.tdst, missing),
    },
    {
      key: "regime.row.window",
      cell: (tf) =>
        (tf.history_complete
          ? `${tf.bars_used}`
          : text("regime.window.short", {
              count: tf.bars_used,
              window: data?.window ?? 499,
            })) + (tf.history_gapped ? ` · ${text("regime.window.gapped")}` : ""),
    },
  ];
  const cellOf = (key: MessageKey, tf: TimeframeContext) =>
    rows.find((row) => row.key === key)?.cell(tf) ?? missing;
  const basis = (side: "intraday" | "swing") => {
    if (!data) return missing;
    const anchorTimeframe = data[side].anchor;
    const anchor = data.timeframes.find((tf) => tf.timeframe === anchorTimeframe);
    return anchor
      ? `${cellOf("regime.row.nine", anchor)} · ${cellOf("regime.row.thirteen", anchor)}`
      : missing;
  };

  return (
    <details className="wh-regime" open>
      <summary>{text("regime.title")}</summary>
      {context.error ? (
        <p className="wh-regime-error" role="alert">
          {String((context.error as Error).message)}
        </p>
      ) : !data ? (
        <p className="wh-regime-note">{text("service.connecting")}</p>
      ) : (
        <>
          <div className="wh-regime-head">
            {(["intraday", "swing"] as const).map((side) => (
              <div key={side} className={`wh-regime-pill is-${data[side].value}`}>
                <span>{tk(`regime.${side}`)}</span>
                <strong>{tk(`regime.value.${data[side].value}`)}</strong>
                <em>{basis(side)}</em>
                <label>
                  <input
                    type="checkbox"
                    checked={calibrate[side]}
                    onChange={(e) =>
                      setCalibrate((c) => ({ ...c, [side]: e.target.checked }))
                    }
                  />
                  {tk(`regime.calibrate.${side}`)}
                </label>
              </div>
            ))}
            <div className="wh-regime-boards" role="radiogroup">
              {(["cta", "opt", "all"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  role="radio"
                  aria-checked={board === item}
                  className={board === item ? "is-active" : ""}
                  onClick={() => setBoard(item)}
                >
                  {tk(`regime.board.${item}`)}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="wh-regime-refresh"
              disabled={refresh.isPending}
              onClick={() => refresh.mutate({ data })}
            >
              {refresh.isPending ? text("action.refreshing") : text("regime.refreshAll")}
            </button>
          </div>
          <p className="wh-regime-note">{text("regime.note", { window: data.window })}</p>
          <div className="wh-regime-scroll">
            <table className="wh-regime-table">
              <thead>
                <tr>
                  <th scope="col" />
                  {data.timeframes.map((tf) => (
                    <th key={tf.timeframe} scope="col">
                      {tf.timeframe.toUpperCase()}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <th scope="row">{text(row.key)}</th>
                    {data.timeframes.map((tf) => (
                      <td key={tf.timeframe} title={reason(tf)}>
                        {row.cell(tf)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </details>
  );
}
```

- [ ] **Step 6：样式（追加到 `market.css`）**

```css
.wh-regime {
  margin-top: 16px;
  border: 1px solid var(--wh-edge);
  border-radius: 8px;
  background: var(--wh-surface);
  padding: 12px 14px;
}
.wh-regime > summary {
  cursor: pointer;
  font-weight: 600;
}
.wh-regime > summary:focus-visible,
.wh-regime button:focus-visible {
  outline: 2px solid var(--wh-cyan);
  outline-offset: 2px;
}
.wh-regime-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 12px 0 6px;
}
.wh-regime-pill {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid var(--wh-edge);
  border-radius: 6px;
  min-width: 220px;
}
.wh-regime-pill span,
.wh-regime-pill label,
.wh-regime-pill em,
.wh-regime-note {
  color: var(--wh-muted);
  font-size: 12px;
}
.wh-regime-pill.is-pump strong { color: var(--wh-cyan); }
.wh-regime-pill.is-rev strong { color: var(--wh-rose); }
.wh-regime-pill.is-decay strong { color: var(--wh-td-thirteen); }
.wh-regime-boards {
  display: inline-flex;
  border: 1px solid var(--wh-edge);
  border-radius: 6px;
  overflow: hidden;
}
.wh-regime-boards button,
.wh-regime-refresh {
  background: transparent;
  border: 0;
  color: inherit;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}
.wh-regime-boards button.is-active {
  background: color-mix(in srgb, var(--wh-cyan) 18%, transparent);
}
.wh-regime-refresh {
  border: 1px solid var(--wh-edge);
  border-radius: 6px;
}
.wh-regime-scroll {
  overflow-x: auto;
}
.wh-regime-table {
  border-collapse: collapse;
  min-width: 760px;
  width: 100%;
  font-family: "JetBrains Mono", monospace;
  font-size: 12px;
}
.wh-regime-table th,
.wh-regime-table td {
  border-top: 1px solid var(--wh-edge);
  padding: 6px 8px;
  text-align: left;
  white-space: nowrap;
}
.wh-regime-table th[scope="row"] {
  color: var(--wh-muted);
  font-family: Inter, sans-serif;
}
.wh-regime-error {
  color: var(--wh-rose);
}
```

- [ ] **Step 7：挂载到页面（`market-page.tsx`）**

在文件顶部 import 区加入：`import { RegimeCheck } from "./regime-check";`

找到主区块结束的 `</section>`，它紧挨在 `<section className="wh-replay">` 之前（当前约第 717–718 行），在两者之间插入：

```tsx
          {method === "td" && <RegimeCheck stream={stream} rules={rules} />}
```

- [ ] **Step 8：运行前端测试**

在仓库根目录运行 `make sync`，然后：

```bash
npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend exec vitest run src/features/wheelhouse
npx --yes pnpm@10.33.4 --dir .local/wealthfolio build:types
npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend type-check
```

预期：
- 全部通过，包括 `i18n.test.ts` 的 en/zh 键一致性检查；
- type-check 无错误。

检查点：核对区块可以渲染，缺数据不会乱猜。

---

### Task 7：核对脚本与文档

**文件：**
- 新建：`scripts/verification/compare_alphabtc_context.py`
- 新建：`docs/features/demark-regime/PARITY-LOG.md`
- 修改：`prototypes/wheel-dashboard/MARKET-STRATEGY-SPEC.md`（§9.3）

**接口：**
- 使用：Task 2 的 `summarize` 与 `as_tradingsignal`、Task 3 的 `derive_state` 与 `regime_of`、Task 4 的 `CONFIG` 与 `WINDOW`。
- 产出：命令行工具。

```text
python scripts/verification/compare_alphabtc_context.py --td9 PATH --captured-at UNIX [--output PATH]
```

- [ ] **Step 1：实现脚本**

```python
"""Replay an AlphaBTC /api/td9 capture against the local context (forming bar rebuilt).

Reads Binance public klines only; never contacts AlphaBTC or TradingSignal and reads no
credentials. The capture JSON is saved by the user or via their logged-in browser.
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/analytics/src"))

from wheelhouse_service.context import CONFIG, WINDOW  # noqa: E402
from wheelhouse_service.indicators.demark import evaluate_demark  # noqa: E402
from wheelhouse_service.indicators.demark.summary import (  # noqa: E402
    as_tradingsignal,
    summarize,
)
from wheelhouse_service.indicators.regime.alphabtc import (  # noqa: E402
    adjust,
    derive_state,
    regime_of,
    signals,
)
from wheelhouse_service.market import (  # noqa: E402
    DURATIONS,
    Bar,
    Dataset,
    StoredBar,
    Stream,
)

API = "https://data-api.binance.vision/api/v3/klines"
TF_NAMES = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1D": "1d"}
STRUCTURAL = (
    "side", "regime", "phase", "step", "target", "setupStep", "countdownStep",
    "barsSinceQualified13", "lastSignal", "prev", "second", "rounds",
)


def klines(client, interval, *, end_ms, limit):
    rows = client.get(
        API,
        params={"symbol": "BTCUSDT", "interval": interval, "endTime": end_ms, "limit": limit},
    )
    rows.raise_for_status()
    return rows.json()


def forming(client, open_ts, captured):
    """OHLC of the bar opened at open_ts as it stood at `captured` (1m, then 1s for the tail)."""
    minutes = []
    start = open_ts * 1000
    while True:
        batch = client.get(
            API,
            params={"symbol": "BTCUSDT", "interval": "1m", "startTime": start, "limit": 1000},
        ).json()
        minutes += [r for r in batch if r[0] // 1000 + 60 <= captured]
        if len(batch) < 1000 or batch[-1][0] // 1000 + 60 > captured:
            break
        start = batch[-1][0] + 60000
    tail = captured - captured % 60
    seconds = (
        client.get(
            API,
            params={"symbol": "BTCUSDT", "interval": "1s", "startTime": tail * 1000,
                    "endTime": captured * 1000 - 1, "limit": 1000},
        ).json()
        if captured % 60
        else []
    )
    rows = minutes + seconds
    if not rows or rows[0][0] // 1000 != open_ts:
        raise SystemExit(f"cannot rebuild forming bar {open_ts}")
    return [open_ts, rows[0][1], str(max(Decimal(r[2]) for r in rows)),
            str(min(Decimal(r[3]) for r in rows)), rows[-1][4]]


def replay(client, tf, as_of, captured):
    step = DURATIONS[tf]
    closed = [
        [r[0] // 1000, r[1], r[2], r[3], r[4]]
        for r in klines(client, tf, end_ms=as_of * 1000 - 1, limit=WINDOW)
    ]
    rows = closed[-WINDOW:] + [forming(client, as_of, captured)]
    bars = []
    for t, o, h, low, c in rows:
        opened = datetime.fromtimestamp(t, UTC)
        bars.append(StoredBar(
            revision_id=f"cmp:{tf}:{t}", revision=1, fetched_at=opened + timedelta(seconds=step),
            bar=Bar(open_time=opened, close_time=opened + timedelta(seconds=step),
                    open=o, high=h, low=low, close=c, is_closed=True)))
    end = bars[-1].bar.close_time
    data = Dataset(stream=Stream(source="binance", symbol="BTCUSDT", timeframe=tf),
                   market_at=end, knowledge_at=end, fetched_at=end, bars=bars, forming=[])
    return summarize(evaluate_demark(data, CONFIG), [b.bar for b in bars],
                     datetime.fromtimestamp(as_of, UTC))


def normalize(capture):
    """Accept `across` as a list with `timeframe` or as a dict keyed by timeframe."""
    across = capture["across"]
    pairs = across.items() if isinstance(across, dict) else ((x["timeframe"], x) for x in across)

    def name(key):
        if str(key) not in TF_NAMES:
            raise SystemExit(f"unknown timeframe in capture: {key!r}")
        return TF_NAMES[str(key)]

    return (
        {name(k): v for k, v in pairs},
        {name(k): v for k, v in capture.get("risk", {}).items()},
    )


def ts_state(x):
    """AlphaBTC dmkLive on the captured TradingSignal fields -> (s9, s13)."""
    p = x.get("prev") or {}
    prev_q13 = bool(p.get("qualified")) and (p.get("countdown") or 0) >= 13
    ex = [r["exhaustedTs"] for r in x.get("rounds") or []
          if (r.get("countdown") or 0) >= 13 and r.get("exhaustedTs")]
    ts_ex13 = ex[-1] if ex else 0
    ls = x.get("lastSignal") or {}
    ts9 = ls.get("ts", 0) if ls.get("kind") == 9 else 0
    last13 = ls.get("kind") == 13 or bool(ts_ex13 and ts_ex13 > ts9)
    carry = bool(last13 and x["phase"] != "countdown" and (x.get("setupStep") or 0) < 9
                 and (prev_q13 or (x.get("countdownStep") or 0) >= 13))
    if carry and p.get("side"):
        up = p["side"] == "SELL"
    elif carry:
        done13 = [r for r in x.get("rounds") or [] if r.get("exhaustedTs")]
        up = (done13[-1]["regime"] if done13 else x.get("regime")) == "up"
    else:
        up = x.get("regime") == "up"
    done = carry or x["phase"] == "countdown" or (x.get("setupStep") or 0) >= 9
    cd = 13 if carry else ((x.get("step") or 0) if x["phase"] == "countdown" else 0)
    return (("up" if up else "down") if done else "none"), cd >= 13


def table(s9, s13):
    if s9 == "none":
        return "none"
    return ("pump" if s13 else "rev") if s9 == "down" else ("rev" if s13 else "decay")


def ts_levels(s9, s13, intraday, swing):
    side = "buy" if s9 == "down" else "sell"
    return [
        (adjust(base, side, intraday), adjust(base, side, swing)) if active else (None, None)
        for base, active in ((2, s9 != "none"), (3, s13))
    ]


def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k != "strong"}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--td9", type=Path, required=True)
    parser.add_argument("--captured-at", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    by_tf, risk = normalize(json.loads(args.td9.read_text()))
    report = {"captured_at": args.captured_at, "timeframes": {}}
    summaries, states = {}, {}
    with httpx.Client(timeout=10) as client:
        for tf, ts_across in by_tf.items():
            summary = replay(client, tf, ts_across["asOf"], args.captured_at)
            across, local_risk = as_tradingsignal(summary)
            summaries[tf], states[tf] = summary, derive_state(summary)
            report["timeframes"][tf] = {
                "structural_mismatches": {
                    k: {"ts": ts_across.get(k), "local": across.get(k)}
                    for k in STRUCTURAL
                    if strip(ts_across.get(k)) != strip(across.get(k))
                },
                "prices": {k: {"ts": risk.get(tf, {}).get(k), "local": local_risk.get(k)}
                           for k in ("risk9", "setupClose", "riskLevel", "close13", "tdst")},
            }
    ts_s = {tf: ts_state(x) for tf, x in by_tf.items()}
    ts_reg = {k: table(*ts_s[a]) if a in ts_s else "unavailable"
              for k, a in (("intraday", "1h"), ("swing", "4h"))}
    anchors = (("intraday", "1h"), ("swing", "4h"))
    local_reg = {k: regime_of(states.get(a), "fresh") for k, a in anchors}
    report["regime"] = {"alphabtc": ts_reg, "local": local_reg, "match": ts_reg == local_reg}
    for tf, item in report["timeframes"].items():
        local = [(sg.intraday_level, sg.swing_level) for sg in
                 signals(states[tf], summaries[tf], local_reg["intraday"], local_reg["swing"])]
        expected = ts_levels(*ts_s[tf], ts_reg["intraday"], ts_reg["swing"])
        s9, s13 = ts_s[tf]
        item["state"] = {"alphabtc": [s9, s13], "local": [states[tf].s9, states[tf].s13],
                         "match": (s9, s13) == (states[tf].s9, states[tf].s13)}
        item["levels"] = {"alphabtc": expected, "local": local, "match": expected == local}
    text = json.dumps(report, indent=1, ensure_ascii=False, default=str)
    if args.output:
        args.output.write_text(text)
    for tf, item in report["timeframes"].items():
        flags = f"state={'OK' if item['state']['match'] else 'DIFF'} " \
                f"levels={'OK' if item['levels']['match'] else 'DIFF'}"
        print(tf, flags, "structure OK" if not item["structural_mismatches"]
              else sorted(item["structural_mismatches"]))
    print("regime", report["regime"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：用黄金快照自检**

1. 把样本中的 TS across/risk 还原成 `/api/td9` 的形状（`across` 为带 `timeframe` 的列表，`risk` 以周期为键）：

```bash
.venv-foundation/bin/python -c '
import json
fx = json.load(open("services/analytics/tests/regime/fixtures/alphabtc-td9-2026-09-27T162832Z.json"))
td9 = {"across": [dict(v["across"], timeframe=tf) for tf, v in fx["timeframes"].items()],
       "risk": {tf: v["risk"] for tf, v in fx["timeframes"].items()}}
json.dump(td9, open("/private/tmp/claude-501/-Users-gary-code-AlgoForceNext/766fdf7e-1bf6-49dd-af42-f417d07fde53/scratchpad/td9-20260927.json", "w"))
'
```

2. 运行（`<scratchpad>` 即上面的目录）：

```bash
.venv-foundation/bin/python scripts/verification/compare_alphabtc_context.py \
  --td9 <scratchpad>/td9-20260927.json --captured-at 1790526512
```

预期：
- 5 个周期 `state=OK levels=OK`；
- 1h、4h、1d 为 `structure OK`；5m 只列出 `barsSinceQualified13` 与 `prev`；
- 最后一行 regime 为 `{'intraday': 'pump', 'swing': 'decay'}` 且 `match: True`。
- 15m 在这里用的是 Binance 行情，而研究时 13 用的是 TS 导出的行情，两者差一根，所以 15m 可能列出 `lastSignal` 或 `prev` 的时间差。把实际结果写进 PARITY-LOG，并说明原因。

- [ ] **Step 3：写 `PARITY-LOG.md`**

```markdown
# DeMark Regime 对照记录

每行一次对照。「一致」指结构字段一致；价格残差单列。未收盘 bar 按抓取时刻，由 1m/1s K 线重建。

| 抓取时刻 (UTC) | 覆盖情形 | 结构字段 | Regime（日内/跨天） | 置信度 | 备注 |
|---|---|---|---|---|---|
| 2026-09-27 16:28:32 | 1h 刚走完 13、4h 保留 Countdown 同时新 9、1d 取消过的 Countdown | 5m 的 prev 与 barsSinceQualified13 不同（行情源）；15m 在 Binance 行情下 lastSignal/prev 差 1 根 | 阴跌爆拉 / 突破减弱，一致 | 5/5 一致 | 黄金样本，见 tests/regime/fixtures |
```

并追加 Step 2 的实际输出摘要。

- [ ] **Step 4：修订 `MARKET-STRATEGY-SPEC.md` §9.3**

保留该节标题，把三条 `Reversal Fade` / `Breakout Decay` / `Compression Reversal` 定义替换为：

```markdown
The business labels follow AlphaBTC's verified client rules (2026-09-28), not the earlier
Wheelhouse-defined conditions. Anchor 1h for intraday and 4h for swing:

| Anchor 9 | Anchor 13 | Label |
|---|---|---|
| up confirmed | no | Breakout decay (突破减弱) |
| up confirmed | yes | Reversal fade (反转阴跌) |
| down confirmed | no | Reversal fade (反转阴跌) |
| down confirmed | yes | Selloff exhausted (阴跌爆拉) |
| not confirmed | — | none |

Missing or stale anchor data is `unavailable` (AlphaBTC shows "Breakout decay"; Wheelhouse
does not). Details: docs/features/demark-regime/SPEC.md and
research/alphabtc-regime-cycle-source-2026-09-28.md §2.
```

检查点：核对工具可以复跑，文档不再互相矛盾。

---

### Task 8：整体验收

**文件：** 无新增。

- [ ] **Step 1：全量检查**

在仓库根目录运行：`make check`

预期：ruff、mypy、pytest、types、type-check、vitest 全部通过。

- [ ] **Step 2：重启 Python 服务，加载新代码**

`make dev` 下 Python 服务运行在 8787 端口。先请用户确认可以重启：用户可能正在使用 `make dev`。

确认后执行 `make stop && make dev`，然后检查新接口：

```bash
curl -s "http://127.0.0.1:8787/api/wheelhouse/v1/market-context?source=binance&symbol=BTCUSDT" | head -c 400
```

预期：返回 JSON，`window` 为 499，并有 5 个周期。

- [ ] **Step 3：浏览器验收**

用 Chrome 打开：
- `http://127.0.0.1:1420/market-intelligence?timeframe=5m&method=td`
- `http://127.0.0.1:1420/market-intelligence?timeframe=1h&method=td`

逐项检查：
- 核对区块显示在图表下方；首次打开时，非 fresh 的周期会被自动刷新。
- 5 列都有值，或写明 Unavailable。
- 切换看板和校准开关时，置信度按规则变化。
- 切到中文后，状态名与 AlphaBTC 原文一致。
- 在 390px 宽度下，表格只在自身区域内横向滚动，页面本身不横向溢出。
- 控制台没有错误。

- [ ] **Step 4：与 AlphaBTC 实时并排对照**

用户说「抓快照」后：
1. 在用户已登录的 Chrome 中读取 `https://alphabtc-regime.vercel.app/api/td9?symbol=BTC%2FUSDT` 的响应。
2. 存到 `services/analytics/tests/regime/fixtures/`：文件名带抓取时刻，**只保留 `across` 与 `risk` 两个字段**（白名单），其他字段一律不存。
3. 运行 Task 7 的脚本，并在 PARITY-LOG 记一行。

目标：累计至少 5 份，覆盖 spec §1 列出的情形。遇到结构不一致时：
1. 先判断是行情源还是规则问题；
2. 属于规则问题的，只修改 `summary.py` 或 `alphabtc.py`；
3. 为该情形补一条单元测试。

- [ ] **Step 5：汇报**

向用户汇报以下内容，并询问是否 commit：
- 通过的检查项及其输出摘要；
- 浏览器截图；
- PARITY-LOG 的累计结果；
- 仍待确认的问题（研究笔记 §8 中尚未被新样本回答的条目）。
```
