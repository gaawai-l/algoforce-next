# AlphaBTC 市场周期与 Regime 规则核验

核验日期：2026-09-28。页面版本：主站 v2.95.0。

## 证据来源与边界

- 读取的是用户登录后浏览器实际运行的客户端脚本：主站内联脚本（145,396 字符），以及 `/onchain/cycle-dashboard` 的逻辑脚本（135,149 字符）。
- 读取了主站 `/api/td9` 的返回结构。该接口转发的是 TradingSignal 多周期 TD 数据；直接请求上游 `tradingsignal.pro/api/methods` 会返回 403，要求 API key。
- 服务端代理怎样计算 `risk9`、`nextBarNeeds`、`read.text`，以及它的源码，本轮没有取得。
- 用户的 DeMark 实现已按 TradingSignal 对照测试并一致（见 [RESULTS](../docs/features/demark/RESULTS.md)）。因此 Regime 可以直接由本地的 1h/4h DeMark 结果推导，不依赖上游接口。

| 结论 | 验证方式 | 状态 |
|---|---|---|
| 周期六态分类 | 用 bitview.space 公开日线在本地复算：当前状态、本段天数、切换次数、各段统计与看板一致 | 已验证 |
| 四成分周期指数 | 本地复算 A/B/C/D、综合值和 1/7/30/90 日变化，与看板一致 | 已验证 |
| DeMark 三态 Regime 与置信度 | 用同一份 `/api/td9` 按源码规则手推，与页面自动选中结果、5 个周期的置信度文字一致 | 已验证（单一时点） |
| 首页五档 | 源码只在点击时赋值，没有自动来源 | 已验证 |

## 1. 三个容易混淆的“周期 / regime”

| 名称 | 所在位置 | 输入 | 自动还是手动 |
|---|---|---|---|
| `across[].regime: up/down` | `/api/td9` 字段 | TD 序列 | 自动。只表示当前在数的趋势方向（SELL setup = up，BUY setup = down），**不是**页面上的 Regime |
| 日内 / 跨天 Regime（反转阴跌 / 突破减弱 / 阴跌爆拉） | 主站 ⑤ 动态市场观点 | 1h、4h 的 DeMark 9/13 状态 | 自动，可手动覆盖 |
| 周期六态（Advance … Capitulation）与 0–100 周期指数 | `/onchain/cycle-dashboard` | BTC 链上成本与盈亏（BRK / bitview.space） | 自动 |
| 首页五档（熊市投降 … 牛市终结） | 主站 ④ 周期观点 | 无 | **手动**。默认“初期突破”，源码中没有与六态或指数的映射 |

## 2. DeMark Regime：精确规则

### 2.1 每个周期先归成 9 / 13 状态（`dmkLive`）

输入是 `/api/td9` 中该周期的一项 `x`。

```text
prevQ13  = x.prev.qualified && x.prev.countdown >= 13
tsEx13   = rounds 中最后一个 countdown>=13 且有 exhaustedTs 的时间
ts9Last  = lastSignal.kind==9 ? lastSignal.ts : 0
lastIs13 = lastSignal.kind==13 || (tsEx13 && tsEx13 > ts9Last)
carry13  = lastIs13 && phase != countdown && setupStep < 9 && (prevQ13 || countdownStep >= 13)
up       = carry13 ? (prev.side == SELL) : (x.regime == up)
setupDone= carry13 || phase == countdown || setupStep >= 9
s9       = setupDone ? (up ? 绿 : 红) : 未确认
cd       = carry13 ? 13 : (phase == countdown ? step : 0)
s13      = cd >= 13
```

`carry13` 的含义：13 刚走完，而新一轮 Setup 还没数到 9 时，继续显示刚走完的那一轮，直到新一轮的 9 确认。

### 2.2 1h / 4h 推出 Regime（`cycAuto`）

日内 Regime 看 1h，跨天 Regime 看 4h。

| s9 | s13 = 否 | s13 = 是 |
|---|---|---|
| 绿：上涨 9 确认 | 突破减弱 `decay` | 反转阴跌 `rev` |
| 红：下跌 9 确认 | 反转阴跌 `rev` | 阴跌爆拉 `pump` |
| 未确认 | 暂无状态 | — |

- 源码注释写着“口径待用户校正”。
- 界面副标题只描述了部分情形，例如“反转阴跌”写的是“9 确认后转跌 · 反转未出”，但代码里“上涨 13 走完”也归为反转阴跌。
- **缺陷：** 该周期没有实时数据时，函数会退回到手动状态的默认值（s9 = 绿，s13 = 否），显示成“突破减弱”。本轮在数据加载前确实观察到了这个显示。本项目不能照搬这一行为，应显示 unavailable。

