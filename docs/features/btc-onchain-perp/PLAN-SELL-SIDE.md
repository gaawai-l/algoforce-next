# 计划：state-report 图 1A / 1B（Sell Side Breakdown by LTH & STH）

日期：2026-10-19（独立复核后修订）。依据：[CHART-VERIFICATION.md](CHART-VERIFICATION.md) 的 SR-1A、SR-1B，以及阶段 A 的实现方案（`.local/research-samples/alpha-dashboards-2026-10-16/verification-2026-10-19/verify/SR-1A-A.md` §3、`SR-1B-A.md` §3）。

用户 2026-10-19 的要求："先做出来让我有东西检查"。所以凡是原站有现成做法的，一律照原站（SPEC D5：v1 照原站口径）；原站没有的（三栏说明），先写一版给用户审。

## 已定的做法

| 事项 | 做法 | 理由 |
|---|---|---|
| 口径 | 三种 Measure（Realized P&L $ / Spent vol BTC / Spent vol $）、三档 Exclude（Off / <1h / <24h）、三档 Smoothing、四档 Span，全照原站 | 照原站；数据都有，只多 18 条序列。SPEC §1"不做图 1 的多种口径"随之删去 |
| 计算分层 | worker 逐小时算出各条腿（原站 loader 那一段），存进 derived；平滑、行过滤、Span、Relative 分母在前端算（原站 `build()` 那一段） | 隐藏图例里的某条腿会改变分母和保留的行，这一步本来只能在前端做；读接口仍然只读库 |
| 位置 | Flows 新增子视图 **Sell side**（`flow=sellside`），排在 Seller pressure 和 Perp states 之间；默认子视图不变 | 不打乱已有页面；以后图 2 也放这里 |
| 排布 | 照原站：1A 在上、1B 在下；两张图各有一行控件，两行同步；四条腿的开关也同步；1B 控件行后有一句 "Span, Smoothing, Measure and Exclude all drive both A and B" | 照原站 |
| 规则 | 只有 v1：读数取最后一行（正在形成的小时也算），按 SPEC 标出 forming；`rules` 恒为空 | 照原站；O1 等以后再说 |
| 三栏说明 | 原站没有。按 Flows 约定写 What it shows / What extreme values imply / How to read 的中英文初稿，交用户审 | AGENTS.md 规定 Flows 每张图都有三栏 |
| 配色 | LTH 用 sky（深色为盈利、浅色为亏损），STH 用 rose（同样深浅区分） | 语义与原站一致（蓝为长期、红为短期），色值沿用本地主题；与本地卖压图 1 的 LTH sky、STH rose 一致 |
| 图高 | 随宽度变化，300–440px | 核对时发现本地 Flows 图普遍太扁；原站为 440 |
| 悬停 | 沿用本地卖压图的做法：悬停或方向键时，图例和 foot 改为显示该小时 | 与本地其他图一致，也支持键盘 |

## 后端

1. `onchain/brk.py`：新增 `SELL_SIDE_SERIES`，即图 1 要用、而 `HOUR1_SERIES` 没有的 18 条序列（量的 BTC/USD 版本，以及 `utxos_1h_to_1d_old_*`）。**不并进 `HOUR1_SERIES`**：卖压的门控、O3 的补行和 `PRESSURE_REASONS` 都按它判断，并进去会让新序列一缺就把卖压三图打掉。
   - 一次增量请求最多 29 个名字，约 1,400 字符，低于 BRK 的约 2,000 字符上限，不改分片逻辑（图 2 扩到 138 条时再改）。
2. `onchain/sellside.py`（新，纯函数）`sell_side(rows, *, computed_at) -> SellSide | None`，逐条照原站 loader（`state-report/raw/script_3_app.js:163-217`）：
   - 回看 2600 个小时位置（`V1_LOOKBACK`），按时间对齐。
   - 行门控：本小时价格不为空，且 12 条主腿（3 种 Measure × LTH/STH × profit/loss）在本小时和上一小时都不为空。
   - 每条腿 `max(0, C[h] − C[h−1])`。
   - 剔除：6 个 STH 键 × 2 个群体（<1h、1h–1d），每个群体先 clamp 再求和；12 个值里有任何一个为空，就这一小时全部不剔除，并计入 `xgap`。
   - 残差 `max(0, 腿 − 剔除量)`，用原值相减，只取整一次。
   - 取整：P&L 取 $100，USD 量取 $1000（都是 0.5 进位，同 `Math.round`）；BTC 量取 0.1 BTC，用 `Decimal` 半进位（同 `toFixed(1)`）。价格也取到 0.1（原站 `PX` 就是这样存的，否则图例价格会有 $1 的差）。
   - 输出列式数据：`at[]`、`price[]`，以及 `pnl`/`volb`/`volu` 各 8 列（LTH profit/loss、STH profit/loss 的 Off、x1、x24 三版），另有 `last_at`、`latest_at`、`kept`、`xgap`、`qc`（`xgap>0` 时为 `intraday_legs`）。
