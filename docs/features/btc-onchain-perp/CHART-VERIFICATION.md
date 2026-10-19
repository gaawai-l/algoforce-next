# 原站图表逐图核对报告

日期：2026-10-19（UTC 05:09–07:20 抓取）。清单见 [CHART-INVENTORY.md](CHART-INVENTORY.md)。

## 怎么核对的

- **本地环境**：commit `1f3a4da`；analytics 设 `WHEELHOUSE_RULES=v1`（计算照原站，不开 O1–O6）；overlay 用 `python3 scripts/foundation.py overlay` 启动；Wealthfolio 后端在 :8088。
- **原站**：在已登录的浏览器里打开三个线上页面，全程没有遇到登录墙，也没有输入密码。
- **一张图一个子代理，分两段做**：
  - 阶段 A（并行，不用浏览器）：读原站源码笔记和 `raw/` 脚本、本地前后端实现、本地 API；用 BRK 独立复算。
  - 阶段 B（串行，同一时间只有一个子代理用浏览器）：在原站页面读 DOM 和页面全局数据，几分钟内再读本地页面和 API，对齐到同一根已收盘的 bar（或同一个快照日）比较。
- **390px**：浏览器窗口是全屏，调整窗口大小无效，原站和本地又都禁止 iframe 嵌入。改为用真实点击打开一个 390px 宽的同源弹窗，读它的 DOM（是否横向溢出、三栏是否单列展开、字号、控件是否可见）。弹窗截不了图，所以窄屏只做了结构检查。
- **数据缺口不算实现问题**：永续的历史清算和 Bybit 主动买卖差由另一个会话改用 Coinalyze 补。凡是因为缺数据造成的空白，下文都归到"数据"。perp-squeeze 原站用 Glassnode，本地用 Binance/Bybit，来源差单独标明。
- **逐图原始记录、复算脚本、截图、黄金样本**都在 `.local/research-samples/alpha-dashboards-2026-10-16/verification-2026-10-19/`（不入库）：
  - `verify/<ID>.md` 是阶段 B 结果，`verify/<ID>-A.md` 是阶段 A 的源码分析和实现方案；
  - 其余目录（`sr1a/`、`sr2/` 等）放复算脚本和抓取数据。
  - 下文的 `file:line` 都以仓库根目录为基准。

## 先修好的问题：页面完全显示不出来

- **根因**：启动链路缺了 :8088 的 Wealthfolio 后端，代码和接口本身没有问题。
  - 后端不在时，整个 Wealthfolio 外壳只显示 "Backend unavailable"，Market intelligence 根本不挂载。
  - `.claude/launch.json` 只启动 analytics 和 overlay；只有 `make dev` 会拉起后端容器，而且 `make dev` 退出时会停掉它。
- **修复**：`1f3a4da` 新增 `python3 scripts/foundation.py overlay`，依次 sync、确认 Docker 在运行、拉起 Wealthfolio 容器并等它健康，再启动 Vite。
- **验证**：从冷启动开始，三页都正常显示，控制台零报错。三页的接口返回也全部通过前端 zod 校验。

## 总表

状态的含义：
- **一致**：数值、控件、口径都对得上；
- **有偏差**：数值一致或有来源差，但界面或口径有差别；
- **显示不出**：本地已实现，但现在页面上不渲染；
- **未实现**：本地没有。

