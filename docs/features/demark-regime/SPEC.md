# DeMark Regime 数据层 Spec

日期：2026-09-28。状态：已批准并实施（2026-09-28）；成功标准 2 已完成：5 份新快照对照，结论见 [PARITY-LOG](PARITY-LOG.md)。

依据：
- [AlphaBTC 规则核验](../../../research/alphabtc-regime-cycle-source-2026-09-28.md)
- [TradingSignal 主序列映射](../demark/ACROSS-PRIMARY-SEQUENCE.md)
- [基础 Sequential 结果](../demark/RESULTS.md)

市场周期（链上六态与指数）另写 spec，不在本文范围内。

## 1. 目标与成功标准

**目标：** 用本地 DeMark 引擎和 Binance 行情，算出 AlphaBTC「Demark Regime」区块的全部数据：
- 5 个周期的 9/13 状态；
- 日内 / 跨天 Regime；
- BUY/SELL 1、2 的价格与置信度；
- 新趋势进度；
- 各类风险位。

在 1420 的 Market intelligence 页面用一张朴素的核对表展示，供用户与 AlphaBTC 并排对照。正式 UI 等数据核对通过后另行设计。

**成功标准：**
1. 固定样本（2026-09-27 16:28 UTC 快照）回放时，结构字段与 TradingSignal 快照一致。
   - 15m / 1h / 4h / 1d 全部字段一致。
   - 5m 除 `prev` 与 `barsSinceQualified13` 外一致，这两项的差异已知由行情源造成。
   - 由此推出的 s9/s13、Regime、置信度与 AlphaBTC 页面 5/5 一致。
2. 再抓至少 5 份不同时刻的快照，回放对照要达到：
   - 结构字段一致；有行情源差异的必须逐项写明原因。
   - Regime 与置信度 100% 一致。
   - 这批快照要覆盖以下情形：13 延期、13 之后出现同向被压住的 9、Countdown 被取消、TDST 取消。
3. 线上值只用已收盘 K 线。与 AlphaBTC 的差异只能来自「未收盘那根」和行情源，并且在核对表中可以看出原因。
4. 某周期数据过期或缺失时，对应数值显示「不可用」，不给默认值。

## 2. 已确认的决策

| 决策 | 内容 |
|---|---|
| Regime 规则 | 照搬 AlphaBTC 客户端代码的实际行为，不沿用 [市场策略规格 §9.3](../../../prototypes/wheel-dashboard/MARKET-STRATEGY-SPEC.md) 的自定义三态；实施时同步修订 §9.3 |
| K 线口径 | 线上只用已收盘 K 线（用户选 A）。未收盘那根只在核对回放工具中使用 |
| 主序列 | 按 TradingSignal across 的选法（见映射笔记 §3），规则 B 暂定 |
| 缺数据 | 不照搬 AlphaBTC「没数据时显示突破减弱」的行为，一律显示 unavailable |
| 数据范围 | BTCUSDT 为对照目标；ETHUSDT 用同一逻辑计算，但没有对照样本 |

## 3. 计算口径

### 3.1 窗口

- TradingSignal 用 500 根计算，其中包含 1 根未收盘。
- 本地取截止时刻之前最后 **499 根已收盘 K 线**，让窗口起点与 TradingSignal 对齐，再用现有 v2 配置运行 `evaluate_demark`：
  - `wheelhouse-sequential-2`
  - `retain_active`
  - `strict_at_nine`
- 已存 K 线不足 499 根时照样计算，但该周期 `history_complete=false`，并返回实际根数 `bars_used`。
- 这份计算与 TD tab 图表上的 DeMark 相互独立：图表继续用全部已存历史，本阶段不改。两者可能不同（例如图表多出更早的 13），核对表要注明窗口。

### 3.2 主序列摘要（与 TradingSignal across 等价）

实现映射笔记 §3 和 §5 的规则。输入是 `DemarkResult` 加窗口内的 K 线。输出字段如下：

- **状态：** `side`、`trend`（up/down）、`phase`（setup/countdown）、`step`、`target`、`setup_step`、`countdown_step`。
- **序列关系：** `rounds[]`、`last_signal`、`prev`、`second`、`bars_since_qualified13`、`setup_run`。
- **风险位：**
  - `risk9`、`risk9_at`：TD Setup 风险位，即 Setup 真实极值 ∓ 该 bar 的 true range；
  - `setup_close`：Setup 第 9 根收盘价；
  - `risk_level`、`risk13_at`、`provisional`；
  - `close13`、`tdst`；
  - `next_bar_needs`：方向 above/below 与价格。