3. `onchain/sync.py`：
   - hour1 阶段取 `HOUR1_SERIES + SELL_SIDE_SERIES`；新序列第一次没有存量时，走现有的整段回填（`-3000`）。
   - 卖压门控改为只看自己的序列：`not (hour1_missing & set(HOUR1_SERIES))`。
   - 缺失原因同时覆盖新序列。
   - 新增 `_derive_sell_side`，紧跟在 `_derive_pressure` 之后调用，与卖压共用 hour1 阶段的完成时间。计算出错时照 cost basis 的做法隔离：记固定码 `sellside_failed`、清掉旧结果，不影响其他视图和本轮状态。
   - `VIEWS` 加 `"sellside"`。
4. `rules.py`：`View` 加 `"sellside"`（未实现任何规则）。
5. `onchain/models.py` + `onchain/api.py`（`/status` 不改，它的 hour1 数据集仍只说卖压）：`GET /api/wheelhouse/v1/onchain/sell-side` → `SellSideView`，只读 derived。字段：`data_state`、`reasons`、`refreshing`、`forming_at`、`last_at`、`at`、`price`、`pnl`、`volb`、`volu`、`xgap`、`qc`、`brk_version`、`rules`、`rules_pending`。没有数据时 `unavailable`，各列为空，不用 0 代替。
6. `make contract` 重新生成 `openapi.json` 和 `api-schema.d.ts`。

## 前端

1. `sell-side.ts`（新，纯函数，照原站 `build()`，`state-report/raw/script_2_app.js:820-866`）：
   - 按 Measure 和 Exclude 取四条腿；按行做尾随 SMA（running sum，前 w−1 行丢弃）；只保留可见腿合计 > 0 的行；按行数取最后 Span 行。
   - 照 d3 7 的 `nice()`（count 10）和 `ticks(5)` 算 1B 的 Y 轴；价格轴的范围是可见行价格的最小到最大，两头各加 `(最大−最小)×8%`（为 0 时加 1），不做 nice，`ticks(5)`。
   - 价格线照原站断开：在服务给的全部行上判断与上一行是否相差一小时，不相连的那一点不画；因合计 ≤ 0 被丢掉的行不打断线。
   - 某个选择下一行都不剩时（例如只留一条全为 0 的腿），显示"此图暂无数据"，不画成 0。
   - 格式照原站：占比 `.1%`；USD 为 `$2.0M`、`$1.16B`、`$780,288`；BTC 为 `14,119 BTC`、`45.9 BTC`；轴上 `$` 加 SI 前缀（BTC 不带单位）；foot 为 `19 Oct 2026 · 05:00 UTC · 24-hour mean · realized gain / loss, USD · total $9.7M · STH: >24h old coins only`。
2. `sell-side-charts.tsx`（新）：一次查询（每 5 分钟刷新），状态提示与卖压页相同（unavailable / delayed / stale / forming / refreshing / reasons / QC），两块面板（Relative / Absolute）。
   - 每块面板：标题、控件行、图（每小时一根堆叠柱，缺行留空；价格线在右轴，不连续处断开；forming 那一列描边）、图例（可点击隐藏某条腿，不能全部隐藏；Relative 在少于 4 条时提示分母变了）、foot、三栏说明。
   - 复用 `seller-charts.tsx` 的 `useChartWidth`、`timeTicks`、`runs`、`percent` 等，改为导出。
3. `flows-panel.tsx` 加第三个子视图；`client.ts`、`onchain-contract.ts`（zod，校验各列等长）、`i18n.ts`（中英，原站的中文直接搬）、`market.css`。

## 测试与验证

- **后端黄金样本**：2026-10-19 05:30:50 UTC 同刻抓取的 25 条 BRK 序列（每条 1001 点），放进 `tests/onchain/fixtures/brk-2026-10-19T0530Z/`。期望值由参考实现 `recompute_c1b.py` 生成；该实现已与原站页面的 `DATA` 逐格比对（96 行 × 25 键，0 处不一致）。要求本地各条腿与期望值逐值相等。
- **后端单元测试**：负差 clamp；群体先 clamp 再求和；剔除全有或全无并计 `xgap`；12 条主腿任一缺失时删本行；价格缺失时删行；残差先减后取整；三种取整的边界（含 0.05 BTC）；回看 2600；按时间对齐。
- **sync 回归**：只缺一条图 1 专用序列时，卖压照常、Sell side 为 unavailable 并说明原因；接口不访问网络。
- **前端黄金**：把后端在同一样本上的全部 995 行做成前端样本（约 250 KB），原站核对过的 41 个用例（27 种组合、4 档 Span、8 种隐藏腿组合）的 1B 图例、foot、Y 轴上限与刻度、行数、首行时间逐字一致，1A 占比与参考实现一致。
- **前端单元**：SMA 预热丢行；可见合计 ≤ 0 的行被丢；Span 按行；隐藏腿后分母和提示；最后一条腿不能隐藏；两块面板的控件同步；zod 契约；中英文键一致。
- `make check` 全绿。
- **浏览器**：在本地打开 `?method=flows&flow=sellside`，与原站同一时刻比默认读数和几组控件；检查 390px（弹窗法）和控制台；截图给用户。

## 不做

- O1–O6 在这张图上的版本、tooltip 浮窗（改用图例显示悬停的小时）、图 2。
