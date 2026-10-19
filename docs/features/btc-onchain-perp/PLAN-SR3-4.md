# 计划：state-report 图 3 / 图 4（Buy & Sell Side By Cost Basis，及其 Age Breakdown）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

- 日期：2026-10-20，第 3 版。
- 本版按以下三项修订：
  - 用户 2026-10-19 的裁定（方案 C）；
  - 第一轮评审 `review-PLAN-SR3-4.md`（0 Critical、4 Important、18 Minor）；
  - 第二轮评审 `review-PLAN-SR3-4-v2.md`（0 Critical、3 Important、18 Minor），以及 controller 的裁定。两份评审都在 `.superpowers/sdd/state-report/` 下。
- **分支：** created from main after Chart 2 merges，即等图 2 合入 main 之后，从 main 新建一条分支执行。**绝不在 `claude/state-report` 上执行**：那条分支上有已取消的 SR2 提交（3f2785d..be43339），其中的图 2 实现与用户选定的不同。

**Goal:** 在 Flows 新增子视图 **Cost basis**（`flow=costbasis`），按原站口径完整做出图 3（Buy & Sell Side By Cost Basis）和图 4（同图的 Age Breakdown），保留原站的全部交互。

**Architecture（方案 C）：** 分工与原站的 loader / 图表代码相同（L 对应 worker，A 对应浏览器）：
- **worker 只取数、存输入**，相当于原站的 loader：
  - $500、$200 两个网格上，D 与 D−1/7/30/90 天的分群体供应列；
  - 4 个年轻币龄组；
  - 每个 $500 桶的成交下界档（AGEFLOOR）；
  - QC 结果。
- worker 不做 KDE、峰检测和 GMM。
- 读接口 `GET /onchain/cost-flow` 只读库。
- **浏览器用 TypeScript 做全部计算**，从原站 `raw/` 的 JS 逐行移植，每个函数注明行号：
  - 分段、取行；
  - KDE、峰检测、GMM 和 BIC；
  - 图例、表格。
- 引擎结果按真实输入缓存，悬停和读数不触发重算。
- 图 7 仍用服务端的 Python 引擎 `costbasis.py`，不改。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、SQLite（analytics 服务）；React、TypeScript、zod、vitest（Wealthfolio overlay）。

**Spec 与依据：**
- [SPEC.md](SPEC.md)：D5，「架构」一节的"读接口不现算"。
- [CHART-VERIFICATION.md](CHART-VERIFICATION.md)：SR-3、SR-4 两节，以及共性问题第 10、11 条。
- [PLAN-SELL-SIDE.md](PLAN-SELL-SIDE.md)：分层样板。
- 研究资料（不入库），以下用 `R/` 代指 `/Users/gary/code/AlgoForceNext/.local/research-samples/alpha-dashboards-2026-10-16/`：
  - `R/verification-2026-10-19/verify/SR-3.md`、`SR-3-A.md`、`SR-4.md`、`SR-4-A.md`；
  - 样本目录 `R/.../verify/sr3/`、`sr4/`；
  - `R/state-report/NOTES.md`；
  - 原站脚本：**A** = `R/state-report/raw/script_2_app.js`，**L** = `script_3_app.js`，**H** = `state-report.html`。

## 前提

- **PLAN-SR2 已取消。** 图 2 由另一会话在主检出 `/Users/gary/code/AlgoForceNext` 中实现，计划是那里的 `docs/features/btc-onchain-perp/PLAN-AGE-COHORTS.md`，用户选定该版本。本计划在它合入 main 之后执行。
- 本计划不依赖任何 PLAN-SR2 的名字，所用符号一律按名字定位。下表按主检出的工作区记录预期，第二轮评审已于 2026-10-20 逐项核对；Task 1 的第一步会在 main 上再核实一次，任一项不在或形状不符就停止并报告，不要自行补建：

| 符号 | 文件 | 预期形状 | 本计划的用途 |
|---|---|---|---|
| `AGE_COHORTS` | `onchain/brk.py` | 23 个 cohort 名的 tuple，顺序照 L:33-37，前 6 个是 `utxos_under_1h_old` … `utxos_2m_to_3m_old` | `AGE_URPD_COHORTS = AGE_COHORTS[:6]` |
| `MAX_SERIES_CHARS` | `onchain/brk.py` | `2_000` | 核对 day1 请求长度 |
| `BANDS` | `onchain/agecohorts.py` | 12 个 `(档名, cohort tuple)`，前 4 个是 <1d、1d–1w、1w–1m、1m–3m 及其 cohort | 年轻组的分组 |
| `URPD_SET`、`URPD_COHORT`、`URPD_AGG`、`DAY1_SERIES`、`Urpd`、`BrkClient.urpd` | `onchain/brk.py` | 存在 | 取数 |
| `_cents`、`PAST_DAYS == (1, 7, 30, 90)`、`weighted_kde`、`find_peaks` | `onchain/costbasis.py` | 存在 | 取整、窗口、交叉核对 |
| `final_from`、`day1_state`、`DataState` | `onchain/models.py` | 存在 | 新鲜度 |
| `day_start` | `onchain/api.py` | 只在 api.py 里定义 | Task 2 把它移到 `onchain/models.py` |
| `OnchainSync._urpd`、`_save_urpd`、`_derive`、`_refresh`、`DAY1_VIEWS`、`VIEWS` | `onchain/sync.py` | 存在；`_refresh` 已有图 2 的 age 阶段，但 day1 阶段和 `absent` 仍按 `DAY1_SERIES` 写；`VIEWS` 已含图 2 的视图 | 取数与派生 |
| `View` | `rules.py` | Literal，已含图 2 的视图名 | 加 `"costflow"` |
| `brk_transport` | `tests/onchain/onchain_fixture.py` | 参数含 `urpd_dir`、`urpd_dates`、`urpd_missing`、`urpd_fail`、`missing` | 加 `age_dir` |
| `Segments`（泛型 `T extends string \| number`） | `…/wheelhouse/sell-side-charts.tsx` | 已导出 | 分段按钮 |
| `useChartWidth` | `…/wheelhouse/seller-charts.tsx` | 已导出 | 宽度 |
| `ticks`、`si` | `…/wheelhouse/sell-side.ts` | 已导出 | 刻度 |
| `BANDS12` | `…/wheelhouse/age-cohorts.ts` | 12 个档名，`as const` | 币龄档名 |
| `reasonText`、`rulesNote`、`MessageKey`、`TextFn` | `…/wheelhouse/onchain-text.ts`、`i18n.ts` | 已导出 | 原因、规则行、文案 |
| `Flow`、`flows`、`LABELS` | `…/wheelhouse/flows-panel.tsx` | 本地常量 | 加 `costbasis` |

- SPEC 的章节号会因图 2 的修改而变化。本计划对 SPEC 的改动一律按标题文字定位，不写死编号。
- gzip 只存在于已取消的分支上，本计划不依赖它。约 150 KB 的载荷不压缩也远在客户端 5 s 超时之内。

## Brief 已定的裁定（复述）

| # | 裁定 |
|---|---|
| R1 | Flows 分五个子视图，顺序为 Seller pressure（默认）、Sell side、**Cost basis（`flow=costbasis`：图 3、图 4，以后加图 8）**、Size cohorts、Perp states。本计划新增 Cost basis。390 px 下切换条换行，不横向溢出 |
| R2 | 只做 v1，计算与原站一致（D5），`rules` 恒为空。原站已知缺陷写明原站行为，改用安全显示：缺失显示为 "—" 或留空，绝不显示为 0。逐条列为裁定 |
| R3 | 每张图下都有三栏说明，中英初稿交用户审 |
| R4 | worker 负责取数和预算。读接口只读库：处理请求时不访问 BRK，不做 KDE、GMM 或分位数。缺失或过期显示为缺失；形成中的数据要标出；运行时不用假数据或样本数据 |
| R5 | 测试不访问网络。黄金样本附 README 写明来源和日期。阶段 A/B 记录过数值的地方逐格断言。每个任务最后运行 `make check`，全部通过；改了模型运行 `make contract` |
| R6 | 计划用中文；代码、标识符、注释和 commit 用英文。文案经 `i18n.ts`，en/zh 一一对应 |
| R7 | 复用 Flows 现有图表工具。图高随宽度变化，范围 300–440 px。最后一个任务由 controller 在浏览器检查 1440 px 和 390 px |

## 用户与 controller 的裁定（有约束力）

| # | 裁定 |
|---|---|
| C | **采用方案 C（用户，2026-10-19）。** worker 只取数、存输入，不做 KDE、峰检测或 GMM；读接口只读库；KDE、峰检测、GMM 和 BIC 在浏览器里用 TS 计算，从原站 JS 移植并注明行号 |
| U1 | **保留 Manual 平滑，与原站完全相同。** width 范围 0.005–0.10、步长 0.001，peak cutoff 范围 0.01–0.40、步长 0.005，默认 0.02 / 0.05，只有选 Manual 时可拖动（A:261、266、305、310、401、404、422、425；A:1944-1959；图 4 见 A:3828-3845） |
| U2 | **图 4 的图例可以点击隐藏某一组，并重算 K、Clusters 和 M，与原站相同**（A:3743-3751） |
| U3 | 只取 6 个年轻 cohort。**QC 因此变弱**：原站的 "age bands = all" 检查不做；"age floor" 检查只覆盖 3 个月以下的币。SPEC 和核验记录都写明这一点 |
| U4、U5 | 图上的 K 用表格编号；三栏说明交用户审 |
| 第二轮 I1 | 引擎结果按真实输入缓存；悬停、键盘读数和图例悬停只读缓存，不调用引擎；滑杆的 `input` 事件用 `requestAnimationFrame` 合并为每帧一次重算；加一个统计引擎调用次数的测试；浏览器检查记录 390 px、CPU 4× 降速下的耗时；只有实测超过 100 ms 才报告为发现，不预先做 Web Worker |
| 第二轮 I2 | 再生测试对 crosscheck 样本按数值、相对误差 1e-12 比对；S1、S2 不含 libm 运算的结果，仍逐字节比对 |
| 第二轮 I3 | 以下四种缺失状态都要有文案和测试：<br>- 图 4 的 `age` 为空；<br>- 缺某个窗口；<br>- 图例全部隐藏：照原站禁止隐藏最后一个可见行（A:3745-3747），另加换 Zoom 时的复位，使"全部隐藏"无法出现；<br>- 空快照按缺失处理 |
| N1 | 采纳，并按评审补全隐藏状态与净额标签的规则（见"已定的做法"） |
| `day_start` | 移到 `onchain/models.py`。`sync.py` 本来就从那里导入，不会形成循环；`api.py` 改为从 models 导入 |

## 已定的做法