几个待确认项先取以下默认值，待新样本验证：
- rounds 用规则 B。
- 13 延期（`count13_unqualified`）期间 `step` 记为 12，不算 13。
- `lastSignal` 在 setup 阶段回退到 prev 的信号。
- 不输出 `strong`。

### 3.3 AlphaBTC 推导（照搬 `dmkLive` / `cycAuto` / `regimeDelta` / `sigBlock` / `tdNew`）

**每个周期的状态：**
- `s9`：up / down / none；
- `s13`、`carry13`、`countdown`（0–13）；
- 9 和 13 距今的秒数，以最后一根已收盘 K 线的收盘时刻为「现在」；
- `beyond_risk9`：最新收盘价是否已顺趋势越过 `risk9`，没有 risk9 时为 null。

**Regime：** 只用 1h（日内）和 4h（跨天）两个锚点周期，取值如下：

| s9 | s13 | Regime |
|---|---|---|
| up | 否 | `decay`（突破减弱） |
| up | 是 | `rev`（反转阴跌） |
| down | 否 | `rev`（反转阴跌） |
| down | 是 | `pump`（阴跌爆拉） |
| none | — | `none`（9 未确认） |

锚点周期不是 fresh、delayed 或 simulated（fixture 模拟数据，界面标注「模拟」）时，Regime 记为 `unavailable`；过期或缺失的周期不返回任何数值。

**信号：**
- 信号 1：9 确认后出现，价格取 `setup_close`，基础 2 档。
- 信号 2：13 出现后出现，价格取 `close13`（可能为空），基础 3 档。
- 方向：s9 为 down 时是 BUY，为 up 时是 SELL。
- 后端同时返回两种档位：按日内 Regime 调整后的、按跨天 Regime 调整后的。
  - `pump`：BUY 加 1 档，SELL 减 1 档。
  - `rev`：BUY 减 1 档，SELL 加 1 档。
  - 其余情况不调整。
  - 结果限制在 1–5 档。
  - Regime 为 `unavailable` 时档位等于基础档；界面依据对应 Regime 的值，在档位旁标注「基础档 · regime 不可用」。

**新趋势：**
- Countdown 期间有 `second` setup 时取 `second`，否则在 setup 阶段取主序列本身。
- 输出方向、`n/9`、是否已确认，以及距开始或距 9 确认的秒数。

**看板映射放在前端：**
- 日内网格：各列都用日内 Regime。
- 期权双卖：各列都用跨天 Regime。
- 全部：5m / 15m / 1h 用日内 Regime，4h / 1D 用跨天 Regime。
- 两个校准开关由前端控制，默认开。

## 4. 架构与数据流

```text
Binance → 现有 refresh 任务 → bar_revisions（不变）
                                   │
GET /market-context?source&symbol[&market_at&knowledge_at]
   └ 5 个周期：repository.read(最近 499 根已收盘) → evaluate_demark(v2)
        → summary.summarize() → alphabtc.derive() → 过期判定
   └ 1h / 4h → Regime → 各周期信号档位
   → MarketContext（只读、纯计算、不写库）
```

**新增模块，全部为纯函数，不访问网络：**
- `indicators/demark/summary.py`：主序列摘要和风险位。
- `indicators/regime/alphabtc.py`：9/13 状态、Regime、信号档位、新趋势。
- `context.py`：读取 5 个周期、判断新鲜度并组装结果，不含规则逻辑。

**接口：**
- 新增 `GET /api/wheelhouse/v1/market-context`，返回 `MarketContext`。
- 可选参数 `market_at` / `knowledge_at` 用于历史回放；不带参数时取当前时刻。
- 这是增量接口，`contract_version` 保持 `"1"`。
- 更新 `openapi.json`、`api-schema.d.ts` 和前端 Zod schema。

**新鲜度：**
- 每个周期沿用现有的 `data_state`，按最后一根已收盘 K 线相对当前时刻判断。
- 状态有：fresh、delayed、stale、unavailable、simulated；历史是否够 499 根另用 `history_complete` 标记，不混进状态。
- 5 个周期各自独立标注；不像 AlphaBTC 那样超过 30 分钟就整块隐藏。

**刷新：** 接口本身不抓数据。核对视图打开时和点「全部刷新」时，对不是 fresh 的周期各提交一次现有的 refresh 任务。视图每 30 秒重新读取一次接口。