| ID | 页面 · 图表 | 状态 | 一句话 | 工作量 |
|---|---|---|---|---|
| SR-1A | state-report 图 1A Sell Side Breakdown · Relative | 未实现 | 原站已抓全：27 种控件组合与复算 0 差异，可直接当验收基准 | 与 1B 合计 M–L |
| SR-1B | state-report 图 1B · Absolute | 未实现 | 41 个用例（Y 轴 nice、单位、foot）与复算一致 | 在 1A 之上加 S |
| SR-2 | state-report 图 2 Sell Side by All Age Cohorts | 未实现 | 18 种口径已抓全；扩容前要先修 `brk.py` 的 URL 长度问题 | 单做 L；1A/1B 做完后 M |
| SR-3 | state-report 图 3 Buy & Sell Side By Cost Basis | 未实现（漏项） | 24 种状态 396 行与本地引擎逐格一致，KDE/GMM 可复用 | L |
| SR-4 | state-report 图 4 · Age Breakdown | 未实现 | 12 种状态 196 行逐格一致；原站 90d 有 bug | 单做 L；图 3 做完后 M |
| SR-5 | state-report 图 5 Net Supply Change By Size Cohorts | 未实现 | 16 种组合一致；原站把 null 当 0 | M（与图 6 合做 M–L） |
| SR-6 | state-report 图 6 Net Realized P&L By Size Cohorts | 未实现 | 108 个值中 106 个一致，另 2 个差 $1（取整方式不同） | M（与图 5 合做时加 S） |
| SR-7 | state-report 图 7 Supply by Cost Basis | 有偏差 | 数值全部一致；刻度轨的 LTH 栏被宽带叠满，可读性差 | S |
| SR-8 | state-report 图 8 Cost Basis Distribution | 未实现 | 原站读数已抓全，与本地 URPD 同源；本地只存 5 天快照 | L（属于基建） |
| SR-T2 | state-report 表 2 Price Levels | 有偏差 | 24 格逐格一致；缺元信息行、图注和阻力/支撑配色 | S |
| SR-HEAD | alpha-vol 页头周期 | 有偏差 | 5040 天、49 段逐段一致；缺状态色圆点，中文"破位/下破"用词不同 | S |
| SR-AT | state-report Analyst Take | 未实现 | 原站本身是空模板；spec 写的是不做 | — |
| OS-1 | onchain-seller 图 1 Total Realized Loss | 有偏差 | 2160 点、阈值全精度一致；图太扁、阈值线没有文字、没有 total、三栏是删减版 | S |
| OS-2 | onchain-seller 图 2 STH Loss Share | 有偏差 | 全精度一致；悬停缺金额、三栏改写、图高只有 150 | S |
| OS-3 | onchain-seller 图 3 STH Supply in Loss | 有偏差 | 全精度一致；线色错用 LTH 色、7d 下 Y 轴不从 0 开始、悬停缺 BTC 数 | S |
| OS-SUP | onchain-seller Supplementary 标签页 | 未实现 | **不是空页**，而是整个 onchain-pulse（Chart 1–6、表 2、Exp1–6） | L（大部分与 state-report 重合） |
| PS-T1 | perp-squeeze 表 1 Perp States + Parameters | 显示不出（数据） | 16 种组合的 Prob. 与本地算法一致；完整覆盖的 4h 块为 0 | 数据靠 P6；界面 S |
| PS-1 | perp-squeeze 图 1 Squeezes & Unwinds | 显示不出（数据） | 只依赖价格的部分一致；阴影平涂，原站是斜线 | 界面 S |
| PS-2 | perp-squeeze 图 2 New Long/Short, Spot-led | 显示不出（数据） | Binance 视图下 96% 的块状态相同；阴影和图高有偏差 | 界面 S |
| PS-3 | perp-squeeze 图 3 Price vs OI | 有偏差 | 原站与本地的比值稳定，算法一致；本地 Bybit OI 取的单边字段，只有原站的一半 | S–M |
| PS-4 | perp-squeeze 图 4 Volume Delta & Liquidations | 有偏差 | 口径一致，缺数据的地方画成斜线、不画成 0；delta 配色与原站不同，原站会画尾部的部分块 | S |

## 跨图的共性问题

先把下面这些一并定下来，各图就不用分别讨论。

1. **永续数据为什么一直攒不起来**（PS-T1/1/2/4）：
   - 每次服务重启，采集连接会断 15–45 秒；一个空洞就让整个 4h/8h 块算作"未覆盖"。目前近 90 天累计约 0.46–0.5 天，没有一个完整块。
   - 要等 ≥42 个完整 4h 块（8h 为 21 块），表 1 和图 1、图 2 才会出现。
   - 本机做不到连续采集，因为桌面应用会停掉预览服务；P4 也从没发布到 test，所以现在没有任何地方在连续采集。
   - 给 Coinalyze 会话的提醒：回填的窗口必须同时记为"清算已覆盖"和"Bybit 买卖差已覆盖"，否则 `collecting` 不会解除。
2. **扩容 BRK hour1 序列前，先修两处**（SR-1A/1B/2/5/6）：
   - **URL 长度**：`series` 参数在 2083 字符时 BRK 返回 400 "too long"（2048 字符可以通过），而 `services/analytics/src/wheelhouse_service/onchain/brk.py:161` 只按点数分片。加序列后增量刷新会整批失败，卖压图也会跟着停。修复为 S。
   - **新序列单独一个 sync stage**，不要并进 `HOUR1_SERIES`：`onchain/sync.py:460` 的门控规定缺任一条就清空卖压，会把已上线的卖压三图一起打掉。
3. **SPEC 范围要先改**：
   - SPEC §1「不做」列了图 2、4、5、6、8、"图 1 的多种口径"和人工解读，与这次要做 1A/1B 冲突。
   - 图 3 既不在范围里，也不在排除项里，是漏项。
4. **state-report 的图原站都没有三栏说明**（图 1–8、表 2 都只有一行 caption 或什么都没有），而 AGENTS.md 规定 Flows 里每张图都要有三栏。三种处理：你来写；我们起草你确认；或者修改这条规则。
5. **seller 和 perp 已实现的图，三栏说明都是改写**，不是原文，删掉了一些限定句（例如 "It marks who is selling, not how much."、"does not say that it is over"），也加了原文没有的判断（"capitulation"）。原站有现成的中英文原文（onchain-seller `raw/script_2_app.js:100-102`、`:228-233`）。
6. **Flows 的图普遍偏扁**：seller 图 1 高 220、图 2 和图 3 高 150，perp 各图 180–210；原站都是 440（窄屏 300/360）。宽屏下左轴只剩 2–3 个刻度，Warning 线几乎贴着 0。
7. **阈值线上没有文字**：原站在虚线右端写 `Extreme Level · $x`，本地只把数值放在标题行。
8. **perp 图 1–4 在左边界多画一块**（30d 时 181 点，原站 180 点），见 `perp-charts.tsx:147`。
9. **seller 三张图共用的 forming 提示有瑕疵**：数据仍是 fresh、但那个小时已经过去时（例如 05:00–05:12），页头仍写 "includes the forming hour"（`seller-charts.tsx:959-965`、`onchain/api.py:386`）。
10. **原站自身的缺陷，实现时要定照不照搬**：
    - 图 5、图 6：参考小时没出块时，把 null 当 0，画出等于整条累计值的假柱。今天线上看不到，推算 11-02 14:00 UTC 的 30d 窗口会出现。
    - 图 3、图 4：图上和表里的 K 编号对不上；"auto · k" 标签会停在旧值；买方 K 的标签压在 spot 标签上；文案写 155 天，BRK 实际是 150 天。
    - 图 4：90d 下 `bOn` 只有 3 个元素，第 4 组默认隐藏，净额 −1,361,700 却仍标 "net (issuance)"。
    - 图 7 和表 2：默认高亮 $1000，实际算的是 $500。本地已按 SPEC 修正。
    - 窄屏：state-report 把 SVG 等比缩到 1/3，字只有 4–6px；图 3、图 4 的表格把整页撑到 750px（`state-report.html:416` 的 `1fr` 应改为 `minmax(0,1fr)`）；perp-squeeze 把 `@media` 写成了 `media`，三栏说明在 390px 下仍挤成 3 列。本地都不要照搬。