| 事项 | 做法 | 理由 / 出处 |
|---|---|---|
| **裁定 4 的落实** | **处理请求时不做任何计算**：读接口只读 `derived` 里存好的输入，原样返回；只在读取时算 `data_state`、`forming_at` 这类时间判断，并按原因码过滤。worker 只做 loader 那部分的线性工作：取整、加总、扫描下界档、QC。KDE、峰检测、GMM 和 BIC 都在浏览器里算 | R4；照 PLAN-SELL-SIDE 的分层；裁定 C |
| **两套引擎** | 图 7 用 Python `costbasis.py`（服务端），图 3/4 用 TS 的 `cost-flow-engine.ts`（浏览器），两者都移植自 A:1404-1557。以后若改算法，两处都要改。<br>**阶段 A 参考实现** = `chart3_recompute.py` 中 udiff/segments 的移植 + `costbasis.py` 的 KDE、峰和 GMM（`chart3_recompute.py:5、16-20`）。所以 TS 对阶段 A 的比对、Task 4 的 crosscheck，都是 TS 与 `costbasis.py` 之间的跨实现比对；对原站页面的锚在 Task 5、6。`costbasis.py` 本身在 24 个状态上已与页面逐格一致（SR-3.md:68）。<br>实测原站 JS 对 store-result：峰最大相对差 7.7e-16，GMM 6.0e-14（第二轮评审） | 用户要求写明两套引擎 |
| **浏览器计算的缓存与合并（第二轮 I1）** | - **行与权重**：`useMemo`，依赖图 3 为 `(view, window, holders, aging, zoom)`，图 4 为 `(view, window, zoom, toggles)`。<br>- **每一侧的 `fitSide`**：单独 `useMemo`，依赖为该图的行、权重，加该侧设置 `(smoothing, bw, minProm, mixture, kMode, kManual)`。改一侧不重算另一侧。<br>- **不进依赖**：悬停行、键盘读数、图例悬停、图宽（宽度只影响几何）。读数和图例悬停只读缓存的结果，绝不调用引擎。原站图 4 在 `mouseenter` 时调用 `render()`（A:3741），这一点**不照搬**。<br>- **滑杆**：`input` 事件立即更新滑杆旁的数值；重算用 **`requestAnimationFrame`** 合并：已有待执行的帧时只更新待提交的值，每帧最多提交一次；组件卸载时 `cancelAnimationFrame`。最终结果与原站逐事件重算的最后一次相同。<br>- **计时**：每次 `fitSide` 包在 `performance.mark` / `performance.measure("costflow-fit")` 里（User Timing API，不写日志），供浏览器检查读取。<br>- **Web Worker**：不做。浏览器检查实测超过 100 ms 时，作为发现报告 | 第二轮评审实测（桌面）：BIC 路径 72–190 ms，Manual 加 Bells 30–82 ms；手机慢 3–5 倍 |
| 位置与排布 | Cost basis 子视图：图 3 在上、图 4 在下，页头一行说明快照 | R1；A:181-444 |
| 共享状态 | Window 和 Zoom 两图共用一份状态。Holders、Aging 只属于图 3。每侧的 Smoothing、Bell curves、How many 和微调，两张图各有一套 | A:1919（`U_SHARED`）、A:3466-3487 |
| 默认值 | Window 30d、Holders All、Zoom All、Aging Hide；每侧 `{smoothing:"auto", bw:0.02, minProm:0.05, mixture:"none", kMode:"auto", kManual:4}` | A:1283-1291 |
| 快照与窗口 | D 取今天的 `all lin500`，没有就取昨天的（沿用 `_urpd`）。then 取 D−1/7/30/90 天。网格：STH 用 lin200，All/LTH 用 lin500；每个网格取该粒度下 5 天 × 3 个群体的 floor 并集（`Math.round`），取值按 `+toFixed(2)` 处理，即 `_cents`。spot 取 D 的 `all lin500` close | L:92-97、L:250-300；A:1302 |
| **then 快照的门槛** | 那一天**已收盘**就可用，即 `fetched_at ≥ day_start(day + 1)`。`day_start` 移到 `onchain/models.py`。`final_from`（次日 02:00）只用来决定要不要重取。<br>**代价（M6）**：BRK 在次日 02:00 前仍可能修订当天（`models.py` 中 `closed_day` 的说明），所以 00:00–02:00 取得的 then 快照可能漏掉晚到的区块。原站也是如此；02:00 之后的重取会纠正 | 第一轮 I1；第二轮 M5、M6 |
| **同一快照校验** | 图 3 和图 4 用到 D 的 12 份快照：all/sth/lth × lin500/lin200 共 6 份，加 6 个年龄快照。它们的 close 必须都等于 spot。<br>不相等时，worker 在同一轮把这一组和 D 的 `all lin500` 重取一次；重取 D 若返回 404，保留第一次取到的 D。<br>派生时再检查一次：<br>- 某网格不一致，记 `urpd_mismatch:<cohort>:<agg>`，丢掉这个网格；<br>- 年龄快照不一致，记 `age_urpd_mismatch`，`age` 置为 None。<br>**任何时候都不混用两份快照** | 第一轮 I2 |
| **空快照（第二轮 I3）** | `buckets` 为空的快照按缺失处理，绝不当 0：<br>- D 的记 `urpd_missing:<c>:<agg>`；<br>- then 的记 `window_missing:<w>:<agg>`；<br>- 年龄的记 `age_urpd_missing` | 缺失不当 0 |
| 图 3 的计算（TS） | 照原站逐行移植：<br>- 取差值与取行 `udiff`（A:1304-1335）；<br>- 分段（A:1346-1394）；<br>- 按侧权重（A:1397-1401）；<br>- KDE 与峰（A:1404-1457）；<br>- GMM、BIC、`fitSide`（A:1460-1556）；`samplePDF`（A:1557-1560）；<br>- 曲线绘制（A:1675-1746）；<br>- 图例（A:1748-1779）、Aging 注释（A:1786-1802）、两张表（A:1819-1876）、tooltip（A:1880-1904） | 裁定 C |
| 图 4 的计算（TS） | 照原站逐行移植：<br>- 行 `rows()`（A:3498-3526）：buy 取前 young 个年龄组，sold = then.all − (now.all − bought)，Zoom All 时阈值 0.5、两边各补 3 行；<br>- 分段（A:3528-3541）；<br>- 曲线（A:3636-3702）、图例（A:3705-3762）、表格（A:3764-3778）、tooltip（A:3780-3806） | 同上 |
| worker 的计算（Python，`costflow.py`） | 只做以下几件事：<br>- 网格 floor 并集与取整后的列（L:250-300）；<br>- 年龄组：同组 cohort 加总后取整（L:306-312）；<br>- AGEFLOOR（L:366-377）；<br>- QC（L:448-494 的子集）；<br>- 缺失与不一致的原因 | 与 L 一致 |
| AGEFLOOR | 用 day1 的 `price_high`/`price_low`，从新到旧扫描，跳过 D 之后的日子。天数按 ≤1/7/30/90/180/365/730/1095/1825/2555/3650 映射为 0..10 档，更旧或从未成交记 11（L:366-377）。从 2013-01-01 起算，与原站取 5,600 天的结果相同（SR-4-A §3.1 实测）。<br>高低价的最后一天早于 D 时，照常计算，另加原因 `age_floor_stale` | 照原站，并给出提示 |
| 新增取数 | 见"BRK 请求核对"：<br>- 6 个年轻 cohort 的 D 快照，在 `URPD_SET` 之后抓取；<br>- `price_high`/`price_low` 在 day1 阶段里单独请求（`_day1_range`），不并入 day1 主请求（执行中的裁定，见 Task 2）。<br>两者都单独定义，不并进 `DAY1_SERIES`、`URPD_SET` | 缺了只影响图 4 |
| 载荷 | 上限约 150 KB；第二轮评审实测约 117 KB，gzip 后约 29 KB。内容为：<br>- $500 网格：252 行 × 3 个群体 × 5 天；<br>- $200 网格：629 行 × 3 × 5；<br>- 年龄组：4 × 252；<br>- 下界档：252 | |
| 计算出错时 | worker 记 `costflow_failed` 并清掉旧结果，其他视图不受影响 | 照 sell side |
| QC | worker 计算，只在失败时提示，图照常画：<br>- `cohort_sum:<agg>`：任一天、任一桶 \|all−sth−lth\| ≥ 0.05；<br>- `sold_negative:<window>`：有 sold < −0.05；<br>- `age_floor`：now.all > 0.5 的桶里，比下界档年轻的组（只看前 4 组）合计 > 0.5。<br>原站的 "age bands = all" 不做（U3） | 原站 QC 只在失败时显示 |
| 形成中 | 页头和窗口跨度行都只描述数据本身，不用"today"：<br>- 页头：`forming_at` 非空时写 `includes the forming snapshot of {{day}}`；<br>- 窗口跨度行：快照仍在形成时写 `30d · 19 Sep close → 19 Oct 05:12 UTC`，已收盘时右端写 `19 Oct close` | NOTES §4 |
| 缺失 | 每种缺失都显示一句说明和原因，绝不画成 0：<br>- 缺某个窗口：`costflow.noWindow`；<br>- 缺 $200 网格：`costflow.noGrid`；<br>- 图 4 缺年龄快照、close 不一致或缺高低价：`costflow.c4.noAge`；<br>- 图 4 缺 $500 网格：`costflow.c4.noGrid`。<br>`series_missing:price_high` 这类原因只在页头列出，所以图 4 自己也要有这句说明 | 第二轮 I3 |
| Manual 与微调（U1） | Smoothing 有 Off / Auto / Manual 三档。⚙ 标签：Off 显示 `raw`，Auto 显示 `auto`，Manual 显示 `bw.toFixed(3) / minProm.toFixed(2)`，如 `0.020 / 0.05`。弹层里两个滑杆只在 Manual 时可用，值显示 `auto` 或数值。离开 Manual 时复位为 0.02 / 0.05。滑杆的 `input` 事件按上面的缓存与合并规则重算 | A:1944-1959、A:1968-1969；图 4 见 A:3828-3845 |
| **图 4 的隐藏状态与净额标签（U2、N1，完整规则）** | 1. **点击图例行**：切换该组显示；隐藏的行显示 `off`；不能隐藏最后一个可见的图例行（A:3745-3747）；点击时清除悬停（A:3750）。<br>2. **换窗口**（任一张图的按钮）：开关全部复位为 `ALL_ON`（`bOn` 4 个、`sOn` 12 个），同时清除图 4 的悬停和两张图的读数。<br>3. **换 Zoom**：保留开关（与原站相同）。但如果新图例里没有可见的 bought/sold 行，就复位为 `ALL_ON`。所以"图例全部隐藏"不会出现。<br>4. **净额标签**：只有 Zoom 为 All，且全部 16 个开关都打开时，写 `net (issuance)`；否则写 `net of what is shown`。被隐藏但不在当前图例里的档也算作隐藏。<br>5. **悬停**：只突出可见的行，其他条透明度降到 0.12（A:3605-3607）；只读缓存结果 | 原站的设计意图是"换窗口就复位"（A:3815 注释），从图 3 换窗口不复位更像遗漏。原站的 `hidden` 只看图例里的档（A:3723），这一点不照搬 |
| 配色 | 定义在 `.wh-costflow` 下：<br>- 买方 `#7fc98a`，卖方 `#e0805c`（与本地 `.wh-perp` 的 moss/rust 同值）；<br>- KDE 线与 K 点 `#5fae6b`、`#c8623f`：**新定**，取本地 moss/rust 的深色版本。原站暗色主题是 `#7a9a5c`、`#c25636`（H:58）。暗底上的对比度在浏览器检查时确认；<br>- GMM 线 `#adcf88`、`#f08c63`：原站暗色 `--mix-pos/--mix-neg`（H:65）；<br>- 币龄 12 档 `#f7bf6b … #5a83c4`（H:68-69）；<br>- 老化段：填充 .16 加描边（H:289-291）；sold 条：.45、虚线 2 2、描边 .8（H:294）；spot 虚线 22 7（H:296）；KDE 线宽 1.8；GMM 虚线 4 3（H:350-352） | |
| 图高与几何 | 图高 = clamp(宽 × 660/940, 300, 440)。<br>- X 轴范围 ±1.08 × 单侧最大堆叠量；<br>- Y 轴：图 3 在 Zoom All 时两端各留 5% 边距、下端不低于 0，±z 不留（A:1601-1614）；图 4 不留（A:3581-3584）；<br>- 柱高 max(1, 绘图高/n − (n > 200 ? 0 : 1))；<br>- KDE 缩到最高柱的 92%，GMM 缩到 85%（A:1695、1729）；<br>- 曲线用折线，原站是 Catmull-Rom，只影响线形 | R7 |
| **窄屏几何** | 纯函数 `plotFrame(width)`：<br>- 宽度 < 500：左 44、右 76、上 8、下 34；X 轴 `ticks(3)`，Y 轴 `ticks(6)`；K/M 标签 10 px；<br>- 宽度 ≥ 500：左 64、右 96、上 10、下 36；X 轴 7 个刻度，Y 轴 10 个；标签 11 px。<br>`labelX` 把 K/M 标签限制在绘图区内。spot 标签右对齐到 `width − 2`，落在右边距里。两侧控件在 < 640 px 时单列（H:414）。图例自动换行。表格外层用 `minmax(0,1fr)`，表格在自己的容器里横向滚动。切换条加 `flex-wrap: wrap` | 第一轮 I3；第二轮 M15 |
| 读数 | 悬停或键盘时，图下方读数块显示该桶的 tooltip 内容：↑/↓ 逐桶移动，Home/End 跳到两端，Esc 清除；第一次按键选中 spot 所在的行。只读缓存结果 | 本地卖压图的做法，支持键盘 |
| 规则 | `rules` 恒为空；`View` 加 `"costflow"` | R2 |

### 原站缺陷与本计划的显示（R2）

| 原站行为 | 本计划 |
|---|---|
| 图上 K 按侧编号（A:1711），表格合并后重新编号（A:1832） | 图上用表格的编号（U4）。M 本来就按侧编号，不变 |
| "auto · k" 选项文字在没有拟合结果时停在旧值（A:1716-1724）；图 4 从不更新这段文字 | 每次渲染重算：有拟合时显示 `auto · k`、`auto · k of n` 或 `auto · k (BIC)`，没有拟合时只显示 `auto`，两张图都这样 |
| 买方 K 标签压在 spot 标签上 | spot 标签放进右边距 |
| 文案写 155 天，BRK 实际是 150 天 | 写 150 天（SPEC「优化清单」已定的界面修正） |
| 90d 下 `bOn` 只有 3 个元素，第 4 组默认不画，净额 −1,361,700 仍标 "net (issuance)"（A:3491、A:3723） | `bOn` 改为 4 个元素：默认 4 组都画，净额 +40,725 "net (issuance)"，7 个聚类。手动隐藏第 4 组时，数值与原站页面一致，净额标签为 "net of what is shown" |
| 净额标签只看图例里的档（A:3723），也不看 Zoom | 见"隐藏状态与净额标签"第 4 条 |
| 只有图 4 自己的 Window 按钮会复位开关（A:3820-3823）；从图 3 换窗口不复位 | 任何一处换窗口都复位（N1）。原站隐藏的行会显示 `off`，所以不算"悄悄"隐藏；真正悄悄的情形，是被隐藏的档不在新图例里，规则第 4 条已覆盖 |
| 隐藏若干行后换 Zoom，图例可能全部是 off，什么都不画，净额却显示 `+0` | 规则第 3 条：复位为 `ALL_ON` |
| 图 4 悬停时调用 `render()` 重画（A:3741） | 悬停只读缓存，不重算 |
| 390 px 下表格把整页撑宽 | 表格在自己的容器里滚动 |
| 图 3 选 ±10% 后，图 4 也按 ±10% 画，但它的按钮里没有这一档，所以没有按钮亮起 | 照原站 |
| AGEFLOOR 的高低价落后于 D 时没有提示 | 照原站计算，另显示 `age_floor_stale` |

## 评审处理记录

**第一轮**（全部已在第 2 版落实，第二轮评审确认）：
- I1–I4 采纳。
- M1、M3、M4、M6–M16 采纳。
- M2、M5、M18 在方案 C 下已不适用。
- M17 部分采纳：QC 变弱写进文档；不每天补取 17 个 cohort，因为用户维持 U3。

**第二轮：**

| 项 | 处理 |
|---|---|
| I1 浏览器成本 | 采纳。缓存、合并、计时见"已定的做法"；调用计数测试在 Task 7、8；耗时在 Task 9 记录 |
| I2 CI 逐字节比对 | 采纳：crosscheck 按数值、相对误差 1e-12 比对；S1、S2 逐字节（Task 3） |
| I3 缺失状态 | 采纳四项：<br>- `c4.noAge`、`c4.noGrid` 的文案和测试（Task 8）；<br>- 缺窗口的测试（Task 4、7）；<br>- 全部隐藏：照原站禁止隐藏最后一行，并在换 Zoom 时复位（Task 6）；<br>- 空快照（Task 1） |
| M1 行号 | 采纳：`samplePDF` 为 A:1557-1560；滑杆为 A:1968-1969；图 4 控件为 A:3828-3845 |
| M2 阶段 A 的来源 | 采纳：见"两套引擎"一行 |
| M3 来源标签 | 采纳：90d z0 的 K1/K5/K7 与 7 个聚类、30d ±50% 的 +76,501，改标为"页面记录（图 3 同口径块）"；只有 90d z50/z25 仍是引擎复算 |
| M4 GMM 确定性 | 采纳：写进 Task 4 |
| M5 `day_start` | 采纳：移到 `models.py`（Task 2） |
| M6 已收盘的代价 | 采纳：见"then 快照的门槛"一行 |
| M7 `_flow_set` 的输入 | 采纳：见 Task 2 |
| M8 Python 的 `YOUNG` | 采纳：见 Task 1 |
| M9 N1 补全 | 采纳：见"隐藏状态与净额标签" |
| M10 hilo 元素 | 采纳：元素 0 = `price_high`，元素 1 = `price_low` |
| M11 D 的快照份数 | 采纳：库副本里 D 有 9 份，样本目录收其中 6 份 |
| M12 TS 类型导出 | 采纳：见 Task 4 |
| M13 两种新颜色 | 采纳：标为新定，浏览器检查对比度 |
| M14 CHART-VERIFICATION 第 11 条 | 采纳：Task 9 补一句 |
| M15 标签限制 | 采纳：`labelX` 加测试（Task 7） |
| M16 拆 T5 | 采纳：拆为 Task 5（图 3 读数）和 Task 6（图 4 数据与开关）；Task 4 先做引擎、后做数据层 |
| M17 前提表 | 采纳：`_refresh` 一行已改 |
| M18 两套图 2 | 采纳：分支一行写明不在 `claude/state-report` 上执行；gzip 不在本计划范围 |

