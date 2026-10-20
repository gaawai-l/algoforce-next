# 计划：state-report 图 8（Cost Basis Distribution, All Coins，SR-8）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## 给用户审阅的要点

- **图 8 是什么**：一张热力图。横轴是最近 1,461 天，每天一列；纵轴是 $1,000–$125,500 的成本价，每 $500 一格；格子越亮，那个价位上的 BTC 越多；再叠一条每天的收盘价线。它放在 Flows → Cost basis，图 3、图 4 的下面。
- **存储**：新建一张表 `urpd_history`，每天一行，只存全币 lin500 的已定稿快照，1,461 天在 SQLite 页上实测约 6 MB（一行 250 格约占一个 4 KB 页），另有约 3 MB 的派生结果。现有成本价视图读的表一行都不改。
- **第一天的体验**：部署后每小时补 120 天，从最近往前补。365D 约 2–3 小时补齐，All 约 12–13 小时补齐。补齐之前，缺的日子画斜线，并写明"已存 x / N 天"，不会显示成 0。最后一列是今天的快照，用虚线框标出"仍在形成"。
- **对公开 BRK 的请求**：一次性共约 1,456 个。每轮最多 120 个，一次只发 1 个，两次间隔 0.5 秒，每轮最长 5 分钟；补齐后每天 0 个额外请求。哪个取数阶段出错，那一轮就不回填；BRK 出错就停到下一小时。
- **你已定的**：低于对比度下限的格子画成一级暗色，不画成"没有币"的底色；PLAN-SR2 取消，图 2 已由 PLAN-AGE-COHORTS 完成。
- **还请你看**：
  1. 三栏说明的中英文初稿（Task 5 Step 4）；
  2. 回填速度每轮 120 个（待确认第 2 条）；
  3. "All"取最近 1,461 天，而不是全部历史（第 3 条）；
  4. 分位数放在浏览器里算，与 Sell side 和图 3/4 一致（第 7 条）。
- **部署注意**：这是 onchain 库的第一个新迁移。上线后如果要回滚镜像，必须同时恢复数据库备份（Task 6 写进 RELEASING.md）。

**Goal:** 在 Flows → Cost basis 子视图里、图 3 和图 4 之后，加上图 8：最近 1,461 天、每天一列、按 $500 成本价区间着色的全币供应热力图，叠加每天的链上收盘价。

**Architecture:** worker 把 `all lin500` 已定稿的日快照压成每天一行，存进新表 `urpd_history`。这张表与现有 `urpd` 表及其清理互不相干。只有本轮所有阶段都成功、并且取到了 D 时才回填；请求放在本轮状态写入之后发，每轮最多 120 个、最长 5 分钟，从新到旧，补齐后每天不需要额外请求。每轮刷新后预先派生 `costbasis_history`（1,461 天 × 网格），读接口只按 Span 切片。Contrast 分位、Range、缩放这类随交互变化的显示逻辑放在前端计算。热力格画在 canvas 上；坐标轴、spot 线、缺失标记和 forming 标记用 SVG 画。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、httpx；React、TanStack Query、zod、Vitest、Canvas 2D。

**Spec:** [SPEC.md](SPEC.md)（Task 6 新增图 8 一节）。需求和已定裁定见 `.superpowers/sdd/state-report/planning-brief.md`。

日期：2026-10-19；2026-10-20 按 main 1023827 重新定位。

**基线与分支**：本计划的全部锚点都按 main `1023827`（2026-10-20）核对过。执行时从当时的 main 新开一个分支，不用 `claude/state-report`。main 已包含：
- **图 2**（PLAN-AGE-COHORTS；PLAN-SR2 已取消）：`sync.py` 里独立的 age 阶段（`AGE_ONLY_SERIES`、`age_error`）；Flows → Sell side 在 1A/1B 后面渲染 `AgeCohortChart`。
- **图 3、图 4**（PLAN-SR3-4，方案 C）：
  - Flows → Cost basis（`flow=costbasis`）渲染 `CostFlowCharts`（`cost-flow-charts.tsx`），派生视图是 `costflow`。
  - `sync.py` 多了 `_day1_range`、`_derive_cost_flow` 和 `_flow_set`（URPD 的全有或全无重取）。
  - `day_start` 移到了 `onchain/models.py`。
  - KDE、峰和 GMM 在浏览器里算。本图的 Contrast 分位本来就在前端算（R7），不受影响。
- **图 5、图 6**（PLAN-SR5-6）：独立的 size 阶段（`SIZE_SERIES`、`size_error`）；Flows → Size cohorts；共用的 `flow-notes.tsx`（`ReadColumns`）；`heightFor` 移到了 `sell-side.ts`。
- 没有 `GZipMiddleware`；`onchain/migrations/` 只有 `001_onchain.sql`。

执行时如果 main 已经前进，先按本计划写的符号名重新定位；`flows-panel.tsx` 里没有 `costbasis` 分支就停下来报告。

**依据**：研究资料不入库，路径相对 `/Users/gary/code/AlgoForceNext/.local/research-samples/alpha-dashboards-2026-10-16/`。
- `verification-2026-10-19/verify/SR-8.md`，下称 **SR-8**：阶段 B 的原站读数。
- `verification-2026-10-19/verify/SR-8-A.md`，下称 **SR-8-A**：阶段 A 的源码分析和实现方案。
- `state-report/NOTES.md` §8，下称 **NOTES**。
- 原站脚本：`state-report/raw/script_2_app.js` 下称 **A**，`script_3_app.js` 下称 **L**。
- 仓库内 `docs/features/btc-onchain-perp/CHART-VERIFICATION.md` 的 SR-8 节（246–255 行），下称 **CV**。
- 研究里引用的代码行号（如 `sync.py:305,312,326`、`store.py:209`）基于 `1f3a4da`，现在已经漂移。本计划一律按符号名引用代码。

---

## 已定的做法

### 简报里已定、不再讨论的裁定（复述）

| # | 裁定 | 本计划的落点 |
|---|---|---|
| B1 位置 | Flows 有五个子视图，依次为：Seller pressure（`flow=seller`，默认）、Sell side（`flow=sellside`：1A、1B、图 2）、Cost basis（`flow=costbasis`：图 3、图 4、**图 8**）、Size cohorts（`flow=sizes`：图 5、图 6）、Perp states（`flow=perp`）。SR-8 只往 Cost basis 末尾追加。390px 下切换条换行，不横向溢出 | Task 5 |
| B2 规则 | 只做 v1，照原站算（SPEC D5），`rules` 恒为空，与 Sell side 相同。原站已知缺陷要写明原行为，选安全的显示（缺失显示为"—"或空隙，不显示为 0），并作为裁定写出 | R8–R13 |
| B3 说明 | 原站没有三栏说明，Flows 要求每张图下都有。起草中英文初稿交用户审 | R17、Task 5 |
| B4 数据契约 | 由 worker 从 BRK 取数并预先计算。读接口只读本地库，处理请求时不访问 BRK，也不做 KDE、GMM 或分位数计算。缺失或过期的数据显示为缺失，不显示为 0。forming 要标出。运行时没有假数据 | R1–R7、Task 2–3 |
| B5 测试 | 测试不连网。黄金样本来自已保存的 BRK 数据或阶段 A 的样本，附 README 写明来源和日期。阶段 A 记录了数值的地方，逐格断言。每个 Task 的最后一步都是在工作树根目录运行 `make check` 并全绿。改了后端模型后运行 `make contract` | 全部 Task |
| B6 语言 | 计划用中文。代码、标识符、注释、commit message 用英文。界面文案走 `i18n.ts`，中英一一对应 | 全部 |
| B7 界面 | 复用 Flows 的图表助手；图高随宽度在 300–440px 之间变化；最后由 controller 在浏览器检查 1440px 和 390px | Task 5、Task 7 |

### 本计划的裁定

| ID | 事项 | 做法 | 理由 |
|---|---|---|---|
| R1 | 存储 | 新表 `urpd_history(day PK, close, supplies_json, fetched_at)`，由迁移 `002_urpd_history.sql` 建立，只依赖 `001_onchain.sql`（2026-10-20 核对：main 1023827 和主检出工作树的 `onchain/migrations/` 都只有 `001_onchain.sql`，已合并的图 2–6 都没有加 onchain 迁移）。每天一行，只存 `all lin500`：从 $1,000 起每 $500 一格的 supply，保留到 0.01 BTC（`round(x, 2)`）。`close` 和 `supplies_json` 同为 NULL，表示向 BRK 请求时得到 404（下称 absent 行）。表里只存已定稿的快照（`fetched_at ≥ final_from(day)`） | `urpd` 表、`URPD_SET`、`_urpd` 的 `keep` 集合、`prune_urpd` 和 P3-R14 都不改，现有 cost-basis 和 levels 读到的内容不变。2 位小数是原站自己的精度假设（A:3955–3958 "snapshots are stored to 2dp"），也不影响 0.005 BTC 的占用判断。实测一行约 2.2 KB（2025-10-20 样本为 2,249 字节），一份完整快照约 27 KB（SR-8-A:105） |
| R2 | 窗口 | 以 D 为最后一列，向前共 1,461 天（`D−1460 … D`），与原站 `dates.slice(-1461)`（L:388）一致。D 是 `urpd` 表中最新的 `all lin500`，也就是 `_urpd` 取到的今天或昨天的快照。窗口外的行每轮删除 | 研究已核实最近 1,461 天逐日连续（SR-8-A:103），所以按日历日推算即可，不必另外请求 `/api/urpd/all/dates` |
| R3 | 各天的来源 | **D 和尚未定稿的日子**（UTC 00:00–02:00 之间的 D−1）：从 `urpd` 表直接读，不写进历史表。<br>**已定稿且仍在 `urpd` 表里的日子**（02:00 以后的 D−1，以及 D−7、D−30、D−90）：复制进历史表，不发请求。<br>**其余日子**：向 BRK 请求，只请求 `≤ min(D−1, closed_day(at))` 的日子。<br>"复制 4 天"只适用于 v1：test 环境没设 `WHEELHOUSE_RULES`，默认开 O1，`_urpd_closed` 多保留的已定稿日子也会被复制，首轮复制的天数更多（复核 M12） | 补齐以后每天不需要额外请求：`_urpd` 本来就会每小时重取 D−1，直到它定稿（见 `_urpd` 中处理 past 的循环），过了 02:00 宽限期直接复制即可（SR-8-A:115） |
| R4 | 回填门控与节奏 | **门控**：`backfill = urpd is not None and not errors`，即本轮所有阶段（`_refresh` 里 `errors` 收集的 hour1、age、size、URPD 四个阶段：`hour1_error`、`age_error`、`size_error`、`urpd_error`）都没有错误，并且 `_urpd` 取到了 D。<br>**时机**：复制（不发请求）和派生留在原位置；向 BRK 的请求挪到成功路径写完 `last_success_at`、`next_due` 之后。<br>**节奏**：每轮最多 120 个（`HISTORY_BUDGET`），顺序发送，从新到旧；两次之间等 0.5 秒（`HISTORY_PAUSE_SECONDS`，用 `stopping.wait`，服务停止时立即退出）；每轮最长 5 分钟（`HISTORY_DEADLINE_SECONDS = 300`，用 `time.monotonic()` 计时）。<br>**出错**：遇到第一个 `BrkError` 或坏快照（没有 ≥ $1,000 的桶，或日期与请求的不符，记 `brk_bad_snapshot`）就结束本轮回填，坏快照不作为数据入库，而是记成 absent 行（24 小时后再问），所以一份坏快照不会永远挡住更早的日子；错误码写进 `sync_state.history_error`（R21）。404 记为 absent 行，满 24 小时（`ABSENT_RETRY`）后再请求 | 复核 I1、I5：5 分钟一次的重试轮不会放大请求；回填不推迟本轮状态，进程在回填中途被杀也不会一重启就再跑一整轮；有总时长上限；坏数据不会让图 8 一直不可用 |
| R5 | 回填范围 | 从一开始就以 1,461 天为目标，从新到旧取。365D 在第 3 轮补齐，All 在第 13 轮补齐 | 见下文的建议 |
| R6 | BRK 升版 | `brk_version` 变化时不重取历史行 | URPD 没有 version 字段。SPEC §7 说明不做 as-known 回放，历史修订极少；`urpd` 表里已定稿的快照同样不会重取。确有需要时手动删除这些行，worker 会按 R4 补回 |
| R7 | 派生与分层 | 每轮刷新后派生 `derived` 中的 `costbasis_history`：网格，以及 1,461 天的 close、supply、status。读接口只按 Span 切片。Contrast 分位、Range、y 自动范围、缩放和色阶都在前端计算 | 这些量随交互实时变化，原站也在前端算（A:3933–4008）。B4 约束的是服务端读接口。与 PLAN-SELL-SIDE:12 的"计算分层"做法相同。阶段 A 要求用户确认这种理解（SR-8-A:140），见待确认第 7 条 |
| R8 | 网格 | 取 D 的 lin500 桶中 floor ≥ $1,000 的部分：从 $1,000 起每 $500 一格，到 D 的最高 floor 为止。2026-10 时共 250 格，覆盖 $1,000–$125,500。<br>旧快照没有的高位格补 0。这是真实的 0：那一天这个价位没有币。超出网格的格子丢弃 | 照原站 L:390–402。原站用 D 的 floor 列表建网格，我们按等距建；桶连续时两者相同，两份样本都连续（2025-10-20 为 252/252，2022-10-20 为 137/137） |
| R9 | 缺日 | 原站缺陷：取数失败时，`visDates` 只保留取到的日子，列就会被压缩（A:3933–3946；SR-8-A §1.6 第 4 条）。<br>我们每个日历日固定占一列。`pending`（还没取到）和 `absent`（BRK 返回 404）两种日子的 close 和 supply 都是 `null`：画成斜线，不参与分位和占用计算，spot 线在此断开。状态行写"已存 x / N 天"，回填进行中再加一句说明 | 缺失显示为缺失，不压缩，也不当成 0（B2、B4） |
| R10 | forming | 原站缺陷：最后一列是实时快照，但没有任何标记（SR-8 第 35–37 行）。<br>我们给每列一个 `status`：快照在那一天结束前取到的，记为 `forming`，与 `/cost-basis` 的判断相同（`api.py` 的 `cost_basis` 中 `fetched_at < day_start(day + 1 day)`）。forming 列画虚线框，状态行写明，tooltip 里也标出 | SPEC 成功标准 2 |
| R11 | 低于下限的格子（**已定：用户 2026-10-19 决定加这一级暗色**） | 原站缺陷：这些格子画成底色，看起来与"没有币"一样（NOTES:265–267）。<br>我们的计算照原站（u = 0），显示上多一级暗色"below floor"，与透明的空格区分，图例也加上这一格 | 有币的格子不会看起来像没有币。分位、上限和图例数值仍与原站一致 |
| R12 | "All" 的名称 | 原站缺陷：按钮叫 All，实际只是最近 1,461 天。<br>我们沿用 All（中文"全部"），在 `title` 和覆盖度文字里写明 1,461 天 | 保留原站控件，同时不误导 |
| R13 | 坐标轴 | 原站缺陷：390px 下刻度字只有约 5px（SR-8 第 24 行）。<br>我们按 CSS 像素绘制坐标轴，SVG 的 viewBox 等于实际宽高，与本地其他 Flows 图相同。<br>x 轴刻度照 d3 time ticks 的规则，标签格式随跨度切换：`%d %b`、`%b %y` 或 `%Y`（A:4092–4093）。<br>y 轴刻度照 d3 `ticks(7)`，格式为 `$Xk`（A:3926、4094） | |
| R13a | x 方向映射 | 列、spot 线、十字线、拖框和悬停都按列带定位：第 i 列占 `[i, i+1) × plotW / n`，中心在 `(i + 0.5) × plotW / n`；指针所在的列为 `floor(x / (plotW / n))` | 原站 canvas 按列带均分，而轴、spot 线和十字线按时间比例尺画，拖框和悬停用 `Math.round(px / iw · (n − 1))`（A:4210、4270），两者最多错开半列。统一按列带，修正这个错位（复核 M4） |
| R14 | 配色 | 单一青色相，4 级，越密越亮：`#164a52`、`#1f7f80`、`#33b3a3`、`#59e6cd`（即 `--wh-cyan`）。<br>below floor 为 `#233142`：与面板底色对比 1.36:1，与最暗一级 `#164a52` 对比 1.34:1，主要靠色相区分，T7 在 390px 下实看（复核 M6）。空格透明，露出面板底色 `--wh-surface #101722`。<br>spot 线为 `#f4f7fb` 1.4px，下面垫一条 `#05080d` 3.2px 的衬底，照原站的 price-case/price-line（A:4102） | 用本地已确认的暗色赛博朋克 token，替换原站的 pine 暖色系（SR-8-A §1.6 第 5 条） |
| R15 | 控件与默认值 | **Span**：30D / 90D / **365D** / All。<br>**Range**：**All** / ±50% / ±25% / ±10%，以可见窗口里最后一个有数据的日子的 close 为中心。<br>**Contrast**：双滑杆，0–100，步长 1，默认 **75 / 95**；两柄只夹住、不交换，最小间隔 1。<br>**缩放**：拖框缩放，阈值 6px，x 方向按整天吸附；双击或点"Reset zoom"还原。<br>换 Span 时清掉 x 方向的缩放，保留 y 方向的；点 Range 时清掉 y 方向的缩放 | 照原站 A:536–556、3914、3972–3980、4164–4180、4189–4330。"Reset zoom"按钮是为了让键盘也能还原而加的 |
| R16 | 悬停与键盘 | 十字线加 tooltip，内容为 `2026-10-15`、`Bucket $82.0k–$82.5k`、`Supply 219,106 BTC`、`spot $82k`（SR-8 第 22 行；A:4263–4288）。悬停缺失的日子时说明原因。<br>图可以获得焦点：←/→ 换日，↑/↓ 换价格区间，Home/End 跳到首尾，Esc 退出 | 与本地其他 Flows 图一样支持键盘 |
| R17 | 三栏说明和图注 | 原站没有三栏说明，按 Flows 约定写中英文初稿（文案见 Task 5），交用户审。原站图注（A:565）的英文照搬，中文由我们翻译 | B3 |
| R18 | 图高、刷新与取数失败 | 图高用 `heightFor(width)`（300–440px，与 Sell side 相同）。<br>查询每 15 分钟刷新一次：默认 365D 每次 0.87 MB，gzip 后 0.39 MB；All 3.12 MB，gzip 后 1.29 MB（复核实测）。<br>请求超时：All 30 秒，其余 Span 15 秒。`query()` 新增可选参数 `timeoutMs`，默认仍是 5 秒。<br>换 Span 时先保留旧图，显示 `loading N days…`；新 Span 取数失败时继续显示上一张图，控件行加 `could not load N days`（照原站 A:4310–4314）；只有第一次加载就失败、或当前显示的 Span 自己刷新失败时，才显示 unavailable | worker 每小时只写一次。前端 `query()` 的 5 秒超时包括读取响应体（client.ts:166、181），All 在移动网络下会超时（复核 I4） |
| R19 | 列数上限 | 不做原站超过 1,880 列时取平均的逻辑（A:4062） | 我们最多 1,461 列，原站这段逻辑同样不会触发 |
| R20 | 响应压缩 | `create_app` 里如果还没有 `GZipMiddleware`，就加 `app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)`；main 1023827 上没有，所以本计划加上，执行时若已有就不重复加 | 压缩比约 2.4 倍；本服务没有流式路由；加在 `create_app` 而不是 nginx，本地和 test 都生效（复核 I4，取代原待确认第 6 条"本期不加 GZip"） |
| R21 | 回填暂停的提示 | 最近一次回填因错误中止时，`sync_state.history_error` 记下错误码，派生载荷带 `backfill_error`；状态行把"其余仍在抓取"换成"历史回填暂停：BRK 返回 {code}，下一小时重试"。一次没有错误的回填把它清为 null；不回填的轮次不动它 | 否则 BRK 持续限流时，界面会一直说"仍在抓取"（复核 M16） |

