# BTC 链上融合 P3（成本密集带与价位表）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标**：照原站 state-report 图 7 和表 2 的 v1 口径，在 Key levels tab 实现以下内容：
- STH 和 LTH 的 KDE 密集带（K），画在右侧刻度轨；
- 高斯成分（M）；
- 附近有筹码价带列表；
- 价位表（阻力和支撑各 4 个）；
- Bucket 切换（$200 / $500 / $1000）。

**架构**
- onchain worker 的 URPD 阶段每轮取当天 D 的 9 份快照（`all`、`sth`、`lth` × `lin200`、`lin500`、`lin1000`）。
- 另取 D−1、D−7、D−30、D−90 四个历史日期的快照，每份只取一次，只用来确定桶网格（与原站相同）。
- 新增纯函数模块 `costbasis.py`，三种桶宽都预先算好，存入 `derived` 表（`kind="costbasis"`）。
- 新增只读接口 `GET /onchain/cost-basis`，一次返回三种桶宽。切换桶宽时前端不再发请求，也不访问 BRK。
- 前端新增 `levels-rail.tsx`，画在 `MarketChart` 的价格轴之前；inspector 增加价位表和附近价带。

**技术栈**：同 P1/P2。

**Spec**：[SPEC.md](SPEC.md) v3，相关章节为 §2、§3.0、§3.2、§5、§6。用户已授权全部阶段连续执行。本计划经过两轮独立评审（v1 → v2 → v3），修订记录见文末。

## 黄金样本（执行前已取得）

原站会话已过期，代理不输入密码。改用以下办法取得同一时刻的页面读数：
1. 把已保存的原站 `state-report.html` 放在 `127.0.0.1` 上打开，页面照常实时请求 bitview.space。
2. 在页面加载前后各抓一次 BRK 数据。两次逐字节相同，说明页面用的就是这份数据。

样本位于 `.local/research-samples/p3-golden-20261016T1829Z/`：

| 文件 | 内容 |
|---|---|
| `a/urpd_{all,sth,lth}_lin{200,500,1000}.json` | 2026-10-16 的 9 份 URPD，close 为 81217.6 |
| `past/urpd_{cohort}_lin{agg}_{date}.json` | D−1、D−7、D−30、D−90 的 36 份 URPD |
| `a/d_*.json` | 4 条模型线和 price_close 的 day1 末 3 点 |
| `PAGE.json` | 三种桶宽下的页面读数：表 2、附近价带、两侧总量与盈利占比、K 位置，以及由 SVG 几何反推的 M 的 μ、σ、π |
| `expected-{200,500,1000}.json` | 独立复算脚本 `state-report/tools/oracle_c7.py` 的全精度结果 |

`oracle_c7.py` 与页面逐项一致（例如 M 的 μ：页面 63384.48319993326，oracle 63384.483199933304）。它已按评审意见补上两条：没有峰时用 BIC 选 k；2 位小数取整按 `ROUND_HALF_UP`。补完以后 expected 不变。

## 计划层面的裁定（执行前已定）

| 编号 | 裁定 | 理由 | 如果错了的代价 |
|---|---|---|---|
| P3-R1 | 桶网格照原站，取 D、D−1、D−7、D−30、D−90 五个日期 × 三个 cohort 中出现过的 floor 的并集。历史日期的快照只用来提供 floor | 原站的做法。评审指出：黄金样本里历史日期没有多出 floor，所以"两种网格结果相同"区分不了两种做法 | 每天多 36 个请求，只在日期变化后发一次 |
| P3-R2 | 每个桶的 supply 按 `Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)` 取 2 位小数，等同于 JS `+x.toFixed(2)`（例如 0.125 → 0.13）。模型线先按 `floor(x + 0.5)` 取整，再判断是否落在域内、计入哪一段；显示值不变 | 原站的 `toFixed(2)` 和 `Math.round(MV)` | 无可见影响 |
| P3-R3 | 9 份当天快照由 worker 每轮取回，三种桶宽都预先算好。不采用 spec §3.0 "切换时再取"的写法 | spec §2 规定读接口不访问 BRK、不现算，这一条优先 | 每小时多 8 个请求 |
| P3-R4 | 当天快照都是同一天 D：先照 P1 确定 `all lin500` 的 D（今天，没有就用昨天），其余 8 份取 D 这一天的。`all lin500` 两天都没有时，其余请求一律不发 | 原站所有 cohort 和桶宽都用同一个 NOW | — |
| P3-R5 | 表 2 和附近价带始终计入 5 条模型线（相当于原站参考线全开的默认视图）。Cost lines 开关只控制画不画线 | 结果由后端预先算好 | 关掉线后价带不会重新计数 |
| P3-R6 | 刻度轨只画 K 带（spec D2）。M 只用于价带和表 2；价带列表附一行 M 的说明 | spec §5 已确认的界面 | 图上看不到 M；P5 再评估 |
| P3-R7 | 两侧总量和盈利占比按桶宽分别计算，显示在 STH bands 和 LTH bands 两个开关的图例里 | 原站各面板标题的口径 | — |
| P3-R8 | Bucket 只放在组件 state 中，不写入 URL，默认 $500 | spec 没有要求写入 URL | — |
| P3-R9 | 某个 cohort 的 KDE 没有找到峰时，照原站用 BIC 选 k：k 从 1 到 cap 逐个拟合，取 `−2·logL + (3k−1)·ln(max(域内行数, 2))` 严格最小的 k | 原站 `if (peakCount)` 对 0 个峰也会走到 BIC 分支（评审已指出 script_2:2676） | — |
| P3-R10 | 按取数时刻判断 forming，与 P2-R5 同理。`StoredCostBasis` 记 `snapshot_at`，即所用 D 当天快照中最早的 `fetched_at`。满足以下任一条件就算未收盘：`snapshot_at < D 结束`（快照取于 D 当天）；`computed_at < lines_as_of 结束`（模型线来自尚未结束的那一天）。`forming_at` 取未收盘日期中较晚那一天的 00:00 | 停服后复用的旧快照，以及跨日后的读取，都不会被当成已收盘 | — |
| P3-R11 | 模型线必须 5 条齐全（levels 算得出来，且 median 不为 None）才计算 cost-basis；否则清空。原因码包括 4 条模型线序列的 `series_missing:<name>` | 少了模型线，表 2 和价带会悄悄改变，违反 spec §1 第 2 条 | — |
| P3-R12 | step 取桶宽（200 / 500 / 1000）。如果快照的 aggregation 不是 `lin{bucket}`，抛 `ValueError` | 原站用 `Bs[1] − Bs[0]`，只有前两个 floor 不相邻时才会与桶宽不同，而那属于原站的缺陷 | 无 |
| P3-R13 | P1 fixture 目录 `fixtures/brk-2026-10-16/` 补入黄金样本中另外 8 份当天快照（README 写明它们来自 18:29Z 的抓取）。transport 按文件名提供 URPD，不存在的文件返回 404 | P1/P2 现有测试的"reasons 为空、last_error 为空"保持不变 | — |
| P3-R14 | urpd 表只保留需要的日期：今天、昨天、D、D−1、D−7、D−30、D−90。每次 URPD 阶段结束时删除其余日期；D 不存在时不清理 | 9 份快照每天约 230 KB，不清理的话一年约 80 MB | — |
| P3-R15 | GMM 成分的模型命名为 `GmmComponent` | `cycle.Component` 已是 OpenAPI schema，重名会导致生成的类型改名 | — |
| P3-R16 | cost-basis 的原因码只存在 `StoredCostBasis.reasons` 中，**不写入共享的 `reasons`** | 写进共享 reasons 会打破 P1 的 `test_urpd_outage_uses_latest_stored_snapshot`（D = 昨天时历史日期会 404），也会和 `_fail` 读回的共享 reasons 互相干扰 | — |

