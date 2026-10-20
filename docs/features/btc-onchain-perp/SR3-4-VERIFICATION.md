# SR3-4 核验记录

日期：2026-10-20。分支 `claude/cost-flow`（从 main 48dd7e9 新建），范围见 [PLAN-SR3-4](PLAN-SR3-4.md) v3：state-report 图 3（Buy & Sell Side By Cost Basis）和图 4（同图的 Age Breakdown），界面在 Flows → Cost basis。规则见 [SPEC.md](SPEC.md) 的"成本价买卖两侧"一节。

提交：
- Task 1：`a1426a3`、`ee17781`（worker 输入模块 `costflow.py`）；
- Task 2：`cbc2497`、`5210ffb`、`2677dc4`（取数、同一快照校验、派生）；
- Task 3：`f99575a`（读接口 `/onchain/cost-flow`、契约、前端样本）；
- Task 4：`0d3e901`、`3b997c2`（TS 引擎与图 3 数据层）；
- Task 5：`6668b62`、`0c8b636`、`9d1257a`（图 3 读数）；
- Task 6：`8e8059a`（图 4 数据层与开关）；
- Task 7：`3350edd`（子视图与图 3 界面）；
- Task 8：`0cd261c`、`d93df73`、`0d87153`（图 4 界面与共享 hook 修正）。

## 1. 全量检查（`make check`）

2026-10-20 在 `0d87153`（Task 8 完成，文档提交前）运行，退出码 0。

| 项目 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy strict | 54 个源文件，无问题 |
| pytest | 1018 passed（1 个 warning，是仓库原有的 Starlette/httpx 弃用提示） |
| types、frontend type-check | 通过 |
| vitest `src/features/wheelhouse` | 29 个文件，584 个测试全部通过 |

终审修复轮之后在 `328719e` 再跑一次，退出码 0：ruff、mypy、type-check 均通过；pytest 1024 passed（新增 6 个，warning 同上）；vitest 29 个文件、589 个测试全部通过（新增 5 个）。

各任务完成时的测试数（基线 main 48dd7e9：pytest 973，vitest 517）和变异核对：

| 任务 | pytest | vitest | 变异核对 |
|---|---|---|---|
| 1 worker 输入 | 991 | 517 | 首轮 11 处，修复轮 9 处，全部被测试抓到 |
| 2 取数与派生 | 1009 | 517 | 26 个，修复轮 F1–F8 及 6 个重跑，全部杀死 |
| 3 读接口与样本 | 1018 | 517 | 24 个，23 杀死，1 个等价（Zoom All 左端裁剪在这份数据上不起作用） |
| 4 TS 引擎与图 3 数据层 | 1018 | 528 | 81 个，80 杀死，1 个等价（BIC `<` 与 `<=`） |
| 5 图 3 读数 | 1018 | 538 | 首轮 59 个代码变异加 3 处文案，58 杀死、1 个等价；修订轮 31 个，29 杀死、2 个等价（`Math.round` 与 `toFixed(0)`） |
| 6 图 4 数据层 | 1018 | 550 | 49 个，47 杀死，2 个等价 |
| 7 子视图与图 3 界面 | 1018 | 569 | 42 个，全部杀死 |
| 8 图 4 界面 | 1018 | 584 | 38 个加修正轮 8 个，全部杀死 |

等价变异的理由都写在各任务报告里：变异后的代码在所有可达输入上，输出与原代码逐位相同。

## 2. 黄金对照，按来源分栏

期望值的来源分五类，测试注释里逐条标明。**页面记录**是原站页面上读到的值，是最强的锚；**阶段 A 参考实现**和 TS 引擎同出一源（都移植自 A:1404-1557），所以对它的比对只证明两个实现一致，不证明与页面一致。

### 页面记录（与原站页面逐格相同）

样本：`services/analytics/tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow/`（README 写明来源和命令）。图 3 的页面读数取自 05:55 UTC，图 4 取自 06:04 UTC，快照与前端样本 S2 相同。