---

## 回填节奏、续传与存储

**请求量**（SR-8-A §3.2）：
- 365 天窗口需要 `D−364 … D−1` 共 364 天，减去 `_urpd` 已经存下并已定稿的 D−1、D−7、D−30、D−90 这 4 天，共 **360 个请求**。
- 1,461 天窗口需要 1,460 − 4 = **1,456 个请求**。
- 补齐以后，每天 **0 个**额外请求。
- **URL 长度**：每个请求形如 `/api/urpd/all/YYYY-MM-DD?agg=lin500`，约 40 个字符，远低于 `brk.py` 约 2,000 字符的上限。本计划不新增任何 series，`HOUR1_SERIES` 和分片逻辑都不动。

**门控与时机**（R4）：
- 只在本轮所有阶段都没有错误、并且 `_urpd` 取到了 D 时，才向 BRK 发回填请求。任何阶段失败的轮次都会在 5 分钟后重试（`RETRY_AFTER`）；这些重试轮只复制、只派生，不发回填请求。
- 回填请求在成功路径写完 `last_success_at`、`next_due` 之后才发，所以不推迟本轮状态。进程在回填中途被杀，重启后按已经写好的 `next_due`，到下一个 HH:12 才再跑。

**节奏**：每轮最多 120 个请求，顺序发送，每两个之间等 0.5 秒，每轮最长 5 分钟。BRK 单个 URPD 请求实测耗时 0.63–0.70 秒（SR-8-A:105–106），所以一轮通常约 120 × 1.15 秒 ≈ 2.3 分钟：HH:12 开始的一轮大约在 HH:15 结束。BRK 变慢时，到 5 分钟就停，余下的留给下一轮。
  - 实测（2026-10-20，controller 的验证实例）：首轮复制 4 天、请求 120 个，用时 268,514 ms（约 4.5 分钟），单个请求约 2.2 秒（含停顿），比上面的估计慢一倍；仍在 5 分钟上限之内，但余量只有约 10%。
- **365D**：第 1 轮补上最近约 120 天，第 3 轮补齐，即部署后约 2–3 小时。
- **All**：第 13 轮补齐，约 12–13 小时。
- **上限按轮计，不按滑动小时计**：每个回填轮最多 120 个请求；失败轮不回填，成功轮每个 HH:12 槽位最多一个。约 60 分钟内最多有两个回填轮（HH:12 的一轮失败，不回填；HH:17 的重试轮成功，回填 120 个；下一个 HH:12 又回填 120 个，相隔 55 分钟），所以最多 240 个；规则变更后的重启可能再多一轮。同一时刻只有 1 个在途，两个之间至少 0.5 秒。这只发生在首次回填和 24 小时一次的 absent 重问期间，补齐之后为 0。
- **与原站对比**：原站每次打开页面，都会以并发 32 请求 365 份快照；点 All 再请求 1,096 份（NOTES:19–28）。BRK 作者实测并发 32 时可达 142 req/s（L:417–431 的注释）。我们整个回填一共 1,456 个请求，每轮最多 120 个，同一时刻最多只有 1 个在途。

**建议：直接回填 1,461 天，不分两期。**
- 从新到旧取，365D 自然会先补齐。
- 1,461 天只比 365 天多 1,096 个请求、多约 10 小时，存储约 6 MB（SQLite 页）。
- 分两期反而要多一个开关，还要再评审一次。

**续传**：
- 回填进度就记录在历史表里。每取到一天就立即单独提交。重启后，下一轮重新计算窗口里还缺哪些天，从最新的缺口接着往前取，已存的天不会重取（Task 2 有重启测试）。
- 服务停止时，`stopping.wait` 立即返回，只等正在进行的那一个请求。httpx 的 `timeout=20.0` 是 connect、read、write、pool 各 20 秒，不是总时长，所以通常不超过 20 秒。SQLite 每次写入都是原子的，即使超过 compose 的 `stop_grace_period` 被 SIGKILL 也安全（复核 M7）。

**失败处理**（R4、R21，复核 I5）：
- 回填（复制和请求）与派生各有自己的 `try`。回填出了意外异常，只记 `onchain_urpd_history_failed code=history_failed`，**不清**图 8；只有派生出错，才记 `onchain_derive_failed code=history_failed` 并清掉 `costbasis_history`。
- 遇到第一个 `BrkError` 或坏快照，就结束本轮回填，记 `onchain_urpd_history_failed code=<code>`，错误码写进 `sync_state.history_error`，界面提示回填暂停。坏快照记成 absent 行，24 小时后再问，不会卡住更早的日子。本轮的 `last_error`、`reasons`、`next_due` 都不受影响，下一轮再试。

**存储与传输**（复核实测）：

| 内容 | 365 天 | 1,461 天 |
|---|---|---|
| `urpd_history`（每行 1.2–2.3 KB，越早的日子越小；SQLite 一行约占一个 4 KB 页） | 约 1.5 MB（按每行一页推算） | 约 6 MB（Task 1 复核实测 6.08 MB / 1,461 行） |
| `derived.costbasis_history`（每轮重写，每行补到 250 格） | — | 约 3.1–3.4 MB |
| 接口响应（未压缩 / gzip） | 0.87 MB / 0.39 MB | 3.12 MB / 1.29 MB |

派生载荷总是存满 1,461 天（缺的日子为 null），所以第二行与回填进度无关。服务端读出、解析、切片加序列化共约 25 ms，时间几乎都花在传输上，所以要加 GZip（R20），并放宽前端超时（R18）。作为对比，P3-R14 估算过：9 种快照全部保留，一年约 80 MB。

**回滚**（复核 I3）：迁移 002 应用之后，SR-8 之前的镜像打开 `onchain.sqlite` 会抛 "On-chain database is newer than this application"（store.py:44–45）。onchain router 在 lifespan 里建库，所以整个 analytics 服务都起不来。回滚只能二选一：恢复发布第 3 步取得的 `onchain.sqlite` 备份；或者保持前进，修复后再发布。Task 6 把这一条写进 `docs/deployment/RELEASING.md`。

## 历史不全时怎么显示

以下是 R9、R10 在界面上的具体表现：
- **每个日历日占一列**。缺的日子画斜线（复用 `wh-perp-hatch`），不压缩、不画成底色，也不当成 0。
- **状态行**：例如 `Snapshot 2026-10-19 UTC · 125 of 365 days stored · the rest is still being fetched; missing days are hatched, not zero`。BRK 没有快照的日子另起一句 `N days have no snapshot at BRK`。回填因错误暂停时，"其余仍在抓取"换成 `history fetch paused: BRK returned brk_unavailable; retrying next hour`（R21）。
- **计算范围**：Contrast 分位和 y 自动范围只用有数据的日子。Range 的中心取可见窗口里最后一个有数据的日子的 close。
- **整个可见窗口都没有数据**（只可能出现在缩放后）：显示"No data for this chart"，不画图，界面上不出现任何 0。
- **换到新 Span 取数失败**：保留上一张图，控件行加 `could not load N days`；只有第一次加载就失败，才显示 unavailable（R18）。
- **悬停在缺失的日子**：显示 `2026-07-03 · No snapshot stored for this day yet`（pending），或 `BRK has no snapshot for this day`（absent）。
- **接口没有载荷**（D 还没取到）：`data_state` 为 `unavailable`，各列为空数组。
- **D 已过期**：`data_state` 为 `stale`，界面上提示最新的快照日。

## 待你确认的点（附建议）

1. **低于下限的格子（已定）**：原站画成底色，与"没有币"看起来一样。用户 2026-10-19 决定按 R11 多一级暗色 `#233142`。它与底色、与最暗一级的对比只有 1.36:1 和 1.34:1，主要靠色相区分，所以 T7 仍要在 390px 下实看，分不清就换一个色相更远的颜色。
2. **回填速度**：建议每轮 120 个，365D 在部署后约 2–3 小时补齐，All 约 12–13 小时补齐。改成每轮 400 个，365D 第一轮就能补齐、All 4 轮补齐，但每轮要约 8 分钟，超过了 5 分钟的上限（R4）。要选 400，就得同时放宽这个上限。
3. **"All" 的含义**：建议照原站，取最近 1,461 天（R2、R12）。如果要真正的全部历史（从 2009 年起约 6,494 天），要多约 5,000 个请求、多约 15 MB，不建议。
4. **阶段 B 的 365D 分位读数无法离线复现**：P75 83,745.15、P95 192,900.73 等读数（SR-8 第 18–20 行）包含 06:12Z 的 forming 列，而那份快照没有保存。验证分三层：
   - 离线测试用阶段 A 的 4 个日期逐格对齐（Task 1）；
   - Python 参考实现作为测试辅助入库（`tests/onchain/cbh_reference.py`），并由它生成前端黄金样本（Task 3）；
   - 与原站的分位对照放到 Task 7：由 controller 在同一时刻、两边都排除 forming 列后比较。两边的输入和参考实现的输出都作为 fixture 入库，附来源 README，再由一条测试复算，以便日后复查。
5. **记一笔，留给以后的 Supplementary 计划（本计划不决定）**：简报说 Supplementary 的 Chart 1–6 与 state-report 是同一套模板，但 pulse Chart 5 是 Plotly 改写版（`onchain-pulse/NOTES.md:25、121–132`）：数据用 log200，价格轴是对数轴，默认 90D，Contrast 默认 50–95、步长 5，All 为 2017 年起每 3 天一列。`urpd_history` 只存 lin500，供不了 pulse 版。是复用本图还是另做 pulse 版，由 Supplementary 计划作为待确认点提出。本计划不预留接口。
6. **（已撤回）"本期不加 GZip"**：按复核 I4 推翻。改为 R20 加 `GZipMiddleware`，并按 R18 放宽超时、取数失败时保留旧图。
7. **分位数放在前端算**：阶段 A 要求确认"SPEC §2 的'读接口不现算分位数'只约束服务端"这种理解（SR-8-A:140）。建议按 R7 接受，先例是 PLAN-SELL-SIDE:12 的"计算分层"。如果改在服务端算，就得为每种 Span × Range × Contrast × 缩放的组合预先计算，做不到。

研究资料里没有阻塞本计划的问题。

---

## Global Constraints

- 代码、标识符、注释、commit message 用英文，遵循 conventional commits。界面文案只放在 `i18n.ts` 里，en 和 zh 的键一一对应。
- 只实现 v1。`IMPLEMENTED["costbasis_history"]` 为空集，所以载荷的 `rules` 恒为 `[]`。
- 读接口只读 `onchain.sqlite`：处理请求时不访问 BRK，不做分位或其他计算，只做切片。
- 缺失永远是 `null` 或斜线，不能是 0。forming 列必须标出。运行时不使用任何样本或假数据。
- 以下内容都不改：`urpd` 表、`URPD_SET`、`_urpd` 的 `keep` 集合、`prune_urpd`，以及 `/cost-basis`、`/levels`、`/status` 的载荷。
- 访问 BRK 的规则：
  - 门控为 `urpd is not None and not errors`，请求只在成功路径写完本轮状态之后发；
  - 顺序请求，每轮最多 `HISTORY_BUDGET = 120` 个，两次之间间隔 `HISTORY_PAUSE_SECONDS = 0.5`，每轮最长 `HISTORY_DEADLINE_SECONDS = 300`；
  - 遇到第一个错误或坏快照就停；404 满 `ABSENT_RETRY = 1 day` 后才重问。
- 回填与派生各有自己的 `try`：回填失败永远不清图 8。
- `create_app` 里若还没有 `GZipMiddleware` 就加上，已有就不重复加。main 1023827 上没有，所以本计划会加。现有测试和 deploy 里都没有断言响应不带 `Content-Encoding` 的（2026-10-20 检索过）。
- 日志只记录路由、错误码、计数和耗时，不记录任何数值，也不记录异常内容。
- 测试不连网。新加的 fixture 目录要有 README，写明来源、时间和 BRK `/version`（研究里没记下的写明"not recorded"）。
- 每个 Task 的最后一步：在工作树根目录运行 `make check`，全绿。改了 `onchain/models.py` 或路由之后，先运行 `make contract`。
- 改动前面几份计划也改过的文件时，按符号名定位，以追加为主。
- 迁移文件为 `002_urpd_history.sql`，只依赖 `001_onchain.sql`。2026-10-20 核对过：main 1023827 的 `onchain/migrations/` 只有 `001_onchain.sql`。执行时如果 `onchain/migrations/` 里已经有 002，就改用下一个空号，并同步修改版本断言和 RELEASING 里的说明。
- **前两份计划（图 3/4、图 5/6）执行中的教训，作为硬约束：**
  - 凡是要与原站逐字对照的格式（图例、Contrast 标签、tooltip、缩放备注、覆盖度计数、轴标签），都放在 `cost-basis-history.ts` 的导出纯函数里，界面直接渲染它们的结果，测试也测这些函数；不允许只在测试辅助里实现一遍。
  - 读接口什么都不算。它的"不计算"测试照 `test_cost_flow_reads_no_network` 和 `test_size_cohorts_after_sync_never_touch_network` 的写法：每个要替换的名字先 `assert hasattr`，再替换成 `boom`，并把 `OnchainStore.read_series`（本图再加 `urpd_history`、`urpd`、`latest_urpd`）也替换成 `boom`。
  - `useChartWidth` 只放在有数据时才挂载的子组件里。它的 ResizeObserver 只在挂载时接上一次，放在先渲染"加载中"的父组件里，宽度会一直停在 720。输入（Span、Range、Contrast、缩放）或数据变化时，清掉悬停读数。
  - 新的 worker 步骤要隔离，失败不得让其他视图变差：门控、独立的 `try`、只记日志。最坏情况下的请求数写进 SPEC（Task 6）。
  - 做变异测试时，存活的变异只有在可达输入上核对过、确认不改变任何输出之后，才能标为 equivalent。
- 迁移 SQL 的注释里不能有分号，因为 `OnchainStore.__init__` 按 `;` 切分语句。
- 不 push。commit 结尾按执行会话的署名规则添加。

## Review Focus

1. **回填进行到一半时服务重启、被停止或被杀**：已存的天不能重取，要从最新的缺口接着取；停止时不能再发下一个请求；被杀后不能一重启就再跑一整轮，因为本轮状态已经先写好。见 Task 2 的 `test_history_resumes_after_a_restart`、`test_history_stops_promptly_when_the_worker_stops` 和 `test_history_requests_come_after_the_round_state_is_written`。
2. **UTC 00:00–02:00 之间 D−1 还没定稿**：它不能写进历史表，也不能由回填去请求；图上照常从 `urpd` 表显示这一列，状态为 closed；过了 02:00 再复制进历史表。见 Task 2 的 `test_history_leaves_days_that_are_not_final_to_urpd`。
3. **某个阶段持续失败、URPD 阶段失败、本轮没取到 D、BRK 限流或返回 404**：
   - 前三种情况都不回填，包括 5 分钟一次的重试轮；
   - 限流或 404 时，本轮在第一个错误处停止，404 记为 absent、24 小时后才重问，界面提示回填暂停。
   - 见 Task 2 的 `test_history_is_not_fetched_on_a_retry_round`（参数化 hour1、age、size 三个阶段）、`test_history_is_not_fetched_when_the_urpd_stage_failed`（非空库）、`test_history_is_not_fetched_without_d`、`test_history_stops_at_the_first_brk_failure` 和 404 测试。
4. **BRK 返回坏快照或回填代码出错；网格变长；历史不全**：
   - 坏快照不入库、不清图 8；
   - D 的网格比旧行长时，旧行补 0，前端 y 方向的缩放按价格保存，依然有效；
   - 缺的天画斜线，可见窗口一天数据都没有时显示"No data"。
   - 见 Task 2 的 `test_history_stops_at_a_bad_snapshot_without_clearing_chart_8`、`test_history_copy_failure_keeps_chart_8`，Task 1 的补齐测试，Task 4 的 `occupiedRows` zy 测试，以及 Task 5 的测试。