## 全局约束（沿用 P1/P2，增补如下）

**计算口径（原站 v1；以 `expected-*.json` 为准）**

- **网格**
  - floor 取 5 个日期 × 3 个 cohort 快照（同一桶宽）的并集，按升序排列。
  - 每行的值为 `price = floor + step/2`，以及 `all`、`sth`、`lth` 三列，取 D 当天的值，没有的记 0，都按 P3-R2 取整。
- **价格域**
  1. 只保留 `price ≥ 1000` 的行；
  2. 双指针 `i = 0`、`j = n−1`：在 `i < j` 且 `all[i] ≤ 0.5` 时 `i += 1`；然后在 `j > i` 且 `all[j] ≤ 0.5` 时 `j −= 1`；
  3. 保留 `rows[max(0, i−2) : min(n, j+3)]`。没有任何行的 `all > 0.5` 时，按这个写法会留下最后 ≤3 行；
  4. 域为 `[第一行 price − step/2, 最后一行 price + step/2]`。
- **KDE**（每个 cohort 分开）
  - 权重是域内各行的值，包括 0；
  - `h = 0.02 × (最后一行 price − 第一行 price)`；
  - 只累加 `|xi − xj| ≤ 5h` 的项；
  - 输出 `Σ w·exp(−z²/2) / (h·√(2π)) / Σw`；
  - 行数 < 3 或 Σw ≤ 0 时没有 K，也不拟合 M。
- **峰**
  - 局部极大的条件是 `y[i] > y[i−1]` 且 `y[i] ≥ y[i+1]`，i 从 1 到 n−2；
  - prominence：向左、向右各扫到第一个更高点为止，各取途经的最低值，再用峰高减去两侧最低值中较高的一个；
  - 保留 `prominence ≥ 0.05 × max(y)` 的峰；
  - 半高全宽 `width`：向两侧各找第一个 `y ≤ y[p]/2` 的点，与相邻点做线性插值（写法与原站 `peakFWHM` 相同）；某一侧找不到时，该侧端点就是 `x[p]`；
  - 每个峰输出：
    - `price = x[p]`；
    - `width`；
    - `btc`：落在 `[price − width/2, price + width/2]` 内的权重之和（闭区间）；
    - `share = btc / Σw`；
    - `strength = prominence / max(y)`。

  峰按价格升序，编号从 1 开始。
- **GMM**（每个 cohort 分开）
  - 输入：只取权重 > 0 的行，少于 3 行时没有 M；
  - `cap = max(1, min(5, floor(正权重行数 / 5)))`；
  - 有峰时 `k = max(1, min(cap, 峰数))`；没有峰时按 P3-R9 选 k；
  - **初始化**：
    - μ_j：取按 x 排序后加权累计占比首次 ≥ (j+0.5)/k 的那个 x；找不到时取最后一个 x；
    - 如果后一个 μ 不大于前一个，就设为前一个 + 1e-3；
    - σ0 = √(加权方差) / max(1, 0.6k)，初值 `max(σ0, 1e-6)`；
    - π 均等；
  - **迭代**（最多 120 次）：
    - E 步：
      - 各成分密度之和 ≤ 0 时，该行的 responsibilities 都取 1/k，对数似然项按 `log 1 = 0` 计；
      - 对数似然 = Σ 归一化权重 × log(密度和)；
    - M 步：
      - 某成分的加权 responsibilities 之和 ≤ 1e-12 时，跳过它的更新；
      - σ 的下限为 `max(σ0 × 1e-3, 1e-9)`；
    - 每轮把 π 重新归一化；
    - **M 步之后**才比较对数似然的变化，变化 < 1e-9 就停止，保留这一步的参数；
  - **所有求和都用显式的 `acc += x` 循环按行顺序累加**，不用内置 `sum()`（Python 3.12 起它对浮点做补偿求和，与 JS 不同），也不用 numpy 或 `math.fsum`。KDE、峰、总量的求和同样如此；
  - 输出按 μ 升序，每个成分为 `mu`、`sigma`、`share = π`、`btc = π × 正权重总和`；
  - 返回最后一次的对数似然，供 BIC 使用。
- **两侧总量**：在 D 当天整份快照的网格上计算，不受价格域影响。
  - `total = Σ{price ≥ 1000}`；
  - `in_profit = Σ{price ≥ 1000 且 price ≤ close} / total`；total 为 0 时为 None；
  - close 取 `all` 快照的 `close`，这就是 spot。
- **价带切片**
  - `seed = floor(lo / 4000) × 4000`；
  - 从 seed 开始每 2000 切一段，每段截到域内：`[max(lo, v), min(hi, v + 2000))`，只保留非空段。
- **候选价位**
  - 5 条模型线先取整，取整后满足 `lo ≤ v ≤ hi` 的才算；
  - 每个 STH 和 LTH 成分的 `μ − σ`、`μ`、`μ + σ`。

  一段内满足 `low ≤ v < high` 的候选数就是该段的 n；n > 0 的段算"有筹码"。
- **最近价带**
  - spot 所在的段是 `low ≤ spot < high` 的那一段；
  - 上方：取 `low ≥` spot 段的上沿（没有 spot 段时用 spot）的有筹码段，按 low 升序，取前 4 个；
  - 下方：取 `high ≤` spot 段的下沿的有筹码段，按 low 降序，取前 4 个；
  - 段内的候选按价格升序排列。
- **表 2**：`resistance[i] = above[i].high`，`support[i] = below[i].low`，最多各 4 个。