**拒绝的项：** 无。

## BRK 请求核对

URL 长度上限约 2,000 字符（`brk.py` 的 `MAX_SERIES_CHARS`）。

- **URPD**：每小时多 6 个请求（`/api/urpd/utxos_*_old/<D>?agg=lin500`），每个约 70 字符。close 不一致时再多 12 个：D 的 `all lin500`、5 份网格快照和 6 个年龄快照。
- **day1**：`price_high`、`price_low` 在 day1 阶段里单独请求，不并进 day1 主请求（执行中的裁定：它失败时不能连累周期、价位和图 7）。主请求的 `series` 参数仍是 115 字符，高低价请求 20 字符，都远低于上限。每轮增量比原来多 1 个请求。首次回填，以及每次 BRK 版本变化触发 `_replace` 时：主请求的 6 条序列按 `MAX_POINTS` 分 2 片，高低价另有 1 个请求，共 3 个，与并入时分 3 片的数量相同。

## Global Constraints

- 只读，不做交易。数据只来自 bitview.space 的公开 BRK。日志只记路由、固定错误码和耗时。
- 计算照原站 v1，`rules` 恒为 `[]`。缺失或过期显示为缺失，不画成 0；空快照也是缺失；不同快照绝不混用。
- 读接口不访问网络、不做计算。KDE、峰检测、GMM 和 BIC 只在浏览器里运行，结果按真实输入缓存。运行时代码不得 import 测试样本 JSON。
- 测试不访问网络；黄金样本附 README。
- 每个任务最后在 worktree 根目录运行 `make check`，全部通过；改了 Pydantic 模型先运行 `make contract`。
- 文案经 `i18n.ts`，en/zh 一一对应。代码、注释、commit 用英文（conventional commits）。
- 单独跑测试的命令：
  - 后端：`.venv-foundation/bin/python -m pytest services/analytics/tests/onchain/<file> -q`；
  - 前端：`python3 scripts/foundation.py sync && npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend exec vitest run src/features/wheelhouse/<file>`。
- 别的计划改过的文件，按符号名定位，只做增量。不改 `costbasis.py`。

## Review Focus

1. **慢设备上的交互**：手机上拖 Manual 滑杆、悬停、键盘读数。
   - 悬停和读数不应调用引擎；滑杆的连续输入，每帧只重算一次。
   - 由 Task 7 的 `never calls the engine for hover or the keyboard readout`、`coalesces ten slider inputs into one recompute` 覆盖；Task 9 记录 4× 降速下的实测耗时。
2. **首次部署或 day1 回填之前，图 4 没有输入**：图 4 应当显示一句说明，没有图、图例和表格；图 3 照常。由 Task 8 的 `says what is missing in Chart 4` 覆盖。
3. **点了很多图例再换 Zoom**：不应出现"全部隐藏、净额 +0"。由 Task 6 的 `resets the toggles when a zoom leaves nothing visible` 覆盖。
4. **每天 00:00–02:12 UTC**：1d 窗口照常可用。由 Task 2 的 `test_then_snapshot_counts_once_its_day_closed` 覆盖。
5. **BRK 在一轮内出了新区块**：重取一次，仍不一致就显示为缺失，绝不混用。由 Task 1 的 `test_cost_flow_never_mixes_snapshots` 和 Task 2 的 `test_d_set_close_mismatch_refetches_once` 覆盖。

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `services/analytics/src/wheelhouse_service/onchain/costflow.py`（新） | worker 侧的纯函数：网格列、年龄组、AGEFLOOR、QC、校验与原因，组装 `StoredCostFlow` | 1 |
| `onchain/brk.py` | `AGE_URPD_COHORTS`、`AGE_FLOOR_SERIES` | 1、2 |
| `onchain/sync.py`、`onchain/models.py`（`day_start`）、`rules.py` | 取数、同一快照校验、派生 `costflow` | 2 |
| `onchain/models.py`、`onchain/api.py` | `CostFlowView`、`GET /cost-flow` | 3 |
| `tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow/`（新） | 黄金样本与 README | 1 |
| `tests/onchain/fixtures/brk-2026-10-16/day1_price_{high,low}.json`（新） | 让 P1 的假 BRK 能回答新的 day1 序列 | 2 |
| `tests/onchain/onchain_fixture.py` | `age_dir` 参数 | 2 |
| `tests/onchain/test_onchain_costflow.py`（新）、`costflow_sample.py`（新） | worker 测试；前端样本生成器 | 1、3 |
| `…/wheelhouse/cost-flow-engine.ts`（新） | 原站引擎的 TS 移植（A:1404-1560） | 4 |
| `…/wheelhouse/cost-flow.ts`（新） | 两张图的行、分段、图例、表格、tooltip、开关、格式化和几何 | 4–7 |
| `…/wheelhouse/cost-flow-charts.tsx`（新） | 子视图和两张图的组件 | 7、8 |
| `…/wheelhouse/cost-flow-sample.json`、`cost-flow-sample-0512.json`、`cost-flow-crosscheck.json`、`cost-flow-expected.json`（新） | 测试样本 | 3、4 |
| `…/wheelhouse/onchain-contract.ts`、`client.ts`、`onchain-text.ts`、`flows-panel.tsx`、`i18n.ts`、`market.css` | 契约、接线、文案、样式 | 4–8 |
| `docs/features/btc-onchain-perp/SPEC.md`、`CHART-INVENTORY.md`、`CHART-VERIFICATION.md`、`SR3-4-VERIFICATION.md`（新） | 文档 | 9 |

---

### Task 1：前置核对与 worker 输入模块 `costflow.py`

**Files:**
- Create: `services/analytics/src/wheelhouse_service/onchain/costflow.py`
- Modify: `onchain/brk.py`：在 `AGE_COHORTS` 之后加 `AGE_URPD_COHORTS = AGE_COHORTS[:6]`。
- Create: `services/analytics/tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow/`（README.md 和下列文件）
- Test: `services/analytics/tests/onchain/test_onchain_costflow.py`

**Interfaces:**
- Consumes：`brk.AGE_COHORTS`、`brk.Urpd`、`agecohorts.BANDS`、`costbasis._cents`、`rules.Rule`。
- Produces：

```python
# brk.py
AGE_URPD_COHORTS: tuple[str, ...] = AGE_COHORTS[:6]

# costflow.py
Window = Literal["1d", "7d", "30d", "90d"]
WINDOWS: dict[Window, int]          # {"1d": 1, "7d": 7, "30d": 30, "90d": 90}   L:94-97
YOUNG: dict[Window, int]            # {"1d": 1, "7d": 2, "30d": 3, "90d": 4}     L:260-261
GRIDS: tuple[tuple[str, int], ...]  # (("lin500", 500), ("lin200", 200))         A:1302
YOUNG_GROUPS: tuple[tuple[str, ...], ...] = tuple(cohorts for _, cohorts in BANDS[:4])  # L:38-41

class CohortColumns(Model):
    all: list[float]                # supply per grid row, like the page's +toFixed(2)
    sth: list[float]
    lth: list[float]

class FlowWindow(Model):
    window: Window
    then_day: date
    then: CohortColumns

class FlowGrid(Model):
    step: Literal[200, 500]
    floors: list[float]
    now: CohortColumns
    windows: list[FlowWindow]       # only windows whose three then-day snapshots are closed and non-empty

class AgeFlow(Model):
    groups: list[list[float]]       # <1d, 1d–1w, 1w–1m, 1m–3m on the $500 grid, summed then rounded
    band: list[int]                 # 0..11 per $500 row

class StoredCostFlow(Model):
    now_day: date
    snapshot_at: AwareDatetime
    spot: float
    grids: list[FlowGrid]           # 500 first, then 200; a grid that fails a check is left out
    age: AgeFlow | None
    reasons: list[str]
    qc: list[str]
    rules: list[Rule] = []

def age_band(high: Sequence[tuple[datetime, float | None]], low: Sequence[tuple[datetime, float | None]],
             floors: Sequence[float], step: float, day: date) -> list[int]
def age_groups(ages: Mapping[str, Urpd], floors: Sequence[float]) -> list[list[float]]
def cost_flow(day: date, snapshots: Mapping[tuple[str, str, date], Urpd], ages: Mapping[str, Urpd],
              high: Sequence[tuple[datetime, float | None]], low: Sequence[tuple[datetime, float | None]],
              *, snapshot_at: datetime) -> StoredCostFlow | None
```

`cost_flow` 的规则：
- D 的 `all lin500` 缺失或为空时返回 None。spot 取它的 close。
- **空快照（`buckets` 为空）一律视为缺失。**
- 对每个网格（lin500、lin200）：
  - D 缺任一群体，记 `urpd_missing:<cohort>:<agg>`，不建这个网格；
  - D 有群体的 close ≠ spot，记 `urpd_mismatch:<cohort>:<agg>`，不建这个网格；
  - 否则网格取 D 和已有 then 快照的 floor 并集（`math.floor(price_floor + 0.5)`）；
  - 缺任一 then 快照，加 `urpd_grid_partial:<agg>`；
  - 某窗口 then 日的三个群体都在才建这个窗口，否则记 `window_missing:<window>:<agg>`。
  - 调用方只传已收盘的 then 快照（Task 2）。
- 年龄部分，有 $500 网格才做。按以下顺序取第一个适用的原因，`age` 为 None：
  1. 缺任一年龄快照（含空快照），记 `age_urpd_missing`；
  2. 有 close ≠ spot 的，记 `age_urpd_mismatch`；
  3. 没有高低价行，记 `age_floor_missing`。
- 高低价的最后一天早于 D 时，加 `age_floor_stale`，`age` 照常给出。
- QC 码见"已定的做法"；需要年龄数据的 QC 只在 `age` 存在时检查。`sold_negative` 按 `YOUNG` 取每个窗口的年轻组数。
- 所有求和都用显式循环。

**样本**（`brk-2026-10-19T0512Z-costflow/`）。README 写明下列来源，以及每条命令的原文：
- `urpd_{all,sth,lth}_{lin500,lin200}_{2026-10-19,2026-10-18,2026-10-12,2026-09-19,2026-07-21}.json`，共 30 份：
  - 来自 `R/.../sr3/onchain-copy.sqlite` 的 `urpd` 表，那是 2026-10-19 05:13Z worker 库的只读副本；
  - 每份写成 `{"cohort","date","aggregation","close","total_supply","buckets"}`，其中 buckets = `json.loads(buckets_json)`；`weight` 在存库时已丢弃；
  - 过去日期 04:52:31Z 取得，已定稿；D 在 05:12:06Z 取得。**库副本里 D 有 9 份快照（3 个群体 × lin1000/lin500/lin200），close 都是 82347.76；样本目录只收其中 lin500、lin200 的 6 份**，没有年龄快照；
  - 导出命令（第二轮评审已原样运行，产出 30 个文件）：

```sh
python3 -I -c 'import json,sqlite3,sys; db=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
for c,d,a,cl,ts,bj in db.execute("select cohort,day,agg,close,total_supply,buckets_json from urpd where agg in (\"lin500\",\"lin200\")"):
    open(f"{sys.argv[2]}/urpd_{c}_{a}_{d}.json","w").write(json.dumps({"cohort":c,"date":d,"aggregation":a,"close":cl,"total_supply":ts,"buckets":json.loads(bj)},separators=(",",":")))' \
  "$R/verification-2026-10-19/verify/sr3/onchain-copy.sqlite" services/analytics/tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow
```

- `day1_price_high.json`、`day1_price_low.json`：`R/.../sr4/brk/hilo5600.json` 的两个元素，**元素 0 = `price_high`，元素 1 = `price_low`**（请求顺序是 `price_high,price_low`；元素 0 在每个位置都 ≥ 元素 1）。逐元素重新序列化，值不变。stamp 2026-10-19T05:13:46Z，version 115，start 901，end 6501。
- `expected_chart3.json`：`R/.../sr3/store-result.json` 原样复制。**阶段 A 参考实现** = `chart3_recompute.py` 中 udiff/segments 的移植 + `costbasis.py` 的 KDE、峰和 GMM，在同一库副本上算出 23 个状态，全精度。这个组合在 05:55 与页面逐行一致（396/396，SR-3.md）。
- `oracle-c4/c4_{1d,7d,30d,90d}_z0_2026-10-19.json`：`R/.../sr4/out-B/` 的 4 份 z0 文件原样复制。
  - 来源：`oracle_c4.py` 在 06:04:42Z 的输出，与页面是同一份快照。用这些行求出的全体净买/净卖与页面图例逐一相同：1d +54,914 / −54,811；7d +329,997 / −327,019；30d +1,134,837 / −1,121,241。
  - **注意**：out-B 的 90d 图例写成了 "net of what is shown"，这份输出生成于 14:04，之后 oracle 才改成与页面一致。页面原文以 `expected_B.json` 为准。
- README 预先写好 Task 3、Task 4 生成前端文件的命令，并写明 `cost-flow-crosscheck.json` 的生成平台：macOS，arm64，Python 版本取自 `.venv-foundation`。