5. **在手机上点 All**：响应要 gzip 压缩，超时 30 秒，失败时保留上一张图。见 Task 3 的 `test_cost_basis_history_is_gzipped`、`client.test.ts` 的超时断言，以及 Task 5 的 `keeps the last chart when a new span fails to load`。

---

## 文件结构

**后端**（`services/analytics/src/wheelhouse_service/`）

| 文件 | 改动 | 职责 |
|---|---|---|
| `onchain/migrations/002_urpd_history.sql` | 新建 | 建 `urpd_history` 表 |
| `onchain/costbasis_history.py` | 新建 | 常量；`HistoryDay`、`CostBasisHistory`；纯函数 `history_row` 和 `cost_basis_history` |
| `onchain/store.py` | 追加 | 历史表的读、写、清理，以及 `urpd_days`；`STATE_KEYS` 加 `history_error` |
| `onchain/sync.py` | 追加 | 构造参数 `history_budget` 和 `history_pause`；`_urpd_history`、`_derive_history`；在 `_refresh` 里调用 |
| `onchain/models.py` | 追加 | `HistorySpan`、`CostBasisHistoryView` |
| `onchain/api.py` | 追加 | `GET /cost-basis-history`；worker 传入 `history_budget=HISTORY_BUDGET` |
| `rules.py` | 追加 | `View` 增加 `"costbasis_history"` |
| `http.py` | 追加（若没有） | `GZipMiddleware`（R20） |

**测试**（`services/analytics/tests/onchain/`）：新建 `fixtures/brk-urpd-history/`、`test_onchain_costbasis_history.py` 和 `cbh_reference.py`（参考实现，T7 也要用）；Task 7 再新建 `fixtures/sr8-acceptance-<日期>/`；在 `onchain_fixture.py`、`test_onchain_store.py`、`test_onchain_sync.py`、`test_onchain_api.py` 里追加。

**前端**（`integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/`）

| 文件 | 改动 | 职责 |
|---|---|---|
| `cost-basis-history.ts` | 新建 | 纯函数：可见窗口、占用行、分位、色阶、绘制、刻度、格式化、缩放 |
| `cost-basis-history-chart.tsx` | 新建 | `CostBasisHistoryChart`：查询、状态、控件、canvas 加 SVG、图例、tooltip、说明 |
| `cost-basis-history-sample.json`、`cost-basis-history-expected.json` | 新建 | 前端黄金样本（由 Task 3 生成） |
| `onchain-contract.ts`、`client.ts` | 追加 | zod 校验；`query()` 的可选参数 `timeoutMs`；`getCostBasisHistory` |
| `flows-panel.tsx` | 追加 | `costbasis` 分支照 `sellside` 分支的写法改成 `<><CostFlowCharts /><CostBasisHistoryChart /></>` |
| `flow-notes.tsx`、`sell-side.ts`、`sell-side-charts.tsx` | 不改 | 复用 `ReadColumns`、`heightFor`、`ticks`、`Segments`，main 上都已导出 |
| `i18n.ts`、`market.css` | 追加 | 文案；`wh-cbh-*` 样式 |
| `api-schema.d.ts`，以及 `integrations/wealthfolio/openapi.json` | 生成 | `make contract` |

**文档**：修改 `SPEC.md`、`CHART-INVENTORY.md`、`docs/deployment/RELEASING.md`；新建 `SR8-VERIFICATION.md`。

---

### Task 1：历史表、压缩行与派生纯函数

**Files:**
- Create: `services/analytics/src/wheelhouse_service/onchain/migrations/002_urpd_history.sql`
- Create: `services/analytics/src/wheelhouse_service/onchain/costbasis_history.py`
- Modify: `services/analytics/src/wheelhouse_service/onchain/store.py`（新方法加在 `prune_urpd` 之后）
- Create: `services/analytics/tests/onchain/fixtures/brk-urpd-history/`（6 个快照文件加 `README.md`）
- Modify: `services/analytics/tests/onchain/onchain_fixture.py`
- Create: `services/analytics/tests/onchain/test_onchain_costbasis_history.py`
- Modify: `services/analytics/tests/onchain/test_onchain_store.py`

**Interfaces:**
- Consumes：`brk.Urpd`、`market.Model`、`models.final_from`。
- Produces，在 `onchain/costbasis_history.py` 中：
  - 常量：`HISTORY_DAYS = 1461`、`HISTORY_BUDGET = 120`、`HISTORY_PAUSE_SECONDS = 0.5`、`ABSENT_RETRY = timedelta(days=1)`、`FLOOR_MIN = 1000`、`FLOOR_STEP = 500`、`HISTORY_DEADLINE_SECONDS = 300`
  - `DayStatus = Literal["closed", "forming", "pending", "absent"]`
  - `class HistoryDay(Model)`：字段 `day: date`、`close: float | None`、`supply: list[float] | None`、`fetched_at: AwareDatetime`；`close` 与 `supply` 必须同为 None 或同不为 None，否则 `ValueError`。
  - `class CostBasisHistory(Model)`：字段 `latest_day: date`、`floors: list[int]`、`days: list[date]`、`close: list[float | None]`、`supply: list[list[float] | None]`、`status: list[DayStatus]`、`rules: list[Rule] = []`、`backfill_error: str | None = None`（R21，由 Task 2 填入）。
  - `def history_row(urpd: Urpd) -> list[float]`：没有 ≥ $1,000 且落在 $500 网格上的桶时返回 `[]`，调用方把它当作坏快照
  - `def cost_basis_history(rows: Mapping[date, HistoryDay], latest: date) -> CostBasisHistory | None`：`latest` 缺失、是 absent 行或 supply 为空列表时返回 None
- Produces，在 `OnchainStore` 中：
  - `save_urpd_history(urpd: Urpd, fetched_at: datetime) -> None`：`history_row(urpd)` 为空时抛 `ValueError`，不写空行
  - `save_urpd_history_absent(day: date, fetched_at: datetime) -> None`
  - `urpd_history(first: date, last: date) -> dict[date, HistoryDay]`
  - `prune_urpd_history(oldest: date) -> None`
  - `urpd_days(cohort: str, agg: str) -> list[date]`（升序）
- Produces，在 `onchain_fixture.py` 中：
  - `HISTORY = Path(...)/"fixtures"/"brk-urpd-history"`
  - `history_urpd(day: date) -> Urpd`
  - `HISTORY_SAMPLE_AT = datetime(2026, 10, 16, 18, 29, 37, tzinfo=UTC)`
  - `seed_history_sample(store: OnchainStore) -> None`

- [ ] **Step 1：建 fixture 目录 `tests/onchain/fixtures/brk-urpd-history/`**
  - 逐字节复制阶段 A 的样本（抓取于 2026-10-19 05:00–05:30 UTC，SR-8-A:3）：
    - `verification-2026-10-19/sr8/u_2022-10-20.json` → `urpd_all_lin500_2022-10-20.json`
    - `verification-2026-10-19/sr8/u_2025-10-20.json` → `urpd_all_lin500_2025-10-20.json`
  - 向 BRK 发 4 个请求，顺序发送：`GET https://bitview.space/api/urpd/all/{2026-07-21,2026-09-19,2026-10-12,2026-10-18}?agg=lin500`。响应原样保存为 `urpd_all_lin500_<date>.json`。这 4 天就是阶段 A 表格里的已定稿日期，现在已经从本机库里清掉了。
  - `README.md` 照 `brk-2026-10-16/README.md` 的格式写：每个文件对应的请求、抓取时间、BRK `/version`、桶数、来源（复制还是抓取），以及"do not edit"。两份阶段 A 样本的 `/version` 研究里没有记下，写 "version not recorded (SR-8-A:3)"，不要补猜的值；新抓的 4 份照常记录（复核 M13）。
  - 如果下面 Step 2 的阶段 A 逐格断言在这 4 个文件上不成立，就停下来报告，**不要改期望值**：这说明 BRK 修订了历史数据。

- [ ] **Step 2：写失败的测试 `test_onchain_costbasis_history.py`**

```python
# SR-8-A §2.1 (lines 92-95), read from the local store on 2026-10-19 and matched against the original
# page's CBD.byDate to within Float32 error (SR-8 line 23): close, the sum over the >= $1k grid,
# the largest bucket ($84k), then the $60k, $74k, $82k and $100k buckets.
STAGE_A = {
    date(2026, 7, 21): (66154.98, 16_390_537.77, 603_593.58, 181_182.11, 74_717.10, 58_801.84, 15_262.95),
    date(2026, 9, 19): (81270.08, 16_431_116.67, 572_136.78, 152_736.77, 61_968.93, 53_571.71, 14_087.17),
    date(2026, 10, 12): (81963.83, 16_444_750.01, 751_749.92, 138_931.51, 55_700.95, 171_554.40, 13_853.53),
    date(2026, 10, 18): (81844.61, 16_448_789.77, 731_367.21, 138_054.69, 55_315.76, 218_667.66, 13_526.98),
}
def at(floor: int) -> int: return (floor - 1000) // 500

@pytest.mark.parametrize("day", sorted(STAGE_A))
def test_history_row_matches_stage_a_cell_by_cell(day: date):
    snapshot = history_urpd(day)
    row = history_row(snapshot)
    close, total, top, p60, p74, p82, p100 = STAGE_A[day]
    assert snapshot.close == close
    assert len(row) == 250 and sum(v > 0.005 for v in row) == 250
    assert max(range(250), key=row.__getitem__) == at(84_000) and row[at(84_000)] == top
    assert [row[at(f)] for f in (60_000, 74_000, 82_000, 100_000)] == [p60, p74, p82, p100]
    # Stage A summed unrounded cells; 250 cells rounded to 0.01 move a sum by at most 1.25.
    assert sum(row) == pytest.approx(total, abs=1.26)

def test_history_row_of_an_old_and_a_recent_snapshot():
    old = history_row(history_urpd(date(2022, 10, 20)))
    assert len(old) == 135                      # $1,000-$68,000 (137 buckets from $0)
    assert [old[0], old[at(20_000)], old[at(60_000)]] == [120_929.22, 397_011.71, 100_863.01]
    assert sum(old) == pytest.approx(14_985_650.82, abs=0.005)
    recent = history_row(history_urpd(date(2025, 10, 20)))
    assert len(recent) == 250
    assert [recent[at(f)] for f in (60_000, 74_000, 82_000, 100_000)] == [
        140_446.02, 4_494.45, 70_630.70, 44_050.67]
    assert sum(recent) == pytest.approx(16_214_671.32, abs=0.005)

def test_history_row_skips_low_and_off_grid_buckets_and_zero_fills_gaps():
    # floors 0, 500 dropped (< $1,000); 1700 is off the $500 grid; 1500 absent inside the range
    assert history_row(urpd_with({0: 9.0, 500: 9.0, 1000: 1.234, 1700: 5.0, 2000: 2.0})) == [1.23, 0.0, 2.0]

FETCHED = datetime(2026, 10, 16, 18, 29, 37, tzinfo=UTC)
D = date(2026, 10, 16)

def test_window_is_1461_calendar_days_with_their_statuses():
    rows = {D: kept(D, [1.0, 2.0, 3.0]), D - DAY: kept(D - DAY, [1.0, 2.0, 3.0]),
            D - 3 * DAY: absent(D - 3 * DAY)}
    result = cost_basis_history(rows, D)
    assert result is not None and result.latest_day == D and result.rules == []
    assert result.floors == [1000, 1500, 2000]
    assert len(result.days) == 1461 and result.days[0] == date(2022, 10, 17) and result.days[-1] == D
    assert result.status[-4:] == ["absent", "pending", "closed", "forming"]
    assert result.status.count("pending") == 1458
    assert result.supply[-3] is None and result.close[-3] is None and result.supply[-4] is None

def test_older_rows_are_padded_with_zero_and_cut_to_the_grid():
    rows = {D: kept(D, [1.0, 2.0, 3.0]), D - DAY: kept(D - DAY, [4.0, 5.0]),
            D - 2 * DAY: kept(D - 2 * DAY, [6.0, 7.0, 8.0, 9.0])}
    result = cost_basis_history(rows, D)
    assert result is not None
    assert result.supply[-2] == [4.0, 5.0, 0.0] and result.supply[-3] == [6.0, 7.0, 8.0]

def test_no_history_without_the_newest_snapshot():
    assert cost_basis_history({}, D) is None
    assert cost_basis_history({D: absent(D)}, D) is None

def test_history_day_needs_close_and_supply_together():
    with pytest.raises(ValidationError):
        HistoryDay(day=D, close=None, supply=[1.0], fetched_at=FETCHED)

def test_history_row_is_empty_without_a_bucket_from_1000():
    assert history_row(urpd_with({0: 9.0, 500: 9.0})) == []
    assert cost_basis_history({D: kept(D, [])}, D) is None
```

  测试辅助函数：
  - `urpd_with(floors)` 构造一个 `Urpd`（cohort `all`、aggregation `lin500`、close 1.0）；
  - `kept(day, supply)` 返回 `HistoryDay(day=day, close=1.0, supply=supply, fetched_at=FETCHED)`；
  - `absent(day)` 返回 `HistoryDay(day=day, close=None, supply=None, fetched_at=FETCHED)`（复核 M14：pydantic 模型只收关键字参数）；
  - `DAY = timedelta(days=1)`。

  注意 `FETCHED` 早于 D 当天结束，所以 D 列是 forming，D−1 列是 closed。

  在 `test_onchain_store.py` 中：
  - 把 `test_migration_is_idempotent_and_private` 的断言改为 `[(1,), (2,)]`，并要求 `urpd_history` 在表集合里。
  - 新增以下测试：

```python
def test_urpd_history_round_trip(tmp_path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    snapshot = history_urpd(date(2025, 10, 20))
    store.save_urpd_history(snapshot, FETCHED)
    store.save_urpd_history_absent(date(2025, 10, 21), FETCHED)
    got = store.urpd_history(date(2025, 10, 20), date(2025, 10, 21))
    assert got[date(2025, 10, 20)] == HistoryDay(day=date(2025, 10, 20), close=110893.6,
                                                supply=history_row(snapshot), fetched_at=FETCHED)
    assert got[date(2025, 10, 21)] == HistoryDay(day=date(2025, 10, 21), close=None, supply=None,
                                                fetched_at=FETCHED)
    with store.connection() as db:   # compact JSON: the storage estimate in the plan rests on it
        text = db.execute("SELECT supplies_json FROM urpd_history WHERE day='2025-10-20'").fetchone()[0]
    assert len(text) == 2249

def test_prune_urpd_history_keeps_from_the_oldest_day(tmp_path): ...
    # rows on 10-14, 10-15, 10-16; prune_urpd_history(date(2026, 10, 15)) -> keys {10-15, 10-16}

def test_prune_urpd_leaves_the_history_alone(tmp_path): ...
    # save_urpd(load_urpd("all")) and save_urpd_history(same) -> prune_urpd(set()) ->
    # the urpd table is empty and urpd_history(D, D) still has D

def test_urpd_days_lists_one_kind(tmp_path): ...
    # all lin500 on 10-16 and 10-15 (model_copy(update={"date": ...})), sth lin500 on 10-14
    # -> urpd_days("all", "lin500") == [date(2026, 10, 15), date(2026, 10, 16)]

def test_save_urpd_history_refuses_an_empty_row(tmp_path):
    ...  # a snapshot whose buckets are all under $1,000 -> ValueError, and no row is written

def test_migration_upgrades_a_store_that_has_only_001(tmp_path):
    path = tmp_path / "onchain.sqlite3"
    store = OnchainStore(path)
    with store.connection() as db:   # make it look like a store from before SR-8
        db.execute("DROP TABLE urpd_history")
        db.execute("DELETE FROM onchain_schema WHERE version=2")
    store.save_urpd(load_urpd("all"), FETCHED)
    store.save_derived("costbasis", '{"a":1}', FETCHED)
    reopened = OnchainStore(path)
    with reopened.connection() as db:
        versions = [tuple(r) for r in db.execute("SELECT version FROM onchain_schema ORDER BY version")]
    assert versions == [(1,), (2,)]
    assert reopened.urpd_history(date(2026, 10, 16), date(2026, 10, 16)) == {}
    assert reopened.latest_urpd("all", "lin500").date == date(2026, 10, 16)
    assert reopened.derived("costbasis") == ('{"a":1}', FETCHED)
```

- [ ] **Step 3：运行测试，确认失败**

  Run: `cd services/analytics && ../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_costbasis_history.py tests/onchain/test_onchain_store.py -q`
  Expected: 导入 `costbasis_history` 时出现 ModuleNotFoundError，迁移版本断言失败。

- [ ] **Step 4：实现**
  - 迁移文件内容如下：