**原因码**（P3-R16：只存在 `StoredCostBasis.reasons` 中）
- `all lin500` 缺失时，P1 原样在共享 reasons 中记 `urpd_missing`。
- 以下原因码都在 `_derive` 中按库里的实际情况重新算，不看本轮请求是否成功，所以桶宽是否可用与原因码总是一致：
  - **当天快照**：其余 8 份中某份不在库里（日期为 D）时，记 `urpd_missing:<cohort>:<agg>`，例如 `urpd_missing:sth:lin200`。这个桶宽不可用。
  - **历史快照**：只对可用的桶宽检查。某份不在库里时，记 `urpd_grid_partial:<agg>`；该桶宽照常计算，网格用已有的日期。
  - **价格域为空**：`cost_basis` 返回 None 时，记 `urpd_empty:<agg>`，该桶宽不可用。真实数据中不会出现。
- 一个桶宽都不可用时，仍存一份 `StoredCostBasis`（`buckets=[]`，附原因码）。只有 `urpd` 为 None 或模型线不全时才清空。
- **cost-basis 视图的 reasons**：
  - `only(共享 reasons, ["urpd_missing", "brk_unavailable", 4 条模型线的 "series_missing:<name>"])`，再接上 `StoredCostBasis.reasons`；
  - 没有派生结果且以上为空时，用 `["brk_unavailable"]`。
- **`/status` 中的 urpd 数据集**：reasons 为 `only(共享, URPD_REASONS)` 加上 `StoredCostBasis.reasons`（若有）。

**URPD 阶段失败**（沿用 P1 的 R12）
- **当天 9 份**中任一请求抛出 `BrkError`，就是整个 URPD 阶段失败：
  - 记 `last_error`，5 分钟后重试；
  - cycle、levels、pressure 照常派生；
  - 不在共享 reasons 中加 `brk_unavailable`。
- **历史快照**的请求抛出 `BrkError` 时：只记一行日志（错误码），跳过这一份，阶段继续。缺失会在 `_derive` 中体现为 `urpd_grid_partial:<agg>`。
- cost-basis 用库里日期为 D 的快照计算，D 来自 `_recent_urpd`。同一天里复用的快照可能取自不同的小时，这一点接受；forming 按 P3-R10 判断。
- **请求预算**：
  - 每轮 9 个；
  - 历史快照在库里没有，或尚未"定稿"时，再取。定稿指 `fetched_at ≥ 该日结束 + 2h`，宽限与 day1 的 `GRACE_END` 相同。
  - 日期变化后的那一轮最多 +36 个。历史快照一直 404 时，每轮最多 +36 个，正常情况下为 0。
  - 日期变化后的头几轮里，D−1 每轮再取 9 份，直到定稿（约 3 轮），每天约 +54 个。

**界面**（以 mockup `key-levels.html` 和 `mobile.html` 为准）
- **控件行**：只在 Key levels、BTC、实时视图下显示。
  - 三个开关 Cost lines / STH bands / LTH bands，默认全开，用 `aria-pressed`；
  - Bucket 为 $200 / $500 / $1000 一组按钮，默认 $500。沿用 `market-chart.tsx` 里已有的 `aria-pressed` 按钮组写法，不用 radiogroup。
- **刻度轨**
  - 宽度 `railWidth(chartWidth)`：宽屏为 28；`chartWidth < 600` 时为 16（以图自己的宽度为准）；没有 rail 时为 0；
  - 有 rail 时 `plotWidth = max(120, chartWidth − 128 − railWidth)`，于是 `right` 左移 railWidth；
  - `railX = right + 4`，价格轴标签在 `railX + railWidth + 7 = right + railWidth + 11`，绝对位置与没有 rail 时相同；
  - `visibleWindow` 仍然收到 `chartWidth − 128`，K 线根数不变；
  - `edgeLimit = floor((chartWidth − 32 − railWidth) / 6.6)`，没有 rail 时与现在相同；
  - `onPointerMove` 中先算出 svg 坐标 `svgX`，`svgX > right` 时直接返回，不改变选中的 K 线。
- **rail 的传入**：只要 `onchainShown`，`rail` 就传数组，数据未到或不可用时传 `[]`，这样几何不会在数据到达后跳动。
- **K 条**
  - 分 STH（rose）和 LTH（sky）两条 lane；
  - 每个 K 是从 `price − width/2` 到 `price + width/2` 的竖条，横向宽度随 strength 增大；
  - 只画价格范围内的部分，**不改变 y 轴**。
- **悬停或键盘聚焦 K 条**
  - 在主图上铺一层半透明区带；
  - 图下的 `role="status"` 读数行显示该 K 的信息；这一行只在传入 `rail` 时存在。
  - 结构：rail 是 `<g role="list" aria-label="Cost-basis bands">`，每个 K 条是 `role="listitem"`，带 `tabIndex=0` 和 `aria-label`；
  - K 条在 `onKeyDown` 中 `stopPropagation`，避免触发图的左右键；
  - 有 `:focus-visible` 描边。
- **SVG 角色**：有 rail 时，外层 svg 的 `role` 由 `img` 改为 `group`（aria-label 不变），否则 K 条对读屏软件不可见。
- **inspector 的顺序**：
  1. 价位表；
  2. 附近有筹码价带；
  3. P1 的 Cost lines；
  4. Cycle；
  5. Source。
- **价位表**：列名为 1st–4th，用 `$86.0k` 的写法；空格显示 `—`。
- **附近价带**
  - 上方的行由远到近显示，中间一行是 spot，下方由近到远；
  - 区间用 `$84,000 – $86,000`；
  - 距 spot 的百分比按段的**中点**计算，保留 1 位小数，带正负号，用 `−` 而不是 `-`；spot 行的这一列显示 `—`；
  - 候选标签：模型线用 P1 的线名；成分写成 `STH M2 −σ`、`STH M2`、`STH M2 +σ`；
  - 列表下附一行说明：M 是该 cohort 成本分布的高斯成分，±σ 是一个标准差。
- `reasonText` 能读出 `urpd_missing:<cohort>:<agg>` 和 `urpd_grid_partial:<agg>`，en 和 zh 都要有。
- 文案走 `i18n.ts`，en 和 zh 的键一致。

## 评审重点（Review Focus）