- [ ] **Step 1：前置核对。** 在 main 上逐个核实"前提"表里的符号：用 `rg -n '<name>' <file>` 找到每个符号；Python 符号再用 `.venv-foundation/bin/python -c "from wheelhouse_service.onchain.brk import AGE_COHORTS; assert len(AGE_COHORTS)==23 and AGE_COHORTS[5]=='utxos_2m_to_3m_old'"` 一类的断言确认形状，`agecohorts.BANDS` 前 4 组的名字和 cohort 也照此核实。**任一项不在或形状不符就停止并报告**，不要补建。
- [ ] **Step 2：写失败的测试** `test_onchain_costflow.py`

```python
def test_young_groups_are_the_six_cohorts_the_chart_reads():
    assert AGE_URPD_COHORTS == tuple(c for group in YOUNG_GROUPS for c in group)
    assert [name for name, _ in BANDS[:4]] == ["<1d", "1d–1w", "1w–1m", "1m–3m"]

def test_columns_match_the_stage_a_grid(golden):
    # cost_flow on the 30 snapshots, no ages, no high/low rows:
    # spot 82347.76; grids [500, 200]; 500: 252 floors 0..125,500; 200: 629 floors 0..125,600;
    # four windows each, then days 10-18, 10-12, 09-19, 07-21;
    # round(sum(now.all/sth/lth), 2) == 20100107.36 / 3648914.84 / 16451192.56 (500) and
    # 20100107.43 / 3648914.86 / 16451192.58 (200); age None, reasons == ["age_urpd_missing"]; qc == []

def test_cost_flow_never_mixes_snapshots(golden):    # Review Focus 5
    # sth lin500 of D with close 1.0 -> no 500 grid, age None, "urpd_mismatch:sth:lin500" in reasons
    # all lin200 of D with close 1.0 -> no 200 grid, "urpd_mismatch:all:lin200"

def test_empty_snapshot_is_missing(golden):
    # D sth lin500 with buckets [] -> no 500 grid, "urpd_missing:sth:lin500";
    # 2026-10-18 all lin200 with buckets [] -> 200 grid without 1d, "window_missing:1d:lin200";
    # six ages, one with buckets [] -> age None, "age_urpd_missing"

def test_cost_flow_names_missing_windows(golden):
    # drop sth lin200 of 2026-07-21 -> 200 grid windows 1d/7d/30d; reasons include
    # "window_missing:90d:lin200" and "urpd_grid_partial:lin200"; 500 grid keeps all four

def test_age_band_matches_the_page_histogram():
    # hilo from 2013-01-01 on, D 2026-10-19, floors 0..125,500 step 500
    bands = age_band(high, low, [500.0 * i for i in range(252)], 500.0, date(2026, 10, 19))
    assert [bands.count(g) for g in range(12)] == [4, 5, 6, 36, 8, 58, 19, 59, 26, 22, 8, 1]  # page, SR-4.md
    assert bands == [r["floor"] for r in oracle("30d")["rows"]]
    # the whole 5,600 days give the same bands

def test_age_groups_sum_the_cohorts_then_round():
    # under_1h 1.004 + 1h_to_1d 1.002 in one bucket -> groups[0] == [2.01]; a bucket outside the grid is ignored

def test_age_reasons(golden):
    # six ages at spot + high/low -> age not None, len(groups) == 4, len(band) == 252
    # one age missing -> "age_urpd_missing"; one close 1.0 -> "age_urpd_mismatch";
    # no high/low -> "age_floor_missing"; high/low ending 2026-10-17 -> age built, "age_floor_stale"

def test_qc_codes():   # synthetic 3-row grids
    # |all - sth - lth| == 0.06 on one day -> "cohort_sum:lin500"; sold < -0.05 in 1d -> "sold_negative:1d";
    # a row with now.all 2.0, band 2 and group <1d 1.0 -> "age_floor"
```

- [ ] **Step 3：运行，确认失败**：`.venv-foundation/bin/python -m pytest services/analytics/tests/onchain/test_onchain_costflow.py -q`。
- [ ] **Step 4：导入样本，写 README**，命令见上。
- [ ] **Step 5：实现 `costflow.py` 和 `AGE_URPD_COHORTS`**。
- [ ] **Step 6：运行测试，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 7：Commit**：`feat(onchain): store the inputs of state-report charts 3 and 4`

---

### Task 2：取数、同一快照校验与派生

**Files:**
- Modify: `onchain/models.py`：新增 `day_start(day: date) -> datetime`，从 `api.py` 移来，实现不变。
- Modify: `onchain/api.py`：删掉本地的 `day_start`，改为 `from .models import day_start`。
- Modify: `onchain/brk.py`：新增 `AGE_FLOOR_SERIES = ("price_high", "price_low")`。
- Modify: `onchain/sync.py`，按符号名定位：
  - 新增 `DAY1_FETCH = (*DAY1_SERIES, *AGE_FLOOR_SERIES)`，只用来给 `absent` 排序，即本阶段取的全部 day1 序列，**不是**一次请求的序列清单；
  - `_refresh` 的 day1 主请求仍取 `DAY1_SERIES`；`price_high`/`price_low` 由新方法 `_day1_range` 在主请求和 `brk_version` 落库之后**单独请求**（BRK 版本变化时 `_replace`，否则 `_increment`），`absent` 按 `DAY1_FETCH` 计算；
  - `_day1_range` 出 `BrkError` 时记 `onchain_day1_range_failed code=…`，不计入 `last_error`，库里的行以及上一轮记录的 `day1:price_*` 缺失原样保留；所以它的失败只影响图 4，周期、价位和图 7 不受牵连。代价是每轮多 1 个请求；
  - `_urpd` 的 `URPD_SET` 循环改为收集 `_save_urpd` 的返回值，循环之后、过去日期循环之前调用新方法 `_flow_set`，并以它返回的 D 作为 `_urpd` 的返回值；
  - `_save_urpd` 改为返回存下的 `Urpd | None`，这是增量改动，现有调用方不受影响；
  - 新增 `_cost_flow`、`_derive_cost_flow`；
  - `DAY1_VIEWS` 加 `"costflow"`。

  注意：`sync.py` 已经 `import time`，会遮住 `datetime.time`；`day_start` 从 models 导入，就不会撞名。
- Modify: `rules.py`：`View` 加 `"costflow"`。
- Modify: `tests/onchain/onchain_fixture.py`：`brk_transport(..., age_dir: Path | None = None)`。cohort 以 `utxos_` 开头时去 `age_dir` 找 `urpd_<cohort>_<agg>[_<day>].json`；`age_dir` 为 None 或文件不存在时返回 404。
- Create: `tests/onchain/fixtures/brk-2026-10-16/day1_price_{high,low}.json`：取 hilo5600 中 position 1461–6497 的数据（`start` 1461、`end` 6498），与目录里其他 day1 文件一样止于 2026-10-16。README 补一行说明这次切片。
- Test: `tests/onchain/test_onchain_sync.py`、`test_onchain_api.py`

**Interfaces:**
- Consumes：Task 1 的 `cost_flow`、`AGE_URPD_COHORTS`。
- Produces：
  - `models.day_start`；
  - `sync.DAY1_FETCH = (*DAY1_SERIES, *AGE_FLOOR_SERIES)`（只用于 `absent`）；
  - `OnchainSync._day1_range(at: datetime, *, full: bool) -> set[str]`（日高低价的单独请求，返回缺失的序列名）；
  - `OnchainSync._flow_set(urpd: Urpd, fetched: Mapping[tuple[str, str], Urpd | None], at: datetime) -> Urpd`；
  - `OnchainSync._cost_flow(day: date) -> StoredCostFlow | None`；
  - derived kind `"costflow"`。

要点：
- **`_flow_set`**：
  1. 依次取 6 个年龄快照并保存；出 `BrkError` 时记 `onchain_urpd_age_failed code=…`，跳过年龄部分，不让本阶段失败。
  2. 比较 5 份网格快照和取到的年龄快照，看 close 是否等于 `urpd.close`。5 份网格快照是 sth/lth lin500 和 all/sth/lth lin200，取自 `fetched`；`fetched` 里为 None（404）的，从 store 读当前那一份。
  3. 有不等的，就把 `all lin500`、这 5 份和 6 个年龄快照重取一次并保存。重取 `all lin500` 返回 None 时保留第一次的 D；重取其余快照时出 `BrkError`，照第 1 步的规则处理。
  4. 返回所用的 D。
- **`_cost_flow(day)`** 从库里读：
  - D 的 lin500 和 lin200 三个群体；
  - D−1/7/30/90 的同样快照，**只收 `urpd_fetched_at ≥ day_start(past + 1 day)` 的**；
  - D 的 6 个年龄快照；
  - `price_high`/`price_low` 的 day1 行；
  - `snapshot_at` 取 D 的 `all lin500` 的 `fetched_at`。

  然后调用 `cost_flow`。
- **`_derive_cost_flow(urpd, at)`**：
  - `urpd` 为 None 时清掉 `costflow`；
  - 出异常时记 `onchain_derive_failed code=costflow_failed` 并清掉；
  - 在 `_derive` 里放在 cost basis 之后、pressure 之前。
- **day1**：缺失时记 `series_missing:price_high` 等。`DAY1_SERIES` 和 `/status` 的 `DAY1_REASONS` 都不变。
- **既有测试**，只做最小改动：
  - `urpd_calls` 加参数 `include_ages: bool = False`，默认去掉 `utxos_` 开头的请求；
  - `set(DAY1_SERIES)` 断言改为 `set(DAY1_FETCH)`，涉及 `test_first_run_backfills_and_derives`、`test_incremental_run_starts_three_positions_back`；后者的 `starts` 也按 `DAY1_FETCH` 建；
  - P1 目录的 D 快照 close 本来就不一致（README 已写明：82154.25 对 81217.6），所以在 P1 上同步会多出一次重取（`all lin500` 加 5 份网格快照）。逐条请求序列的断言要补上这一段，已知有 `test_day_rollover_uses_yesterday_for_all`。其余因此失败的测试按同一规则修改，并在提交说明里列出。

- [ ] **Step 1：写失败的测试。** 合成的年龄文件由测试辅助函数写进 `tmp_path`，close 与该次用的 D 相同：P1 是 82154.25，GOLDEN 是 81217.6，costflow 样本是 82347.76。

```python
def test_day_start_lives_in_models():
    # models.day_start(date(2026, 10, 19)) == datetime(2026, 10, 19, tzinfo=UTC); api.day_start is models.day_start

def test_age_snapshots_follow_the_urpd_set_of_d(tmp_path):
    # urpd_calls(calls, include_ages=True) == [*same_day(D), *[(c, D, "lin500") for c in AGE_URPD_COHORTS], *past_of(D)]
    # with urpd_dir=GOLDEN (consistent closes, so no refetch); six age rows stored for D

def test_d_set_close_mismatch_refetches_once(tmp_path):            # Review Focus 5
    # ages at close 1.0 -> after the ages: all lin500, sth/lth lin500, all/sth/lth lin200, six ages again;
    # derived costflow: age None, "age_urpd_mismatch"; grids present

def test_refetched_d_that_is_gone_keeps_the_first(tmp_path):
    # the second all lin500 request gets a 404 -> the stored D is the first one; no stage error

def test_age_snapshot_error_does_not_fail_the_stage(tmp_path):
    # urpd_fail={("utxos_1w_to_1m_old", "lin500")} -> last_error None, costbasis derived, "age_urpd_missing"

def test_stale_age_snapshot_is_never_paired_with_a_new_d(tmp_path):
    # round 1 stores six ages at close X; round 2 serves D at close Y and a 404 for one cohort -> "age_urpd_mismatch"

def test_then_snapshot_counts_once_its_day_closed(tmp_path):         # Review Focus 4
    # store the costflow fixture with D 2026-10-19 and re-save the three 2026-10-18 lin500
    # snapshots fetched at 2026-10-19T00:30Z (closed, not final) -> sync._cost_flow(D) has a 1d
    # window on the 500 grid; re-saved at 2026-10-18T23:12Z instead -> no 1d window,
    # "window_missing:1d:lin500"

def test_day1_stage_fetches_the_daily_range(tmp_path):
    # requested(day1_calls(calls)) == set(DAY1_FETCH); 5,037 rows each for price_high/low;
    # an incremental round sends exactly [",".join(DAY1_SERIES), "price_high,price_low"]
    # (the range is its own request); a BRK version change fetches the range again from START

def test_missing_daily_range_only_takes_chart_4_down(tmp_path):
    # missing={"price_high"} and age_dir at 82154.25 -> shared reasons include "series_missing:price_high";
    # cycle, levels and costbasis derived; costflow.age None with "age_floor_missing"

def test_costflow_derives_the_golden_snapshots(tmp_path):
    # urpd_dir=brk-2026-10-19T0512Z-costflow, now 2026-10-19 05:15Z -> costflow now_day 2026-10-19,
    # spot 82347.76, grids [500, 200] with four windows each, qc [], "age_urpd_missing"

def test_costflow_after_midnight_uses_yesterday_and_its_own_past_days(tmp_path):
    # now 2026-10-20 00:30Z, urpd_dates = {2026-10-19 and its past days} -> now_day 2026-10-19,
    # then days 10-18, 10-12, 09-19, 07-21

def test_costflow_failure_still_derives_everything_else(tmp_path, monkeypatch, caplog):
    # cost_flow raising -> derived("costflow") None, others present, log has "code=costflow_failed"
```

- [ ] **Step 2：运行，确认失败**：`.venv-foundation/bin/python -m pytest services/analytics/tests/onchain/test_onchain_sync.py -q`。
- [ ] **Step 3：实现**：
  - 先把 `day_start` 移到 models（只移动，不改实现），再改 sync；
  - 添加 P1 的 day1 高低价文件，给假 BRK 加 `age_dir`；
  - 按"既有测试"一条修改旧测试。
- [ ] **Step 4：运行 onchain 全部测试，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 5：Commit**：`feat(onchain): fetch the age snapshots and daily range for charts 3 and 4`

---

### Task 3：读接口、契约与前端样本

**Files:**
- Modify: `onchain/models.py`：新增 `CostFlowView`。
- Modify: `onchain/api.py`：新增 `COST_FLOW_REASONS`、`stored_cost_flow()`、`GET /cost-flow`。
- Create: `tests/onchain/costflow_sample.py`
- Create（都在 `…/wheelhouse/` 下，由 README 中的命令生成）：`cost-flow-sample.json`、`cost-flow-sample-0512.json`、`cost-flow-crosscheck.json`。
- Regenerate: `openapi.json`、`api-schema.d.ts`，用 `make contract`。
- Test: `tests/onchain/test_onchain_api.py`