```sql
-- The all-coins lin500 URPD history behind the cost-basis heatmap, one row per day.
-- supplies_json is the supply of every $500 bucket from $1,000 up, in BTC to 0.01, as a JSON array.
-- close and supplies_json are both NULL when BRK had no snapshot for the day when asked at fetched_at.
-- Only final snapshots are kept here, the forming ones stay in urpd.
CREATE TABLE IF NOT EXISTS urpd_history(
    day TEXT PRIMARY KEY,
    close REAL,
    supplies_json TEXT,
    fetched_at TEXT NOT NULL
)
```

  - `history_row`：对每个桶取 `f = round(price_floor)`，只要 `f ≥ 1000` 且 `(f − 1000) % 500 == 0` 的桶，按 `(f − 1000) // 500` 放到对应位置。数组长度到最高的那个 floor 为止，中间缺的位置填 `0.0`，每个值做 `round(supply, 2)`。这与原站 `c8row` 的映射相同（L:395–402）。没有这样的桶时返回 `[]`，不对空序列取 max（复核 I5）。
  - `cost_basis_history`：
    - `rows` 里没有 `latest`，或 `latest` 是 absent 行，或它的 supply 为空列表时，返回 None。
    - 网格为 `floors = [1000 + 500 * i for i in range(len(rows[latest].supply))]`。
    - `days` 为 `latest − 1460 … latest`。
    - 每天的处理：
      - 有数据的行：`supply` 截到网格长度，不足的用 `0.0` 补齐；`status` 在 `fetched_at < datetime.combine(day + 1 day, time(), UTC)` 时为 `"forming"`，否则为 `"closed"`。这里自己写 `datetime.combine`，不从 `models` 导入 `day_start`：`models` 会导入本模块的 `DayStatus`，那样会循环导入。
      - absent 行：`"absent"`。
      - 没有行：`"pending"`。
    - 缺失日子的 close 和 supply 都填 `None`。
  - store：
    - `save_urpd_history` 写入 `json.dumps(history_row(urpd), separators=(",", ":"), allow_nan=False)`，ON CONFLICT 时整行覆盖；行为空时抛 `ValueError`。
    - `save_urpd_history_absent` 写入 NULL、NULL 和 fetched_at。
    - `urpd_history` 按 `day BETWEEN ? AND ?` 读取，返回 `HistoryDay`。
    - `prune_urpd_history` 执行 `DELETE ... WHERE day < ?`。
    - `urpd_days` 执行 `SELECT day FROM urpd WHERE cohort=? AND agg=? ORDER BY day`。
    - 写操作沿用 `BEGIN IMMEDIATE`。
  - `onchain_fixture.py`：
    - `history_urpd(day)` 读取 `HISTORY / f"urpd_all_lin500_{day}.json"`。
    - `seed_history_sample(store)` 的作用：把黄金样本（`brk-2026-10-16T1829Z`）的 `all lin500` 按 `HISTORY_SAMPLE_AT` 写入。具体是：D = 2026-10-16（`golden_urpd("all", "lin500", GOLDEN_D)`）用 `save_urpd` 写进 `urpd` 表；10-15、10-14、10-09、10-08 写进历史表；10-10 写为 absent 行。

- [ ] **Step 5：运行测试，确认通过**

  运行与 Step 3 相同的命令。Expected: 全部通过。

- [ ] **Step 6：运行 `make check`**

  在工作树根目录运行 `make check`。Expected: ruff、mypy、pytest、type-check、vitest 全部通过。

- [ ] **Step 7：Commit**

```bash
git add services/analytics/src/wheelhouse_service/onchain/migrations/002_urpd_history.sql \
  services/analytics/src/wheelhouse_service/onchain/costbasis_history.py \
  services/analytics/src/wheelhouse_service/onchain/store.py services/analytics/tests/onchain
git commit -m "feat(onchain): store the all-coins URPD history in its own table"
```

---

### Task 2：worker 回填与派生

**Files:**
- Modify: `services/analytics/src/wheelhouse_service/onchain/sync.py`（`OnchainSync.__init__`、`_refresh`；新增 `_urpd_history`、`_derive_history`）
- Modify: `services/analytics/src/wheelhouse_service/onchain/store.py`（`STATE_KEYS` 末尾追加 `"history_error"`）
- Modify: `services/analytics/src/wheelhouse_service/onchain/api.py`（`create_router` 里构造 worker 的那一行）
- Modify: `services/analytics/src/wheelhouse_service/rules.py`（`View`）
- Modify: `services/analytics/tests/onchain/test_onchain_sync.py`（`sync_for` 增加 `**options` 并原样传给 `OnchainSync`；新增测试）
- Modify: `services/analytics/tests/onchain/test_onchain_api.py`（新增 1 个测试）
- Modify: `services/analytics/tests/onchain/test_onchain_store.py`（`test_state_roundtrip_and_latest_urpd` 的期望字典加 `"history_error": None`）

**Interfaces:**
- Consumes：Task 1 的全部 Produces。
- Produces：
  - `OnchainSync(store, client, *, rules, history_budget: int = 0, history_pause: float = HISTORY_PAUSE_SECONDS)`。默认 0 表示不向 BRK 请求，但复制、清理和派生照常进行，所以现有测试的请求序列不变。生产环境只由 `create_router` 构造 worker，并传入 `history_budget=HISTORY_BUDGET`。
  - `OnchainSync._urpd_history(at: datetime, *, fetch: bool) -> None`：先清理窗口外的行，再复制 `urpd` 表里已定稿的快照。`fetch=True` 时再按 R4 发请求。`BrkError` 和坏快照在内部处理；其他异常向上抛，由 `_refresh` 隔离。
  - `OnchainSync._derive_history(at: datetime) -> None`：自己隔离异常。出错时记 `onchain_derive_failed code=history_failed` 并清掉派生。
  - `sync_state.history_error`：最近一次中止回填的错误码。一次没有错误的回填把它清为 None；不回填的轮次不动它。
  - `derived` 中 kind 为 `"costbasis_history"` 的载荷：`CostBasisHistory` 的 JSON，`backfill_error` 取自 `history_error`。

- [ ] **Step 1：写失败的测试，加在 `test_onchain_sync.py`**

  共用约定：
  - transport 一律以 `brk_transport(urpd_dir=GOLDEN)` 为底。它对任何日期都返回快照：有日期的文件优先，没有就用 10-16 的文件改写日期。
  - `history_requests(calls, d)` 返回满足以下条件的 `/api/urpd/all/<day>?agg=lin500` 请求的日期列表（ISO 字符串，按请求顺序）：`day ∉ {d − n days | n ∈ (0, 1, 7, 30, 90)}`。
  - `history_of(store)` 返回 `store.urpd_history(D − 1460 days, D)`；`payload(store)` 返回解析后的 `CostBasisHistory`。
  - `NOW` 为 2026-10-16 10:40Z，此时 D = 10-16，closed day = 10-15。下文的 budget 都配 `history_pause=0`。

```python
def test_history_copies_final_snapshots_without_requests(tmp_path):
    # budget 0 (the default): D-1, D-7, D-30, D-90 come from urpd, nothing else is asked
    assert urpd_calls(calls) == same_day(D) + past_of(D)
    assert set(history_of(store)) == {date(2026, 10, 15), date(2026, 10, 9), date(2026, 9, 16), date(2026, 7, 18)}
    result = payload(store)
    assert result.status[-1] == "forming" and result.status[-2] == "closed"
    assert (result.status.count("closed"), result.status.count("pending")) == (4, 1456)
    assert result.backfill_error is None

def test_history_backfills_newest_first_within_the_budget(tmp_path):
    # budget 5
    assert history_requests(calls, D) == ["2026-10-14", "2026-10-13", "2026-10-12", "2026-10-11", "2026-10-10"]
    assert len(history_of(store)) == 9
    assert payload(store).status.count("closed") == 9      # derived again after the backfill

def test_history_requests_come_after_the_round_state_is_written(tmp_path):
    # budget 1; the handler records store.state() at the first history request
    assert seen["last_success_at"] == timestamp(NOW)
    assert seen["next_due"] == timestamp(next_slot(NOW))

def test_history_resumes_after_a_restart(tmp_path):
    # round 1 as above, then a NEW OnchainSync on the same store at NOW + 1h, budget 5
    assert history_requests(second_calls, D) == ["2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05", "2026-10-04"]
    assert not set(history_requests(first_calls, D)) & set(history_requests(second_calls, D))

def test_history_leaves_days_that_are_not_final_to_urpd(tmp_path):
    early = datetime(2026, 10, 16, 1, 30, tzinfo=UTC)      # closed day 10-14, D-1 not final
    # budget 3
    assert history_requests(calls, D) == ["2026-10-14", "2026-10-13", "2026-10-12"]
    assert date(2026, 10, 15) not in history_of(store)
    assert payload(store).status[-2:] == ["closed", "forming"]     # 10-15 read live from urpd

def test_history_records_a_404_and_asks_again_a_day_later(tmp_path):
    # urpd_dates = every day from 2021-01-01 to 2026-10-16 except 2026-10-13; round 1 at NOW, budget 5
    assert history_of(store)[date(2026, 10, 13)].close is None
    assert payload(store).status[-4] == "absent"
    later = sync_for(store, transport, NOW + timedelta(hours=23), history_budget=1, history_pause=0)
    later._urpd_history(NOW + timedelta(hours=23), fetch=True)
    assert history_requests(...) == ["2026-10-08"]           # not due yet
    later._urpd_history(NOW + timedelta(hours=24), fetch=True)
    assert history_requests(...) == ["2026-10-13"]           # due: the newest gap again

def test_history_stops_at_the_first_brk_failure(tmp_path, caplog):
    # wrap the transport: /api/urpd/all/<day> with day outside {D, D-1, D-7, D-30, D-90} -> 503; budget 5
    assert history_requests(calls, D) == ["2026-10-14"]
    state = store.state()
    assert state["last_error"] is None and strings(state["reasons"]) == []
    assert state["history_error"] == "brk_unavailable" and payload(store).backfill_error == "brk_unavailable"
    assert "onchain_urpd_history_failed code=brk_unavailable" in caplog.text
    # a clean round at NOW + 1h (plain transport, budget 5) clears it
    assert store.state()["history_error"] is None and payload(store).backfill_error is None

@pytest.mark.parametrize("names", [set(HOUR1_SERIES), set(AGE_ONLY_SERIES), set(SIZE_SERIES)])
def test_history_is_not_fetched_on_a_retry_round(tmp_path, names):
    # round 1 at NOW, plain, budget 5; round 2 at NOW + 1h, budget 5, with
    # recorded(failing_for(names, urpd_dir=GOLDEN)): the hour1, age or size stage fails, retried in 5 minutes
    assert history_requests(second_calls, D) == []
    assert store.state()["next_due"] == timestamp(NOW + timedelta(hours=1) + RETRY_AFTER)
    assert store.derived("costbasis_history")[1] == NOW + timedelta(hours=1)    # copy and derive still ran
```

  - `failing_for(names, **options)` 是 `test_onchain_sync.py` 里现有的辅助函数：hour1 的 bulk 请求只要点名了 `names` 里任一条，就返回 503。它不返回请求记录，所以本测试再包一层 `recorded(transport) -> (transport, calls)`，在转发前记下 `(path, params)`。
  - 列表要覆盖 `_refresh` 里 `errors` 收集的全部取数阶段：现在是 hour1、age、size，URPD 由下一条测试覆盖。以后每多一个阶段，就在这里加一个参数。

```python
def test_history_is_not_fetched_when_the_urpd_stage_failed(tmp_path):
    # round 1 at NOW, plain, budget 5 (9 rows stored); round 2 at NOW + 1h, budget 5, with the transport wrapped
    # so that only /api/urpd/all/2026-10-16 (D) returns 503: `_urpd` fails, the stored D is reused.
    # Without the gate this round would ask for 10-08 ... 10-04.
    assert history_requests(second_calls, D) == []
    assert len(history_of(store)) == 9
    assert store.derived("costbasis_history") is not None

def test_history_is_not_fetched_without_d(tmp_path):
    # round 1 at NOW, plain, budget 5; round 2 at 2026-10-18T10:40Z, budget 5, urpd_dates without 10-17 and 10-18:
    # `_urpd` returns None without an error
    assert urpd_calls(second_calls) == [("all", "2026-10-18", "lin500"), ("all", "2026-10-17", "lin500")]
    assert [d for d, row in history_of(store).items() if row.close is None] == []

@pytest.mark.parametrize("bad", [{"buckets": []}, {"date": "2026-10-13"}])
def test_history_stops_at_a_bad_snapshot_without_clearing_chart_8(tmp_path, caplog, bad):
    # the transport answers /api/urpd/all/2026-10-14 with 200 and the golden snapshot updated by `bad`; budget 5
    assert history_requests(calls, D) == ["2026-10-14"]
    assert history_of(store)[date(2026, 10, 14)].close is None      # marked absent, never stored as data
    # a second round at NOW + 1h, plain transport, budget 1: the bad day does not block the older ones
    assert history_requests(second_calls, D) == ["2026-10-13"]
    assert store.derived("costbasis_history") is not None
    assert store.state()["history_error"] == "brk_bad_snapshot"
    assert "onchain_urpd_history_failed code=brk_bad_snapshot" in caplog.text

def test_history_backfill_has_a_five_minute_cap(tmp_path, monkeypatch, caplog):
    # monkeypatch wheelhouse_service.onchain.sync.time.monotonic to return 0, 100, 200, 300, ... (called once at
    # the start of the requests and once before each request); budget 10
    assert len(history_requests(calls, D)) == 2
    assert "onchain_urpd_history_paused reason=deadline" in caplog.text
    assert store.state()["history_error"] is None

def test_history_window_drops_rows_older_than_1461_days(tmp_path):
    # pre-seed history rows re-dated to D-1461 and D-1460 (golden 10-15 with model_copy)
    assert D - timedelta(days=1460) in history_of(store)
    assert store.urpd_history(D - timedelta(days=1461), D - timedelta(days=1461)) == {}

def test_history_stops_promptly_when_the_worker_stops(tmp_path):
    # history_budget=10, history_pause=60; the handler sets sync.stopping on the first history request
    assert len(history_requests(calls, D)) == 1 and elapsed < 5

def test_history_does_not_change_what_the_cost_basis_views_read(tmp_path):
    # two stores, rounds at NOW and NOW + 1h, budget 0 vs budget 5
    for kind in ("costbasis", "levels"):
        assert plain.derived(kind)[0] == backfilled.derived(kind)[0]
    assert urpd_rows(plain) == urpd_rows(backfilled)

def test_history_derive_failure_is_isolated(tmp_path, monkeypatch, caplog):
    # monkeypatch wheelhouse_service.onchain.sync.cost_basis_history to raise RuntimeError("boom")
    assert store.state()["last_error"] is None
    assert store.derived("costbasis") is not None and store.derived("costbasis_history") is None
    assert "onchain_derive_failed code=history_failed" in caplog.text and "boom" not in caplog.text

def test_history_copy_failure_keeps_chart_8(tmp_path, monkeypatch, caplog):
    # round 1 plain; round 2 with OnchainStore.save_urpd_history patched to raise RuntimeError("boom")
    assert store.derived("costbasis_history")[1] == NOW + timedelta(hours=1)
    assert store.state()["last_error"] is None
    assert "onchain_urpd_history_failed code=history_failed" in caplog.text and "boom" not in caplog.text
```

  在 `test_onchain_api.py` 中新增：

```python
def test_router_worker_backfills_history(tmp_path, monkeypatch):
    # replace wheelhouse_service.onchain.api.OnchainSync with a recorder whose start/stop do nothing
    with TestClient(router_app(tmp_path / "onchain.sqlite", start_worker=True)):
        pass
    assert recorded["history_budget"] == HISTORY_BUDGET == 120
```

- [ ] **Step 2：运行测试，确认失败**

  Run: `cd services/analytics && ../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_sync.py tests/onchain/test_onchain_api.py -k history -q`
  Expected: 出现 `unexpected keyword argument 'history_budget'`；或者因为派生里没有 `costbasis_history` 而断言失败。

- [ ] **Step 3：实现**
  - `__init__` 保存 `history_budget` 和 `history_pause`。`store.py` 的 `STATE_KEYS` 末尾加 `"history_error"`。
  - `_urpd_history(at, *, fetch)`：步骤顺序决定了预算、续传和出错的语义，所以按下面的写法实现。

```python
newest = self.store.latest_urpd(URPD_COHORT, URPD_AGG)
if newest is None:
    return
latest = newest.date
first = latest - timedelta(days=HISTORY_DAYS - 1)
self.store.prune_urpd_history(first)
rows = self.store.urpd_history(first, latest)
# Final snapshots `_urpd` already holds cost no request (D-1 after 02:00, D-7, D-30, D-90).
for day in self.store.urpd_days(URPD_COHORT, URPD_AGG):
    if first <= day < latest and (day not in rows or rows[day].supply is None):
        fetched_at = self.store.urpd_fetched_at(URPD_COHORT, day, URPD_AGG)
        snapshot = self.store.urpd(URPD_COHORT, day, URPD_AGG)
        if (fetched_at is not None and snapshot is not None and fetched_at >= final_from(day)
                and history_row(snapshot)):
            self.store.save_urpd_history(snapshot, fetched_at)
if not fetch or self.history_budget <= 0:
    return
rows = self.store.urpd_history(first, latest)
last = min(latest - timedelta(days=1), closed_day(at))
todo = [day for day in (last - timedelta(days=n) for n in range((last - first).days + 1))
        if (row := rows.get(day)) is None
        or (row.supply is None and row.fetched_at + ABSENT_RETRY <= at)]
started = time.monotonic()
error: str | None = None
for n, day in enumerate(todo[: self.history_budget]):
    if self.stopping.wait(self.history_pause if n else 0):
        break
    if time.monotonic() - started >= HISTORY_DEADLINE_SECONDS:
        logger.info("onchain_urpd_history_paused reason=deadline")
        break
    try:
        snapshot = self.client.urpd(URPD_COHORT, day, URPD_AGG)
    except BrkError as exc:
        error = exc.code
        break
    if snapshot is None:
        self.store.save_urpd_history_absent(day, at)
    elif snapshot.date != day or not history_row(snapshot):
        # Never stored as data. Marked absent, it is asked again in a day and never blocks the
        # older days behind it.
        self.store.save_urpd_history_absent(day, at)
        error = "brk_bad_snapshot"
        break
    else:
        self.store.save_urpd_history(snapshot, at)
if error is not None:
    logger.warning("onchain_urpd_history_failed code=%s", error)
self.store.set_state(history_error=error)
```

  另外记一条 info 日志 `onchain_urpd_history copied=%d fetched=%d absent=%d`，只记计数。

  - `_derive_history(at)`：整个函数体包在 `try` 里，出错时记 `onchain_derive_failed code=history_failed` 并清掉 `costbasis_history`。函数体的步骤：
    1. `latest_urpd` 为 None 时，执行 `clear_derived("costbasis_history")`。
    2. 否则读取窗口内的 `urpd_history`。对 `urpd_days` 中落在窗口内、且历史表里没有数据的日子（包括 D 和未定稿的 D−1），用 `urpd` 表里的快照构造 `HistoryDay(day=…, close=…, supply=history_row(snapshot), fetched_at=urpd_fetched_at(…))`。
    3. 调用 `cost_basis_history(rows, latest)`，结果为 None 时清掉派生。
    4. 结果不为 None 时，用 `model_copy(update={"rules": rules_for_view("costbasis_history", self.rules), "backfill_error": self.store.state()["history_error"]})` 后，以 `save_derived("costbasis_history", ..., at)` 写入。
  - `_refresh` 分两处改：
    - **原位置**：紧接在 `self._derive_sizes(hour1_missing, size_done)` 之后、拼装 `absent = [...]` 之前。main 1023827 上的派生顺序是：`_derive`（其中依次是 `_derive_cost_flow`、`_derive_pressure`、`_derive_sell_side`）→ `_derive_age_cohorts` → `_derive_sizes`，图 8 排在最后。这里只复制、只派生，不发请求：