1. **某个桶宽缺一份当天快照**（例如 `sth lin200` 返回 404）：只有 $200 不可用并显示原因，$500 和 $1000 照常。测试在 Task 2、Task 6。
2. **`all lin500` 成功、之后某份请求失败**：levels 和 cycle 照常更新，共享 reasons 中没有 `brk_unavailable`，cost-basis 用库里同一天的快照，原因码与可用桶宽一致。测试在 Task 2。
3. **spot 恰好落在段的边界上**（spot = 80000）：spot 段是 [80000, 82000)。测试在 Task 1。
4. **K 带或模型线超出价格范围**：y 轴不变，K 线根数不变。测试在 Task 5。
5. **跨日**：00:12 时今天的 URPD 还不存在，9 份都用昨天的；forming 按 P3-R10 判断。测试在 Task 2、Task 3。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `onchain/costbasis.py`（新建） | 网格、KDE、峰、GMM 与 BIC、总量、切片、最近价带、表 2；`StoredCostBasis` |
| `onchain/store.py`（修改） | `urpd(cohort, day, agg)`、`urpd_fetched_at(cohort, day, agg)`、`prune_urpd(keep)` |
| `onchain/sync.py`（修改） | 当天 9 份快照、历史快照、清理、派生 `costbasis` |
| `onchain/models.py`、`onchain/api.py`（修改） | `CostBasisView`、`/cost-basis` 接口、`/status` 的 urpd 原因码 |
| `tests/onchain/fixtures/brk-2026-10-16T1829Z/`（新建） | 黄金样本：当天 9 份、历史 36 份、day1 末 3 点、`expected-*.json`、`page.json`、README |
| `tests/onchain/fixtures/brk-2026-10-16/`（修改） | 补入 8 份当天快照（P3-R13） |
| `tests/onchain/onchain_fixture.py`（修改） | transport 按文件提供 URPD，可指定目录，可按 (cohort, agg) 注入 404 或 500 |
| `tests/onchain/test_onchain_costbasis.py`（新建）；`test_onchain_{store,sync,api}.py`（修改） | 后端测试 |
| `openapi.json`、`api-schema.d.ts`（由 `make contract` 生成） | 契约 |
| `onchain-contract.ts`、`client.ts`（修改） | `costBasisViewSchema`、`costBasisSample`、`getCostBasis` |
| `levels-rail.tsx`、`levels-rail.test.tsx`（新建）；`market-chart.tsx`（修改） | 刻度轨、悬停铺开 |
| `cost-basis-panel.tsx`、`cost-basis-panel.test.tsx`（新建） | 价位表、附近价带 |
| `market-page.tsx`、`onchain-levels.tsx`、`i18n.ts`、`market.css` 及相关测试（修改） | 控件行、组装 |
| `docs/features/btc-onchain-perp/P3-VERIFICATION.md`（新建） | 核验记录 |

后端检查命令：在仓库根目录运行 `make check`。只跑 Python 时用 `.venv-foundation/bin/python -m pytest services/analytics/tests/onchain -q`，再加上 `ruff` 和 `mypy`，命令写法照 `Makefile`。

---

### Task 1：成本分布计算（`costbasis.py`）与黄金样本

**Files**
- 新建：`onchain/costbasis.py`、`tests/onchain/test_onchain_costbasis.py`
- 新建：`tests/onchain/fixtures/brk-2026-10-16T1829Z/`，所有文件平铺在这一层，文件名不会重复。从 `.local/research-samples/p3-golden-20261016T1829Z/` 复制以下文件：
  - `a/urpd_*.json`，共 9 份；
  - `past/*.json`，共 36 份；
  - `a/d_*.json`，改名为 `day1_<name>.json`；
  - `expected-{200,500,1000}.json`；
  - `PAGE.json`，改名为 `page.json`。

  再写一个 README，说明来源和取数方法，内容参照本计划"黄金样本"一节。

**Interfaces**
- 常量：`BUCKETS = (200, 500, 1000)`、`COHORTS = ("all", "sth", "lth")`、`MIN_PRICE = 1000.0`、`LIVE_SUPPLY = 0.5`、`PAD = 2`、`BANDWIDTH = 0.02`、`MIN_PROMINENCE = 0.05`、`KERNEL_CUT = 5.0`、`MAX_COMPONENTS = 5`、`EM_ITERATIONS = 120`、`EM_TOLERANCE = 1e-9`、`SLICE = 2000.0`、`NEAREST = 4`、`PAST_DAYS = (1, 7, 30, 90)`
- 类型：`Bucket = Literal[200, 500, 1000]`、`Cohort = Literal["sth", "lth"]`
- 模型（`Model` 基类来自 `..market`）：
  - `Peak`：`price`、`width`、`btc`、`share`、`strength`，均为 float
  - `GmmComponent`：`mu`、`sigma`、`share`、`btc`，均为 float（P3-R15）
  - `CohortClusters`：`cohort: Cohort`、`total: float`、`in_profit: float | None`、`peaks: list[Peak]`、`components: list[GmmComponent]`
  - `Candidate`：
    - `kind: Literal["line", "component"]`
    - `price: float`：模型线为取整后的值
    - `line: LineName | None`
    - `cohort: Cohort | None`
    - `index: int | None`：从 1 开始
    - `edge: Literal["low", "mid", "high"] | None`
  - `Band`：`low: float`、`high: float`、`candidates: list[Candidate]`
  - `BucketCostBasis`：
    - `bucket: Bucket`
    - `domain_low: float`、`domain_high: float`
    - `spot: float`
    - `sth: CohortClusters`、`lth: CohortClusters`
    - `above: list[Band]`、`below: list[Band]`：都按离 spot 由近到远排列
    - `resistance: list[float]`、`support: list[float]`
  - `StoredCostBasis`：`urpd_date: date`、`lines_as_of: date`、`snapshot_at: AwareDatetime`、`buckets: list[BucketCostBasis]`、`reasons: list[str]`
- 函数：
  - `weighted_kde(centers: Sequence[float], weights: Sequence[float], h: float) -> list[float]`
  - `find_peaks(centers: Sequence[float], weights: Sequence[float]) -> list[Peak]`
  - `fit_gmm(xs: Sequence[float], ws: Sequence[float], k: int) -> tuple[list[GmmComponent], float] | None`：返回成分和最后一次的对数似然
  - `select_components(xs: Sequence[float], ws: Sequence[float], peaks: int, rows: int) -> list[GmmComponent]`：有峰时按峰数选 k；没有峰时按 BIC 选 k（`rows` 是域内行数）；少于 3 行时返回空列表
  - `cost_basis(today: dict[str, Urpd], past: Sequence[Urpd], bucket: Bucket, lines: Sequence[ModelLine]) -> BucketCostBasis | None`
    - `today` 以 `all`、`sth`、`lth` 为键，日期相同；
    - `past` 是同一桶宽的历史快照，只取 floor，可以为空；
    - aggregation 不是 `lin{bucket}`、缺 cohort、日期不同，或 `lines` 不是 5 条（每个 `LineName` 恰好一条）时，抛 `ValueError`；
    - 价格域内不足 1 行时返回 None。

步骤：