**Interfaces:**

```python
class CostFlowView(Model):
    data_state: DataState              # day1_state(now_day, now); unavailable without a payload
    reasons: list[str]                 # only(shared, COST_FLOW_REASONS) + stored reasons
    refreshing: bool
    forming_at: AwareDatetime | None   # day_start(now_day) when snapshot_at < day_start(now_day + 1)
    now_day: date | None
    snapshot_at: AwareDatetime | None
    computed_at: AwareDatetime | None
    spot: float | None
    grids: list[FlowGrid]
    age: AgeFlow | None
    qc: list[str]
    brk_version: str | None
    rules: list[Rule]
    rules_pending: bool
COST_FLOW_REASONS = ("urpd_missing", "series_missing:price_high", "series_missing:price_low", "brk_unavailable")
```

三个样本，生成器都在 `costflow_sample.py`，`render_*()` 输出 `json.dumps(model_dump(mode="json"), separators=(",", ":")) + "\n"`：
- **`cost-flow-sample-0512.json`（S1，阶段 A，05:12）**：`sample_0512()` 对样本目录的 30 份快照调用真正的 `cost_flow`，不带年龄快照，`snapshot_at` 05:12:06Z。`computed_at` 05:12:30Z，读取时钟 05:20Z。两个网格各 4 个窗口，`age` 为 None。
- **`cost-flow-sample.json`（S2，与 05:55 页面是同一份快照，06:04 取数）**：`sample_0604()` 用保存的数据**重建**这份快照：
  - $500 网格的 now 列 = `_cents(then_30d + d_30d)`。then_30d 是样本目录里已定稿的 2026-09-19 lin500 快照，d_30d 是 `oracle-c4/c4_30d_z0` 每行的 all/sth/lth 差值；
  - 生成器要断言：用 7d、90d 的行重建出的 now 列与此逐值相同；用 1d 的 250 行求出的差值与 out-B 相差不超过 1e-6；
  - then 列取样本目录四天的 lin500 快照，并按 `_cents` 取整；
  - 年龄组取 90d 行的 `buy[0..3]`，下界档取 30d 行的 `floor`；
  - spot 82361.33，`snapshot_at` 06:04:42Z，`computed_at` 06:05:00Z，读取时钟 06:10Z；
  - 只有 $500 网格，4 个窗口齐全；
  - **reasons 里的 `urpd_missing:all:lin200`、`urpd_missing:sth:lin200`、`urpd_missing:lth:lin200` 是样本的构造**：oracle 没有保存 $200 的数据，README 写明这一点；
  - `qc` 用 worker 的 QC 函数对重建出的列计算，应为 `[]`。
- **`cost-flow-crosscheck.json`**：`crosscheck()` 从 S1 取四个侧——30d All Zoom All 的两侧、30d STH Aging Show Zoom All 的两侧，取行与权重规则见 A:1304-1401。每侧记 `centers`、`weights`，以及 `weighted_kde(centers, weights, 0.02 × 跨度)` 和 `find_peaks(centers, weights)` 的结果。

**再生测试的比对方式（第二轮 I2）：**
- S1、S2 只含 `_cents`（Decimal）、加减和比较，**不含 libm 运算的结果**，跨平台一致，所以**逐字节**比对。
- crosscheck 含 `math.exp` 的结果，Ubuntu 上的 glibc 与 macOS libm 可能差一个末位，所以比对**结构相同**（键、长度、峰数），**数值的相对误差 ≤ 1e-12**。

- [ ] **Step 1：写失败的测试**

```python
def test_cost_flow_is_unavailable_without_a_payload(tmp_path): ...   # unavailable, ["brk_unavailable"], grids [], age None
def test_cost_flow_serves_the_derived_payload(tmp_path): ...
    # synced(urpd_dir=COSTFLOW, at 05:15Z), GET at 05:20Z: fresh, forming_at "2026-10-19T00:00:00Z",
    # now_day "2026-10-19", spot 82347.76, steps [500, 200], "age_urpd_missing" in reasons, rules []
def test_cost_flow_reads_no_network(tmp_path): ...                   # blocked client, start_worker False
def test_samples_regenerate_identically(tmp_path): ...
    # S1 and S2: committed text == render_*() byte for byte; the route serves each from the same
    # stored payload; crosscheck: same structure, every number within relative 1e-12 of crosscheck()
# test_capability_and_get_only_schema: add f"{PREFIX}/cost-flow" to the expected paths
```

- [ ] **Step 2：运行，确认失败**。
- [ ] **Step 3：实现模型、路由和生成器**；按 README 的命令生成三个样本文件；运行 `make contract`。
- [ ] **Step 4：运行测试，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 5：Commit**：`feat(onchain): serve the cost-flow inputs read-only`

---

### Task 4：TS 引擎、契约与图 3 的数据层（对阶段 A 的 23 个状态）

**Files:**
- Create: `cost-flow-engine.ts`、`cost-flow-engine.test.ts`、`cost-flow.ts`、`cost-flow.test.ts`、`cost-flow-expected.json`
- Modify: `onchain-contract.ts`、`onchain-contract.test.ts`、`client.ts`

以上文件都在 `…/wheelhouse/` 下。

**Interfaces（Produces）：**

```ts
// cost-flow-engine.ts — the original page's engines, ported line by line (same loop order, same sums).
export function weightedKDE(centers: readonly number[], weights: readonly number[], h: number): number[]; // A:1404-1422
export interface EnginePeak { index: number; location: number; height: number; prominence: number;
  strength: number; width: number; supply: number; share: number }
export function detectPeaks(centers: readonly number[], sm: readonly number[], weights: readonly number[],
  minPromFrac: number): EnginePeak[];                                   // A:1423-1457
export interface GmmComp { mu: number; sigma: number; w: number }
export function fitGMM1D(xs: readonly number[], ws: readonly number[], k: number):
  { comps: GmmComp[]; logL: number } | null;                           // A:1460-1511
export function bic(logL: number, nFull: number, k: number): number;   // A:1512
export interface SideSetting { smoothing: "none" | "auto" | "kde"; bw: number; minProm: number;
  mixture: "none" | "gmm"; kMode: "auto" | "manual"; kManual: number }
export const DEFAULT_SIDE: SideSetting; // { smoothing:"auto", bw:0.02, minProm:0.05, mixture:"none", kMode:"auto", kManual:4 } A:1284-1285
export interface Mixture { comps: GmmComp[]; k: number; src: "peaks" | "bic" | "manual"; raw: number | null; totalW: number }
export interface SideCurves { sm: number[] | null; peaks: EnginePeak[]; mix: Mixture | null }
// null when fewer than 3 rows or no weight on the side (A:1680, A:1688); sm null when smoothing is "none"
export function fitSide(centers: readonly number[], weights: readonly number[], s: SideSetting): SideCurves | null; // A:1514-1556, A:1675-1746
export function samplePDF(c: GmmComp, xs: readonly number[]): number[]; // A:1557-1560

// onchain-contract.ts
export type CostFlowView = components["schemas"]["CostFlowView"];
export type FlowGrid = components["schemas"]["FlowGrid"];
export type FlowWindow = components["schemas"]["FlowWindow"];
export type CohortColumns = components["schemas"]["CohortColumns"];
export type AgeFlow = components["schemas"]["AgeFlow"];
export const costFlowSchema: z.ZodType<CostFlowView, z.ZodTypeDef, unknown>;
// refine: now/then columns and the age groups/band have floors.length entries; age only with a 500 grid
// client.ts
export const getCostFlow: (signal?: AbortSignal) => Promise<CostFlowView>; // "/onchain/cost-flow"

// cost-flow.ts (data layer of Chart 3)
export type Window = "1d" | "7d" | "30d" | "90d"; export type Zoom = 0 | 50 | 25 | 10;
export type Holders = "all" | "sth" | "lth"; export type Side = "pos" | "neg";
export const WINDOWS: readonly Window[]; export const ZOOMS3: readonly Zoom[]; export const ZOOMS4: readonly Zoom[];
export interface FlowRow { b: number; price: number; all: number; sth: number; lth: number }
export interface Seg { v: number; cls: "bar-pos" | "bar-neg" | "bar-aging-pos" | "bar-aging-neg"; aging: boolean }
export type Found<T> = { ok: true; value: T } | { ok: false; missing: "grid" | "window" | "age" };
export function gridFor(view: CostFlowView, h: Holders): FlowGrid | null;      // sth -> 200, else 500 (A:1302)
export function udiff(grid: FlowGrid, w: Window, h: Holders, aging: boolean, z: Zoom, spot: number): Found<FlowRow[]>; // A:1304-1335
export function segments(r: FlowRow, h: Holders, aging: boolean): Seg[];       // A:1346-1394
export function sideWeights(rows: readonly FlowRow[], h: Holders, aging: boolean, side: Side): number[]; // A:1397-1401
```

**确定性（M4）：** `fitGMM1D` 不含随机数，下列各项一律照原站，不得改写：
- 加权分位数初始化（A:1465-1474）及相邻初值至少相隔 1e-3；
- σ0（A:1477）和 σ 下限（A:1482）；
- 最多 120 次迭代，收敛阈值 1e-9（A:1483、1506）。

不得"改进"成 k-means++ 或其他初始化。

`cost-flow-expected.json` 由 README 中的命令生成，内容为：
- `"chart3_page"`：`sweep-expected.json` 的字符串原样，05:55 页面，25 个块；
- `"chart4_page"`：`expected_B.json` 原样，06:04 页面，12 个状态；
- `"chart3_stage_a"`：`store-result.json` 原样，05:12 阶段 A 参考实现，23 个状态。

- [ ] **Step 1：写引擎的失败测试** `cost-flow-engine.test.ts`

```ts
it("agrees with costbasis.py on KDE and peaks", ...);
  // cost-flow-crosscheck.json, four sides: every KDE value and every peak field (price, width,
  // btc/supply, share, strength) within relative 1e-12; same peak count. Python and JS port
  // A:1404-1457 with the same loop order; only exp()'s last bit can differ.
it("fits the page's GMM when asked for k", ...);   // fitGMM1D returns null when n < k; comps sorted by mu
```

- [ ] **Step 2：运行，确认失败；实现 `cost-flow-engine.ts`；运行，确认通过。** 先单独把引擎和 crosscheck 跑通，再做数据层，出错时便于定位。引擎函数逐行照原站：变量名可改为 TS 风格，循环顺序、比较符和常数一律不改，每个函数的注释写出行号。
- [ ] **Step 3：写数据层的失败测试** `cost-flow.test.ts`（S1）和契约测试

```ts
// stage A = the Python reference port (chart3_recompute.py udiff/segments + costbasis.py engines),
// 05:12, sample-0512; a cross-implementation check, the page anchors are in Tasks 5 and 6
it("reproduces the 23 stage-A states", ...);
  // for each state of expected.chart3_stage_a: udiff rows length, first floor, last floor + step,
  // Net Buy / Net Sell / Aging summed from segments in row order (rel 1e-9); fitSide with
  // mixture "gmm": peaks (location, width, supply, share, strength) and auto mixture (mu, sigma,
  // w, w * totalW) within rel 1e-9; fitSide with smoothing "none": mix.k == gmm_bic_k (0 = null)
  // pinned: 30d All Zoom All -> 252 rows, Net Buy 1,133,415.16, buy peak 83,750 width 6,776.48,
  // M1 mu 83,665.05 sigma 1,365.87; 30d STH Show -> 629 rows, Aging 334,783 (23% of sell side);
  // 30d LTH Show sell side: 6 peaks, mixture k 5, raw 6
it("keeps the zoom bands and the half-cent trim", ...);  // hand rows as in A:1316-1333
it("maps All with Aging Show to the All segments", ...);
it("reports a missing window and a missing $200 grid", ...);
  // S1 with the 90d window removed from the 500 grid: udiff(…, "90d", …) -> { ok: false, missing: "window" };
  // gridFor(S2, "sth") === null
```

在 `onchain-contract.test.ts` 加两个用例：两个样本都能通过 `costFlowSchema` 校验；把某个 then 列截短一项后，校验失败。

- [ ] **Step 4：运行，确认失败；实现契约、client 和数据层；运行，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 5：Commit**：`feat(wheelhouse): port the original cost-basis engines to TypeScript`

---

### Task 5：图 3 的读数（对页面记录的 17 块）

**Files:**
- Modify: `cost-flow.ts`、`cost-flow.test.ts`
- Modify: `onchain-text.ts`：`reasonText` 新增 `window_missing:<w>:<agg>`、`urpd_mismatch:<c>:<agg>` 两类码。
- Modify: `i18n.ts`

**Interfaces（Produces，加进 `cost-flow.ts`）：**

```ts
export const fmtSigned: (v: number) => string; export const fmtPrice: (v: number) => string;
export const fmtBtc: (v: number) => string;
export function vsSpot(text: TextFn, price: number, spot: number): string;
export function flowTotals(rows: readonly FlowRow[], h: Holders, aging: boolean):
  { buy: number; sell: number; aging: number | null; share: number | null };          // A:1748-1779
export function barCounts(rows: readonly FlowRow[], h: Holders, aging: boolean): Record<Seg["cls"], number>;
export function agingNote(text: TextFn, h: Holders, aging: boolean, step: number): string;   // A:1786-1802
export interface Cluster { n: number; side: Side; peak: EnginePeak }
export function clusters(pos: SideCurves | null, neg: SideCurves | null): Cluster[];  // A:1819-1840
export interface MixRow { m: number; side: Side; comp: GmmComp; totalW: number }
export function mixRows(pos: SideCurves | null, neg: SideCurves | null): MixRow[];   // A:1842-1866
export function clusterMeta(text: TextFn, cs: readonly Cluster[]): string;
export function mixtureMeta(text: TextFn, pos: SideCurves | null, neg: SideCurves | null): string; // A:1867-1876
export function kLabel(text: TextFn, s: SideSetting, curves: SideCurves | null): string;   // A:1719-1724, refreshed every render
export function chip(s: SideSetting): string;    // "raw" | "auto" | `${bw.toFixed(3)} / ${minProm.toFixed(2)}`  A:1944-1948
export function flowTip(text: TextFn, r: FlowRow, step: number, w: Window): string[];      // A:1880-1904
```