11. **原站的图表计算放在前端**（KDE/GMM、平滑、Relative 分母都随控件实时变），而 SPEC §2 规定读接口不现算。图 1、3、4、7 的控件要先定：后端预算默认组合，前端移植一份 TS，还是改 SPEC。
    - 图 3、图 4 已定为方案 C：worker 只存输入，KDE/峰/GMM 在浏览器计算（2026-10-19）。

## 清单更正（已同步到 CHART-INVENTORY.md）

- "页头周期"属于 onchain-seller 和 perp-squeeze 的页头；state-report 线上没有任何周期元素，"周期"二字只出现在站名里。
- onchain-seller 的 Supplementary 不是空页。它懒加载 `onchain-pulse.html`（5.3 MB，约 381 个 BRK 请求），点击后约 10 秒内是黑屏，所以容易看成空的。
- perp 表 1 并不是"采满 7 天就显示"，条件是 ≥42 个完整 4h 块；图 4 的"只显示采集开始之后的部分"目前也不成立，因为一个完整块都没有。
- 清单里图 1 的本地阈值 $32.6M 是当时开着 O2 造成的；v1 下与原站全精度一致。

## 要你决定的事

### 最急的 1A/1B

| # | 问题 | 选项 |
|---|---|---|
| D1 | SPEC 写着"不做图 1 的多种口径" | (a) 照原站做 Realized P&L $ / Spent vol BTC / Spent vol $ 三种口径，新增 18 条序列；(b) 只做 P&L，新增 2 条序列 |
| D2 | 平滑、Span、Relative 分母放在哪一层算 | (a) 后端只给每小时各条腿，其余前端算（建议：隐藏腿会改变分母，这一步本来只能在前端做；代价是接口约 1–1.9 MB）；(b) 后端预算 27 种组合 |
| D3 | 放在哪里 | (a) Flows 新增 Sell side 子视图，放图 1A、1B，以后放图 2；(b) 接在 Seller pressure 三张图后面；(c) Flows 新增 State report 子视图，以后放 state-report 的全部图；(d) 其他 |
| D4 | 1A 和 1B 怎么排 | (a) 照原站上下两张，共享一套控件；(b) 一张图加 Relative/Absolute 切换（原站图 2 就是这样做的） |
| D5 | 三栏说明 | 原站没有。你写；我们起草你确认；或者这类图不要三栏 |
| D6 | 控件 | 原站两张图共享控件，而 AGENTS.md 写的是 Flows 里各图自带 Span |

### 其他

- **SR-7 刻度轨**：LTH 栏现在画的是 K（FWHM 很宽，叠满一栏）。可选：(a) 改画 M 的 μ±σ，照原站；(b) 保留 K，只画中心短刻度，悬停时才铺开；(c) K 和 M 分两栏。
- **PS-3 的 Bybit OI**：本地取 `singleOpenInterest`（单边），原站和 Bybit 自己的 ticker 用 `openInterest`（是前者的两倍）。这一项会影响 All venues 的状态判定，进而影响图 1、图 2。
- **"All venues" 名字**：本地只有 Binance 加 Bybit 的 BTCUSDT，原站是 Glassnode 汇总的十几家所有 BTC 永续，量级差约 3.4 倍。可以改名，或在说明里写明口径。
- **已实现图的三栏说明**：恢复原文，还是保留改写。
- **图高**：照原站 440，按宽度分档，还是保持现在的高度、只增加刻度。
- **原站缺陷**：第 10 条列的那些，照搬还是修正。
- **图 8 是否做**：要新建历史表，首次回填约 360 个请求（1461 天约 1456 个），属于基建改动。
- **Supplementary 是否做**：其中 Chart 1–6 和表 2 与 state-report 是同一套模板，Exp1–6 按 SPEC 不做。
- **Analyst Take**：(a) 不做；(b) 人工笔记槽（S–M）；(c) 自动生成（不建议，涉及金融数据外发边界）。

## 建议的先后（仅供参考，由你排）