## 5. 核对视图（1420，TD Sequential tab）

- **位置：** 图表卡片与 Snapshots & replay 之间，新增一个可折叠区块：「Cross-timeframe check · AlphaBTC parity」。
- **不改动：** 图表和右侧 DeMark 面板。
- **顶部一行：**
  - 日内 Regime（1h）与跨天 Regime（4h）的名称和依据；
  - 看板切换：日内网格 / 期权双卖 / 全部；
  - 短期、长期两个校准开关；
  - 「全部刷新」按钮；
  - 各周期的数据时间与状态。
- **主体：** 表格按 5m、15m、1h、4h、1D 分列，行依次为：
  - 9 状态；
  - 13 状态与 Countdown n/13；
  - Setup n/9；
  - 9 距今、13 距今；
  - 趋势衰退阈值（risk9），并标出现价是否越过；
  - 本轮 / 上轮反转位（risk_level + provisional）；
  - 下一根需要的收盘条件；
  - BUY/SELL 1 的价格与置信度；
  - BUY/SELL 2 的价格与置信度；
  - 新趋势进度；
  - TDST；
  - 使用根数与窗口。
- **文案：**
  - 中文模式下，状态名与 AlphaBTC 原文一致（反转阴跌 / 突破减弱 / 阴跌爆拉、弱…强），方便逐字对照。
  - 英文模式用直译，另附原文。
  - 所有文案走现有 i18n。
- **标注：**
  - 一行说明：本表只用已收盘 K 线，AlphaBTC 含未收盘 K 线，两者可能差一根。
  - 不可用的格子写 Unavailable，并悬停说明原因。
- **视觉：** 沿用现有页面样式，不做新视觉设计。

## 6. 核对工具与测试

**测试样本：**
- 把 16:28 快照整理成测试样本：TS 的 across 与 risk 字段、所用 K 线、重建的未收盘那根。
- 只保留行情结构，去掉 AI 解读文字，不含任何账户数据。
- 存放于 `services/analytics/tests/regime/fixtures/`。

**单元测试：**
- `summarize` 在样本上与 TS 字段逐项一致。5m 的 `prev` 单独断言本地值，并注释差异原因。
- AlphaBTC 规则表：`carry13` 的各种分支、Regime 五种取值、档位上下限、两种 Regime 同时存在、`unavailable` 时退回基础档。
- `context`：
  - 截止时刻只取已收盘 K 线；
  - 不足 499 根时 `history_complete=false`；
  - 锚点过期时 Regime 为 unavailable；
  - 回放参数生效。

**前端测试：** Zod schema、看板映射、核对表渲染不可用状态。

**核对脚本 `scripts/verification/compare_alphabtc_context.py`：**
- 以研究脚本为基础改写。
- 输入：一份 AlphaBTC `/api/td9` JSON 和抓取时刻。
- 脚本自己从 Binance 取 K 线，并用 1m/1s K 线重建未收盘那根。
- 输出逐字段对照报告。
- 不访问 AlphaBTC 或 TradingSignal，不读取任何凭据。

**新快照的采集：** 用户说「抓快照」时，由我通过用户已登录的 Chrome 读取 `/api/td9`，存为新样本并运行对照。结果写入 `docs/features/demark-regime/PARITY-LOG.md`。

**浏览器验收：** 在 1420 打开 5m 与 1h 页面，与 AlphaBTC 并排检查，并检查窄屏下核对表可以横向滚动。

## 7. 不在本期范围

- 市场周期（链上六态与指数），另写 spec。
- 首页五档、Regime Plus 事件监测、AI 解读、期权与风控动作、回测表。
- 未收盘预览行。
- 正式 UI 设计。
- 对 TD 图表 DeMark 窗口的调整。
- 自动定时抓取 AlphaBTC：需要登录，只在用户要求时手动抓。

## 8. 风险

- **行情源差异：**
  - TS 的行情源不是 Binance 现货，15m 收盘价平均差约 4.6 USDT。
  - 5m 等短周期在阈值附近可能差一个 13。
  - 这是已知、可以解释的差异，不会为了凑数调整规则。
- **只有少数样本：** 规则 B、延期显示等默认值可能被新样本推翻；推翻时只改 `summary.py` 并补样本。
- **AlphaBTC 规则会变：** 源码注释写着「口径待用户校正」。本期以 2026-09-28 核验的版本为准，并在核验笔记中记录版本。