```python
try:
    self._urpd_history(at, fetch=False)
except Exception:
    # Never log the exception: it may carry values. A fixed code is enough here.
    logger.warning("onchain_urpd_history_failed code=history_failed")
self._derive_history(clock())
```

    - **门控**：在 `errors = [error for error in (hour1_error, age_error, size_error, urpd_error) if error is not None]` 之后、`if errors:` 之前，加一行 `backfill = urpd is not None and not errors`。这里的 `urpd` 是 `_urpd` 返回的 D，可能已被 `_flow_set` 重取替换；URPD 阶段失败时它是 `_recent_urpd` 的旧值，但那时 `errors` 不为空。
    - **成功路径**：紧接在写 `last_success_at`、`last_error`、`next_due` 的 `set_state(...)` 之后、`return None` 之前：

```python
if backfill:
    try:
        self._urpd_history(at, fetch=True)
    except Exception:
        logger.warning("onchain_urpd_history_failed code=history_failed")
    # Derived again even when nothing was written, so a cleared history_error reaches the payload.
    self._derive_history(clock())
```

  - `api.create_router`：改为 `OnchainSync(store, client or BrkClient(), rules=rules, history_budget=HISTORY_BUDGET)`。
  - `rules.py`：在 `View` 里加 `"costbasis_history"`。`IMPLEMENTED` 会自动给它空集，`test_rules.py:56` 照样通过。

- [ ] **Step 4：运行测试，确认通过**

  运行 Step 2 的命令，再运行整个 `tests/onchain`。Expected: 全部通过。原有测试只需改两处：`sync_for` 增加 `**options`，以及 `test_state_roundtrip_and_latest_urpd` 的期望字典。

- [ ] **Step 5：运行 `make check`**

  Expected: 全绿。

- [ ] **Step 6：Commit**

```bash
git add services/analytics/src/wheelhouse_service/onchain/sync.py \
  services/analytics/src/wheelhouse_service/onchain/store.py \
  services/analytics/src/wheelhouse_service/onchain/api.py \
  services/analytics/src/wheelhouse_service/rules.py services/analytics/tests/onchain
git commit -m "feat(onchain): backfill the URPD history politely and derive Chart 8"
```

---

### Task 3：读接口、压缩、契约与前端黄金样本

**Files:**
- Modify: `services/analytics/src/wheelhouse_service/onchain/models.py`、`onchain/api.py`
- Modify: `services/analytics/src/wheelhouse_service/http.py`（仅当 `create_app` 里还没有 `GZipMiddleware` 时）
- Create: `services/analytics/tests/onchain/cbh_reference.py`（Python 参考实现，测试辅助，T7 也用）
- Modify: `services/analytics/tests/onchain/test_onchain_api.py`（新测试；`test_capability_and_get_only_schema` 的 onchain 路由全集加上 `/cost-basis-history`，复核 M2）
- Modify: `services/analytics/tests/onchain/test_onchain_costbasis_history.py`（参考实现测试）
- Generated: `integrations/wealthfolio/openapi.json`、`.../wheelhouse/api-schema.d.ts`（`make contract`）
- Modify: `.../wheelhouse/onchain-contract.ts`、`client.ts`、`onchain-contract.test.ts`、`client.test.ts`
- Create: `.../wheelhouse/cost-basis-history-sample.json`、`cost-basis-history-expected.json`

**Interfaces:**
- Consumes：derived 中的 `"costbasis_history"`（含 `backfill_error`）；Task 1 的 `seed_history_sample` 和 `HISTORY_SAMPLE_AT`；Task 2 的 `_derive_history`。
- Produces：
  - `HistorySpan = Literal["30", "90", "365", "all"]`
  - `class CostBasisHistoryView(Model)`：字段依次为
    - `data_state: DataState`
    - `reasons: list[str]`
    - `refreshing: bool`
    - `span: HistorySpan`
    - `latest_day: date | None`
    - `computed_at: AwareDatetime | None`
    - `floors: list[int]`
    - `days: list[date]`
    - `close: list[float | None]`
    - `supply: list[list[float] | None]`
    - `status: list[DayStatus]`
    - `backfill_error: str | None`
    - `brk_version: str | None`
    - `rules: list[Rule]`
    - `rules_pending: bool`
  - `GET /api/wheelhouse/v1/onchain/cost-basis-history?span=30|90|365|all`，默认 `365`。
  - `cbh_reference.reference(view: dict[str, Any], range_pct: int, lo: int = 75, hi: int = 95) -> dict[str, Any]`：返回 `{"range", "r0", "r1", "n", "floor", "cap", "top", "key", "label"}`。`view` 是接口 JSON，或其切片。
  - 前端：
    - `export type CostBasisHistoryView`、`costBasisHistorySchema`；
    - `query(path, schema, init?, timeoutMs = 5000)`；
    - `getCostBasisHistory(span: CostBasisHistoryView["span"], signal?: AbortSignal)`：`span` 为 `"all"` 时超时 30_000，其余为 15_000。

- [ ] **Step 1：写失败的测试**

  `history_app(tmp_path, now)` 的做法：先 `seed_history_sample(store)`，再 `OnchainSync(store, blocked_client()[0], rules=frozenset())._derive_history(HISTORY_SAMPLE_AT)`，最后返回 `router_app(path, now)`。

```python
SAMPLE_NOW = datetime(2026, 10, 16, 18, 40, tzinfo=UTC)
SAMPLE = Path(__file__).parents[4] / "integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse"

def test_cost_basis_history_slices_the_span(tmp_path):
    with TestClient(history_app(tmp_path, SAMPLE_NOW)) as http:
        body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
        assert body["span"] == "30" and body["data_state"] == "fresh" and body["latest_day"] == "2026-10-16"
        assert len(body["days"]) == 30 and body["days"][0] == "2026-09-17" and body["days"][-1] == "2026-10-16"
        assert len(body["floors"]) == 250 and body["floors"][0] == 1000 and body["floors"][-1] == 125500
        assert Counter(body["status"]) == {"pending": 24, "absent": 1, "closed": 4, "forming": 1}
        assert body["supply"][0] is None and body["close"][0] is None        # missing is null, never 0
        assert body["supply"][-1][(82000 - 1000) // 500] == 252722.29
        assert body["close"][-2] == 82203.57
        assert body["backfill_error"] is None
        assert body["rules"] == [] and body["rules_pending"] is False
        assert body["computed_at"].startswith("2026-10-16T18:29:37")
        assert len(http.get(f"{PREFIX}/cost-basis-history").json()["days"]) == 365
        everything = http.get(f"{PREFIX}/cost-basis-history?span=all").json()
        assert len(everything["days"]) == 1461 and everything["days"][0] == "2022-10-17"

def test_cost_basis_history_matches_the_frontend_sample(tmp_path):
    # the committed sample is exactly what the service answers (PLAN-SR5-6:396 does the same)
    with TestClient(history_app(tmp_path, SAMPLE_NOW)) as http:
        body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert body == json.loads((SAMPLE / "cost-basis-history-sample.json").read_text())

def test_cost_basis_history_rejects_an_unknown_span(tmp_path):
    ...  # ?span=7 -> 422

def test_cost_basis_history_is_unavailable_without_a_payload(tmp_path):
    ...  # empty store: data_state "unavailable", reasons ["urpd_missing"], floors/days/close/supply/status == [],
         # latest_day None, computed_at None, backfill_error None, span "365"

def test_cost_basis_history_goes_stale_after_the_grace(tmp_path):
    ...  # now 2026-10-17T01:59Z -> "fresh"; 2026-10-17T02:00Z -> "stale" (day1_state)

def test_cost_basis_history_reads_no_network_and_computes_nothing(tmp_path, monkeypatch):
    # seed tmp_path / "onchain.sqlite" and derive first, as in history_app; only then patch
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the read route computed something")

    # Each name must still be there, or the patch would silently patch nothing; and no stored input
    # is read, which any recomputation, under whatever name, would need.
    for module in (costbasis_history, sync_module):
        for name in ("cost_basis_history", "history_row"):
            assert hasattr(module, name), f"{module.__name__}.{name}"
            monkeypatch.setattr(module, name, boom)
    for name in ("read_series", "urpd_history", "urpd", "latest_urpd"):
        monkeypatch.setattr(OnchainStore, name, boom)
    client, seen = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset())
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/cost-basis-history?span=all")
    assert response.status_code == 200 and len(response.json()["days"]) == 1461
    assert seen == []

def test_cost_basis_history_is_gzipped(tmp_path):
    # seed tmp_path / "onchain.sqlite" as in history_app, then the whole app, so the middleware is in the path
    client, _ = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset())
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/cost-basis-history?span=all", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200 and response.headers["content-encoding"] == "gzip"
```

  在 `test_onchain_costbasis_history.py` 中，加参考实现的测试：

```python
def test_reference_reproduces_the_frontend_expected():
    view = json.loads((SAMPLE / "cost-basis-history-sample.json").read_text())
    expected = json.loads((SAMPLE / "cost-basis-history-expected.json").read_text())
    assert [reference(view, r) for r in (0, 50, 25, 10)] == expected
    assert reference(view, 0) == {"range": 0, "r0": 0, "r1": 249, "n": 1250, "floor": 87116.49,
        "cap": 197436.37, "top": 765418.85, "key": ["−87k", "115k", "142k", "170k", "197k+"],
        "label": "75–95% · 87k–197k+"}
```

- [ ] **Step 2：运行测试，确认失败**

  Run: `cd services/analytics && ../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_api.py tests/onchain/test_onchain_costbasis_history.py -k "cost_basis_history or reference" -q`
  Expected: 返回 404，或者 `cbh_reference` 不存在。

- [ ] **Step 3：实现接口与压缩**
  - `api.py`：
    - `HISTORY_REASONS = ("urpd_missing", "brk_unavailable")`
    - `SPAN_DAYS: dict[HistorySpan, int] = {"30": 30, "90": 90, "365": 365, "all": HISTORY_DAYS}`
    - 路由函数取名 `cost_basis_history_view(span: HistorySpan = "365")`，避免与纯函数重名。逻辑是读 `derived("costbasis_history")`，各列取 `[-SPAN_DAYS[span]:]`。
      - `data_state=day1_state(result.latest_day, now)`
      - `reasons=only(stored_reasons(state), HISTORY_REASONS)`
      - `backfill_error=result.backfill_error`
      - `rules_pending=pending("costbasis_history", result.rules)`
      - 没有载荷时，`reasons` 为 `reasons or ["urpd_missing"]`，各列为 `[]`，`backfill_error` 为 None。
  - `models.py`：加上 Interfaces 里列出的 `HistorySpan` 和 `CostBasisHistoryView`，并给 `supply` 加注释：`# One row per day, lined up with floors; null when there is no snapshot, never zeros.`
  - `http.py`：先在 `create_app` 里查 `GZipMiddleware`（main 1023827 上没有），已有就跳过这一步。没有就紧接在 `TrustedHostMiddleware` 之后加：`app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)`，从 `fastapi.middleware.gzip` 导入。
  - `cbh_reference.py`：参考实现照 A:3961–4008 和 A:4117–4139，只用标准库：

```python
js_round = lambda x: math.floor(x + 0.5)                      # Math.round for x >= 0
stored = [i for i, row in enumerate(view["supply"]) if row is not None]
lo = min(r for i in stored for r, v in enumerate(view["supply"][i]) if v > 0.005); hi = max(...)
spot = view["close"][stored[-1]]
# range f: a = max(lo, floor((spot*(1-f) - 1000)/500)), b = min(hi, ceil((spot*(1+f) - 1000)/500)); keep only if b > a
cells = sorted(v for i in stored for v in view["supply"][i][a:b + 1] if v > 0.005)
q = lambda p: cells[min(len(cells) - 1, max(0, js_round(p / 100 * (len(cells) - 1))))]
floor_, cap = q(lo_q), max(q(hi_q), q(lo_q) + 1e-9)
# key / label: the original's fmtBtc8 and drawKey8 / clipLabel8, with "−" (U+2212) and "–" (U+2013)
```

  - 运行 `make contract`。

- [ ] **Step 4：前端契约与客户端**
  - `onchain-contract.ts`：

```ts
export type CostBasisHistoryView = components["schemas"]["CostBasisHistoryView"];
const dayStatus = z.enum(["closed", "forming", "pending", "absent"]);
// Columns of one length, rows as wide as the grid, and a missing day missing in every column: a
// payload that breaks any of this would misplace cells, so it is refused rather than drawn.
export const costBasisHistorySchema: z.ZodType<CostBasisHistoryView, z.ZodTypeDef, unknown> = z
  .object({ /* the fields above; floors z.array(z.number().int()); supply z.array(z.array(z.number()).nullable());
               backfill_error z.string().nullable() */ })
  .refine((v) => /* close, supply, status as long as days; every row length === floors.length;
                    (status is pending|absent) === (supply null) === (close null) */,
          { message: "cost-basis history columns differ" });
```

  - `client.ts`：`query()` 加第四个参数 `timeoutMs = 5000`，把原来写死的 `AbortSignal.timeout(5000)` 换成它，其余 getter 不变。

```ts
export const getCostBasisHistory = (span: CostBasisHistoryView["span"], signal?: AbortSignal) =>
  query(`/onchain/cost-basis-history?${new URLSearchParams({ span })}`, costBasisHistorySchema,
        { signal }, span === "all" ? 30_000 : 15_000);
```

  - `client.test.ts`：spy `AbortSignal.timeout`，mock `fetch` 返回样本。断言 `getCostBasisHistory("all")` 用 30000，`getCostBasisHistory("365")` 用 15000，`getSellSide()` 仍用 5000。

- [ ] **Step 5：生成前端黄金样本**
  1. 用一个一次性脚本生成样本，脚本放在 scratchpad，不入库。在临时库上依次运行 `seed_history_sample`、`_derive_history(HISTORY_SAMPLE_AT)`，然后用 `TestClient` 在 `SAMPLE_NOW` 请求 `?span=30`，把 JSON 原样写入 `cost-basis-history-sample.json`（约 15 KB）。
  2. 用已入库的 `cbh_reference.reference` 算 Range 0/50/25/10 四档，写入 `cost-basis-history-expected.json`。
  3. 输出必须与写计划时、复核时都独立算出的下表一致：

  | Range | 行 r0–r1 | y 轴 | 行数 | 格数 n | floor | cap | 图例 |
  |---|---|---|---|---|---|---|---|
  | All | 0–249 | $1,000–$126,000 | 250 | 1,250 | 87,116.49 | 197,436.37 | `−87k 115k 142k 170k 197k+` |
  | ±50% | 79–242 | $40,500–$122,500 | 164 | 820 | 100,984.37 | 211,844.19 | `−101k 129k 156k 184k 212k+` |
  | ±25% | 119–202 | $60,500–$102,500 | 84 | 420 | 142,883.05 | 238,690.49 | `−143k 167k 191k 215k 239k+` |
  | ±10% | 144–177 | $73,000–$90,000 | 34 | 170 | 160,548.58 | 302,419.22 | `−161k 196k 231k 267k 302k+` |

  四种 Range 的最大格都是 765,418.85。spot 为 81,217.6，即 10-16 的 close。在 `cost-basis-history.test.ts` 的文件头注释里写明样本的来源：fixture 目录、`HISTORY_SAMPLE_AT`、`cbh_reference.py`。

  在 `onchain-contract.test.ts` 中增加以下测试：
  - 样本能通过 `costBasisHistorySchema`；
  - 把某一行改成 249 格时被拒；
  - pending 的日子带了数字时被拒；
  - `close` 少一项时被拒。

- [ ] **Step 6：运行测试，确认通过**

  运行 Step 2 的命令。然后运行 `make sync && npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend exec vitest run src/features/wheelhouse/onchain-contract src/features/wheelhouse/client`。Expected: 全部通过。

- [ ] **Step 7：运行 `make check`**

  Expected: 全绿，其中 `type-check` 能识别新的 schema 类型。

- [ ] **Step 8：Commit**

```bash
git add services/analytics integrations/wealthfolio/openapi.json \
  integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse
git commit -m "feat(onchain): serve the cost-basis history by span, gzipped"
```

---

### Task 4：前端纯函数（照原站的 Contrast、Range、轴与色阶）

**Files:**
- Create: `.../wheelhouse/cost-basis-history.ts`
- Create: `.../wheelhouse/cost-basis-history.test.ts`

**Interfaces:**
- Consumes：`CostBasisHistoryView`（Task 3）；`ticks` 来自 `sell-side.ts`。
- Produces（全部从 `cost-basis-history.ts` 导出）：