### 2.3 Regime 对置信度的校准（`regimeDelta` + `sigBlock`）

- **信号方向：** 下跌 9（红）对应 BUY，上涨 9（绿）对应 SELL。
- **两个信号：**
  - 信号 1：9 确认后出现，价格取 `risk.setupClose`。
  - 信号 2：13 出现后出现，价格取 `risk.close13`。
- **基础档位：** 信号 1 为 2 档，信号 2 为 3 档。
  - 阴跌爆拉：BUY 加 1 档，SELL 减 1 档。
  - 反转阴跌：BUY 减 1 档，SELL 加 1 档。
  - 突破减弱：档位不变。
  - 结果限制在 1–5 档，依次称为 弱 / 中等偏弱 / 中等 / 中等偏强 / 强。信号未出现时显示“——”。
- **视图与 Regime 的对应：**
  - 日内网格趋势反转（默认视图）：所有列都用日内（1h）Regime。
  - 期权双卖：所有列都用跨天（4h）Regime。
  - 全部：5m / 15m / 1h 用日内 Regime，4h / 1D 用跨天 Regime。
- **开关：** 短期、长期两个校准开关各自独立，默认都开。
- 这些档位是规则赋值，**不是概率或胜率**。

### 2.4 Regime 的下游用途

- ⑥ 期权策略面板只在块头显示当前 Regime 名称。
- 近端 / 远端 Call、Put 的默认动作来自所选“形态”（`pattern.acts`，例如“突破衰减”形态为近端 Call 下移、其余上移），再叠加手动修改。**Regime 不决定期权动作。**

### 2.5 单点核对（`/api/td9` asOf 1790526900）

| 周期 | 本地手推 | 页面显示 |
|---|---|---|
| 1h | s9 红，carry13 成立 → 阴跌爆拉 | 日内：阴跌爆拉（自动） |
| 4h | s9 绿，countdown 8/13 → 突破减弱 | 跨天：突破减弱（自动） |

默认视图下 5 个周期的 BUY/SELL 1、2 置信度与上述规则逐项一致。

### 2.6 新趋势监测（`tdNew`）

- 有 Countdown 在进行、旁边又冒出一段新 Setup（`second`）时，显示这段新 Setup；否则主序列本身处在 setup 阶段时，显示主序列；两者都没有时，显示「暂无新趋势」。
- 走完 9 即为「已确认」，时长从 9 确认那根算起；尚未走完时，时长从这段 Setup 的第 1 根（`setupRun.start`）算起。

## 3. 周期六态：精确规则（classifier v2）

数据：bitview.space（Bitcoin Research Kit v0.12.2）日线，公开 API，无需鉴权。起点为 2015-01-01。

```text
W   = utxos_1d_to_1w_old_realized_price     # 1 天–1 周持有者成本
STH = sth_realized_price                    # 短期持有者成本
TMM = true_market_mean                      # 真实市场均价
depth  = ln(W / TMM)
spread = ln(STH / TMM)
pvs    = depth - spread = ln(W / STH)
```

**第 1 步：每个比较量各自做滞回（死区）。**
- 状态初值：首个有效日取 `gap >= 0`。
- 之后 `gap > thr` 置真，`gap < -thr` 置假，落在 `±thr` 之内保持原状态。恰好等于 thr 也保持。
- 基准阈值：depth 0.0139，pvs 0.0133，spread 0.0028。这组数按各自日变化标准差成比例设定，平均为 0.01。
- 看板滑块范围 1–7×，**HTML 默认 5×**，实际阈值为 0.0695 / 0.0665 / 0.0140。

**第 2 步：三个布尔值 `(depth, pvs, spread)` 对应三条成本线的排序，得到六态。**

| 状态 | 中文 | 排序 |
|---|---|---|
| Advance | 上行 | W > STH > TMM |
| Breakout | 突破 | W > TMM > STH |
| Pressure | 承压 | STH > W > TMM |
| Repair | 修复 | TMM > W > STH |
| Breakdown | 破位 | STH > TMM > W |
| Capitulation | 投降 | TMM > STH > W |

- **不可能组合的保护：** `(假, 真, 真)` 和 `(真, 假, 假)` 在代数上不可能出现，但独立滞回可能锁出这两种组合。出现时沿用上一个标签。
- **缺数据：** 当日数据缺失时沿用上一个标签。
- **周期环顺序：** Advance → Pressure → Breakdown → Capitulation → Repair → Breakout → Advance。