- [ ] **Step 1：写失败的测试**

  `test_golden_parity[bucket]` 对 200、500、1000 各跑一次：
  - 输入：当天 9 份中对应桶宽的 3 份，以及对应桶宽的历史 12 份；
  - `lines` 为 day1 fixture 的最后一个值（true_mean 77481.81、short_term 74475.07、average 53845.04、long_term 49245.48），加上 P1 的 `median_cost(all lin500)`；
  - 与 `expected-{bucket}.json` 比较，`pytest.approx(rel=1e-9)`，比较项包括：
    - `domain_low`、`domain_high`、`spot`；
    - 两侧的 `total`、`in_profit`；
    - 每个峰的五个字段；
    - 每个成分的四个字段；
    - `resistance`、`support`；
    - 每个价带的 low、high 和候选标签。标签按约定写法从 Candidate 拼出，例如 `STH M2 −σ`、`True mean`。
  - 期望值摘录如下，测试中要直接写出：

    | 项目 | 200 | 500 | 1000 |
    |---|---|---|---|
    | 价格域 | 1000 – 125800 | 1000 – 126000 | 1000 – 126000 |
    | STH K | 63500, 82300 | 63750, 82250 | 63500, 82500 |
    | LTH K | 6900, 39100, 67300, 84900, 108100 | 6750, 38750, 67250, 84750, 108250 | 7500, 39500, 67500, 85500, 108500 |
    | resistance | 86000, 88000, 96000, 104000 | 同 200 | 86000, 90000, 96000, 104000 |
    | support | 76000, 74000, 70000, 64000 | 同左 | 同左 |
    | STH in_profit | 0.6385303598567579 | 0.6227192201679547 | 0.6227192222272292 |
    | LTH in_profit | 见 expected | 见 expected | 0.5854495647196322 |

  - `test_matches_page_readings`：用 `page.json` 中各桶宽的读数核对以下各项：
    - 表 2 的 `$x.xk` 字符串；
    - 价带区间、n、标签；
    - 两侧 `3.66M BTC total · 62% in profit` 的读数，按页面格式化后比较；
    - K 价位，容差 1e-6；
    - M 的 μ，容差 0.01。
  - 边界和规则用例：
    - `test_trim_keeps_two_padding_rows`；
    - `test_trim_without_live_rows_keeps_last_three`；
    - `test_spot_on_slice_boundary`：spot = 80000 时，spot 段为 [80000, 82000)；
    - `test_slices_clip_to_domain`：第一段为 [1000, 2000)，最后一段为 [124000, 126000)；
    - `test_line_outside_domain_not_counted`；
    - `test_line_rounding_half_up`：74998.5 取整为 74999，四舍六入五成双会得到 74998；
    - `test_supply_rounding_matches_tofixed`：0.125 → 0.13；
    - `test_past_floor_extends_grid`：历史快照多出一个上沿 floor 时，价格域的上沿随之改变；
    - `test_select_components_uses_bic_without_peaks`：直接测试 `select_components(..., peaks=0, rows=n)`。用两簇分得很开的合成数据，并在测试里按全局约束手算每个 k 的 BIC，结果是 BIC 严格最小的 k；`peaks=3` 时 k 等于 `min(cap, 3)`；
    - `test_gmm_zero_density_falls_back`：一个成分离数据极远，密度下溢为 0，不抛异常；
    - `test_four_lines_raise`；
    - `test_gmm_needs_three_positive_rows`；
    - `test_component_k_capped_by_rows`：正权重行 9 行、峰 4 个时，k = 1；
    - `test_mismatched_dates_raise`；
    - `test_wrong_aggregation_raises`。

- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 运行后端检查，然后提交。
  - commit message：`feat(onchain): compute cost-basis clusters with original v1 rules`

### Task 2：URPD 快照、清理与 `costbasis` 派生

**Files**
- 修改：`onchain/store.py`、`onchain/sync.py`、`onchain/costbasis.py`（如需辅助函数）
- 修改：`tests/onchain/onchain_fixture.py`、`tests/onchain/test_onchain_store.py`、`tests/onchain/test_onchain_sync.py`
- 修改：`tests/onchain/fixtures/brk-2026-10-16/`，补入 8 份当天快照，README 加一行说明（P3-R13）。说明这个目录里原有的 `urpd_all_lin500.json` 取自 13:39Z（close 82154.25，`test_onchain_sync.py:123` 依赖它），补入的 8 份取自 18:29Z（close 81217.6），所以这个目录**不能用来断言 cost-basis 的数值**，数值只对黄金目录断言。

**Interfaces**
- 消费 Task 1 的 `cost_basis`、`BUCKETS`、`PAST_DAYS`、`StoredCostBasis`。
- `OnchainStore`：
  - `urpd(cohort: str, day: date, agg: str) -> Urpd | None`
  - `urpd_fetched_at(cohort: str, day: date, agg: str) -> datetime | None`
  - `prune_urpd(keep: Set[date]) -> None`
- `sync.py`：
  - 常量 `URPD_SET`：9 个 (cohort, agg) 组合，`("all", "lin500")` 排在第一个；
  - derived 的 kind 为 `"costbasis"`，载荷为 `StoredCostBasis`。
- `onchain_fixture.brk_transport` 新增参数：
  - `urpd_dir: Path | None`：默认用 P1 fixture 目录；
  - `urpd_missing: Set[tuple[str, str]]`：对这些 (cohort, agg) 返回 404；
  - `urpd_fail: Set[tuple[str, str]]`：对这些 (cohort, agg) 返回 500。

  其他规则：
  - `_urpd` 先找 `urpd_{cohort}_{agg}_{date}.json`，找不到再找 `urpd_{cohort}_{agg}.json`；都找不到返回 404。删掉原来的 400 分支；
  - 返回体的 `date` 改成请求的日期（P1 原样）；
  - 黄金目录中历史日期有专门的文件；P1 目录没有，历史日期的请求就用当天那份文件。

**行为**（P2 合并后 `_derive` 的签名为 `_derive(urpd, at, hour1_missing, hour1_at)`，`hour1_at is None` 时会提前返回）
1. 照 P1 确定 `all lin500` 的快照和日期 D。D 不存在（两天都 404）时，其余请求都不发，也不清理。
2. 按 `URPD_SET` 的顺序，用日期 D 取其余 8 份，取到的存库。这 8 份中任一请求抛出 `BrkError`，就是本阶段的错误：`urpd` 改用 `_recent_urpd`（P1 原样）。
3. **历史快照**：对 `PAST_DAYS` 中的每个日期 `d = D − n` 和 9 个组合，满足以下任一条件就请求，取到的存库：
   - 库里没有；
   - 尚未定稿：`urpd_fetched_at < d 的次日 00:00 + 2h`。

   这些请求抛出 `BrkError` 时，只记一行日志（错误码），跳过，不算阶段错误。