1. **1A/1B**：先修 `brk.py` 分片（S），新建独立 stage，再做后端（M）和前端（M）。
2. **一组 S 级界面修正**，各自独立、风险低：seller 三图的图高、阈值线文字、悬停 total 和金额、图 3 的线色与 Y 轴、三栏说明；表 2 的元信息行、图注、配色；页头圆点和中文"下破"；perp 的左边界。
3. **图 2**：在 1A/1B 之后做是 M。
4. **图 3，再做图 4**：L，然后 M。
5. **图 5 和图 6 一起做**：M–L。
6. **图 8**：L，属于基建，要先写计划再复核。
7. **永续**：等 Coinalyze 合并；顺便定 Bybit OI 字段（S）。

## 逐图详情

### SR-1A Chart 1 — Sell Side Breakdown by LTH & STH · Relative (A)

- **状态**：未实现。前后端都没有相关代码，`/onchain/sell-side` 返回 404，Flows 只有 seller 和 perp 两个子视图（`flows-panel.tsx:7-8`）。
- **原站**（05:24 UTC，Data 05:00，这一小时尚未收盘）：
  - 控件：Span 1d/7d/**30d**/90d；Smoothing 1h/**24h**/168h；Measure **Realized P&L $**/Spent vol BTC/Spent vol $；Exclude from STH Off/<1h/**<24h**。A、B 两张图共享这套控件。
  - 默认读数：LTH profit 56.9%、LTH loss 16.4%、STH profit 18.9%、STH loss 7.8%，total $9.7M。
  - 已收盘的 10-17 22:00（tooltip）：57.2 / 8.4 / 14.9 / 19.5%，total $11.3M。
  - 图形：每小时一根 100% 堆叠柱，从下到上依次为 LTH profit `#4d90c0`、LTH loss `#a8d4f0`、STH profit `#d1653c`、STH loss `#f4a99e`；白色价格线用右轴；缺块的小时留空，不画成 0。
  - 没有阈值，也没有三栏说明（`.read`、`.cap` 都是空的）。
- **验证**：
  - 原站 `DATA` 最后 96 行 × 25 个键，与同一分钟 BRK 复算逐值相同，0 处不一致。这说明以下几点理解都对：剔除量先 clamp 再求和；残差先相减再取整；BTC 半进位取整；xgap 全有或全无。
  - 27 种组合（3 Measure × 3 Exclude × 3 Smoothing）的图例，与页内按公式复算的结果、与 oracle 输出都是 0 差异。
- **实现要点**：
  - Span 按行数取，不按小时（30d 的首行是 09-19 02:00，不是 06:00）。
  - Relative 的分母是"可见腿各自平滑后之和"。隐藏一条腿后，分母和 foot 的 total 都只算可见腿，并出现提示 "shares of the 3 visible legs, not the full sell side"。最后一条腿不能隐藏。
  - 只保留 tot>0 的行；平滑按行数计。
- **数据**：需要 25 条 hour1 序列，全部存在；本地已有 7 条，缺 18 条（量的 BTC/USD 版本，以及 1h–1d 群体）。
- **390px**：原站把 SVG 等比缩小，坐标轴字只剩约 5.5px，本地不要照搬。
- **实现方案**：`verify/SR-1A-A.md` §3（后端 `sellside.py`、`SELL_SIDE_SERIES`、`/onchain/sell-side`、契约草案、测试方法）。截图：`verify/SR-1A-original-1A-default.jpg`。

### SR-1B Chart 1 — Sell Side Breakdown by LTH & STH · Absolute (B)

- **状态**：未实现。后端与 1A 完全共用；Absolute 只在绘制层不同。
- **原站**（05:31 UTC，Data 05:00）：
  - 默认读数 $5.6M / $1.6M / $1.9M / $780,288，total $9.9M。
  - Y 轴是 d3 `nice([0, 可见堆叠峰值])`，结果 [0, $100M]。
- **验证**：
  - 加载器：96 行 × 25 键，共 2400 格，0 处不一致；volb、volu 和 x1 分支是第一次核验。
  - 41 个用例（27 组控件 + 3 种 Span + 隐藏腿的组合）：图例、foot、Y 刻度、nice 上限全部一致。
- **Absolute 独有的细节**：
  - nice 上限常常高于最后一个刻度标签，例如 [0, $110M] 的刻度只标到 $100M。
  - Y 区间随 Span 和隐藏腿变化：1d [0,$13M]，7d [0,$40M]；只看 STH [0,$70M]，只看 LTH [0,$55M]。
  - 没有分母提示；foot 的 total 只加可见腿。
  - 单位格式：USD 低于 $1M 写全数（`$780,288`），十亿级保留两位小数；BTC 低于 1000 保留一位小数；Y 轴上 BTC 不带单位。
  - 原站措辞不一致：1h 平滑时 tooltip 写 `1h SMA`，foot 写 `no smoothing`。
- **验收样本**：`verify/sr1b/expect_B.json`（41 个用例和 tooltip 期望值）。截图：`verify/SR-1B-original-1B-default.jpg`。

### SR-2 Chart 2 — Sell Side Breakdown by All Age Cohorts

- **状态**：未实现（SPEC §1 写的是不做）。
- **原站**（06:12 UTC）：
  - 控件：Span 30d、Smoothing 24h、Measure P&L $、Detail 6/12 bands、Scale Relative/Absolute、One at a time。
  - 图形：上下发散堆叠柱，盈利向上、亏损向下，颜色表示币龄。
  - 默认读数：<1w $4.50625M · 1w–1m $342.238k · 1m–6m $1.39219M · 6m–2y $1.80055M · 2y–5y $1.39578M · 5y+ $4.03948M，与 BRK 复算逐字一致。
  - 图例用 d3 `~s` 格式，保留 6 位有效数字；本地卖压用的是 3 位。
- **数据**：23 个币龄群体 × 6 个后缀，共 138 条，全部存在。闸门比图 1 严：138 条全部非空才保留这一行。
- **注意**：168h 平滑下会出现 `-0.0`（浮点残差），原站用 `lv>0` 判断所以不画，本地要同样处理。
- **工作量**：先修 `brk.py` 分片（S）；后端 M，前端 M。1A/1B 做完后再做，合计 M。

### SR-3 Chart 3 — Buy & Sell Side By Cost Basis

- **状态**：未实现，是 SPEC 的漏项。
  - 本地 Flows → Seller 里的 "Chart 3 — STH supply in loss" 是 onchain-seller 的图 3，不是这一张。
  - 本地 Key levels 的 "Nearest occupied bands" 属于图 7 和表 2，用的是存量；图 3 用的是快照差。
- **原站**（05:55 UTC）：
  - 控件：Window **30d**；Holders **All**/STH/LTH；Zoom **All**/±50/±25/±10%；Aging Show/**Hide**；两侧各有 Smoothing、Bell curves、How many。
  - 默认读数：Net Buy +1,134,837 BTC，Net Sell −1,121,241 BTC。
  - Clusters：卖方 $41,750 / $63,750 / $77,750 / $91,250，买方 $83,750。
- **验证**：24 种状态共 396 行（图例、K/M 标签、两张表、meta），用本地库数据加本地 `costbasis.py` 引擎，与原站逐格一致。
- **可复用**：KDE、峰检测、GMM、BIC（`services/analytics/src/wheelhouse_service/onchain/costbasis.py:135-335`）。快照已经在库里（`brk.py:49-59`、`sync.py:286-327`），不需要新的 BRK 请求。
- **要新写的**：快照差、AGING 分段、按买卖两侧的权重、Zoom 裁剪、手动平滑参数和手动选 k。
- **工作量**：L（后端 M，前端 L），另加 S 把样本固化成测试（`verify/sr3/sweep-expected.json`）。截图：`verify/SR-3-original-chart3-default.jpg`。

### SR-4 Chart 4 — Buy & Sell Side By Cost Basis · Age Breakdown

- **状态**：未实现（SPEC §1 写的是不做）。
- **原站**（06:04 UTC）：
  - 默认 30d/All：bought 分 3 档、sold 按"上次成交时间"分 12 档，`net (issuance) +13,597`，5 个 cluster。
  - Window 和 Zoom 与图 3 共享。
- **验证**：4 个 Window × 3 档 Zoom，共 196 行逐格一致。
- **原站 90d 的 bug 已实测**：bought 1m–3m 默认 off，净额 −1,361,700 却仍标 "net (issuance)"；打开后是 +40,725，cluster 从 3 个变成 7 个。
- **数据**：缺两样，BRK 上都有：今天的 6 个年龄 cohort URPD，以及 day1 的 `price_high`/`price_low`。
- **工作量**：单做 L；图 3 做完后增量 M。截图：`verify/SR-4-original-chart4-default.jpg`。

### SR-5 Chart 5 — Net Supply Change By Size Cohorts

- **状态**：未实现（SPEC §1 写的是不做）。
- **原站**（06:16 UTC）：
  - 控件：Window **7d**、Breakdown **Entities**/Bands、Scale **BTC**/% of band。
  - 默认读数：Large −7,385、Mid +15,861、Small −3,167、Retail −2,012；图例 +15,861 / −12,564 / 净 +3,297 BTC。
  - 页面全局 `SIZE` 与 BRK 复算逐档相同；16 种开关组合全部一致。