复算结果（5×，数据截至 2026-09-27）：
- 当前状态 Breakout，本段第 5 天；
- 历史共 42 次切换；
- Breakout 共 6 段、合计 136 天，均值 22.7 天、中位数 27 天、最长 42 天。

以上全部与看板一致。当日 depth 为 +9.5%，spread 为 −5.6%。

## 4. 四成分周期指数

| 成分 | 原始通道 | bitview 序列 |
|---|---|---|
| A 未实现盈亏 | 未实现盈利占比 − 未实现亏损占比（NUPL） | `unrealized_profit_to_mcap_ratio`、`unrealized_loss_to_mcap_ratio` |
| B 已实现盈亏 | ln(已实现盈利 / 已实现亏损) | `realized_profit_sum_24h`、`realized_loss_sum_24h` |
| C 盈亏供应量 | 盈利供应 / (盈利 + 亏损供应) | `supply_in_profit`、`supply_in_loss` |
| D 年轻 / 长期资金 | ln(3 个月以内币龄的已实现市值 / 1–2 年币龄的已实现市值) | `utxos_{under_1h,1h_to_1d,1d_to_1w,1w_to_1m,1m_to_2m,2m_to_3m}_old_realized_cap`；`utxos_1y_to_18m_old_realized_cap` + `utxos_18m_to_2y_old_realized_cap`；`realized_cap` |

**每个成分的处理步骤：**
1. 在它自己的全部历史上计算滚动百分位：窗口 1460 天，至少 365 个历史值才输出，比较时历史值 `<=` 今日值计入。
2. 取 7 日尾随中位数。
3. 乘以 100。
4. B 与 D 的对数运算中加 ε = 1e-9。

**综合指数：** 四个成分等权平均。任一成分缺失时当日为空，不做“三项平均”。看板说明 A 与 C 相关系数约 0.94，所以实际有效权重并不相等，作者只做了披露，没有修正。

**区间：** 0–20 周期低位，20–40 过渡期，40–60 周期中段，60–80 过渡期，80–100 周期顶部。

**复算结果（截至 2026-09-27）：** A 45 / B 68 / C 46 / D 20，综合 45；1/7/30/90 日变化分别为 +4 / +9 / +5 / +33。与看板一致。

## 5. 与本项目现有文档的差异

- **三态标签定义不同。** [市场策略规格 §9.3](../prototypes/wheel-dashboard/MARKET-STRATEGY-SPEC.md) 的 Reversal Fade / Breakout Decay / Compression Reversal 是 Wheelhouse 自定义的，与 AlphaBTC 实际规则不同：
  - 规格的 Breakout Decay 不区分方向；AlphaBTC 的“突破减弱”只对应上涨方向，下跌 9 未到 13 归为“反转阴跌”。
  - 规格的 Compression Reversal 要求 Risk 有效且反向 Setup ≥ 1；AlphaBTC 的“阴跌爆拉”只看下跌 13 是否走完，而上涨 13 走完归为“反转阴跌”。
  - 如果目标是复刻数据，需要先决定以哪一套为准，并同步修订规格。（已决定：见 docs/features/demark-regime/SPEC.md）
- **Phase 的待验证项已有答案。** [接入计划](../docs/features/demark/INTEGRATION-PLAN.md) P0 列出的六态条件、死区、初始态和缺失态，第 3 节都已给出。五档与六态的映射在源码中不存在，不能自动生成五档。
- **多周期组合尚未实现。** 本项目目前各周期独立计算。要在 5m 页面上给出日内 Regime，需要在同一 as-of 取得已收盘的 1h 结果。
- **数据过期处理。** AlphaBTC 在 TD 数据超过 30 分钟未更新时隐藏全部 DeMark 信号。本项目应按各周期自身的 K 线节奏判断 stale，不能显示默认 Regime。

## 6. 仍待确认

1. **主序列选择。** 本地 `DemarkResult.sequences[]` 可能同时有多条活动序列（`retain_active`），而 TradingSignal 的 across 每个周期只给一条主序列。需要一条选择规则，把本地结果映射到上面的 s9/s13，再用 1h/4h 的历史快照对照验证。（已决定：见 docs/features/demark-regime/SPEC.md）
2. **是否保留作者的缺陷。** 无数据时默认显示“突破减弱”、`cta` 视图下隐藏的 4h/1D 列也用日内 Regime——这些是否属于“复刻”范围。（已决定：见 docs/features/demark-regime/SPEC.md）
3. **死区倍数。** 周期六态是否固定为 5×，是否需要可调。
4. **首页五档。** 是否实现为手动选择的研究标签，还是不做。