| 项目 | 数量 | 比对方式 | 结果 |
|---|---|---|---|
| 图 3 | 17 块（`chart3_page` 共 25 块，其中没有 STH、不需要 $200 网格的 17 块） | 用 S2 按 sweep 的格式重建每一行（图例、注释、柱数、两张表的 meta 与各行），与页面块逐行相等，只去掉 `labels:` 一行（K 的编号改用表格编号） | 17/17 相等 |
| 图 3 的 17 块构成 | 4 个窗口的 All、Zoom All、Bells On；4 个窗口的 LTH Zoom All 的 Aging Hide 与 Show；30d All 的 ±50 / ±25 / ±10%；30d All 的平滑关闭（BIC）；还原默认值 | 同上 | 同上 |
| 图 4 | 9 个状态：1d / 7d / 30d × Zoom All / ±50% / ±25% | 图例 16 行、meta、Clusters 各行逐行相等；±50%、±25% 的净额标签按 N1 写 `net of what is shown` | 9/9 相等 |
| 图 4，90d 隐藏 1m–3m | 3 个状态：90d × Zoom All / ±50% / ±25% | 用 `toggle` 复现页面的 `bOn` 状态，图例、meta、聚类逐行相等；z0 净额 −1,361,700；净额标签按 N1 写 `net of what is shown`（页面写 `net (issuance)`，见 SPEC 的缺陷表） | 3/3 相等 |
| 图 4，90d z0 的三项读数 | `bought 1m–3m ago +1,402,425`；`net (issuance) +40,725`；`7 clusters · 2 in · 5 out` | 页面上把 1m–3m 打开之后读到的值 | 相等 |
| 图 3 同口径块推出的 90d K 行 | K1、K5、K7 三行（以及其余 4 行） | Zoom All 且不隐藏时，图 4 每行权重 = bought − sold = all_d，行数与图 3 相同，所以聚类等于图 3 的 `90d all zoomAll` 块：K1 `Net Sell \| $27,250 \| $31,616 \| 197,677 BTC \| 10.5% \| 6% \| 66.9% below`，K5 `Net Buy \| $82,250 \| $8,534 \| 1,581,751 BTC \| 82.1% \| 100% \| 0.1% below`，K7 `Net Sell \| $113,750 \| $36,217 \| 353,944 BTC \| 18.8% \| 10% \| 38.1% above` | 7 行全部相等 |
| 30d ±50% 净额 | `+76,501` | 图 3 的 `30d all zoom 50` 图例 1,134,837 − 1,058,336；另与图 3 的 `flowTotals` 在相同行上交叉核对，相对误差 ≤ 1e-9 | 相等 |
| 两个 tooltip | 图 3：$77,500 桶，`Real net flow −115,540` / `Aging to LTH −64,706` / `STH apparent −180,246` / `36% of the STH decline is aging, not selling · 30d window`；图 4：同一桶，`sold from levels last traded 1m–3m ago −115,540` / `net −115,540` / `aging removed · 30d window` | 页面 tooltip 原文 | 相等 |
| 界面层（Task 7、8 的渲染测试） | 图 3 默认读数：图例 `+1,134,837 BTC` / `−1,121,241 BTC`，252 行，12 根 pos 柱与 240 根 neg 柱，`5 clusters · 1 in · 4 out`，K4 行；Bells On：`in: 1 bell · out: 4 bells`，买方 M1 `$83,663`，卖方 4 个中心；90d LTH Show：`Aging STH→LTH 1,283,400 BTC · 40% of buy side`，35 根 aging 柱；图 4 的 30d 读数：16 行图例，`net (issuance) +13,597`，`5 clusters · 1 in · 4 out`，252 根 sold 柱；z25 复位后净额 `+253,707` | 渲染后的 DOM 与页面值逐项相等 | 全部相等 |
| 数据层的整体锚 | 全体净买/净卖 1d `+54,914 / −54,811`，7d `+329,997 / −327,019`，30d `+1,134,837 / −1,121,241` | 由 S2 的 `all` 列求得，与页面图 4 图例逐一相同 | 相等 |

### 阶段 A 参考实现（跨实现比对）

阶段 A 参考实现 = `chart3_recompute.py` 中 udiff/segments 的移植，加 `costbasis.py` 的 KDE、峰和 GMM，在 05:12 的库副本上算出 23 个状态，全精度（`expected_chart3.json`）。这个组合在 05:55 与页面逐行一致（396/396，[CHART-VERIFICATION](CHART-VERIFICATION.md) SR-3）。