- **没有阈值和三栏说明**：只有一行 caption，Read 块是空的。
- **数据**：12 条 `addrs_<band>_supply`，全部存在。
- **原站缺陷**：null 当 0。建议 v1 遇到这种情况显示 "—"；开 O3 时取前一个有值的小时，供应量没有变化，所以这个值是准的。
- **工作量**：单做 M（约 1.5 天）；与图 6 合做 M–L（约 2–2.5 天），共用一个 stage、一个 `/onchain/size-cohorts` 接口、一个发散条形组件。

### SR-6 Chart 6 — Net Realized Profit & Loss By Size Cohorts

- **状态**：未实现（SPEC §1 写的是不做）。
- **原站**（06:21 UTC）：
  - 控件：7d / Entities / **Gross**/Net / **USD**/% of realized cap。
  - 默认读数：Large −$211.6M、Mid +$176.8M、Small +$519.7M、Retail +$261.2M；图例 +$2.51B / −$1.77B / +$746M。
- **验证**：108 个值中 106 个一致；另外 2 个差 $1，原因是原站用 JS `Math.round`（.5 向上进位），Python 用银行家舍入。本地要逐美元对齐的话，用 `floor(x+0.5)`。
- **数据**：36 条（12 档 × profit/loss/realized cap），全部存在。
- **工作量**：单做 M；与图 5 合做时增量 S。