```ts
export type SpanKey = CostBasisHistoryView["span"];
export type DayStatus = CostBasisHistoryView["status"][number];
export const CBH_SPANS: readonly { key: SpanKey; days: number }[];   // 30, 90, 365, all = 1461 (sell-side.ts already exports SPANS)
export const DEFAULT_SPAN: SpanKey;                                 // "365"
export const RANGES: readonly [0, 50, 25, 10];
export type RangePct = (typeof RANGES)[number];
export const DEFAULT_CONTRAST: { lo: 75; hi: 95 };
export const OCCUPIED = 0.005;                                      // A:3959
export const STEP = 500;
export const UNDER_FLOOR: string;                                   // "#233142"
export const RAMP: readonly [string, string, string, string];       // R14, dim -> bright
export interface Visible { days: string[]; close: (number | null)[]; supply: (number[] | null)[]; status: DayStatus[] }
export function visibleWindow(view: CostBasisHistoryView, zx: [string, string] | null): { vis: Visible; zx: [string, string] | null };
export function occupiedRows(floors: number[], vis: Visible, range: RangePct, zy: [number, number] | null): { r0: number; r1: number; zy: [number, number] | null } | null;
export function sortedCells(vis: Visible, r0: number, r1: number): Float64Array;
export interface Contrast { floor: number; cap: number; span: number; clipped: boolean; dropped: boolean }
export function contrast(sorted: Float64Array, lo: number, hi: number): Contrast;
export type Level = 0 | 1 | 2 | 3 | 4 | 5;                          // 0 empty, 1 below floor, 2-5 ramp
export function cellLevel(v: number, c: Contrast): Level;
export function paint(vis: Visible, r0: number, r1: number, c: Contrast, out: Uint8ClampedArray): void;
export function keyLabels(c: Contrast): string[];                   // 5 labels
export function contrastLabel(c: Contrast, lo: number, hi: number): string | null;  // null = "full range"
export function clampHandle(which: "lo" | "hi", value: number, lo: number, hi: number): [number, number];
export function zoomFromDrag(box: { x0: number; x1: number; y0: number; y1: number }, plot: { width: number; height: number }, days: string[], yLo: number, yHi: number): { zx: [string, string] | null; zy: [number, number] | null } | null;
export function dayTicks(first: string, last: string, count: number): string[];
export function dayLabel(day: string, spanDays: number): string;
export const fmtSupply: (v: number) => string;  // A:3924 fmtBtc8 (sell-side.ts already exports fmtBtc)
export const fmtK: (v: number) => string;       // A:3926
export const fmtBucket: (v: number) => string;  // A:3927
export type TipParts = { day: string; bucket: string; supply: string; spot: string | null } | { day: string; missing: "pending" | "absent" };
export function tipParts(vis: Visible, i: number, r: number, floors: number[]): TipParts;   // A:4263-4288
export function zoomText(zx: [string, string] | null, zy: [number, number] | null): string; // A:4235-4245, without the i18n suffix
export function coverage(vis: Visible): { have: number; want: number; pending: number; absent: number; forming: number };
```

- [ ] **Step 1：写失败的测试**。期望值都有出处：SR-8 第 18–22 行，以及 Task 3 的期望表。

```ts
const grid = Array.from({ length: 250 }, (_, i) => 1000 + 500 * i);
const full = (spot: number): Visible => ({ days: ["2026-10-18", "2026-10-19"], close: [spot, spot],
  supply: [grid.map(() => 1), grid.map(() => 1)], status: ["closed", "forming"] });

it("centres Range on the latest close as the original (SR-8 lines 20-21)", () => {
  const rows = (range: RangePct) => { const o = occupiedRows(grid, full(82374.12), range, null)!; return [o.r0, o.r1]; };
  expect(rows(0)).toEqual([0, 249]);
  expect(rows(50)).toEqual([80, 246]);   // $41,000-$124,500, 167 rows
  expect(rows(25)).toEqual([121, 204]);  // $61,500-$103,500, 84 rows
  expect(rows(10)).toEqual([146, 180]);  // $74,000-$91,500, 35 rows
});
it("lets a dragged price band win over Range and drops one that is empty", () => {
  expect(occupiedRows(grid, full(82374.12), 25, [60000, 70000])).toEqual({ r0: 118, r1: 138, zy: [60000, 70000] });
  expect(occupiedRows(grid, full(82374.12), 0, [60000, 60000])!.zy).toBeNull();
});
it("trims rows that hold nothing and ignores missing days", () => { /* rows 0-9 at 0.004 -> r0 10; a null day
  with a later close does not move the Range centre: spot comes from the last stored day */ });
it("picks quantiles by nearest rank with Math.round", () => {
  const s = Float64Array.from({ length: 100 }, (_, i) => i + 1);
  expect(contrast(s, 75, 95)).toMatchObject({ floor: 75, cap: 95, clipped: true, dropped: true });
  expect(contrast(s, 0, 100)).toMatchObject({ floor: 0, cap: 100, clipped: false, dropped: false });
  const eleven = Float64Array.from({ length: 11 }, (_, i) => i + 1);   // 9.5 rounds up, 7.5 rounds up
  expect(contrast(eleven, 75, 95)).toMatchObject({ floor: 9, cap: 11, clipped: false });
});
it("labels the key and the contrast as the original (SR-8 lines 18-19)", () => {
  const c = { floor: 83745.15, cap: 192900.73, span: 192900.73 - 83745.15, clipped: true, dropped: true };
  expect(keyLabels(c)).toEqual(["−84k", "111k", "138k", "166k", "193k+"]);
  expect(contrastLabel(c, 75, 95)).toBe("75–95% · 84k–193k+");
  expect(contrastLabel({ ...c, floor: 87327.15, cap: 199792.63 }, 75, 95)).toBe("75–95% · 87k–200k+");
  expect(contrastLabel({ ...c, floor: 85947.41, cap: 197795.52 }, 75, 95)).toBe("75–95% · 86k–198k+");
  expect(contrastLabel({ ...c, clipped: false, dropped: false }, 0, 100)).toBeNull();
});
it("maps cells to empty, below floor and four steps", () => {
  const c = { floor: 83745.15, cap: 192900.73, span: 109155.58, clipped: true, dropped: true };
  expect([0.005, 0.0051, 83745.15, 83745.16, 111034.05, 192900.73, 1e6].map((v) => cellLevel(v, c)))
    .toEqual([0, 1, 1, 2, 3, 5, 5]);
});
it("paints missing days and empty cells transparent", () => { /* 2 days x 2 rows, day 2 null, floor 1 cap 5:
  pixel (0,1) [row 0, value 0.004] alpha 0; pixel (0,0) [row 1, value 10] = #59e6cd -> [89,230,205,255];
  pixels of day 2 alpha 0 */ });
it("matches the Python reference on the sample (cost-basis-history-expected.json)", () => {
  // for each Range: r0, r1, n, floor, cap, keyLabels and contrastLabel exactly as recorded
});
it("clamps the contrast handles without swapping", () => {
  expect(clampHandle("lo", 96, 75, 95)).toEqual([94, 95]);
  expect(clampHandle("hi", 10, 75, 95)).toEqual([75, 76]);
  expect(clampHandle("lo", -5, 0, 95)).toEqual([0, 95]);
  expect(clampHandle("lo", 100, 75, 100)).toEqual([99, 100]);
});
it("places time ticks by d3's rule (SR-8 lines 19, 21)", () => {
  expect(dayTicks("2025-10-20", "2026-10-19", 7)).toEqual(["2026-01-01", "2026-04-01", "2026-07-01", "2026-10-01"]);
  expect(dayTicks("2026-09-20", "2026-10-19", 7)).toEqual(["2026-09-20", "2026-09-27", "2026-10-04", "2026-10-11", "2026-10-18"]);
  expect(dayTicks("2022-10-20", "2026-10-19", 7)).toEqual(["2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01"]);
  expect(dayTicks("2022-10-20", "2026-10-19", 3)).toEqual(["2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01"]);
  expect(dayTicks("2022-10-20", "2026-10-19", 4)).toEqual(["2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01"]);
  expect(dayTicks("2022-10-20", "2026-10-19", 2)).toEqual(["2024-01-01", "2026-01-01"]);
  expect(["2026-01-01", "2026-10-04", "2024-01-01"].map((d, i) => dayLabel(d, [364, 29, 1460][i])))
    .toEqual(["Jan 26", "04 Oct", "2024"]);
});
it("formats as the original", () => {
  expect([887948.13, 1234567, 999.6].map(fmtSupply)).toEqual(["888k", "1.23M", "1000"]);
  expect([82374.12, 9500, 20000].map(fmtK)).toEqual(["$82k", "$9.5k", "$20k"]);
  expect([82000, 82500].map(fmtBucket)).toEqual(["$82.0k", "$82.5k"]);
  expect(ticks(1000, 126000, 7)).toEqual([20000, 40000, 60000, 80000, 100000, 120000]);  // SR-8 line 21
});
it("builds the readouts the UI renders (SR-8 line 22)", () => {
  const { vis } = visibleWindow(sample, null);
  // the original's tooltip on 2026-10-15; the golden fixture's 10-15 $82k cell is 219,105.90
  expect(tipParts(vis, 28, 162, sample.floors)).toEqual({ day: "2026-10-15", bucket: "$82.0k–$82.5k", supply: "219,106 BTC", spot: "$82k" });
  expect(tipParts(vis, 26, 162, sample.floors)).toEqual({ day: "2026-10-13", missing: "pending" });
  expect(zoomText(["2026-09-20", "2026-10-11"], [60000, 70000])).toBe("09-20–10-11 · $60k–$70k");
  expect(zoomText(null, [9500, 70000])).toBe("$9.5k–$70k");
  expect(coverage(vis)).toEqual({ have: 5, want: 30, pending: 24, absent: 1, forming: 1 });
});
it("turns a dragged box into whole days and a price band", () => {
  const days = Array.from({ length: 365 }, (_, i) => isoDay(Date.UTC(2025, 9, 20) + i * 864e5));
  expect(zoomFromDrag({ x0: 10.2, x1: 20.7, y0: 0, y1: 125 }, { width: 365, height: 250 }, days, 1000, 126000))
    .toEqual({ zx: [days[10], days[20]], zy: [63500, 126000] });
  expect(zoomFromDrag({ x0: 10, x1: 13, y0: 0, y1: 3 }, { width: 365, height: 250 }, days, 1000, 126000)).toBeNull();
  expect(zoomFromDrag({ x0: 10, x1: 20, y0: 0, y1: 2 }, { width: 365, height: 250 }, days, 1000, 126000)!.zy).toBeNull();
});
```

- [ ] **Step 2：运行测试，确认失败**

  Run: `make sync && npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend exec vitest run src/features/wheelhouse/cost-basis-history.test.ts`
  Expected: 模块不存在。

- [ ] **Step 3：实现**。函数体不完全由签名决定的地方，规则如下：
  - **`visibleWindow`**：有 zx 时只保留 `zx[0] ≤ day ≤ zx[1]` 的日子；剩下不到 2 天时丢弃 zx（A:3948–3958）。
  - **`occupiedRows`**：
    - 先在有数据的日子里找 `v > 0.005` 的最低行和最高行；一行都没有时返回 null。
    - 有 zy 时：`a = max(lo, floor((zy0 − floors[0]) / 500))`，`b = min(hi, ceil((zy1 − floors[0]) / 500))`；`b > a` 才采用，否则丢弃 zy，继续往下判断。
    - range > 0 时，以可见窗口里最后一个有数据的日子的 close 为 spot，按同样的公式取 `spot × (1 ∓ f)`；`b > a` 才采用。
    - 都不满足时返回 `[lo, hi]`。参照 A:3960–3982。
  - **`contrast`**：空数组按 `[0, 1]` 计算。
    - `at(q) = s[min(n − 1, max(0, Math.round(q / 100 × (n − 1))))]`
    - `floor = lo ≤ 0 ? 0 : at(lo)`
    - `cap = hi ≥ 100 ? top : max(at(hi), floor + 1e-9)`
    - `span = max(1e-9, cap − floor)`
    - `clipped = cap < top`，`dropped = floor > 0`
    - 参照 A:4009–4019。
  - **`cellLevel`**：`v ≤ 0.005` 时为 0；`v ≤ floor` 时为 1；否则为 `2 + min(3, floor(min(1, (v − floor) / span) × 4))`。这是 A:4041–4046 加上 R11 的那一级。
  - **`paint`**：输出宽为可见天数、高为 `r1 − r0 + 1` 的 RGBA。行 r 画在 `y = r1 − r`。level 0 和缺失的日子 alpha 为 0。level 1 用 `UNDER_FLOOR`，level 2–5 依次用 `RAMP[0..3]`，alpha 都是 255。
  - **`keyLabels`**：`floor + k/4 · span`（k = 0..3）用 `fmtSupply` 格式化，第一个在 `dropped` 时加前缀 "−"（U+2212）；最后一个是 `fmtSupply(cap)`，`clipped` 时加 "+"。参照 A:4117–4131。
  - **`contrastLabel`**：格式为 `` `${Math.round(lo)}–${Math.round(hi)}% · ${fmtSupply(floor)}–${fmtSupply(cap)}${clipped ? "+" : ""}` ``，其中 "–" 是 U+2013。参照 A:4133–4139。
  - **`clampHandle`**：
    - lo：`min(value, hi − 1)`，再夹到 [0, 99]；
    - hi：`max(value, lo + 1)`，再夹到 [1, 100]；
    - 参照 A:4164–4180。
  - **`zoomFromDrag`**：
    - |dx| 和 |dy| 都小于 6 时返回 null（A:4189）。
    - |dx| ≥ 6 时：列 = `clamp(floor(x / (width / n)), 0, n − 1)`，两端都换成日期，前者小于后者才设置 zx。
    - |dy| ≥ 6 时：`price = yHi − y / height × (yHi − yLo)`，按升序设置 zy。
  - **`dayTicks`**：移植 d3-time 的 `tickInterval`。
    - 候选间隔为 [1 天, 2 天, 1 周（周日）, 1 月, 3 月, 1 年]，时长依次为 1、2、7、30、90、365 天。
    - `target = (last − first) / count`。
    - target ≥ 365 天时（即 `bisector.right` 落到候选表末尾），年步长取 d3 的 `tickStep(first / 年, last / 年, count)`，1 年按 365 天计。可以把 sell-side.ts 的 `tickSpec` 导出复用，或另写一个 `tickIncrement`。取能被步长整除的年份的 1 月 1 日（复核 M1）。
    - 否则取 i = 第一个时长大于 target 的候选（`bisector.right`）。i 为 0 时用 1 天；否则当 `target / dur[i−1] < dur[i] / target` 时取 i−1，否则取 i。
    - 对齐方式：2 天间隔取 1970-01-01 起的偶数日（原站内嵌 d3 v7.9.0 的 `unixDay`，Task 4 复核与原站 31,147 个窗口一致；不是 `(UTC 日 − 1) % 2`，那是更早版本 d3-time 的做法）；3 月间隔取 `月 % 3 === 0` 的月份。
  - **`dayLabel`**：`spanDays` 是可见窗口首尾两天相差的天数，即 `(last − first) / 1 天`，同 A:4091，不是列数（复核 M15）。`spanDays ≤ 120` 时为 `DD Mon`；`≤ 800` 时为 `Mon YY`；否则为 `YYYY`。月份缩写用固定数组 `["Jan", …, "Dec"]`，不用 `Intl`，因为 en-GB 的 September 缩写可能是 "Sept"。
  - **`tipParts`**：bucket 为 `` `${fmtBucket(f)}–${fmtBucket(f + 500)}` ``（A:4285）；supply 为 `Math.round(v).toLocaleString("en-US") + " BTC"`（A:4286 的 `,.0f`）；spot 为 `fmtK(close)`，close 为 null 时为 null（A:4287）。缺失的日子只返回日期和状态。
  - **`zoomText`**：zx 写成 `` `${zx[0].slice(5)}–${zx[1].slice(5)}` ``，zy 写成 `` `${fmtK(zy[0])}–${fmtK(zy[1])}` ``，有哪段写哪段，用 " · " 连接（A:4239–4242）。
  - **`coverage`**：按 `vis.status` 计数；have 为 closed 与 forming 之和，want 为天数。

- [ ] **Step 4：运行测试，确认通过**

  运行与 Step 2 相同的命令。Expected: 全部通过。

- [ ] **Step 5：运行 `make check`**

  Expected: 全绿。

- [ ] **Step 6：Commit**

```bash
git add integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/cost-basis-history.ts \
  integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/cost-basis-history.test.ts
git commit -m "feat(flows): port Chart 8's contrast, range and axis rules"
```

---

### Task 5：图 8 组件、接入 Cost basis、文案与样式

**Files:**
- Create: `.../wheelhouse/cost-basis-history-chart.tsx`、`cost-basis-history-chart.test.tsx`
- Modify: `.../wheelhouse/flows-panel.tsx`（`costbasis` 分支）、`flows-panel.test.tsx`
- Modify: `.../wheelhouse/i18n.ts`、`market.css`

**Interfaces:**
- Consumes：Task 4 的全部导出；`getCostBasisHistory`；`useChartWidth`（`seller-charts.tsx`）；`Segments`（`sell-side-charts.tsx`）；`heightFor`、`ticks`（`sell-side.ts`）；`ReadColumns`（`flow-notes.tsx`）；`reasonText`、`rulesNote`（`onchain-text.ts`）。
- Produces：`export function CostBasisHistoryChart(): JSX.Element`，渲染为 `section.wh-seller-panel.wh-cbh[data-chart="cost-basis-history"]`。组件不接收 props，以后 Supplementary 也可以直接复用。