格式规则：
- **整数**：`Number(v.toFixed(0)).toLocaleString("en-US")`；`fmtSigned` 按 v ≥ 0 加 "+"，否则加 "−"，再接绝对值。
- **百分比**：Share `.toFixed(1)%`，Strength `.toFixed(0)%`，Aging 占比 `.toFixed(0)%`，vs spot 保留 1 位。
- **M 表**：Centre 和 Spread 先 `Math.round` 再格式化，Est. BTC 用 `w × totalW`（A:1861-1864）。

i18n 键（en 取自原站，zh 未注明出处的为新译）：

| 键 | en | zh |
|---|---|---|
| `costflow.buy` / `.sell` | Net Buy (Accumulation) / Net Sell (Distribution) | 净买入（累积） / 净卖出（派发） |
| `costflow.agingRow` / `.ofSell` / `.ofBuy` | Aging STH→LTH / {{btc}} BTC · {{pct}} of sell side / {{btc}} BTC · {{pct}} of buy side | 币龄迁移 STH→LTH / {{btc}} BTC · 占卖方 {{pct}} / {{btc}} BTC · 占买方 {{pct}} |
| `costflow.bins` | ${{step}} bins | ${{step}} 价格桶 |
| `costflow.note.all` / `.sthHide` / `.sthShow` / `.lthHide` / `.lthShow` | 原站 A:1795-1801 的五句原文，**"155 days" 改为 "150 days"**，句末接 ` {{bins}}.` | 全体持有者的差值天然抵消了币龄迁移，这个开关在这里不起作用。/ STH 原始差值。减少的部分既有真实卖出，也有刚跨过 150 天的币。/ STH 的真实买卖，加上因币龄增长离开 STH 的币，两者都在卖方。币龄迁移是下界。/ LTH 原始差值，币龄迁入与 LTH 卖出相互抵消。/ LTH 的真实买卖，加上因币龄增长进入 LTH 的币，两者都在买方。币龄迁移是下界。（每句后接 {{bins}}。） |
| `costflow.clusters.one` / `.many` | 1 cluster · {{in}} in · {{out}} out / {{n}} clusters · {{in}} in · {{out}} out | {{n}} 个聚类 · 流入 {{in}} · 流出 {{out}} |
| `costflow.mix.in` / `.out` / `.one` / `.many` / `.of` / `.bic` | in / out / {{side}}: 1 bell / {{side}}: {{k}} bells / {{side}}: {{k}} of {{n}} bells / {{part}} (BIC) | 流入 / 流出 / {{side}}：1 条 / {{side}}：{{k}} 条 / {{side}}：{{n}} 条中取 {{k}} 条 / {{part}}（BIC） |
| `costflow.k.auto` / `.autoK` / `.autoOf` / `.autoBic` | auto / auto · {{k}} / auto · {{k}} of {{n}} / auto · {{k}} (BIC) | 自动 / 自动 · {{k}} / 自动 · {{n}} 取 {{k}} / 自动 · {{k}}（BIC） |
| `costflow.below` / `.above` | {{pct}}% below / {{pct}}% above | 低于现价 {{pct}}% / 高于现价 {{pct}}% |
| `costflow.tip.*`（real, agingToLth, lthDist, sth, agingShare, sthBought, left, window） | Real net flow / Aging to LTH / LTH distribution / STH apparent / {{pct}}% of the STH decline is aging, not selling / STH acquired at this cost basis / supply left this bucket outright / {{verdict}} · {{window}} window | 真实净流动 / 迁移至长期持有者 / 长期持有者派发 / 短期持有者表观（A:940-941）/ 短期持有者减少中有 {{pct}}% 是币龄迁移而非卖出 / 短期持有者在此成本价买入 / 供应直接离开了这个价格桶 / {{verdict}} · {{window}} 窗口 |
| `cycle.reason.windowMissing` / `.urpdMismatch` | No {{window}} comparison at {{bucket}}: a snapshot it needs is missing / The {{cohort}} {{bucket}} snapshot is from another block; not used | {{bucket}} 桶宽下无法比较 {{window}}：缺少所需的快照 / {{cohort}} 的 {{bucket}} 快照来自另一个区块，未使用 |

- [ ] **Step 1：写失败的测试**（数据用 S2）。注释里标明期望值的来源：**页面记录**、**阶段 A 参考实现**、**由页面值推出**或**引擎复算**。

```ts
// Chart 3, page-recorded (05:55, same snapshot as S2): the 17 blocks of expected.chart3_page that
// have no STH ($200 grid not in S2): "{1d,7d,30d,90d} all zoomAll aging off bells on",
// "{1d,7d,30d,90d} lth zoomAll aging {off,on} bells on", "30d all zoom {50,25,10} bells on",
// "30d all zoomAll smoothing Off bells on (BIC)", "restored defaults". Rebuild every line in the
// sweep's format (legend " || ", note, bars, clusterMeta, K rows with BUY/SELL, mixtureMeta, M rows)
// and expect equality, except the "labels:" line (U4). Block settings: bells on = mixture "gmm"
// both sides; BIC block = smoothing "none" both sides; restored defaults = DEFAULT_SIDE.
it("matches the page's Chart 3 readings cell for cell", ...);
it("Manual at its defaults equals Auto", ...);
  // fitSide with smoothing "kde", bw 0.02, minProm 0.05 deep-equals smoothing "auto"; chip "0.020 / 0.05"
it("Manual cutoff 0.40 keeps only the strong sell peak", ...);
  // derived from page values: 30d All Zoom All, sell side minProm 0.40 -> one peak, $77,750,
  // width $6,960, 490,118 BTC (the page's K3, strength 99%); the other sell strengths are 7%, 30%, 7%
it("labels auto as the original does", ...);
  // page-recorded via mixtureMeta: "auto · 1" (buy), "auto · 4" (sell), "auto · 5 of 6" (90d LTH Show,
  // sell), "auto · 2 of 3" (30d ±10%, buy), "auto · 1 (BIC)" (smoothing off); plain "auto" when
  // kMode is manual or there is no fit
it("kLabel and mixtureMeta skip a side without a fit", ...);   // a side with fewer than 3 weighted rows
it("reads one bucket like the page's tooltip", ...);
  // page-recorded: flowTip({ b: 77500, all: -115540.48, sth: -180246.45, lth: 64705.98 }, 500, "30d") ->
  // ["$77,500 – $78,000", "Real net flow −115,540", "Aging to LTH −64,706", "STH apparent −180,246",
  //  "36% of the STH decline is aging, not selling · 30d window"]
```

- [ ] **Step 2：运行，确认失败**。
- [ ] **Step 3：实现**。
- [ ] **Step 4：运行测试，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 5：Commit**：`feat(wheelhouse): add the chart 3 readings of the cost-basis flow`

---

### Task 6：图 4 的数据层与开关（对页面记录的 12 个状态）

**Files:**
- Modify: `cost-flow.ts`、`cost-flow.test.ts`、`onchain-text.ts`、`i18n.ts`

**Interfaces（Produces，加进 `cost-flow.ts`）：**

```ts
export const YOUNG: Record<Window, number>;   // { "1d": 1, "7d": 2, "30d": 3, "90d": 4 }  L:260-261
export interface AgeRow { b: number; price: number; band: number; all: number; sth: number; lth: number;
  buy: number[]; bought: number; sold: number }
export interface Toggles { bought: boolean[]; sold: boolean[] }   // 4 and 12 entries
export const ALL_ON: Toggles;
export function ageRows(view: CostFlowView, w: Window, z: Zoom): Found<AgeRow[]>;  // A:3498-3526; missing "age" | "grid" | "window"
export interface AgeSeg { v: number; key: string; band: number; sold: boolean }   // keys "a<g>" / "s<band>"
export function ageSegments(r: AgeRow, t: Toggles): AgeSeg[];       // A:3528-3541
export function ageWeights(rows: readonly AgeRow[], t: Toggles, side: Side): number[];
export interface AgeLegendRow { key: string; band: number; label: string; value: string; on: boolean; kind: "bought" | "sold" | "net" }
export function ageLegend(text: TextFn, rows: readonly AgeRow[], young: number, t: Toggles, z: Zoom): AgeLegendRow[]; // A:3705-3740
export function anyHidden(t: Toggles): boolean;   // any of the 16 toggles off, in the legend or not
export function toggle(t: Toggles, key: string, legend: readonly AgeLegendRow[]): Toggles;  // refuses hiding the last visible row, A:3745-3747
export function afterZoom(t: Toggles, legend: readonly AgeLegendRow[]): Toggles;   // ALL_ON when no bought/sold legend row is on
export function ageTip(text: TextFn, r: AgeRow, step: number, w: Window): string[];        // A:3780-3806
```

净额标签：Zoom 为 0 且 `!anyHidden(t)` 时写 `net (issuance)`，否则写 `net of what is shown`。完整规则见"已定的做法"中"图 4 的隐藏状态与净额标签"。

i18n 键：

| 键 | en | zh |
|---|---|---|
| `costflow.age.bought` / `.sold` / `.off` | bought {{group}} ago / sold · last traded {{group}} ago / off | 买入 {{group}} 前 / 卖出 · 该价位上次成交于 {{group}} 前（A:3710-3717）/ 关（A:950） |
| `costflow.age.netIssuance` / `.netShown` | net (issuance) / net of what is shown | 净额（新增发行） / 所示部分净额（A:948） |
| `costflow.age.tip*`（Bought, Sold, Net, Foot） | bought {{group}} ago / sold from levels last traded {{group}} ago / net / aging removed · {{window}} window | 买入 {{group}} 前 / 卖出，该价位上次成交于 {{group}} 前 / 净额 / 已剔除币龄迁移 · {{window}} 窗口 |
| `cycle.reason.age_urpd_missing` / `age_urpd_mismatch` / `age_floor_missing` / `age_floor_stale` | Age-cohort snapshots missing / Age-cohort snapshots are from another block than the whole supply / Daily high and low missing / Daily high and low end before the snapshot day | 缺少币龄群体快照 / 币龄群体快照与全体快照不是同一区块 / 缺少每日最高价和最低价 / 每日最高价和最低价早于快照日 |

- [ ] **Step 1：写失败的测试**（数据用 S2；S1 用于 `age` 为空的情形）

```ts
// page-recorded (06:04): expected.chart4_page["{1d,7d,30d} z{0,50,25}"] — legend lines
// "<label> / <value>", meta, cluster rows equal; at z50/z25 our net label is "net of what is shown".
it("matches the page's Chart 4 readings cell for cell", ...);
// page-recorded through the hide control: 90d with "bought 1m–3m ago" hidden -> legend values,
// meta and clusters equal expected.chart4_page["90d z{0,50,25}"] (the page's bOn state);
// net label "net of what is shown" where the page wrote "net (issuance)".
it("reproduces the page's 90d state when 1m–3m is hidden", ...);
// 90d with every group drawn:
//   page-recorded (SR-4.md, after turning 1m–3m on): z0 "bought 1m–3m ago / +1,402,425",
//   "net (issuance) / +40,725", "7 clusters · 2 in · 5 out";
//   page-recorded (Chart 3's matching block: at z0 with nothing hidden each row weighs
//   bought − sold = all_d over the same 252 rows, so the clusters equal the sweep's
//   "90d all zoomAll"): K1 "Net Sell (Distribution) | $27,250 | $31,616 | 197,677 BTC | 10.5% | 6% |
//   66.9% below", K5 "Net Buy (Accumulation) | $82,250 | $8,534 | 1,581,751 BTC | 82.1% | 100% | 0.1% below",
//   K7 "Net Sell (Distribution) | $113,750 | $36,217 | 353,944 BTC | 18.8% | 10% | 38.1% above";
//   engine-computed: z50 "net of what is shown / +271,503", "6 clusters · 2 in · 4 out";
//   z25 "net of what is shown / +889,501", "5 clusters · 2 in · 3 out".
it("draws every 90d group by default", ...);
// page-recorded (Chart 3's "30d all zoom 50" legend, 1,134,837 − 1,058,336): 30d z50 net "+76,501".
it("nets the ±50% rows", ...);
it("never hides the last visible legend row", ...);           // A:3745-3747: toggle returns t unchanged
it("resets the toggles when a zoom leaves nothing visible", ...);   // Review Focus 3:
  // 30d z0: hide the 3 bought rows and every sold row but "10y+"; afterZoom for z25 (no 10y+ sold
  // row there) -> ALL_ON; the z25 legend is all on and the net reads "+253,707" (page-recorded value)
it("names the net by every toggle, not only the legend's", ...);
  // a sold band hidden at z0 that has no row at z25 keeps anyHidden true -> "net of what is shown"
it("finds no ages in the 05:12 sample", ...);    // ageRows(S1, "30d", 0) -> { ok: false, missing: "age" }
it("reads one bucket like the page's tooltip", ...);
  // page-recorded: ageTip on S2's 30d row at 77,500 -> ["$77,500 – $78,000",
  //  "sold from levels last traded 1m–3m ago −115,540", "net −115,540", "aging removed · 30d window"]
```

- [ ] **Step 2：运行，确认失败**。
- [ ] **Step 3：实现**。
- [ ] **Step 4：运行测试，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 5：Commit**：`feat(wheelhouse): add the chart 4 rows and legend toggles of the cost-basis flow`

---

### Task 7：Cost basis 子视图、图 3 界面、窄屏几何与缓存

**Files:**
- Create: `cost-flow-charts.tsx`、`cost-flow-charts.test.tsx`
- Modify: `cost-flow.ts`（加 `plotFrame`、`labelX`）、`flows-panel.tsx`、`flows-panel.test.tsx`、`market.css`、`i18n.ts`

**Interfaces:**
- Consumes：Task 4–6 的全部导出；`useChartWidth`、`Segments`、`ticks`、`si`、`reasonText`、`rulesNote`。
- Produces（Task 8 使用）：