### SR-7 Chart 7 — Supply by Cost Basis

- **状态**：有偏差。数值全部一致；样式差异（用价格图右侧的刻度轨代替原图）是你确认过的设计，不算偏差。
- **怎么比的**：把原站页面正在画的那份快照取出来，交给本地 `cost_basis()` 计算。三种桶宽都核对了，以下各项逐项相同：
  - 盈利占比：$500 时 STH 76% / LTH 59%；$1000 时 69% / 59%；
  - 7 个 K 的位置；7 个 M 的 μ/σ/π；8 条附近价带；表 2；
  - 成本线 STH $74,503、True mean $77,523、Average $53,864、Median $63,738、LTH $49,286。
- **偏差**：
  1. **刻度轨可读性**：本地刻度轨画的是 K，带高等于 FWHM（`cost-basis-panel.tsx:54-74`、`levels-rail.tsx:77-98`）；原站的 rail 画的是 M 的 μ±σ。
     - 1h 视图下，STH 和 LTH 都成了贯穿全高的均匀色条，看不出结构。
     - 1D 视图下，LTH 栏被几条很宽的带叠满，只有 K4 能看清。
     - 原站 LTH 的 5 段、STH 的 2 段互不重叠，信息量明显更高。
     - 截图在 `verify/sr7/b/shots/`。
  2. **三个开关只影响显示**：原站关掉参考线或 Bell curves，会改变价带计数和表 2。
  3. **图例精度**：盈利占比只显示整数（原站 1 位小数），BTC 数量 3 位有效数字。
- **原站有、本地没有的控件**：Snapshot、Range 和拖拽缩放、平滑和 GMM 设置。这些属于 v1 范围之外。
- **修复**：刻度轨 S（三选一，见"要你决定的事"）；图例精度 S。

### SR-8 Chart 8 — Cost Basis Distribution, All Coins

- **状态**：未实现（SPEC §1 写的是不做）。
- **原站**（06:26 UTC）：
  - 默认 365D / All / Contrast 75–95；250 个桶（$1k–$125.5k）。
  - 读数：P75 83,745.15，P95 192,900.73。30D、90D 和各档 Range 都已独立重算一致。
  - "All" 实际是最近 1461 天，不是全部历史。原站没有三栏说明。
- **同源已证实**：取 4 个已定稿日期，本地 URPD 与原站 `CBD.byDate` 的差 ≤0.03 BTC（Float32 误差）。
- **本地缺口**：只保存 5 天快照，每轮刷新都会删掉其余日期（`sync.py:305,326` → `store.py:209`）。
- **实现**：新建 `urpd_history` 表，首次回填约 360 个请求（365 天），稳态每天 0 个额外请求；前端用 canvas 画热力图。合计 L，属于基建改动，要先写计划再复核。

### SR-T2 Table 2 — Price Levels

- **状态**：有偏差。数值一致，界面差几处。
- **验证**：原站页面那份输入交给本地代码，三种桶宽共 24 格逐格相同。
  - $500：阻力 86.0k / 88.0k / 96.0k / 104.0k，支撑 80.0k / 76.0k / 74.0k / 70.0k。
  - $1000：阻力第 2 格是 90.0k。
  - 本地页面和接口的读数也一样。
- **有意修正**（SPEC 规定的）：列名用 1st–4th；默认 $500，高亮和实际计算一致。
- **界面偏差**（都是 S）：
  - 缺元信息行 `<快照日> · $<bucket> bands · n above and m below spot at $X`；数据接口里已经有这些字段。
  - 缺图注"阻力取上沿，支撑取下沿"。
  - 没有阻力红、支撑绿的配色和色块。
  - 标题是 "Cost-basis levels"，原站是 "Table 2 — Price Levels"。
- **注意**：spot 离 82k 边界只有约 350，$1000 的阻力第 2 格会在 88k 和 90k 之间来回跳。这是快照时刻敏感，不是 bug。

### SR-HEAD 页头周期（onchain-seller、perp-squeeze）

- **状态**：计算一致，展示有偏差。
- **验证**：两个原站页面和本地都是 Breakout、自 2026-09-23 起、第 27 天、全史 48 次切换。5040 天、49 段逐段相同；depth / pvs / spread 与 BRK 复写的差值为 0。
- **偏差**（都是 S）：
  - 没有状态色圆点（原站暗色主题下是 `#d28a44`）。
  - 中文 Breakdown 本地写"破位"，原站两页都写"下破"（`i18n.ts:1024`）。
  - 日期不带年份。
  - Cycle 区块的起始日用 ISO 格式，与徽章写法不一致（`onchain-levels.tsx:177-180`）。
  - tooltip 内容不同。
- **"Cycle ·" 前缀和 forming 文案**：这是 spec §5 定下的写法，不算偏差。

### SR-AT Analyst Take（state-report）

- **原站**：标题可见，正文只有 `<p>&nbsp;</p>`，10 个解读块也都是空的。
- **本地**：没做，SPEC §1 写的是不做。三个选项见"要你决定的事"。

### OS-1 Chart 1 — Total Realized Loss By Cohorts (USD)