4. 阶段结束时（D 存在，包括第 2 步失败时：先清理再抛出）调用 `prune_urpd({today, yesterday, D, D−1, D−7, D−30, D−90})`。
5. **`_derive` 中 cost-basis 的位置**：在 levels 之后、`if hour1_at is None: return` 之前，复用 levels 的 `lines` 和 `as_of`。hour1 失败不影响 cost-basis。
   - `urpd` 为 None，或模型线不全（P3-R11）时：`clear_derived("costbasis")`。
   - 否则，对每个桶宽从库中读取 D 的 3 份当天快照：
     - 缺任何一份，就跳过这个桶宽，记 `urpd_missing:<cohort>:<agg>`；
     - 3 份都在时，再读取历史快照（缺失的记 `urpd_grid_partial:<agg>`），然后调用 `cost_basis`；返回 None 时记 `urpd_empty:<agg>`。
   - 结果总是存成一份 `StoredCostBasis`，包括 `buckets=[]` 的情况：
     - `lines_as_of = as_of.date()`；
     - `snapshot_at` 为所用当天快照中最早的 `urpd_fetched_at`；没有可用桶宽时，取 `all lin500` 的 `fetched_at`；
     - `reasons` 为上面这些原因码。
   - 计算中出现任何意外异常时：`clear_derived("costbasis")`，日志只记固定错误码 `costbasis_failed`，继续派生 pressure 并写共享状态，不影响 `last_error`。
6. 共享的 `reasons` 和 `missing_series` **不变**（P3-R16）。

步骤：

- [ ] **Step 1：写失败的测试**
  - `test_store_urpd_by_day_and_fetched_at`、`test_prune_urpd_keeps_listed_days`
  - `test_sync_fetches_nine_snapshots_for_one_day`：用黄金目录作 `urpd_dir`。期望：
    - 9 个当天请求的日期都是 D；
    - 第一轮另有 36 个历史请求，第二轮没有；
    - 三种桶宽都在，`urpd_date` 等于 D。
  - `test_past_snapshot_stored_intraday_is_refetched`：历史快照的 `fetched_at` 早于"次日 00:00 + 2h"时会再取；晚于时不再取。
  - `test_past_snapshot_error_does_not_fail_the_stage`：历史日期返回 500 时，`last_error` 为空；该桶宽照常存在，并带 `urpd_grid_partial:<agg>`。
  - `test_all_buckets_missing_still_stores_reasons`：8 份全部 404 时，costbasis 存在，`buckets=[]`，reasons 列出 6 个 `urpd_missing:*`（sth/lth × 3 种桶宽），再加上 `urpd_missing:all:lin200` 和 `urpd_missing:all:lin1000`。
  - `test_costbasis_reasons_stay_out_of_shared_reasons`：同上场景下，共享 reasons 中没有任何 `urpd_missing:*`。
  - `test_missing_snapshot_drops_only_that_bucket`：`urpd_missing={("sth", "lin200")}`。期望：
    - buckets 只有 500 和 1000；
    - `StoredCostBasis.reasons` 中有 `urpd_missing:sth:lin200`，并且没有 `urpd_grid_partial:lin200`；
    - `last_error` 为空，`last_success_at` 推进。
  - `test_failed_snapshot_keeps_stored_same_day`：第一轮全部成功；第二轮 `urpd_fail={("lth", "lin1000")}`。期望：
    - `last_error` 为 BRK 的错误码；
    - 共享 reasons 中没有 `brk_unavailable`；
    - levels 和 cycle 的 computed_at 推进；
    - costbasis 仍有三种桶宽；
    - 原因码与可用桶宽一致。
  - `test_hour1_failure_still_derives_costbasis`
  - `test_day_rollover_uses_yesterday_for_all`
  - `test_no_urpd_sends_no_other_requests_and_clears_costbasis`
  - `test_missing_lines_clears_costbasis`
  - P1/P2 现有的 sync 和 api 测试**不改断言**，全部通过（P3-R13）。

- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 运行后端检查，然后提交。
  - commit message：`feat(onchain): fetch URPD snapshots for cost basis and derive it`

### Task 3：接口与契约

**Files**
- 修改：`onchain/models.py`、`onchain/api.py`、`tests/onchain/test_onchain_api.py`
- 生成：`make contract`

**Interfaces**
- `CostBasisView(Model)`：
  - `data_state: DataState`：取 `day1_state(min(urpd_date, lines_as_of), now)`；没有派生结果时为 `unavailable`
  - `reasons: list[str]`、`refreshing: bool`
  - `forming_at: AwareDatetime | None`：按 P3-R10
  - `urpd_date: date | None`、`lines_as_of: date | None`、`snapshot_at: AwareDatetime | None`、`computed_at: AwareDatetime | None`
  - `buckets: list[BucketCostBasis]`
  - `brk_version: str | None`
- `GET /api/wheelhouse/v1/onchain/cost-basis`，response_model 为 `CostBasisView`。reasons 按全局约束组合；没有派生结果且为空时用 `["brk_unavailable"]`（P1 惯例）。
- `COST_BASIS_SHARED = ("urpd_missing", *(4 条模型线的 "series_missing:<name>"), "brk_unavailable")`：用于从共享 reasons 中筛选。
- `/status` 中 urpd 数据集的 reasons 为 `only(共享, URPD_REASONS)` 加上 `StoredCostBasis.reasons`（若有）。

步骤：

- [ ] **Step 1：写失败的测试**
  - `test_cost_basis_view_from_golden_fixture`：用黄金目录作 `urpd_dir` 同步一轮。期望：
    - 三种桶宽都在；
    - 500 的 resistance 为 `[86000, 88000, 96000, 104000]`，support 为 `[76000, 74000, 70000, 64000]`；
    - urpd_date 为 2026-10-16。

    这里的 day1 是 P1 fixture 而不是黄金样本，所以**只比较表 2 和价带**，不与 expected 全量比较。
  - `test_cost_basis_forming`（P3-R10），各情况都直接构造 `StoredCostBasis` 存入库，再请求接口：
    - 快照和计算都在 2026-10-16 当天：forming_at 为 2026-10-16T00:00Z；
    - 同一份结果，第二天 00:30 读取：forming_at 仍为 2026-10-16T00:00Z；
    - 停服复用：快照取于 10-16 23:12，computed_at 为 10-17 00:30，urpd_date 和 lines_as_of 都是 10-16：forming_at 为 2026-10-16T00:00Z；
    - 快照取于 10-17 02:30（10-16 已定稿），urpd_date 和 lines_as_of 都是 10-16，computed_at 为 10-17 02:31：forming_at 为 None；
    - 混合：urpd_date 为 10-17、快照取于当天，lines_as_of 为 10-16、computed_at 为 10-17：forming_at 为 2026-10-17T00:00Z；
    - `data_state` 按 `min(urpd_date, lines_as_of)` 计算。
  - `test_cost_basis_unavailable_before_sync`：`data_state == "unavailable"`，`reasons == ["brk_unavailable"]`。
  - `test_cost_basis_reasons_filtered`：pressure 的原因码不出现在 cost-basis 中；共享的 `urpd_missing` 和 `StoredCostBasis.reasons` 都出现。
  - `test_status_urpd_reasons_include_snapshot_codes`：`StoredCostBasis.reasons` 出现在 `/status` 的 urpd 数据集中，不出现在 day1 和 hour1 中。
  - `test_read_does_not_touch_network`：沿用 P1 的模式。

- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 运行 `make contract` 和后端检查，然后提交。
  - commit message：`feat(onchain): expose cost basis endpoint`

### Task 4：前端契约与客户端

**Files**
- 修改：`onchain-contract.ts`、`client.ts` 及对应测试

**Interfaces**
- `costBasisViewSchema`（Zod），字段与 `CostBasisView` 一一对应。
- `costBasisSample`：expected 文件里没有 `Candidate` 结构，所以 sample 由后端生成。用 Task 1 的 `cost_basis` 在黄金输入上算出三种桶宽（写一个一次性的脚本，或用 pytest 打印），把得到的 `BucketCostBasis` JSON 照抄进 TS。外层包成一份 fresh 视图：`urpd_date`、`lines_as_of` 都为 `2026-10-16`，`snapshot_at` 为 `2026-10-16T18:29:40Z`。数值可以四舍五入到 6 位有效数字，但表 2、价带区间、候选价位和 K 价位必须与后端输出完全相同。
- `getCostBasis(signal?: AbortSignal): Promise<CostBasisView>`

步骤：

- [ ] **Step 1：写失败的测试**
  - sample 能通过校验；
  - 缺字段的载荷被拒绝；
  - `getCostBasis` 返回解析后的对象（fetch 桩）。
- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 提交，commit message：`feat(onchain): add cost basis contract and client`

### Task 5：刻度轨与悬停铺开

**Files**
- 新建：`levels-rail.tsx`、`levels-rail.test.tsx`
- 修改：`market-chart.tsx` 及其测试、`market.css`

**Interfaces**
- 类型：

  ```ts
  export interface RailBand {
    id: string;                // "sth-1"
    cohort: "sth" | "lth";
    index: number;             // K number, 1-based
    price: number;
    low: number;               // price - width / 2
    high: number;              // price + width / 2
    strength: number;          // 0..1
    btc: number;
    share: number;
  }
  ```

- `MarketChart` 新增可选 prop `rail?: RailBand[]`，几何按全局约束的"刻度轨"一节。
- `railWidth(chartWidth: number): number`：返回 28 或 16。
- `LevelsRail({ bands, y, top, bottom, x, width, plotLeft, plotRight, onActive })`：渲染 `<g role="list">`。
  - 每个 band 是一个 `role="listitem"` 的可聚焦 `<rect>`，带 `tabIndex=0`、`aria-label`，`onKeyDown` 中 `stopPropagation`；
  - band 完全在 [bottom, top] 之外就不画，部分超出的截到边界；
  - band 的横向宽度 = `2 + strength × (laneWidth − 2)`，`laneWidth = width / 2 − 1`；
  - 悬停或聚焦时，在 plotLeft 到 plotRight 之间画 `.wh-rail-spread`，并调用 `onActive(band | null)`。
- 读数行（`role="status"`）只在传入 `rail` 时存在，例如：`STH K2 · $82,250 · width $9,971 · 1.91M BTC (52.1%) · strength 100%`。

步骤：

- [ ] **Step 1：写失败的测试**
  - `rail` 为 undefined 时：现有快照和测试不变，没有 rail 元素，也没有读数行；svg 的 role 仍是 `img`。
  - 传入 `rail=[]` 时（jsdom 中 `chartWidth` 保持 980）：
    - 价格轴标签的 x 与不传 rail 时相同；
    - 最后一根 candle 的 x 左移 28；
    - K 线根数不变，用渲染出的 candle 数比较；
    - svg 的 role 为 `group`。
  - mock `ResizeObserver` 让 `chartWidth` 为 500 时，rail 宽 16。
  - 在 `svgX > right` 的位置触发 pointermove，选中的 K 线不变。
  - 传入两个 band，其中一个完全在价格范围外：只画一个；`top` 和 `bottom` 不变，用一条 overlay 线的 y 坐标前后相同来验证。
  - 聚焦 band 后出现 `.wh-rail-spread`，读数行包含 `STH K2` 和 `$82,250`；在 band 上按左方向键，选中的 K 线不变；失焦后两者都消失。
  - band 的横向宽度随 strength 单调增加。
- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 运行 wheelhouse 全套测试和 type-check，然后提交。
  - commit message：`feat(onchain): draw K bands on a price rail`

### Task 6：价位表、附近价带与 Key levels 组装

**Files**
- 新建：`cost-basis-panel.tsx`、`cost-basis-panel.test.tsx`
- 修改：`market-page.tsx`、`onchain-levels.tsx`、`i18n.ts`、`market.css` 及相关测试（如 `market-defaults.test.tsx`）

**Interfaces**
- `CostBasisPanel({ view, error, bucket })`：渲染价位表和附近价带。各状态的显示：
  - 加载中；
  - 请求失败：显示错误，不显示旧数据；
  - `unavailable`：显示原因；
  - `stale`：显示提示；
  - `refreshing`：显示 `role="status"` 的提示；
  - 有 `forming_at`：显示 "the {{date}} snapshot was still forming"（en + zh），date 取 `forming_at` 的日期；
  - 所选桶宽不在 `buckets` 中：显示 "not available for this bucket size" 和对应原因。
- `OnchainLevels` 新增可选 props `costBasis`、`costBasisError`、`bucket`，在 Cost lines 之前渲染 `CostBasisPanel`。
- `reasonText` 支持 `urpd_missing:<cohort>:<agg>` 和 `urpd_grid_partial:<agg>`。
- `market-page.tsx`：
  - 新增 query：key 为 `["wh", "onchain", "cost-basis"]`，`refetchInterval: 300000`，`enabled: onchainShown`；
  - 新增 state：`showLines`、`showSth`、`showLth`（默认 true），`bucket`（默认 500）；
  - 控件行放在图上方，只在 `onchainShown` 时显示；
  - 两个 bands 开关的图例显示该桶宽的总量和盈利占比，例如 `3.66M BTC ≥$1k · 62% in profit`；`in_profit` 为 None 时显示 `—`；cost-basis 为 stale 时，图例追加 stale 标记；
  - `overlays` 只在 `showLines` 时传入；
  - 只要 `onchainShown`，`rail` 就传数组：所选桶宽 `sth.peaks` 和 `lth.peaks` 的映射，按开关过滤，不可用时为 `[]`。