```ts
// cost-flow.ts
export interface Frame { left: number; right: number; top: number; bottom: number; plotW: number;
  xTicks: number; yTicks: number; labelPx: number; spotX: number }
export function plotFrame(width: number): Frame;
// < 500: left 44, right 76, top 8, bottom 34, xTicks 3, yTicks 6, labelPx 10;
// >= 500: left 64, right 96, top 10, bottom 36, xTicks 7, yTicks 10, labelPx 11; spotX = width - 2
export function labelX(x: number, side: Side, f: Frame): number;
// labels are at most 3 characters, about ceil(3 * 0.62 * labelPx) px wide (19 at 10 px);
// "neg" labels end-anchored at x - 8, at least f.left + that width; "pos" start-anchored at x + 8,
// at most f.left + f.plotW - that width
```

```tsx
// cost-flow-charts.tsx
export function CostFlowCharts(): JSX.Element;   // query ["wh","onchain","cost-flow"], refetch 300000
interface Shared { window: Window; zoom: Zoom }  // default { "30d", 0 }; a window change resets Chart 4's toggles, hover and both readouts
export function FlowPlot(props: { prices: number[]; step: number; yDomain: [number, number]; mag: number;
  bars: { row: number; x0: number; x1: number; className: string; key?: string }[];
  curves: { side: Side; kind: "kde" | "mix"; points: [number, number][] }[];
  marks: { side: Side; btc: number; price: number; label: string; kind: "k" | "m" }[];
  spot: number; captions: [string, string]; label: string; dim: string | null;
  active: number | null; onActive: (row: number | null) => void }): JSX.Element;
export function SideControls(props: { side: Side; setting: SideSetting; curves: SideCurves | null;
  onSetting: (next: SideSetting) => void }): JSX.Element;
  // Smoothing Off/Auto/Manual, Bell curves, How many, ⚙ chip + popover; slider input updates its label at
  // once and commits through requestAnimationFrame, at most once per frame
export function useSideCurves(rows: readonly { price: number }[], weights: readonly number[],
  setting: SideSetting): SideCurves | null;      // useMemo over (rows, weights, setting); wraps fitSide in performance.measure("costflow-fit")
export function ClustersTable(props: { rows: Cluster[]; spot: number; empty: string }): JSX.Element;
export function ReadColumns(props: { shows: MessageKey; implies: MessageKey; how: MessageKey }): JSX.Element;
```

图 3 面板（`section[data-chart="costflow-3"]`），由上到下：
1. 标题。
2. 控件行：Window / Holders / Zoom。
3. 窗口跨度行。
4. `FlowPlot`（`svg.wh-cf-svg[data-rows]`）或缺失说明。
5. 图例；Aging Show 时加空心的 Aging 行。
6. Aging 行：Show/Hide 按钮加注释。
7. 两侧控件：< 640 px 时单列。
8. 读数块（`aria-live="polite"`）。
9. Clusters 表；Bell curve components 表。
10. 三栏说明。

页头写快照信息；forming、stale 或 QC 时另起一行提示；再列出 reasons 和 `rulesNote`。

缓存：行和权重用 `useMemo`；每侧调用 `useSideCurves`。悬停、读数和宽度只读这些结果，不进它们的依赖。

UI 文案键：

| 键 | en | zh |
|---|---|---|
| `flows.costbasis` | Cost basis | 成本分布 |
| `costflow.loading` / `.unavailable` | Loading the cost-basis flows… / Cost-basis flows unavailable | 正在加载成本价买卖分布… / 成本价买卖分布不可用 |
| `costflow.meta` | URPD snapshot {{day}} · {{time}} UTC · Source Bitcoin Research Kit | URPD 快照 {{day}} · {{time}} UTC · 来源 Bitcoin Research Kit |
| `costflow.forming` / `.stale` | includes the forming snapshot of {{day}} / Snapshot out of date · {{day}} | 含 {{day}} 尚未收盘的快照 / 快照已过期 · {{day}} |
| `costflow.spanForming` / `.spanClosed` | {{window}} · {{then}} close → {{day}} {{time}} UTC / {{window}} · {{then}} close → {{day}} close | {{window}} · {{then}} 收盘 → {{day}} {{time}} UTC / {{window}} · {{then}} 收盘 → {{day}} 收盘 |
| `costflow.noWindow` / `.noGrid` | No {{window}} comparison: a snapshot it needs is missing. / {{holders}} needs the ${{step}} snapshots, which are missing. | 无法比较 {{window}}：缺少所需的快照。/ {{holders}} 需要 ${{step}} 桶宽的快照，目前缺失。 |
| `costflow.c3.title` | Chart 3 — Buy & Sell Side By Cost Basis | 图 3 — 按成本价的买卖两侧 |
| `costflow.window` / `.holders` / `.zoom` / `.aging` / `.all` / `.show` / `.hide` | Window / Holders / Zoom / Aging / All / Show / Hide | 窗口 / 持有者 / 缩放 / 币龄迁移 / 全部 / 显示 / 隐藏（A:884-896） |
| `costflow.smoothing` / `.off` / `.auto` / `.manual` / `.bells` / `.on` / `.howMany` | Smoothing / Off / Auto / Manual / Bell curves / On / How many | 平滑 / 关 / 自动 / 手动 / 正态曲线 / 开 / 数量（A:889、910） |
| `costflow.fineSell` / `.fineBuy` / `.width` / `.cutoff` | Fine tuning · net sell / Fine tuning · net buy / width / peak cutoff | 微调 · 净卖出 / 微调 · 净买入 / 带宽 / 峰值阈值（A:916） |
| `costflow.eyebrow.sell` / `.buy` | ◀ Net Sell (Distribution) / Net Buy (Accumulation) ▶ | ◀ 净卖出（派发） / 净买入（累积）▶ |
| `costflow.axis.buy` / `.sell` / `.spot` | Net Buy (Accumulation) → BTC / BTC ← Net Sell (Distribution) / spot {{price}} | 净买入（累积）→ BTC / BTC ← 净卖出（派发） / 现价 {{price}} |
| `costflow.clustersTitle` / `.componentsTitle` | Clusters / Bell curve components | 聚类 / 正态分量（A:911） |
| `costflow.col.*`（12 列） | # / Side / Price level / Width / BTC / Share / Strength / vs spot / M / Centre / Spread / Est. BTC | # / 方向 / 价格水平 / 宽度 / BTC / 占比 / 强度 / 相对现价 / M / 中心 / 离散度 / 估计 BTC（A:901-903） |
| `costflow.noClusters` / `.bellsOff` | No clusters. Turn smoothing on for a side, or lower its peak cutoff. / Bell curves are off. Turn them on for either side above. | 没有聚类。请为某一侧打开平滑，或调低它的峰值阈值。/ 正态曲线已关闭。请在上方为任一侧打开。 |
| `costflow.qc` / `.qc.cohort_sum` / `.qc.sold_negative` / `.qc.age_floor` | QC failed: {{list}} / STH + LTH ≠ All at {{bucket}} / sold below zero in {{window}} / age floor contradicted | QC 未通过：{{list}} / {{bucket}} 桶宽下 STH + LTH ≠ 全体 / {{window}} 中出现负的卖出量 / 币龄下界与数据矛盾 |
| `costflow.c3.shows` | Where supply changed hands over the window, by cost basis. Each bar is one price bucket ($500; $200 for STH): the coins whose cost basis sits in that bucket in the latest snapshot, minus those at the start of the window. Coins added to a bucket — bought at that price — run right as Net Buy; coins that left it run left as Net Sell. Holders picks the whole supply, short-term or long-term holders. With Aging shown, the STH and LTH views separate real buying and selling from coins that only crossed the 150-day line, drawn hollow. The curves smooth each side: K marks their peaks, M the bell curves fitted to them. | 按成本价看窗口期内筹码在哪里换手。每根柱子是一个价格桶（$500；STH 为 $200）：最新快照里成本价落在该桶的币，减去窗口起点的快照。桶里增加的币，即在这个价位买入的，向右画为净买入；离开的币向左画为净卖出。Holders 选择全体、短期或长期持有者。Aging 选 Show 时，STH 和 LTH 视图会把真实买卖与只是跨过 150 天线的币分开，后者画成空心。两侧的曲线是平滑后的分布：K 标出峰，M 是拟合的正态分量。 |
| `costflow.c3.implies` | A large Net Buy cluster at spot is a fresh cost base: many coins are now held at today's price, which tends to be defended or tested there. A large Net Sell cluster below spot means older, cheaper coins were spent, mostly profit taking; above spot it means holders who bought higher sold out. In the STH view, a big hollow aging bar means much of the decline is coins maturing into LTH, not selling. The chart measures coins moved, not intent, and every window ends at the latest snapshot. | 现价附近的大块净买入是新形成的成本区：大量筹码以当前价格持有，往往在这里被防守或检验。现价下方的大块净卖出说明更早、更便宜的币被花掉了，多为获利了结；在现价上方，则是高位买入的人离场。STH 视图里空心的币龄迁移柱很大时，短期持有者的减少主要是币龄增长转入长期持有者，而不是卖出。这张图衡量的是移动的币量，不是意图；每个窗口的终点都是最新的快照。 |
| `costflow.c3.how` | Price runs up the vertical axis and BTC across: right is accumulation, left distribution, and the dashed line is spot. Switch windows to see whether a cluster is new or has been building. The Clusters table lists each peak with its width, BTC and share of its side; turn Bell curves on for the components table, and use ⚙ with Manual smoothing to change the curve's width and peak cutoff. Hover the chart or use the arrow keys to read one bucket. | 纵轴是价格，横轴是 BTC：右边是累积，左边是派发，虚线是现价。切换窗口，看一个聚类是新出现的还是逐步累积的。Clusters 表列出每个峰的宽度、BTC 和占该侧的比例；打开 Bell curves 后出现正态分量表；平滑选 Manual 时，可用 ⚙ 调整曲线的带宽和峰值阈值。在图上悬停或用方向键可以读取单个价格桶。 |

- [ ] **Step 1：写失败的测试。** mock `getCostFlow`，默认返回 S2。引擎调用的计数办法：

```ts
vi.mock("./cost-flow-engine", async (orig) => {
  const m = await orig<typeof import("./cost-flow-engine")>();
  return { ...m, fitSide: vi.fn(m.fitSide) };
});
```

`window.requestAnimationFrame` 换成一个手动排空的队列。

```tsx
it("plotFrame keeps the plot and the spot label inside 330 px", ...);
  // plotFrame(330): plotW 210 (>= 200), xTicks 3, labelPx 10, spotX 328 with left + plotW < spotX <= 330;
  // plotFrame(1100): left 64, right 96, xTicks 7
it("labelX keeps K and M labels inside the plot", ...);
  // f = plotFrame(330): labelX(46, "neg", f) === 63; labelX(250, "pos", f) === 235
it("never calls the engine for hover or the keyboard readout", ...);   // Review Focus 1
  // after the first render, note fitSide's call count; move the pointer over 20 rows and press
  // ArrowUp 20 times -> the count is unchanged; a resize (useChartWidth) leaves it unchanged too
it("coalesces ten slider inputs into one recompute", ...);               // Review Focus 1
  // sell side Manual; fire 10 input events on the cutoff slider without flushing the frame ->
  // no new fitSide call and the slider label shows the 10th value; flush the frame -> exactly one
  // new call, for the sell side, with the 10th value; the buy side is not recomputed
it("draws Chart 3 with the original's default readings", ...);
  // page-recorded: legend "+1,134,837 BTC" / "−1,121,241 BTC"; svg data-rows "252"; 12 .wh-cf-bar--pos,
  // 240 .wh-cf-bar--neg; Clusters "5 clusters · 1 in · 4 out", K4 row "Net Buy (Accumulation) | $83,750 |
  // $6,773 | 1,134,837 BTC | 100.0% | 100% | 1.7% above"; components "Bell curves are off. Turn them on
  // for either side above."; chart K labels: buy "K4", sell K1 K2 K3 K5; text.wh-cf-spot "spot $82,361"
it("fits bell curves on request", ...);
  // page-recorded: both sides On -> "in: 1 bell · out: 4 bells"; buy M1 "$83,663" "$1,363" "100.0%"
  // "1,134,837 BTC" "1.6% above"; sell centres $26,743 $63,489 $77,733 $83,835; How many "auto · 1", "auto · 4"
it("tunes a side by hand", ...);
  // sell side Manual: chip "0.020 / 0.05", sliders enabled with min/max/step 0.005/0.10/0.001 and
  // 0.01/0.40/0.005; cutoff 0.40 (frame flushed) -> one sell row in Clusters, $77,750;
  // back to Auto -> chip "auto", sliders disabled at 0.02 / 0.05
it("shows the aging split for LTH", ...);
  // page-recorded: 90d LTH Show -> "Aging STH→LTH 1,283,400 BTC · 40% of buy side", 35 .wh-cf-bar--aging-pos, sell "auto · 5 of 6"
it("says a window is missing instead of drawing zeros", ...);
  // S2 with the 1d window removed from the 500 grid: select 1d -> both charts show "No 1d comparison: a
  // snapshot it needs is missing." and neither has an svg; 7d draws both charts again
it("says the $200 grid is missing", ...);
  // STH -> "STH needs the $200 snapshots, which are missing." and no svg in Chart 3; header lists the reasons
it("reads a bucket with the keyboard", ...);
  // focus the svg, ArrowUp once -> the spot row: readout ["$82,000 – $82,500", "Real net flow +220,010",
  // "LTH distribution +13,621", "STH apparent +233,631", "STH acquired at this cost basis · 30d window"];
  // ArrowUp again -> first line "$82,500 – $83,000"; Escape clears the readout
it("puts the three explanations under Chart 3", ...);
  // headings "What it shows", "What extreme values imply", "How to read"; first sentences
  // "Where supply changed hands over the window, by cost basis.", "A large Net Buy cluster at spot is a
  // fresh cost base:", "Price runs up the vertical axis and BTC across:"
it("marks the forming snapshot by its day", ...);
  // header "includes the forming snapshot of 19 Oct 2026"; span "30d · 19 Sep close → 19 Oct 06:04 UTC";
  // with forming_at null the span ends "19 Oct close" and the header has no forming text
// flows-panel.test.tsx
it("offers the flows in order and opens Cost basis from the URL", ...);
  // buttons Seller pressure, Sell side, Cost basis, Perp states; ?flow=costbasis renders Chart 3 and queries getCostFlow only
```