| 项目 | 门槛 | 最大相对误差 |
|---|---|---|
| 23 状态的图例 Net Buy / Net Sell / Aging（含 STH 的 Aging） | 1e-9 | 0（逐位相同） |
| 峰位置 price（23 状态 × 2 侧） | 精确 | 0 |
| 峰 width / strength | 1e-9 | 7.66e-16 / 5.41e-16 |
| 峰 btc（supply）/ share | 1e-9 | 0 |
| GMM μ / σ / w / w × totalW | 1e-9 | 5.30e-15 / 3.74e-14 / 6.01e-14 / 6.02e-14 |
| BIC 选出的 k（Smoothing Off，46 个侧） | 精确 | 46/46 一致 |

固定值（Task 4）：30d All Zoom All 为 252 行、Net Buy 1,133,415.16、买方峰 83,750 宽 6,776.48、M1 μ 83,665.05 σ 1,365.87；30d STH Show 为 629 行、Aging 334,783（占卖方 23%）；30d LTH Show 卖方 6 个峰、混合取 5 个。

### 由页面值推出

| 项目 | 依据 | 结果 |
|---|---|---|
| Manual 的 peak cutoff 0.40 | 页面上 30d All Zoom All 的卖方四个峰中，K1、K2、K5 的强度为 7%、30%、7%，K3 为 99%。cutoff 0.40 只留下 K3：$77,750 / 宽 $6,960 / 490,118 BTC / 占比 43.7% / 强度 99% / 5.6% below | 单行相等 |
| Manual 默认值（0.020 / 0.05）等于 Auto | `fitSide` 在 `smoothing:"kde"`、`bw:0.02`、`minProm:0.05` 与 `"auto"` 下深度相等 | 相等 |
| `auto · k` 的各种写法 | 页面 `mixtureMeta`：`auto · 1`（买方）、`auto · 4`（卖方）、`auto · 5 of 6`（90d LTH Show 卖方）、`auto · 2 of 3`（30d ±10% 买方）、`auto · 1 (BIC)`（平滑关闭）；Manual 或没有拟合时只写 `auto` | 全部相等 |

### 引擎复算

只有 90d z50 / z25 两个状态的值没有页面记录，由 TS 引擎算出，属于引擎复算：

| 状态 | 净额 | 聚类 |
|---|---|---|
| 90d ±50% | `net of what is shown +271,503` | `6 clusters · 2 in · 4 out` |
| 90d ±25% | `net of what is shown +889,501` | `5 clusters · 2 in · 3 out` |

另有 3 个手工 GMM 用例、两组 EM 边界用例（成分被跳过、权重重新归一化）和手动 k=3 的用例，参考值由 `costbasis.fit_gmm` 算出（同样是跨实现的复算），门槛 1e-9，最大误差 2.18e-15。

### TS 与 Python 引擎的交叉核对

| 项目 | 门槛 | 结果 |
|---|---|---|
| `cost-flow-crosscheck.json` 四个侧（30d All 的两侧、30d STH Show 的两侧，行数 252 / 252 / 629 / 629）的 KDE，共 1,762 个值 | 相对误差 1e-12 | 最大 4.59e-16，只有 49 个值有末位差 |
| 同四个侧的 8 个峰（price、width、btc、share、strength） | 相对误差 1e-12 | 全部逐位相同，峰数相同 |
| 同四个侧的 GMM（终审 M3）：`fit_gmm` 在 k = 1 到上限（2 / 5 / 5 / 5）上共 17 组的成分与 logL；`select_components`（v1）有峰、无峰各 4 个侧的结果 | 相对误差 1e-9 | 最大 4.09e-12；k 全部一致（有峰时 1 / 4 / 1 / 2，无峰时 BIC 都选 1） |
| 同一份引擎，分别在 Python 和 JS 里的运算顺序 | 逐行移植 | Task 4 评审：把移植版与原站 `script_2_app.js` 的引擎在同一个 V8 里对比，**43,459 项检查，0 处差异**（逐位相同） |
| 再生测试 | crosscheck 按结构相同、数值相对误差 ≤ 1e-12；S1、S2 逐字节 | 通过（S1、S2 不含 libm 运算的结果，跨平台一致） |

引擎的突变核对：81 个突变中 80 个被杀死，存活的 1 个（BIC 比较 `<` 改为 `<=`）是等价突变。首轮曾有两个被误判为等价的突变（rw 跳过阈值、π 重新归一化）经评审纠正并补了用例。

### AGEFLOOR 直方图