- **状态**：有偏差，数值和口径一致。
- **验证**（05:19 UTC，对齐 05:00 和已收盘的 04:00）：
  - 阈值全精度一致：P95 31,472,200、P75 8,451,675、n 716。
  - 最后 2160 行的哈希两边都是 `8a7cb7a1`，即逐点相同。
  - Span 7d/30d/90d 对应 168/720/2160 行，切换不影响阈值。
- **偏差**（都是 S，只改前端）：
  1. 图太扁：高 220、宽 1875，原站 846×440（`seller-charts.tsx:853`）。
  2. 阈值虚线没有文字（`seller-charts.tsx:434-451`）。
  3. 悬停没有 total（`seller-charts.tsx:661-684`）。
  4. 三栏说明是删减版（`i18n.ts:503-508`、`:1166-1171`），缺 Warning "top 25%"、"does not say that it is over" 等句。
  5. 小格式差：标题大小写，价格写成 `$82,347.8`（原站 `$82.3k`）。
- **有意增加的**：forming 虚线框和 "includes the forming hour"（SPEC 要求）。

### OS-2 Chart 2 — STH Realized Loss as a Share of the Sell Side (%)

- **状态**：有偏差，数值一致。
- **验证**（05:14 UTC）：04:00 值 0.008265250339788052，P95 0.5671254807641084，P75 0.22961783132658015，n 716，全精度相同。Span 柱数 168/710/2149，两边相同。
- **偏差**：
  1. 三栏说明是改写（`i18n.ts:512-517`、`:1174-1179`）。
  2. 悬停缺 STH loss $ 和分母 total $：接口的 share 点只有 value（`onchain/pressure.py:410-420`）。后端加两个字段即可，S。
  3. 阈值线没有标签。
  4. 图高 150（`seller-charts.tsx:858-865`），原站 440。

### OS-3 Chart 3 — STH Supply in Loss (%)

- **状态**：有偏差，数值一致。
- **验证**（06:41 UTC）：05:00 值 0.24700548426736163，P95 0.3466989755113415，P75 0.2693092882683648，全精度相同；2160 点里只有正在形成的那一点差 1.9e-4（两边取数时刻不同）。
- **偏差**：
  1. 线色用了 sky 蓝，而本地图 1 里 sky 代表 LTH，颜色语义错位；原站用 STH 的鲑红（`market.css:1482-1485`、`seller-charts.tsx:677`）。
  2. 7d 下 Y 轴是 20–40%，不从 0 开始，波动看起来被放大；原站一律从 0 开始（`seller-charts.tsx:240-245`）。
  3. 悬停缺 "STH coins in loss / STH supply（BTC）" 和 ">1h old coins only" 脚注；要后端在 `pressure.py:433-439` 加两个字段，S–M。
  4. 图高 150（`seller-charts.tsx:869`）。
  5. 三栏说明少了两句原文（`i18n.ts:520-525`、`:1182-1187`）。

### OS-SUP onchain-seller Supplementary 标签页

- **状态**：未实现。原站**有内容**：
  - 它是 `onchain-pulse.html`，高 13,491px，共 14 个区块：Chart 1A/1B、2、3、4、5、6、Table 2、Experimental 1–6。
  - 没有 X-Frame-Options 或 CSP 拦截。
- **为什么会看成空页**：点击后约 10 秒内是黑屏，BRK 请求要到 10.6 秒才结束；本机有缓存，首次下载 5.3 MB 会更久。这一点是推断。
- **与 state-report 的关系**：pulse 的 Chart 1–6 和表 2，与 state-report 的图 1A/1B、2、3、4、8、7 和表 2 是同一套模板。
- **未测**：Supplementary 的 390px。再打开一次会重新触发约 381 个请求，所以没有做。

### PS-T1 Table 1 — Perp States + Parameters

- **状态**：显示不出（数据）。数据齐全时，计算口径与原站一致。
- **验证**（06:49 UTC）：
  - 原站 16 种组合（4 个交易所 × 4h/8h × 7d/30d）的块计数，交给本地 `states.shares()` 算出的 Prob. 与页面逐格相同。
  - 阶段 A 在原站 Glassnode 样本上跑 12 种组合，也全部一致。
  - 原站 all/4h/30d 的 Prob. 为 4/8/5/3/3/3/10/64。
- **本地现在显示什么**：页头、`Rules: original v1`、覆盖说明 "0.5 d"、横幅 "0.0 of 7 days (target 90)"、Parameters、图 3、图 4。表 1、图 1、图 2 不渲染（`perp-states.tsx:552`、`perp-charts.tsx:880-887`）。
- **偏差**：
  - 缺 Hyperliquid（P4-D1 已定不做）。
  - 表 1 是 4 列，原站 7 列；这是 spec 定稿的。
  - 副标题缺块长和 "542 ranked"。
  - 三栏说明是改写；Max DD 改名为 Max move。
  - 色块是纯色，没有斜线纹理；最新块所在行没有背景高亮。
  - "0.5 d" 与 "0.0 of 7 days" 两处天数口径不同，容易误读。
- **来源差**：价格阈值原站 0.6231%、本地 0.6183%；OI 阈值原站 2849.67、本地 975.00 BTC（原站汇总的交易所多得多）。