- [ ] **Step 1：写失败的组件测试**

  准备工作：
  - mock `getCostBasisHistory`。
  - 用 `vi.spyOn(HTMLCanvasElement.prototype, "getContext")` 返回一个假的 2D 上下文：`createImageData(w, h)` 返回 `{ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }`，`putImageData` 是 spy。
  - `sample` 取自 `cost-basis-history-sample.json`。

  测试用例：
  1. **`draws Chart 8 with the original's default controls`**
     - 标题为 `Chart 8 — Cost Basis Distribution, All Coins`。
     - 第一次请求的参数是 `"365"`。
     - Span 按钮依次为 `30D 90D 365D All`，按下的是 365D；Range 按下的是 `All`。
     - 两个滑杆的值分别为 `"75"` 和 `"95"`。
     - Contrast 标签为 `75–95% · 87k–197k+`；图例为 `−87k 115k 142k 170k 197k+`。
     - canvas 的 `data-cols="30"`、`data-rows="250"`。
     - `putImageData` 收到的 ImageData 为 30×250。
  2. **`hatches missing days and outlines the forming one`**
     - `[data-missing]` 共 2 个，`data-days` 分别为 `"21"` 和 `"4"`。
     - `[data-forming="true"]` 共 1 个。
     - 状态行包含 `5 of 30 days stored`、`the rest is still being fetched`、`1 day has no snapshot at BRK` 和 `The last column is today's snapshot, still forming`。
  3. **`Range ±25 narrows the rows`**：点击 `±25%` 后，`data-rows="84"`，标签为 `75–95% · 143k–239k+`。
  4. **`Span All asks for 1,461 days and keeps the chart while it loads`**：第二次调用返回一个不 resolve 的 promise。点击 All 后，mock 收到 `"all"`；显示 `loading 1,461 days…`；canvas 仍在。
  5. **`clamps the contrast handles`**：把 hi 滑杆改成 10，值变为 `"76"`；把 lo 滑杆改成 99，值变为 `"75"`（因为 hi 此时是 76）。
  6. **`reads a day with the keyboard and says when it is missing`**：先让 svg 获得焦点。每次按键，`fireEvent.keyDown` 都返回 false，即已经 `preventDefault`。
     - 按一次 ArrowLeft：tooltip 包含 `2026-10-15`、`Bucket $81.0k–$81.5k`、`` `Supply ${Math.round(sample.supply[28]![160]).toLocaleString("en-US")} BTC` `` 和 `spot $82k`。起始行是 latest close 所在的行 `floor((81217.6 − 1000) / 500) = 160`。
     - 再按两次 ArrowLeft：tooltip 显示 `2026-10-13` 和 `No snapshot stored for this day yet`。
     - 按 End：tooltip 显示 `2026-10-16` 和 `forming`。
  7. **`drags a box to zoom and resets it`**
     - mock svg 的 `getBoundingClientRect` 为 `{ left: 0, top: 0, width: 720, height: 338 }`（useChartWidth 默认宽 720，`heightFor(720) = 338`）。
     - 用鼠标从 (100, 40) 拖到 (400, 200)：备注匹配 `/^\d\d-\d\d–\d\d-\d\d · \$[\d.]+k–\$[\d.]+k · double-click to reset$/`，并出现 `Reset zoom` 按钮。
     - 点击 `Reset zoom`：备注变为 `drag the chart to zoom`。
  8. **`shows no data, never zero, when nothing in view is stored`**：把 sample 改成所有天都是 pending、supply 和 close 都为 null。显示 `No data for this chart`，没有 canvas，页面上没有 `0 BTC`。
  9. **`unavailable, failed and stale`**
     - `data_state: "unavailable"`、`reasons: ["urpd_missing"]`：显示 `Cost basis history unavailable` 和 `URPD distribution unavailable`。
     - 请求被 reject：显示 unavailable。
     - `data_state: "stale"`：显示 `Latest snapshot is 2026-10-16; the data is stale`。
  10. **`has the three notes and the original caption`**：三栏标题、`cbh.shows` 的英文和图注都在。
  11. **`keeps the last chart when a new span fails to load`**：第一次调用返回 sample，第二次（All）被 reject。点击 All 后：canvas 仍在且 `data-cols="30"`；显示 `could not load 1,461 days`；页面上没有 `Cost basis history unavailable`；All 按钮为按下状态。
  12. **`says when the backfill is paused`**：sample 的 `backfill_error` 改为 `"brk_unavailable"`。状态行包含 `history fetch paused: BRK returned brk_unavailable; retrying next hour`，不包含 `the rest is still being fetched`。
  13. **`clears the readout when inputs or data change`**：用键盘读出一格后，点 `±25%`，tooltip 消失；再读一格，用一个 `computed_at` 不同的 sample 重新 resolve 并触发 refetch，tooltip 也消失。

  在 `flows-panel.test.tsx` 中加 `getCostBasisHistory` 的 mock，并新增一条：打开 `?flow=costbasis` 后，`.wh-flows` 里最后一个 `section[data-chart]` 的 `data-chart` 为 `"cost-basis-history"`，紧跟在 `costflow-4` 之后（`getCostFlow` 已经有 mock，见现有的 `show("?flow=costbasis")` 测试）。

- [ ] **Step 2：运行测试，确认失败**

  Run: `make sync && npx --yes pnpm@10.33.4 --dir .local/wealthfolio --filter frontend exec vitest run src/features/wheelhouse/cost-basis-history-chart.test.tsx src/features/wheelhouse/flows-panel.test.tsx`
  Expected: 模块不存在，或者找不到元素。

- [ ] **Step 3：实现组件**。要点如下：
  - **查询**：`useQuery({ queryKey: ["wh", "onchain", "cost-basis-history", span], queryFn: ({ signal }) => getCostBasisHistory(span, signal), refetchInterval: 900_000, retry: false, placeholderData: (previous) => previous })`。
    - `isPlaceholderData` 为真时显示 `cbh.fetching`（n 为该 Span 的天数，用 en-US 千分位）。
    - 失败处理（R18）：组件记住最后一次成功的 `{ span, view }`。新 Span 取数失败、且之前已有成功的图时，继续画那张图；Span 按钮仍按下新选的那个，控件行加 `cbh.couldNotLoad`（n 为新 Span 的天数），再点一次该 Span 会重试。只有第一次加载就失败，或者当前显示的 Span 自己刷新失败时，才显示 unavailable。后者沿用 Sell side 的约定：当前数据刷新失败时，失败优先于旧数据。
  - **状态**：`span`、`range`、`lo`、`hi`、`zx`、`zy`、`hover`。
    - 换 Span 时清掉 zx，保留 zy。
    - 悬停读数（hover 和 tooltip）在 span、range、lo、hi、zx、zy 或数据（`computed_at`、`latest_day`）变化时一律清掉。
    - 点 Range 时清掉 zy。
    - 双击或点"Reset zoom"时，zx 和 zy 都清掉。
  - **计算**：用 `useMemo` 按顺序算：
    1. `visibleWindow`
    2. `occupiedRows`
    3. `sortedCells`：依赖窗口和行，拖动滑杆时不重新排序。
    4. `contrast`：依赖 lo 和 hi。
  - **布局**：
    - 绘图放在子组件 `CbhPlot` 里：它调用 `useChartWidth()`，高度用 `heightFor(width)`，只在 `occupiedRows` 不为 null（有数据）时才挂载（Global Constraints 的教训）。
    - 边距：left 56（宽度小于 500 时为 44），right 12，top 10，bottom 24。
    - `div.wh-cbh-plot` 用 `position: relative`。
    - 里面放 `canvas.wh-cbh-canvas`：`width` 为天数，`height` 为行数，`data-cols`、`data-rows` 同值；用 px 定位到绘图区，`image-rendering: pixelated`。
    - 上面叠一层 `svg.wh-cbh-svg`，`viewBox="0 0 width height"`、`role="img"`、`tabIndex=0`，`aria-label` 为 `cbh.aria`。
  - **canvas 绘制**：在 `useEffect` 里执行 `getContext("2d")`；为 null 时直接返回。否则依次调用 `createImageData`、`paint`、`putImageData`。
  - **SVG 内容**：
    - y 轴：`ticks(yLo, yHi, 7)`，标签用 `fmtK`。其中 `yLo = floors[r0]`，`yHi = floors[r1] + 500`。
    - x 轴：`dayTicks(first, last, max(2, min(8, floor(plotW / 110))))`，标签用 `dayLabel`；左下角写 `UTC`。
    - 列 i 的中心为 `left + (i + 0.5) × plotW / n`（R13a）。
    - 缺失日按连续段合并成 rect，用斜线 pattern 填充（线条用 `wh-perp-hatch` 的 class），带 `data-missing` 和 `data-days`。pattern 的 id 用 `useId()` 生成，避免与 perp-charts 的 pattern 重名（复核 M9）。
    - forming 列画 `rect.wh-seller-forming[data-forming="true"]`。
    - spot 线画两条 path：`wh-cbh-price-case` 和 `wh-cbh-price`。close 为 null 的地方断开；超出 y 范围时夹到边界（A:4100）。
    - 悬停时画十字线 `wh-seller-cursor`；拖动时画 `rect.wh-cbh-drag`。
  - **指针**：
    - `pointermove` 更新 hover。
    - 鼠标按下左键并移动时进入拖动，松开时调用 `zoomFromDrag`。
    - 触摸点按只读取格子，不做拖框缩放，以免抢走页面滚动。
  - **键盘**：
    - ←/→ 换日，↑/↓ 换行；Home 跳到第一列，End 跳到最后一列；Esc 清掉 hover。这些键都要 `preventDefault()`，否则页面会跟着滚动（复核 M9）。
    - 获得焦点后的初始位置：最后一列，latest close 所在的行。
  - **tooltip**：`div.wh-cbh-tip`，`aria-live="polite"`。
    - 只渲染 `tipParts` 的结果。有数据的日子显示：日期；`cbh.bucket` 加 `bucket`；`cbh.supply` 加 `supply`；`cbh.spot` 加 `spot`。标签走 i18n，数值格式只来自 `tipParts`。forming 的日子再加 `forming`。
    - 缺失的日子：日期，加上 `cbh.pendingDay` 或 `cbh.absentDay`。
  - **控件行**（`wh-ss-controls`）：
    - `Segments` Span：标签用 `cbh.days`（n = 30/90/365）和 `cbh.all`，All 的按钮 `title` 为 `cbh.allTitle`。
    - `Segments` Range：选项为 `All` 和 `±50%`、`±25%`、`±10%`。
    - Contrast：`div.wh-cbh-contrast` 里放两个 `input[type=range]`，`min=0`、`max=100`、`step=1`，`aria-label` 分别为 `cbh.lower` 和 `cbh.upper`，旁边是标签（`contrastLabel ?? cbh.fullRange`）。
    - 缩放备注：未缩放时显示 `cbh.zoomHint`。缩放后显示 `` `${zoomText(zx, zy)} · ${text("cbh.zoomReset")}` ``，并显示"Reset zoom"按钮。
  - **图例**（`wh-cbh-key`）：先是 `cbh.supplyBtc`；`dropped` 时显示 below-floor 色块和 `cbh.belowFloor`；然后是 4 个色块，配 `keyLabels` 的前 4 项；最后是 cap。
  - **状态行**（`wh-seller-meta`）：
    - 依次为 `cbh.meta`（latest_day）、`cbh.coverage`（have、want 取自 `coverage(vis)`，pending、absent、forming 的判断也用它）、`cbh.backfilling`（有 pending 且 `backfill_error` 为 null 时）或 `cbh.paused`（有 pending 且 `backfill_error` 不为 null 时，R21）、`cbh.absentOne` 或 `cbh.absentMany`（有 absent 时）、`cbh.formingNote`（有 forming 时）。
    - 接着是 `rulesNote` 的输出，stale 时的警告，refreshing，以及 `reasons`。
  - **无数据**：`occupiedRows` 返回 null 时，显示 `seller.noData`，不画 plot。
  - **底部**：图注 `cbh.caption`（`wh-ss-foot`）；三栏说明用 `flow-notes.tsx` 的 `<ReadColumns shows="cbh.shows" implies="cbh.implies" how="cbh.how" />`。
  - **`flows-panel.tsx`**：`flow === "costbasis"` 分支现在渲染 `<CostFlowCharts />`。照 `sellside` 分支（`<><SellSideCharts /><AgeCohortChart /></>`）的写法，改成 `<><CostFlowCharts /><CostBasisHistoryChart /></>`。

- [ ] **Step 4：文案**。`i18n.ts` 的 `en` 和 `zh` 各加以下键，原站已有中文的直接用原站的。两边都放在最后一个 `costflow.` 键之后、第一个 `sizes.` 键之前。

| 键 | en | zh |
|---|---|---|
| `cbh.title` | Chart 8 — Cost Basis Distribution, All Coins（A:532） | 图 8 — 全部币的成本价分布（A:880） |
| `cbh.loading` | Loading the cost basis history… | 正在加载成本价分布… |
| `cbh.unavailable` | Cost basis history unavailable | 成本价分布数据不可用 |
| `cbh.span` / `cbh.range` | Span / Range | 时间跨度 / 价格范围（A:888–889） |
| `cbh.days` / `cbh.all` | {{n}}D / All | {{n}}天 / 全部（A:887、894） |
| `cbh.allTitle` | The last 1,461 days (four years), not the whole history | 最近 1,461 天（四年），不是全部历史 |
| `cbh.contrast` / `cbh.fullRange` | Contrast / full range | 对比度 / 全范围（A:885） |
| `cbh.lower` | Lower quantile: cells at or below it draw in the below-floor shade | 下分位：等于或低于它的格子画成"低于下限"的暗色 |
| `cbh.upper` | Upper quantile: cells above it saturate | 上分位：高于它的格子都取最亮一级 |
| `cbh.zoomHint` / `cbh.zoomReset` | drag the chart to zoom / double-click to reset | 拖动图表可缩放 / 双击还原（A:886） |
| `cbh.reset` | Reset zoom | 还原缩放 |
| `cbh.fetching` | loading {{n}} days… | 正在加载 {{n}} 天… |
| `cbh.couldNotLoad` | could not load {{n}} days | {{n}} 天加载失败（"加载失败"取自 A:887） |
| `cbh.supplyBtc` / `cbh.belowFloor` | Supply · BTC / below floor | 供应量 · BTC / 低于下限 |
| `cbh.bucket` / `cbh.supply` / `cbh.spot` / `cbh.forming` | Bucket / Supply / spot / forming | 价格区间 / 供应量 / 现价 / 形成中（前三个取自 A:884–885、944；"形成中"是我们的译文） |
| `cbh.formingNote` | The last column is today's snapshot, still forming | 最后一列是今天的快照，仍在形成 |
| `cbh.pendingDay` | No snapshot stored for this day yet | 这一天的快照还没有存入 |
| `cbh.absentDay` | BRK has no snapshot for this day | BRK 没有这一天的快照 |
| `cbh.meta` | Snapshot {{day}} UTC | 快照日 {{day}}（UTC） |
| `cbh.coverage` | {{have}} of {{want}} days stored | 已存 {{have}} / {{want}} 天 |
| `cbh.backfilling` | the rest is still being fetched; missing days are hatched, not zero | 其余仍在抓取；缺失的日期画斜线，不是 0 |
| `cbh.paused` | history fetch paused: BRK returned {{code}}; retrying next hour | 历史回填暂停：BRK 返回 {{code}}，下一小时重试 |
| `cbh.absentOne` / `cbh.absentMany` | 1 day has no snapshot at BRK / {{n}} days have no snapshot at BRK | BRK 缺 1 天的快照 / BRK 缺 {{n}} 天的快照 |
| `cbh.stale` | Latest snapshot is {{day}}; the data is stale | 最新快照是 {{day}}，数据已过期 |
| `cbh.aria` | Chart 8 heatmap: supply by cost basis, one column per day. Use the arrow keys to read a day and a bucket; Escape leaves. | 图 8 热力图：按成本价分布的供应，每天一列。用方向键读取某一天某个价格区间，Esc 退出。 |
| `cbh.caption` | Supply by $500 cost-basis bucket, one column per day, with spot overlaid. Contrast sets which quantile band of supply the colour ramp is spent on; it rescales the colour, it does not remove supply. Excludes cost basis under $1,000.（A:565 原文） | 按 $500 成本价区间统计的供应量，每天一列，叠加现价。对比度决定颜色梯度用在供应的哪一段分位区间：它只重新分配颜色，不移除供应。不含成本价低于 $1,000 的部分。（我们的译文） |

  三栏说明是初稿，交用户审：
  - **`cbh.shows`**
    - en: "Where the cost basis of every coin sits, day by day. Each column is one day's snapshot of the whole supply, sorted into $500 buckets by the price at which those coins last moved; the brighter the cell, the more BTC in that bucket. The light line is that day's close. Cost basis under $1,000 is left out: millions of very old or lost coins sit there and would take up the whole colour scale."
    - zh: "每天所有币的成本价分布。每一列是某一天全部供应的快照，按币最后一次转移时的价格分进 $500 的价格区间；格子越亮，这个区间里的 BTC 越多。浅色线是当天的收盘价。成本价低于 $1,000 的部分不计入：那里有数百万枚很老或已丢失的币，计入的话会占满整条色阶。"
  - **`cbh.implies`**
    - en: "A bright band that runs across many columns is a price where a lot of supply changed hands and has not moved since. When price comes back to it, those holders are back at break-even: approached from below, the band can act as resistance as some sell to get out even; from above, as support. A band that fades means those coins are being spent again. Dark gaps between bands are prices where little supply was bought. The chart shows where coins last moved, not what their holders will do."
    - zh: "一条亮带如果跨越很多列，说明有大量供应在这个价位换手后一直没动。价格回到这里时，这些持有者回到成本：价格从下方回来，这条带可能成为阻力，因为有人想保本离场；从上方回落，则可能成为支撑。亮带逐渐变暗，说明这些币又被花出去了。亮带之间的暗区是很少有人买入的价位。这张图只说明币最后一次转移的位置，不预测持有者会怎么做。"
  - **`cbh.how`**
    - en: "Span sets how many days are shown, up to today; All is the last 1,461 days, not the whole history. The last column is today's snapshot, still forming, and is outlined. Range zooms the price axis around the latest close. Contrast spreads the four colour steps over the cells between its two handles, as quantiles of the cells on screen: cells at or below the lower handle take the dim below-floor shade, they are not removed, and cells above the upper handle all take the brightest step. The key gives the BTC at which each step starts. Drag a box to zoom; double-click or Reset zoom to undo. Hatched columns are days with no stored snapshot: missing, not empty."
    - zh: "时间跨度决定显示多少天，截至今天；"全部"是最近 1,461 天，不是全部历史。最后一列是今天的快照，仍在形成，用虚线框标出。价格范围以最新收盘价为中心放大价格轴。对比度把四级色阶分配给两个滑块之间的格子，按屏幕上格子的分位数计算：等于或低于下滑块的格子画成暗色的"低于下限"，并没有被删除；高于上滑块的格子都取最亮一级。图例给出每一级起点的 BTC 数。拖出一个框可放大，双击或点"还原缩放"恢复。画斜线的列是没有存到快照的日期：表示缺失，不是空。"