| 项目 | 期望 | 结果 |
|---|---|---|
| `age_band`：高低价从 2013-01-01 起，D = 2026-10-19，$500 网格 252 行 | 各档行数 `[4, 5, 6, 36, 8, 58, 19, 59, 26, 22, 8, 1]`（页面直方图，SR-4） | 相等 |
| 同一输入的逐行 `floor` | 等于 oracle 30d 的 `floor` 列（252 行） | 逐行相等 |
| 取 2013 起与取完整 5,600 天 | 结果相同（SR-4-A 实测） | 测试里两种都跑，相同 |

### worker 侧的黄金值（Task 1、3）

- 30 份 URPD 快照（D = 2026-10-19 及其 4 个窗口日）上：spot 82347.76；两个网格 [500, 200]，$500 为 252 行（floor 0 到 125,500），$200 为 629 行（0 到 125,600），各 4 个窗口；$500 的 all / sth / lth 供应列合计 20100107.36 / 3648914.84 / 16451192.56，$200 为 20100107.43 / 3648914.86 / 16451192.58；`qc == []`；没有年龄快照时 `reasons == ["age_urpd_missing"]`。
- 前端样本 S2（06:04 快照）由保存的数据重建：用 7d、90d 的行重建的 now 列与 30d 的逐值相同；1d 的 250 行差值与 oracle 的最大偏差为 0（门槛 1e-6）；`qc == []`。S2 的 $200 三项 `urpd_missing` 是样本的构造（oracle 没有保存 $200 的数据），README 已写明。

## 3. 实时对照（可选）

2026-10-19 约 23:25–23:45 UTC，controller 在同一时刻打开原站 https://alphabtc-regime.vercel.app/onchain/state-report 和本地页面。两边的 D 都是 10-19，快照 23:23 UTC，spot $82,153。

本地环境：
- 分支 `claude/cost-flow` @0d87153，analytics 起在 8797，`WHEELHOUSE_RULES=v1`、`WHEELHOUSE_PERPS=off`；
- 数据目录用主检出 `onchain.sqlite` 的备份副本，overlay 起在 1430；
- 新增的取数（6 个年龄快照、日高低价）跑了一轮，用时 8,789 ms。之后 `/onchain/cost-flow` 为 fresh，两个网格都在，`age` 不为空，reasons 为空。

| 状态 | 图 3 | 图 4 |
|---|---|---|
| 30d · All（默认） | 图例 +1,164,702 / −1,150,749 相同；Clusters 5 行逐格相同（`5 clusters · 1 in · 4 out`） | 图例 16 项逐项相同，`net (issuance) +13,953`；表格逐格相同 |
| 90d · All | 图例 +1,939,014 / −1,897,933 和 7 行聚类逐格相同 | 唯一的差别来自 `bOn` 修正：原站默认隐藏 bought 1m–3m，本地显示 +1,398,374。本地手动隐藏该组后，图例数值、`3 clusters · 1 in · 2 out` 和 3 行聚类都与原站逐格相同。标签按规则 4 写 "net of what is shown"，原站写 "net (issuance)"，属预期 |
| 7d · STH · 两侧 Bells On | 图例 +410,409 / −360,352、5 行 K、5 行 M（含 BIC 选出的 k）逐格相同 | — |

图上的 K 标签用表格编号（U4）：原站是每侧各自编号，这处差别是有意的。

## 4. 浏览器检查与耗时

**1440 px 以上**
- 自动化窗口是全屏的 2,056 px，`resize_window` 无效，所以直接在全宽下检查：
  - 两张图、图例和表格正常；
  - Window、Zoom、Holders 联动正常；
  - 图 4 点击图例隐藏后会重算聚类（7 → 3）。
- 重新加载并切换窗口、Zoom、Holders 之后，控制台没有报错。
- 页面顶部的 "Python service unavailable (HTTP 403)" 来自 :1430 的 POST 来源检查（只接受 :1420），与本功能无关。
- 1440 px 弹窗检查：待 controller 填写

**390 px**
检查方法：用真实点击打开一个 390 px 的同源弹窗，再检查它的 DOM。
- `scrollWidth` = 390，除表格容器外没有元素溢出。
- 两张图的 SVG 宽 330 px，SVG 里没有越界的文字。
- 两侧控件单列，表格在各自的容器里横向滚动（clientWidth 330，scrollWidth 681，`overflow-x: auto`）。
- 图 4 的图例 15 项各占一行。
- 两张图的三栏说明都纵向展开，宽 330 px。
- Flows 切换条在 4 个按钮时一行放得下，第 5 个子视图加入后再看换行。