### PS-1 Chart 1 — Long/Short Squeezes & Unwinds

- **状态**：显示不出（数据）。
- **算法**：与原站一致（原站样本 12/12）。只依赖价格的部分可以直接比：T_px 原站 4h 0.6231%、本地 0.6183%；抽 9 个已收盘块比 dPx，涨跌方向全部一致，最大差 0.029 个百分点。
- **展示偏差**（数据补齐后图 1 出来也会存在，都是 S）：
  1. 阴影：原站用斜线，方向分多空、疏密分挤压和离场；本地是平涂两档透明度（0.34/0.14），unwind 很淡。本地的做法来自 mockup。
  2. 图高 210，原站 440。
  3. 价格线在左边界多画一块。
  4. 图例没有 BTC/USD 最新价。
  5. 悬停方式不同：原站在非图 1 状态显示 "none shaded"。

### PS-2 Chart 2 — New Long/Short, Spot-led

- **状态**：显示不出（数据）。
- **验证**：
  - 原站 all/4h/30d 的图例：新多头建仓 5、新空头建仓 5、现货主导 19（/180）。
  - Binance 视图 30 天内，原站不是 squeeze 的 159 块里，本地推算出的状态有 153 块相同（96%）。其余 6 块都在 OI 阈值附近；本地 Binance 的 ΔOI 约为原站 0.86 倍，是来源差。
- **偏差**（S）：
  - 原站两种建仓是底色加方向斜线，本地三种状态都是纯色。spec 没有记录这个决定。
  - 图高 210。
  - 图例没有最新价。
  - 悬停方式不同。
  - 左边界多画一块。
  - 图 2 说明写的 "grey hatching for unjudged blocks"，应为"未覆盖"块。

### PS-3 Chart 3 — Price vs OI

- **状态**：有偏差。画法与原站一致，差异来自 OI 的取数口径和交易所覆盖。
- **验证**：按 11 个已收盘 4h 块对齐，原站/本地的比值很稳定：All 3.43–3.48、Binance 1.387–1.401、Bybit 2.268–2.283。价格原站低 0.06–0.11%，块间变化的相关系数 0.9999。
- **偏差**：
  1. **Bybit OI 只取单边**（`sources.py:298-300` 用 `singleOpenInterest`），只有原站口径的一半，All venues 里 Bybit 的权重也跟着减半。要不要改需要你定。
  2. **只取 BTCUSDT**：原站是各交易所全部 BTC 永续之和；"All venues" 本地只有两家，原站是十几家汇总。
  3. 30d 时多画左边界一块（181 点对 180 点，`perp-charts.tsx:147`）。
  4. 图高 180，左轴刻度只有 2–3 个（`perp-charts.tsx:30`、`:383`）。
  5. 图例写 `BTC/USD`，实际是 Bybit 的 BTC/USDT。
- **修复**：Bybit 字段二选一（S）；写明口径或改名 All venues（S）；按交易所补齐合约（M）；左边界、图高、刻度（各 S）。

### PS-4 Chart 4 — Volume Delta & Liquidations

- **状态**：有偏差。计算口径与原站一致，偏差都在展示层；缺数据的地方没有画成 0。
- **验证**（原站 07:12 UTC，本地 07:15 UTC）：
  - **volume delta 口径**：主动买入减主动卖出，单位 BTC；Binance 用 `2·takerBuy − volume`。本地最新块 +500.6，已用 Binance 公共 K 线独立复算吻合。
  - **Binance 与原站对比**：对齐 179 个完整块，同号 92%，相关系数 0.981；原站/本地斜率 1.20，但逐块比值在 0.98–1.64 之间，不如 OI 稳定。原因是 Glassnode 还含 USDC 和币本位合约的净流，与 BTCUSDT 不成比例。
  - **清算方向**：short 向上、long 向下，不堆叠。用 05:00–06:40 的 10 分钟桶对照：Binance 多空全部同侧，本地数值相同或偏低（每秒一条快照只能当下限）；Bybit 5 个非零桶的方向和数量完全相同，`v` 的单位确认是 BTC。
- **本地现在显示什么**：
  - All 和 Bybit 视图：181 格灰色斜线，没有刻度也没有零线，读数为 "uncovered · forming"。
  - Binance 视图：有 181 根 delta 柱（来自 REST 回填），清算带全是斜线。
  - 若服务不重启，约 12:00 UTC 会出现第一个完整覆盖的块。
- **偏差**（都是 S）：
  1. **delta 配色**：本地是青/粉，原站是苔绿/锈红，与清算同色。spec 里没有这项改色的记录。
  2. **尾块**：不足半块时本地不画，读数显示三个 "—" 且不说明原因；原站会画部分和。这次最后一块是正在形成的块，没有遇到尾块，所以这一条是按代码和测试推断的。
  3. **左边界多画一块**：181 点对 180 点。
  4. **刻度和图高**：刻度 3 个对原站 5 个，图高 210。
  5. **三栏说明**：少了"左轴读 delta、右轴读清算"，以及"平空等于被迫买入、平多等于被迫卖出"两句。
  6. 小差异：标题大小写，清算图例没有 "(BTC)"。
- **390px**：本地无溢出，三栏纵排且全部展开；原站三栏仍挤成 3 列，每列约 82px。