- [ ] **Step 5：样式（`market.css`，追加在文件末尾、图 3/4 的 `wh-cf-*` 块之后）**
  - `.wh-cbh-plot`：`position: relative; min-width: 0`。
  - `.wh-cbh-canvas`：`position: absolute; image-rendering: pixelated; pointer-events: none`。
  - `.wh-cbh-svg`：`position: relative; display: block; width: 100%; touch-action: pan-y`。
  - `.wh-cbh-price-case`：`stroke: #05080d; stroke-width: 3.2; fill: none`。
  - `.wh-cbh-price`：`stroke: #f4f7fb; stroke-width: 1.4; fill: none`。
  - `.wh-cbh-drag`：`fill: rgba(89, 230, 205, 0.08); stroke: var(--wh-cyan); stroke-dasharray: 3 3`。
  - `.wh-cbh-tip`：绝对定位；`max-width: min(260px, 100%)`；背景 `var(--wh-surface)`，边框 `var(--wh-edge)`；数字用 JetBrains Mono。
  - `.wh-cbh-contrast`：两个 range 叠在同一条轨道上，只有滑块响应指针；有清晰的 `:focus-visible` 样式。
  - `.wh-cbh-key`：一行 flex，色块 14×10。
  - 窄屏规则照图 3/4 的做法，放进本节自己的 `@media (max-width: 600px)` 块：控件换行；Contrast 占满一行；按钮最小高度 44px，与 `.wh-seller-span` 一致；页面不能出现横向滚动。

- [ ] **Step 6：运行测试，确认通过**

  运行与 Step 2 相同的命令，再运行 `vitest run src/features/wheelhouse/i18n.test.ts`。Expected: 全部通过，中英键一致。

- [ ] **Step 7：运行 `make check`**

  Expected: 全绿。

- [ ] **Step 8：Commit**

```bash
git add integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse
git commit -m "feat(flows): draw Chart 8 as a canvas heatmap under Cost basis"
```

---

### Task 6：SPEC、清单、回滚说明与验收记录骨架

**Files:**
- Modify: `docs/features/btc-onchain-perp/SPEC.md`
- Modify: `docs/features/btc-onchain-perp/CHART-INVENTORY.md`
- Modify: `docs/deployment/RELEASING.md`（"失败与回滚"一节）
- Create: `docs/features/btc-onchain-perp/SR8-VERIFICATION.md`

**Interfaces:** 不涉及代码。

- [ ] **Step 1：修改 `SPEC.md`**，全部是追加或局部替换：
  - **§1 "不做"**：main 上这一条以"state-report 的图 8。"开头，后面接着各图的纳入记录。删掉开头的"state-report 的图 8。"，在末尾补"图 8 于 <日期> 纳入，规则见 §3.7，做法见 [PLAN-SR8.md](PLAN-SR8.md)。"。删掉后这一条如果只剩纳入记录，就把它挪到 §10 修订记录，"不做"里不留空条目。另记一句备注："onchain-pulse Chart 5（Plotly/log200 改写版）是否复用图 8，留给 Supplementary 计划决定"。
  - **§2**：在"读接口只读本地库"那一条下面补一句：图 8 的 Contrast 分位、Range 和缩放在前端按屏幕上可见的格子计算，服务端只按 Span 切片。另加一句：服务对响应启用 gzip（R20）。
  - **§3.0 的存储表**：加一行 `urpd_history`，字段为 day、close、supplies_json、fetched_at。说明：只存 `all lin500` 已定稿的日快照，覆盖最近 1,461 天，不受 P3-R14 的清理影响。
  - **§3 末尾**，即 §3.6 规模分组之后：新增 `### 3.7 成本价分布（state-report 图 8）`。照 §3.6 的写法，用 6–10 条要点写清以下内容：
    - 数据和网格（R2、R8）；
    - 各天的来源（R3）；
    - 回填的门控与节奏：只在全部阶段成功且取到 D 时、写完本轮状态之后才发请求；每轮 120 个，间隔 0.5 秒，上限 5 分钟；第一个错误或坏快照即停；404 满 24 小时再问；停止与续传（R4、R5）；
    - BRK 升版时不重取，需要时手动删行，worker 会补回（R6）；
    - 派生与接口 `GET /onchain/cost-basis-history?span=`，以及 gzip 和前端超时（R7、R18、R20）；
    - 缺日、forming、低于下限的显示，以及回填暂停的提示（R9–R11、R21）；
    - 原站缺陷的处理（R9–R13a 的一行汇总）；
    - 最坏情况下的请求数，照 §3.6"最坏情况"的写法：
      - 正常回填：每轮 ≤ 120 个，共 1,456 个；补齐后每天 0 个；
      - BRK 对按日请求持续 5xx 或 429、而 URPD 阶段正常：每小时 1 个；
      - BRK 对所有历史日都返回 404：约 13 轮内把 1,456 天都记成 absent，之后每 24 小时再问一遍，约 1,456 个/天（平均约 61 个/小时，每轮都不超过 120 个）；
      - 坏快照：每个日子每天最多 1 个；
      - 任何阶段失败的重试轮：0 个；
      - 每轮最长 5 分钟。
  - **§10 修订记录**：加一条"图 8（2026-10-19）"，指向本计划。

- [ ] **Step 2：修改 `CHART-INVENTORY.md`**
  - 把"图 8"那一行的本地现状改为：`**已做**（<日期>，Flows → Cost basis），见 [PLAN-SR8.md](PLAN-SR8.md)；首次回填约 1,456 个请求，按每轮 120 个约 12–13 小时补齐`。
  - 在"目前本地做了"的计数里加上图 8。

- [ ] **Step 3：修改 `docs/deployment/RELEASING.md`**（复核 I3）。在"失败与回滚"一节、perps 迁移 003 那段之后，照它的写法追加一段：

  > **onchain 迁移 002（SR-8）同样如此。** 它新增 `urpd_history` 表，不改已有的表。应用之后，SR-8 之前的镜像（onchain 迁移最高到 001）打开 `onchain.sqlite` 时，会以 "On-chain database is newer than this application" 拒绝启动；onchain router 在 lifespan 里建库，所以整个 analytics 服务都起不来。发布前按第 3 步备份 `onchain.sqlite`，这份备份必须在迁移 002 之前取得，并已验证能恢复。回滚只能二选一：先停写，用这份备份恢复 `onchain.sqlite`，再回滚镜像；或者保持前进，修复后再发布。只回滚镜像不会让服务恢复。

- [ ] **Step 4：新建 `SR8-VERIFICATION.md` 骨架**。各节标题和要填的表头如下，内容留给 Task 7 填写：
  1. **环境**：commit、抓取时间，以及两处的规则：本地 `WHEELHOUSE_RULES=v1`；test 环境没有设置，默认全部开启（复核 M12）。
  2. **回填**：
     - 表头：轮次、开始时间、本轮请求数、404 数、失败码、历史表行数、用时。
     - 另记：365D 和 All 分别在第几轮补齐；`urpd_history` 和 `derived.costbasis_history` 的大小；`?span=365` 和 `?span=all` 的响应体积（未压缩 / gzip）；重启续传的证据，即重启后第一轮请求的第一天，以及重启后没有立刻再跑一轮。
  3. **历史不全时的显示**：在第 1 轮后检查，记录覆盖度文字、斜线列、forming 框，附 30D、365D、All 的截图。
  4. **与原站对照**：同一时刻、两边都排除 forming 列。
     - 表头：设置、原站 floor/cap、本地 floor/cap、差。
     - 要比的设置：365D All 75–95，30D，90D，以及 365D 下的 ±50%、±25%、±10%。
     - 另记：4 个已定稿日期的探针格（$60k、$74k、$82k、$100k）；包含 forming 列的默认读数，即标签、图例、y 轴范围、x 刻度；对照输入存档的 fixture 目录名。
  5. **1440px 和 390px**：横向溢出、控件换行、刻度字号、tooltip 是否越界、三种暗色能否分清。
  6. **控制台与键盘**。
  7. **未解决**。

- [ ] **Step 5：运行 `make check`**

  Expected: 全绿。文档改动不影响检查，这一步只是确认没有误碰代码。

- [ ] **Step 6：Commit**

```bash
git add docs/features/btc-onchain-perp/SPEC.md docs/features/btc-onchain-perp/CHART-INVENTORY.md \
  docs/features/btc-onchain-perp/SR8-VERIFICATION.md docs/deployment/RELEASING.md
git commit -m "docs(onchain): record Chart 8 in the spec, inventory and rollback notes"
```

---

### Task 7（controller 执行，不派子代理）：浏览器验收与对照存档

- [ ] **准备环境**：用 `WHEELHOUSE_RULES=v1` 启动 analytics，再用 `python3 scripts/foundation.py overlay` 启动前端。记录每一轮的 `onchain_urpd_history` 日志，以及 `SELECT COUNT(*) FROM urpd_history`。
- [ ] **第 1 轮后**：打开 `?method=flows&flow=costbasis`，检查"历史不全"时的显示：覆盖度、斜线、forming 框、30D 和 All。截图。
- [ ] **重启一次服务**：确认重启后不会立刻再跑一轮（`next_due` 已经写好），并且下一轮第一个请求的是最新的那个缺口。
- [ ] **第 3 轮后（365D 已补齐）**，与原站在同一时刻对照：
  - 原站：在 SR-8-A §4.1 片段 1 的基础上，把 `S.dates` 中的 NOW 去掉后，重新计算各设置下的 n、r0、r1、floor 和 cap，再记下 4 个已定稿日期的探针格。
  - 本地：取 `GET ?span=365` 的 JSON，去掉最后一列，用 `tests/onchain/cbh_reference.py` 计算同样的量。
  - 对 365D、30D、90D 和三档 Range 逐项比较。floor 和 cap 的差应 ≤ 0.05 BTC：原站存的是 Float32，我们存的是 2 位小数。4 个探针格的差应 ≤ 0.035 BTC。
  - 原站上**不要点 All**，否则会多发 1,096 个请求（SR-8-A §4.1）。
- [ ] **把对照输入存档成 fixture**（待确认第 4 条，复核 M3）：新建 `services/analytics/tests/onchain/fixtures/sr8-acceptance-<YYYY-MM-DD>/`，放入：
  - `original-readings.json`：原站各设置的读数（日期首尾、n、r0、r1、floor、cap），以及 4 个探针格；
  - `local-span365.json.gz`：同一时刻本地 `?span=365` 的原始响应，约 0.39 MB；
  - `reference-output.json`：`cbh_reference` 在去掉最后一列的本地数据上的输出；
  - `README.md`：抓取时间（UTC）、原站 URL、本地 commit、BRK `/version`、规则设置，以及每个文件是怎么得到的。

  然后在 `test_onchain_costbasis_history.py` 加 `test_sr8_acceptance_readings`：
  - 从 `local-span365.json.gz` 去掉最后一列后重算，结果应等于 `reference-output.json`；
  - 本地与原站 floor、cap 的差 ≤ 0.05；探针格的差 ≤ 0.035。
- [ ] **压缩经过代理**：在浏览器的网络面板确认，经 Wealthfolio host 代理（:1420）拿到的 `?span=all` 响应带 `content-encoding: gzip`，并且 30 秒内完成。
- [ ] **1440px 和 390px**：390px 用弹窗法检查。
  - 确认无横向溢出（`scrollWidth ≤ innerWidth`），Cost basis 切换条正常换行，刻度字号 ≥ 10px，tooltip 不越出视口，键盘可以读格子，控制台零报错。
  - 在 390px 下实看三种暗色能否分清：空格（面板底色 `#101722`）、below floor（`#233142`）和最暗一级（`#164a52`）。它们之间的对比只有约 1.35:1（1.36:1 和 1.34:1），见 R11、R14、复核 M6。分不清时，把 below-floor 换成色相更远的颜色，并在 R14 和 SPEC 里记下新的对比度。
- [ ] **收尾**：把以上结果填进 `SR8-VERIFICATION.md`，然后 commit 两次：先 `test(onchain): keep the Chart 8 acceptance readings`，再 `docs(onchain): record the Chart 8 acceptance`。

---

## 不做

- O1–O6 在这张图上的版本。
- `/status` 新增历史数据集。
- 原站超过 1,880 列时取平均。
- 真正的"全部历史"（2009 年起）。
- onchain-pulse Chart 5：是否复用本图，留给 Supplementary 计划决定，本计划只记一笔（待确认第 5 条）。
- Analyst Take、`.read` 人工解读块。
- 因 BRK 升版而自动重取历史。

## 复核修订记录（2026-10-19）

依据 `.superpowers/sdd/state-report/review-PLAN-SR8.md`（READY_AFTER_FIXES：Critical 0，Important 5，Minor 16）和 controller 的裁定。全部采纳，没有驳回。

| ID | 处理 |
|---|---|
| I1 | 门控改为 `urpd is not None and not errors`；请求挪到成功路径写完状态之后；每轮上限 5 分钟；加参数化的重试轮测试（hour1、age、size）、没取到 D 的测试和"状态先写"的测试（R4、Task 2） |
| I2 | URPD 阶段失败的测试改在非空库上进行，去掉门控就会失败（Task 2） |
| I3 | 加"只有 001 的库升级"测试（Task 1）；RELEASING.md 加回滚说明（Task 6）；迁移名和依赖写进 R1 和 Global Constraints |
| I4 | 若还没有就加 `GZipMiddleware`，并测试 `content-encoding`（R20、Task 3）；All 超时 30 秒、其余 15 秒；新 Span 取数失败时保留旧图（R18、Task 5）。原待确认第 6 条撤回 |
| I5 | 回填和派生各用一个 `try`；坏快照记 `brk_bad_snapshot`、不入库、不清图 8；`history_row` 遇到空数据返回 `[]`（R4、Task 1–2） |
| M1 | `dayTicks` 年刻度改用 d3 的 `tickStep`；补 count 为 3 和 4 的测试 |
| M2 | Task 3 修改 `test_capability_and_get_only_schema` |
| M3 | 参考实现作为 `cbh_reference.py` 入库；加样本相等测试和期望值复算测试 |
| M4 | 新增 R13a：x 方向统一按列带映射 |
| M5 | 只读测试直接用 `create_router` 和自己的 `blocked_client` |
| M6 | R14 记下对比度；T7 在 390px 下实看；R11 已由用户在 2026-10-19 定为加这一级暗色 |
| M7 | 改写停止耗时的说法 |
| M8 | 改名为 `CBH_SPANS`、`fmtSupply` |
| M9 | 方向键等 `preventDefault`；pattern 的 id 用 `useId()` |
| M10 | 待确认第 7 条，引用 PLAN-SELL-SIDE:12 作先例 |
| M11 | 待确认第 5 条改为只记一笔，留给 Supplementary 计划 |
| M12 | R3 写明"4 天"只适用于 v1；SR8-VERIFICATION 同时记录本地和 test 的规则 |
| M13 | 阶段 A 样本的 README 写 "version not recorded" |
| M14 | 测试辅助改用关键字参数 |
| M15 | 定义 `spanDays` |
| M16 | 新增 R21：`history_error` 和 `backfill_error`，界面提示回填暂停 |

**之后的变更（2026-10-19）**：
- 用户决定 R11 加暗色一级。
- PLAN-SR2 取消：图 2 改由 PLAN-AGE-COHORTS 实现，相关名字改为 `AGE_ONLY` 和 `age_error`，重试轮测试改用本地的 `failing_hour1` 包装函数。
- SR-3/4 改为方案 C。
- 执行分支改为合并后从 main 新开。
- 迁移编号对照主检出工作树重新核对，仍为 002。
- 2026-10-20 按 main 1023827 重新定位：
  - 插入点改为 `_derive_sizes` 之后；门控写明 `errors` 收集的四个阶段；重试轮测试改用现有的 `failing_for`。
  - 图 8 接在 `CostFlowCharts` 后面（照 `sellside` 分支的 fragment 写法），复用 `ReadColumns`、`sell-side.ts` 的 `heightFor`，i18n 放在 `costflow.` 和 `sizes.` 之间，CSS 追加在 `wh-cf-*` 之后。
  - SPEC 新节定为 §3.7，写最坏情况请求数；迁移仍为 002；GZip 由本计划新加。
  - 把两份已执行计划的教训写进 Global Constraints，并新增导出纯函数 `tipParts`、`zoomText`、`coverage`，补上不计算测试的 `hasattr` 和 `boom` 写法，以及读数清除测试。
  - 坏快照改为记成 absent 行，避免一份坏快照永远挡住更早的日子。
  - 文件开头加"给用户审阅的要点"。