**耗时**
在 390 px 的弹窗里读 `performance.getEntriesByName("costflow-fit")`。这个工具无法通过 CDP 设置 CPU 降速，所以下表是**未降速**的实测值：

| 操作 | 每次 fit 耗时 |
|---|---|
| 图 3 STH、Aging Show、Smoothing Manual、Bells On：拖动滑杆 8 步 | 2.3–4.4 ms |
| 图 4 90d、Bells On：点击图例 3 次 | 0.2–3.4 ms |

- 每一步记到两条 measure，是开发模式下 React StrictMode 对 `useMemo` 双调用造成的，生产构建只有一条。
- 按 4 倍降速估算，最多约 18 ms，远低于 100 ms 的门槛，所以不做 Web Worker。

**BIC 路径（终审 M4，估算）**

上表没有覆盖最重的 BIC 路径（Smoothing Off + Bells On）。终审在 Node 里补测了引擎本身，下表是**估算**，不是浏览器里的实测：
- 测法：把 `cost-flow-engine.ts` 复制到 scratchpad，用 Node 24 在本机跑 S1（`cost-flow-sample-0512.json`），每种情形跑 21 次，取中位数和最大值，单位 ms。

| 情形 | 中位数 | 最大值 |
|---|---|---|
| BIC，629 行，卖方 | 13.5 | 27.7 |
| BIC，629 行，买方 | 1.2 | 1.8 |
| BIC，252 行，卖方 | 6.1 | 6.3 |
| Manual + Bells | 0.5–4.8 | 5.0 |

- 按 4 倍估算，BIC 两侧合计约 60 ms，偶发最大值约 110 ms。
- BIC 只在点击时重算，不在拖动时重算：滑杆只在 Manual 下可拖，那时 k 取 KDE 的峰数；只有一个峰都没留下时，才会在拖动中走 BIC。
- 第二轮计划评审给出的 72–190 ms，是在 `vm` 上下文里跑原站脚本测的，跨 realm 有额外开销，测的不是这份移植。

## 5. QC 变弱的说明（U3）

按用户裁定（U3），只取 6 个年轻 cohort（<1h 到 2m–3m）的年龄快照，不补齐 23 个 cohort。所以本地的 QC 比原站弱：

| 原站的检查 | 本地 |
|---|---|
| `cohort_sum`：all = sth + lth | 照做：任一天、任一桶 \|all − sth − lth\| ≥ 0.05 记 `cohort_sum:<agg>` |
| `sold_negative`：sold 不能为负 | 照做：有 sold < −0.05 记 `sold_negative:<window>`，按 `YOUNG` 取每个窗口的年轻组数 |
| `age floor`：现有存量的价位上，比成交下界档还年轻的币不应超过 0.5 BTC | **只覆盖 3 个月以下的币**：now.all > 0.5 的桶里，比下界档年轻的组（只看前 4 组）合计 > 0.5 记 `age_floor`。3 个月以上的币与下界档矛盾时，查不出来 |
| `age bands = all`：全部币龄档加总应等于 all | **不做**。它需要全部 23 个 cohort |
| identity 里的 \|bought − sold − (now − then)\| 恒等式项 | **不做**（本计划只列了 `sold < −0.05`） |

后果：
- 图 4 的年龄拆分只对 3 个月以下的部分有交叉校验。下界档（由日高低价推出）如果错了，而错在 3 个月以上的档位，QC 不会报。
- QC 只在失败时提示，图照常画。"没有提示"只说明上面三项通过，不说明年龄拆分完整无误。
- 补齐 23 个 cohort 的完整 QC 不在本期范围内（PLAN-SR3-4 "不做"）；需要时另立计划，代价是每小时多取 17 个 cohort 的快照。

## 6. 遗留

终审修复轮之后仍留下的项：
- 中文三栏说明里用了英文的控件名（`costflow.c3.how`、`costflow.c3.shows`），与全部三栏说明的中英文措辞一起交用户审；
- 仓库原有的 Starlette/httpx 弃用警告，与本功能无关；
- 终审 M6 的小处重复（`stackBars` 与 `stackAge`、重复查 `then_day`、`MONTHS`、`COHORTS`），按外科手术原则有意不改；
- 终审 T7-M7 的 Flows 切换条两行时的边框：4 个按钮时一行放得下，等第 5 个子视图加入时再查。