步骤：

- [ ] **Step 1：写失败的测试**
  - 用 `costBasisSample` 渲染 `CostBasisPanel`，桶宽为 500。期望：
    - Resistance 行为 `$86.0k $88.0k $96.0k $104.0k`；
    - Support 行为 `$76.0k $74.0k $70.0k $64.0k`；
    - 列名为 1st–4th；
    - 价带共 8 行，外加 1 行 spot，spot 行的百分比为 `—`；
    - 第一行为 above `$102,000 – $104,000`，n 为 1，标签 `LTH M5 −σ`，`+26.8%`；
    - 最后一行为 below `$64,000 – $66,000`，n 为 2，标签 `STH M1 +σ, LTH M3`，`−20.0%`。
  - 桶宽为 1000 时，Resistance 第 2 列为 `$90.0k`。
  - 只有 3 个上方价带时，第 4 列显示 `—`。
  - sample 中去掉 200，选中 200 时显示桶宽不可用和 `urpd_missing:sth:lin200` 的可读文案。
  - 有 forming 和 refreshing 时，各自的文案出现。
  - `MarketPage`（BTC，Key levels，实时视图）：
    - 控件行存在；
    - 关掉 Cost lines：overlay 线消失，价位表不变；
    - 关掉 STH bands：rail 中没有 sth band；
    - 切换桶宽不触发新的 cost-basis 请求，用请求计数验证；
    - cost-basis 尚未返回时，图已经按 `rail=[]` 留出刻度轨。
  - ETH 和快照视图下，没有控件行，也没有 rail。
  - en 和 zh 的 i18n 键一致（沿用现有测试）。
- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 运行 wheelhouse 全套测试和 type-check，然后提交。
  - commit message：`feat(onchain): show levels table and nearest bands with bucket switch`

### Task 7：核验与记录

**Files**
- 新建：`docs/features/btc-onchain-perp/P3-VERIFICATION.md`

步骤：

- [ ] **Step 1**：运行 `make check`。
- [ ] **Step 2**：用分支代码重启本机的 Python 服务；`make sync` 后重启 Vite。
- [ ] **Step 3：与原站同时对照**
  1. 抓一次 BRK（当天 9 份，`fetch_urpd.py` 的写法）；
  2. 把本机开发库的 `next_due` 置空，触发一轮同步，并确认库里的 9 份快照与第 1 步抓到的逐字节相同（比较 buckets 和 close）；
  3. 在本地打开已保存的原站页面，读取三种桶宽的读数；
  4. 再抓一次 BRK，与第 1 步一致。

  四步都一致后，比较表 2、附近价带和两侧读数，要求与 `/cost-basis` 逐格一致。同时记录当天网格与五日并集网格是否有差异。
- [ ] **Step 4：浏览器核验**（1440px 和 390px）
  - 控件行；
  - 刻度轨，窄屏为 16px；
  - 悬停和键盘聚焦时的铺开；
  - 贴边标注；
  - 表 2 和价带列表；
  - 无横向溢出、控制台无错误；
  - 与 mockup 对照。
- [ ] **Step 5**：写核验记录并提交。
  - commit message：`docs(onchain): record P3 verification`

## 评审修订记录（v1 → v2）

独立评审（opus）给出 1 个 Critical、9 个 Important、13 个 Minor，处理如下：

| 评审意见 | 处理 |
|---|---|
| C1：默认 fixture 只有 `all lin500`，并对其他桶宽返回 400，会让 P1/P2 的测试失败 | P3-R13：补入 8 份当天快照；transport 改为文件不存在时返回 404 |
| I1：0 个峰时原站走 BIC | P3-R9 |
| I2：GMM 缺少零密度回退、收敛判断的位置和求和顺序 | 写入全局约束，并加测试 |
| I3：hour1 失败时 `_derive` 会提前返回，跳过 cost-basis | Task 2 行为第 6 条 |
| I4：原因码与可用桶宽可能不一致 | 原因码改为按库里的实际情况计算；D 不存在时其余请求都不发 |
| I5：缺模型线会悄悄改变表 2 | P3-R11 |
| I6：forming 的判断不完整 | P3-R10，并加测试和面板状态 |
| I7：刻度轨几何没有写清 | 全局约束的"刻度轨"一节 |
| I8：K 条在 `role="img"` 内，读屏软件不可见 | 有 rail 时 role 改为 group；`stopPropagation`；`:focus-visible` |
| I9：P3-R1 的依据区分不了两种做法 | 改为照原站取五日并集 |
| M1–M13 | 全部采纳，分别写进裁定、全局约束和各 Task。其中 M11 对应 P3-R14，M12 对应 Task 7 第 3 步 |

## 评审修订记录（v2 → v3）

v2 的复核（sonnet）给出 1 个 Critical、6 个 Important，以及若干 Minor，处理如下：

| 评审意见 | 处理 |
|---|---|
| C-1：cost-basis 的原因码写进共享 reasons，会打破 P1 的 `test_urpd_outage_uses_latest_stored_snapshot` | P3-R16：原因码只存在 `StoredCostBasis.reasons` 中 |
| I-1：停服后复用的盘中快照会被当成已收盘 | P3-R10 改为按 `snapshot_at` 判断；面板文案写明日期；补 forming 测试 |
| I-2：一个桶宽都不可用时原因码丢失；`urpd_grid_partial` 对不可用的桶宽也会出现；价格域为空时没有原因码 | 总是存一份结果（`buckets=[]` 也存）；`urpd_grid_partial` 只对可用桶宽检查；新增 `urpd_empty:<agg>` |
| I-3：刻度轨测试的几何断言与规则矛盾；`edgeLimit` 和指针规则没写清 | 改为价格轴标签位置不变、最后一根 candle 左移；给出 `edgeLimit` 公式和指针规则，并加测试；`railWidth(chartWidth)` |
| I-4：`Component` 与 `cycle.Component` 重名 | P3-R15：改名为 `GmmComponent` |
| I-5：历史快照的错误没有限定范围 | 历史快照出错只记日志，不算阶段错误；写明请求预算；D 不存在时不清理；定稿判断加 2h 宽限 |
| I-6：`_derive` 的签名已经变了 | 写明 P2 合并后的签名，cost-basis 放在提前返回之前 |
| Minor | 求和改用显式循环；新增 `select_components` 及其 BIC 测试；5 条模型线必须齐全；sample 由后端生成；K 条用 list/listitem 角色；`data_state` 取两个日期中较早的；补混合 forming 测试；fixture 平铺，并写明默认目录不能用来断言数值；`in_profit` 为 None 时显示 `—` |