- [ ] **Step 2：运行，确认失败**。
- [ ] **Step 3：实现**：
  - 组件、`plotFrame`、`labelX`、`useSideCurves` 和子视图接线；
  - CSS：`.wh-costflow` 下的色值、`.wh-cf-*`、两侧控件 `@media (max-width:640px)` 单列、`.wh-flows-switch{flex-wrap:wrap}`、表格外层 `minmax(0,1fr)`、`.wh-cf-table-wrap{overflow-x:auto}`；
  - i18n 键见上表。
- [ ] **Step 4：运行测试，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 5：Commit**：`feat(wheelhouse): add the Cost basis flow with Chart 3`

---

### Task 8：图 4 界面（Age Breakdown）

**Files:**
- Modify: `cost-flow-charts.tsx`、`cost-flow-charts.test.tsx`、`market.css`、`i18n.ts`

**Interfaces:**
- Consumes：
  - Task 7 的 `FlowPlot`、`SideControls`、`useSideCurves`、`ClustersTable`、`ReadColumns`、`Shared`；
  - Task 6 的 `ageRows`、`ageSegments`、`ageWeights`、`ageLegend`、`toggle`、`afterZoom`、`anyHidden`、`ageTip`、`ALL_ON`；
  - `BANDS12`。
- Produces：图 4 面板 `section[data-chart="costflow-4"]`。

图 4 面板，由上到下：
1. 标题。
2. 控件行：Window（共享），Zoom 只有 All/±50%/±25%（共享；当前为 ±10% 时三个都不亮）。
3. 窗口跨度行。
4. `FlowPlot`：bought 条按组上色（`--wh-age-g`），sold 条加 `.wh-cf-bar--sold`，按下界档上色；轴下两侧注为 `Net accumulation → BTC` 和 `BTC ← Net distribution`。
5. 图例：可点击的 bought/sold 行和 net 行；悬停或获得焦点时突出该组（`.wh-cf-dim` 透明度 .12）。悬停只读缓存。
6. 注释。
7. 两侧控件。
8. 读数块。
9. Clusters 表；M 只画在图上，没有 components 表。
10. 三栏说明。

`ageRows` 返回 `missing: "age"` 或 `"grid"` 时，面板只显示标题、控件行和对应的一句说明（`c4.noAge` / `c4.noGrid`），不画图、图例和表格。

CSS：`--wh-age-0…11` 依次为 `#f7bf6b #f0a04a #e58244 #d96a48 #c66a56 #a97466 #8a8270 #6f9179 #5f9f95 #57a0b5 #5497c9 #5a83c4`（H:68-69）；`.wh-cf-bar--sold{fill-opacity:.45;stroke-dasharray:2 2;stroke-opacity:.8}`；`.wh-cf-dim{fill-opacity:.12}`。

UI 文案键：

| 键 | en | zh |
|---|---|---|
| `costflow.c4.title` | Chart 4 — Buy & Sell Side By Cost Basis · Age Breakdown | 图 4 — 按成本价的买卖两侧 · 币龄拆分 |
| `costflow.c4.noAge` | Chart 4 needs the age-cohort snapshots and the daily high and low for {{day}}, which are missing or from another block. | 图 4 需要 {{day}} 的币龄群体快照和每日最高价、最低价，目前缺失或来自另一个区块。 |
| `costflow.c4.noGrid` | Chart 4 needs the $500 snapshots, which are missing. | 图 4 需要 $500 桶宽的快照，目前缺失。 |
| `costflow.c4.axis.buy` / `.sell` | Net accumulation → BTC / BTC ← Net distribution | 净累积 → BTC / BTC ← 净派发（A:953） |
| `costflow.c4.note` | Bought is exact. Sold is grouped by when price was last at that level, which bounds how young those coins can be; drawn faint because it is an inference, not a measurement. Click a legend row to hide it, hover to isolate. | 买入是精确值。卖出按该价位上次成交的时间分组，这给出了这些币最年轻的可能币龄；它是推断而不是测量，所以画得较淡。点击图例中的一行可以隐藏它，悬停可以单独突出它。 |
| `costflow.c4.noClusters` | No clusters at this smoothing setting. | 当前平滑设置下没有聚类。 |
| `costflow.c4.shows` | The same buying and selling with ageing removed and split by age. Bought, on the right, is the latest snapshot's supply younger than the window, split exactly by age band: those coins moved during the window. Sold, on the left, is what the bucket held at the start of the window minus what is still there and older than the window. Sold coins can no longer be aged, so each sold bar takes the colour of when price was last at that level — the youngest those coins can be — and is drawn faint because it is an inference, not a measurement. | 同样的买卖，剔除币龄迁移后按币龄拆分。右侧的买入是最新快照中比窗口更年轻的筹码，按币龄段精确拆分：这些币都在窗口期内移动过。左侧的卖出是窗口起点时该价格桶的筹码，减去现在仍在桶里、且比窗口更老的部分。卖出的币已无法确定币龄，所以每根卖出柱按该价位上次成交的时间上色，那是这些币最年轻的可能币龄；它是推断而不是测量，所以画得较淡。 |
| `costflow.c4.implies` | Summed over every bucket, bought minus sold is the coins mined in the window, so at Zoom All, with nothing hidden, the net row reads as issuance, not demand. Sold bars in the old colours (six months and more) mean long-held coins were spent at those cost bases; bought bars mostly in the youngest band mean the buying is very recent. The window starts at a day's close while bought counts coins younger than the window in the latest snapshot, so the oldest band counted can include coins bought up to a day before the window began. | 对全部价格桶求和，买入减卖出等于窗口期内新挖出的币，所以在 Zoom All 且没有隐藏行时，净额读作发行量，而不是需求。老币颜色（六个月及以上）的卖出柱，说明长期持有的币在这些成本价被花掉；买入集中在最年轻一档，说明买入发生得很近。窗口起点是某天的收盘，而买入按最新快照中比窗口年轻的币计算，所以计入的最老一档可能包含窗口开始前不到一天买入的币。 |
| `costflow.c4.how` | Window and Zoom are shared with Chart 3. Click a legend row to hide it — the curves, clusters and the net row then cover only what is shown — and hover a row to isolate it. The Clusters table lists the peaks of each side, as in Chart 3; bell curves are drawn on the chart only. | Window 和 Zoom 与图 3 共用。点击图例中的一行可以隐藏它，此时曲线、聚类和净额都只按所示部分计算；悬停一行可以单独突出它。Clusters 表与图 3 一样列出两侧的峰；正态曲线只画在图上。 |

- [ ] **Step 1：写失败的测试**（引擎计数办法同 Task 7）

```tsx
it("says what is missing in Chart 4", ...);   // Review Focus 2
  // with S1 (age null): Chart 4 shows "Chart 4 needs the age-cohort snapshots and the daily high and
  // low for 19 Oct 2026, which are missing or from another block." and has no svg, legend or Clusters;
  // Chart 3 draws (svg data-rows "252")
it("draws Chart 4 with the original's 30d readings", ...);
  // page-recorded: 16 legend rows equal expected.chart4_page["30d z0"].legend; "net (issuance)" "+13,597";
  // "5 clusters · 1 in · 4 out"; 252 .wh-cf-bar--sold
it("shares the window with Chart 3 and draws every 90d group", ...);
  // 90d in Chart 4 presses 90d in Chart 3; "bought 1m–3m ago" "+1,402,425", "net (issuance)" "+40,725",
  // "7 clusters · 2 in · 5 out" (page-recorded)
it("hides a group and recomputes only Chart 4", ...);
  // 90d, click "bought 1m–3m ago": row reads "off", net "net of what is shown" "−1,361,700",
  // Clusters equal expected.chart4_page["90d z0"].clusters, "3 clusters · 1 in · 2 out" (page-recorded);
  // fitSide is called exactly twice (Chart 4's two sides) and Chart 3 is not recomputed
it("never hides the last visible row", ...);
it("resets the toggles, hover and readouts when the window changes", ...);
  // N1: hide a row, switch to 30d in Chart 3 -> every row on, no dimmed bar, both readouts empty
it("follows Chart 3's ±10% zoom with no pill pressed", ...);
  // Chart 3 ±10% -> Chart 4 svg data-rows "33", none of All/±50%/±25% aria-pressed "true"
it("isolates a legend row on hover and focus without the engine", ...);
  // hover "sold · last traded 1m–3m ago" -> every bar with another key has .wh-cf-dim; fitSide count unchanged
it("reads a bucket with the keyboard", ...);
  // ArrowUp once -> ["$82,000 – $82,500", "bought <1d ago +73,948", "bought 1d–1w ago +95,458",
  // "bought 1w–1m ago +67,094", "sold from levels last traded <1d ago −16,490", "net +220,010",
  // "aging removed · 30d window"]
it("puts the three explanations under Chart 4", ...);
  // first sentences "The same buying and selling with ageing removed and split by age.",
  // "Summed over every bucket, bought minus sold is the coins mined in the window,",
  // "Window and Zoom are shared with Chart 3."
```

- [ ] **Step 2：运行，确认失败**。
- [ ] **Step 3：实现**。
- [ ] **Step 4：运行测试，确认通过**；再运行 `make check`，全部通过。
- [ ] **Step 5：Commit**：`feat(wheelhouse): add Chart 4, the age breakdown of the cost-basis flow`

---

### Task 9：文档、核验记录与浏览器检查

**Files:**
- Modify: `docs/features/btc-onchain-perp/SPEC.md`、`CHART-INVENTORY.md`、`CHART-VERIFICATION.md`
- Create: `docs/features/btc-onchain-perp/SR3-4-VERIFICATION.md`

内容。一律按标题或行文字定位，不写编号：
- **SPEC.md**：
  - 「计算规则（v1 = 原站口径）」一章末尾新增一节「成本价买卖两侧（state-report 图 3、图 4）」，编号取当时最后一节加一。内容覆盖：
    - 输入：网格列、6 个年轻 cohort 的快照、day1 高低价；then 快照只要收盘就可用，以及这样做的代价；12 份快照的 close 校验；空快照即缺失；
    - worker 与浏览器的分工、缓存与合并，以及两套引擎的事实；
    - 计算的引用行号；
    - "原站缺陷与本计划的显示"表；
    - 图 4 的隐藏状态规则；
    - QC 变弱（U3）；
    - 载荷。
  - 「目标与范围」中的「不做」：仍列着图 4 就删掉；图 3 本来不在清单里。
  - 「架构」一节：说明"读接口只读库"不变，并补一句"图 3、图 4 的 KDE/峰/GMM/BIC 在浏览器计算（用户 2026-10-19 选方案 C）"；后端文件表加 `costflow.py`。
  - 「界面」中的「Flows（BTC）」：子视图列表加 Cost basis。
  - 「修订记录」加一行。
- **CHART-INVENTORY.md**：
  - 图 3、图 4 两行的本地现状改为"**已做**（日期，Flows → Cost basis），见 [PLAN-SR3-4.md](PLAN-SR3-4.md)"；
  - 图 4 的"需要的数据"写明：6 个年轻 cohort，day1 高低价从 2013 起；
  - "目前本地做了"的图数加 2。
- **CHART-VERIFICATION.md**：在共性问题"原站的图表计算放在前端"那一条下补一句："图 3、图 4 已定为方案 C：worker 只存输入，KDE/峰/GMM 在浏览器计算（2026-10-19）"。
- **SR3-4-VERIFICATION.md** 骨架，照 P3-VERIFICATION 的样式：
  1. `make check` 结果；
  2. 黄金对照，按来源分栏：
     - **页面记录**：图 3 共 17 块；图 4 共 9 个状态，另有 90d 隐藏 1m–3m 后的 3 个状态，以及 90d z0 的三项读数；图 3 同口径块推出的 90d K 行和 30d ±50% 净额；两个 tooltip；
     - **阶段 A 参考实现**：图 3 的 23 个状态，属于跨实现比对；
     - **由页面值推出**：cutoff 0.40，`auto · k` 的各种写法；
     - **引擎复算**：只有 90d z50/z25；
     - TS 与 Python 引擎的交叉核对；
     - AGEFLOOR 直方图；
  3. 实时对照（可选）：同一分钟抓原站读数和本地 `/onchain/cost-flow`，比较默认视图；
  4. 浏览器检查与耗时；
  5. QC 变弱的说明（U3）。

- [ ] **Step 1：写文档**。
- [ ] **Step 2：运行 `make check`**，全部通过，把结果写进核验记录第 1 节。
- [ ] **Step 3（controller）：浏览器检查**：打开本地 `?method=flows&flow=costbasis`，检查以下项目，结果写进核验记录第 4 节：
  - **1440 px**：
    - 两张图和默认读数（实时数据以当时为准）；
    - Window/Zoom 联动；Manual 滑杆即时重算；图 4 点击隐藏后聚类随之变化；
    - 悬停读数；控制台无报错；
    - KDE 和 GMM 线（`#5fae6b`、`#c8623f`、`#adcf88`、`#f08c63`）在暗底上看得清。
  - **390 px**（用弹窗法）：
    - `document.documentElement.scrollWidth <= 390`；
    - 切换条换行；绘图区至少 200 px；spot 标签、刻度和 K/M 标签都在图内；
    - 两侧控件单列；两张表在各自容器里滚动；
    - 三栏说明纵向展开；图 4 的图例换行。
  - **耗时**：390 px，CPU 降速 4×（DevTools 的 Performance 面板，或 CDP `Emulation.setCPUThrottlingRate` 设为 4）。读取 `performance.getEntriesByName("costflow-fit")`，记录：
    - 图 3 STH Show、Smoothing Manual、Bells On 时，每拖一步滑杆的耗时；
    - 图 4 90d、Bells On 时，每点一次图例的耗时。

    超过 100 ms 的作为发现报告；不在本计划里做 Web Worker。
- [ ] **Step 4：Commit**：`docs(onchain): record charts 3 and 4 in the spec and inventory`

## 不做

- 图 3、图 4 的 O1–O6 版本。
- 补齐 23 个币龄 cohort 的完整 QC（U3）。
- Web Worker（只有浏览器检查实测超过 100 ms 时，另行讨论）。
- 图 8（SR-8 计划）。
- 原站 tooltip 浮窗：改用图下方的读数块。
