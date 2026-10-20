# 计划：state-report 图 5 / 图 6（Size cohorts）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Flows 新增子视图 Size cohorts（`flow=sizes`），照原站做出图 5「Net Supply Change By Size Cohorts」和图 6「Net Realized Profit & Loss By Size Cohorts」。

**Architecture:** worker 新增一个独立的 hour1 阶段，取 12 个地址规模档 × 4 条 BRK 序列（共 48 条），照原站 loader（`raw/script_3_app.js:323-339`）算出每档的当前量和 4 个窗口的差分，存进 derived `"sizes"`；新只读接口 `GET /onchain/size-cohorts` 原样读出。分组折叠、百分比、图例合计、坐标轴和格式化照原站图表代码（`raw/script_2_app.js:1993-2397`）放在前端纯函数里，两张图共用一个横向发散条形组件。

**Tech Stack:** Python 3 / FastAPI / pydantic / SQLite（`services/analytics`）；React + TypeScript + zod + TanStack Query + vitest（Wealthfolio overlay）；手写 SVG，不引图表库。

**Spec:** [SPEC.md](SPEC.md)（「架构」「界面（已用可视化伴侣逐屏确认）」两节）；规划 brief `.superpowers/sdd/state-report/planning-brief.md`；[CHART-VERIFICATION.md](CHART-VERIFICATION.md) 的 SR-5、SR-6（`:206-226`）与跨图共性第 2、10 条（`:68-85`）；阶段 A/B 研究 `.local/research-samples/alpha-dashboards-2026-10-16/verification-2026-10-19/verify/{SR-5,SR-5-A,SR-6,SR-6-A}.md`、样本 `verify/sr5/`、`sr6/`；源码笔记 `state-report/NOTES.md:175-201`。下文研究路径都以 `.local/research-samples/alpha-dashboards-2026-10-16/` 为根，`L` 指 `state-report/raw/script_3_app.js`，`A` 指 `state-report/raw/script_2_app.js`。

日期：2026-10-19，2026-10-20 改锚。按独立复核 `.superpowers/sdd/state-report/review-PLAN-SR5-6.md`（READY_AFTER_FIXES）修订后，PLAN-SR2 已取消，改为建立在用户选定的图 2 实现上。

**在哪里执行：** 等图 2 和 PLAN-SR3-4 都合并到 `main` 之后，从 `main` 新开分支执行本计划；**绝不在 `claude/state-report` 上执行**。图 2 目前是仓库 `/Users/gary/code/AlgoForceNext` 分支 `claude/age-cohorts` 上的提交 `d6572aa`（其计划为 `PLAN-AGE-COHORTS.md`），合并前还可能改动，所以 Task 1 第一步先在 `main` 上逐个核对下面用到的符号；缺任何一个就停下报告，**不要自己补建**。

本计划消费的符号（只认名字，不引用行号；常量的取值只在下文说明里出现，代码和测试里不写死）：
- 图 2（`d6572aa`）：`brk.py` 的 `MAX_SERIES_CHARS`（该提交为 2,000）、`_chunks`、`AGE_SERIES`（138 条）与 `AGE_ONLY_SERIES`（其中 126 条）；`sync.py` 的 `VIEWS`（含 `"agecohorts"`）、独立的币龄阶段（`age_missing`、`age_error`，失败分支 `self._stored_hour1_missing() - set(AGE_ONLY_SERIES)`，之后 `hour1_missing |= age_missing`）、`_derive_age_cohorts`；`test_onchain_sync.py` 的本地助手 `failing_for(names, **options)` 与 `bulk_names(request)`；前端 `sell-side-charts.tsx` 已导出 `Segments`（`heightFor` 仍未导出）。它没有改 `http.py`，也没有新 migration。
- PLAN-SR3-4：Cost basis 子视图（`flow=costbasis`）、视图 `costflow`、`.wh-flows-switch` 的 `flex-wrap`。

改到它们也改过的文件时，按符号名定位，改动都是追加。

---

## 已定的做法

前 7 条是 brief 里已定的裁定（不再讨论），后面是本计划的决定。

| 事项 | 做法 | 理由 / 依据 |
|---|---|---|
| 位置（已定 1） | Flows 子视图顺序：Seller pressure（`seller`，默认）· Sell side（`sellside`）· Cost basis（`costbasis`）· **Size cohorts（`sizes`）** · Perp states（`perp`）。本计划只加 `sizes`，图 5 在上、图 6 在下。390px 下切换按钮换行，不横向溢出 | brief 裁定 1 |
| 规则（已定 2） | 只有 v1：照原站算（SPEC D5），`rules` 恒为空；`rules.py` 的 `IMPLEMENTED["sizes"]` 为空集。原站缺陷照下面「缺失值」一行处理 | brief 裁定 2 |
| 三栏说明（已定 3） | 原站两张图只有一行 caption（A:480、A:526），没有三栏。按 Flows 约定写 What it shows / What extreme values imply / How to read 的中英初稿（Task 5 表格），交用户审；原 caption 的内容并进三栏，不另显示 caption | brief 裁定 3；与 Sell side 做法一致 |
| 数据契约（已定 4） | worker 取 BRK 并预算；读接口只读库；缺失或过期显示为缺失，不当 0；forming 标出；运行时不用任何样例数据 | brief 裁定 4、SPEC「架构」 |
| 测试（已定 5） | 测试不联网；黄金样本来自已存 BRK 数据或阶段 A 样本，配 README；阶段 A 记录过的读数逐格断言；每个任务最后 `make check` 全绿，后端模型改动后跑 `make contract` | brief 裁定 5 |
| 语言（已定 6） | 计划中文；代码、标识符、注释、commit 英文（conventional commits）；界面文案走 `i18n.ts`，en/zh 一一对应 | brief 裁定 6、AGENTS.md |
| 界面（已定 7） | 复用 `seller-charts.tsx`（`useChartWidth`）和 `sell-side-charts.tsx`（`Segments` 图 2 已导出；`heightFor` 由本计划 Task 4 加 `export`）；图高随宽度 300–440px；1440/390 浏览器核验由 controller 做（Task 7） | brief 裁定 7 |
| 一个阶段、一个接口、一个组件 | 48 条序列一个 sync 阶段，一个 derived `"sizes"`，一个接口 `/onchain/size-cohorts`，一个发散条形组件 `DivergingBars` 给两张图用 | 阶段 A 建议（SR-5-A §3.8、SR-6-A §3.5） |
| 独立 sync 阶段 | 48 条序列**不并进** `HOUR1_SERIES` 那次增量请求，在图 2 的币龄阶段（`AGE_ONLY_SERIES`）之后、URPD 之前单独 `_increment`，自带 try/except 和缺失集合：它失败只影响 sizes，卖压、Sell side、图 2、URPD 照常；它的错误照 hour1、币龄、URPD 阶段的做法计入本轮 `last_error` 并 5 分钟后重试。写法都照图 2 已有的形式**追加**：hour1 失败分支改为 `self._stored_hour1_missing() - set(AGE_ONLY_SERIES) - set(SIZE_SERIES)`；size 阶段之后 `hour1_missing |= size_missing`；`absent_hour1` 遍历的元组末尾加 `*SIZE_SERIES`；`errors` 加 `size_error`；`_refresh` 里在 `_derive_age_cohorts(...)` 之后调用 `_derive_sizes`，`derive_from_store` 末尾在 `_derive_age_cohorts` 那次调用之后再调一次。sizes 不读其他阶段的序列，所以按自己阶段的完成时间 `size_done` 盖戳 | SR-5-A §3.4、SR-6-A §3.3、CHART-VERIFICATION `:68-70`；复核 M-3 |
| 门控 | 48 条中任一条本轮缺失（BRK 不认识），两张图都不派生（接口 `unavailable`，reasons 写明缺哪条），与 Sell side 的门控一致；`/status` 不改，hour1 数据集仍只说卖压 | PLAN-SELL-SIDE 后端第 3、5 条 |
| 计算分层 | 后端只做原站 loader 那段：每档 `supply`、`realized_cap` 取 SE 时的值，4 个窗口的 `supply_change`、`profit`、`loss` 取 `v[SE] − v[SE−n]`；Entities 折叠、%、图例、刻度、格式在前端 | 与 PLAN-SELL-SIDE「计算分层」相同；L:323-339 / A:2048-2062、2216-2244 |
| SE（读数时点） | 48 条序列都有行的最新小时（原站 `SE = sts.length−1`，L:324，假定序列对齐）；它通常是正在形成的小时，照 seller/sell side 标 forming | L:324；SR-5.md:5-8 |
| 窗口 | 1d/7d/30d/90d = 24/168/720/2160 个**时钟小时**（BRK hour1 每小时一行，无块小时也占位，按行即按时间）；读库深度 2250 行，同原站 `start=-2250` | L:125-131、L:325；SR-5-A.md:54、SR-6-A.md:75 |
| 取整 | `supply`、`supply_change` 照 `+x.toFixed(2)`：对浮点的精确值做 0.01 的半数远离零（`Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)`）；`profit`、`loss`、`realized_cap` 照 JS `Math.round`：`math.floor(x + 0.5)`，**不用** Python `round()`（银行家舍入会让 88.5 → 88、2425253218.5 → …218，原站是 89、…219） | L:332-336；SR-6.md:43-45 |
| 缺失值（原站缺陷的裁定） | 原站 `a[SE]−a[SE−n]` 在 JS 里把 null 当 0（L:332-333）：参考小时没出块时，Δ 变成整条累计量（图 5 约 +5.27M BTC、图 6 约 +$558.8B 的假柱）。**本地裁定：任一端点为 null 或库里没有这一行，该格为 null，界面显示 "—"、不画柱**；Entities 下组内任一成员为 null，整组为 null；图例所在视图有任一行为 null，图例三项都显示 "—"（不静默少算）；%（分母 supply 或 realized_cap 为 null 或 ≤ 0）为 "—"（原站柱和标签给 0，A:2058、A:2233）；图 6 读数的 `vs realized cap` 在 realized_cap ≤ 0 时也是 "—"（**有意偏离**：原站写 `n/a`，A:2366-2367；本地统一用 "—" 表示缺失）。向前沿用上一小时（精确、但属 O3 语义）不在 v1 做。**锚点小时无块**（48 条在该小时都有行且全为 null）时，worker 在载荷的 `no_block` 里记下这个窗口，界面在图下显示专门说明 `sizes.noBlock`，不显示通用的「此图暂无数据」 | brief 裁定 2；SR-5-A.md:152-157、SR-6-A.md:158-164；复核 M-1、M-5 |
| 零值 | 真实的 0 照原站显示：`+0`、`+$0`，0 值柱照画 0.8px 细线（A:2085、A:2286）；格式化函数照原站逐字移植，所以 `Loss booked +$0`（`usd(-0)`）也照原样 | SR-6.md:28、55；可与线上读数逐字对照 |
| 悬停读数 | 原站浮动 tooltip（A:2137-2157、A:2350-2380）改为图下一行读数：悬停某一行、或聚焦图后用上下方向键选中，显示 tooltip 的全部内容；未选中时显示操作提示。不做浮窗 | 与本地 Flows 其他图一致，并满足键盘焦点要求（SR-6-A.md:191） |
| 配色 | 正值/盈利用本地 moss `#7fc98a`，负值/亏损用本地 rust `#e0805c`（`.wh-perp` 已有的色值，在新容器里重新声明，不改 `.wh-perp`）；图 6 的净额竖线和两张图的 Net 图例色块都用浅色墨 `#e5edf6`（原站 net-tick 用 `--ink`，Net 图例用 `--pine-deep`，两者本来就不同色）。图 6 这样做让图例对上竖线；图 5 没有竖线，只是为了两张图的 Net 同色 | 语义同原站（state-report.html:56-58、282-283、360）；色值沿用本地主题；复核 M-11 |
| forming 文案 | 沿用 seller、Sell side 的判定：有 `forming_at` 就写 "includes the forming hour"，delayed/stale 时改写 "last hour was partial when computed"。HH:00–HH:12 之间那一小时其实已结束、页头仍写 forming，这个已知瑕疵与卖压、Sell side 共有（CHART-VERIFICATION 跨图第 9 条），记入 SPEC 遗留问题，**不在本计划单独修**：只改一处会让三处说法不一致 | 复核 M-6（只做记录部分） |
| Task 5 不拆 | 复核建议可拆成 5a/5b。**不拆**：组件用到的全部文案键要先在 `i18n.ts` 里才能过 type-check，拆开后第二块只剩 flows 接线和两处测试；执行时给 Task 5 预留更多评审轮次 | 复核 M-12（拒绝拆分的理由） |
| 窄屏 | 不照原站整体等比缩小（390px 下字只有 4–6px，SR-5.md:65-69）。容器宽 < 560px 时改排版：行标签放到每根条上方，左右边距 56/64，图高按行数 300–440；绘图区 < 480px 时 x 轴刻度从 `ticks(7)` 改为 `ticks(3)`；两侧小字改成图下 HTML 一行，可换行 | SR-6.md 修复建议 4；brief 裁定 7 |
| 中文 | 图内由 JS 生成的文字（档名、组名与副标题、图例、两侧小字、读数）全部翻译；原站这些不走 `t()`（SR-5.md:80、SR-6-A.md:28），属于有意改进。原站已有的中文直接沿用（A:877-878、892、895、928-931、939、948、953） | brief 裁定 6 |

## 开放点（附建议裁定；计划按建议执行，用户可在审阅时改）

| # | 问题 | 建议裁定 |
|---|---|---|
| OP-1 | 锚点落在无块小时时，v1 让该窗口整列为 "—"（按空块率估算，每小时约 1–2% 的概率有某个窗口整列为空；默认 7d 约每 230 小时一次，每次通常 1 小时；最新的小时还没出块时，再多 1 小时） | 照本计划显示 "—"，并在图下用 `sizes.noBlock` 说明原因、通常一两个小时内补上（终审 M2）。若用户嫌空白，可另立 O3 版本（向前沿用上一小时，供应和累计量在无块小时确实不变，结果精确），本计划不做 |
| OP-2 | 原站有浮动 tooltip | 改为图下读数行（见上表），不做浮窗 |
| OP-3 | Net 图例色块用墨色而不是原站的 pine-deep 棕 | 两张图都用墨色：图 6 与净额竖线一致；图 5 没有竖线，只为两图同色 |
| OP-4 | 三栏说明是我们起草的（原站没有） | 用 Task 5 的初稿，交用户审定后再改字 |
| OP-5 | 48 条中缺一条就让两张图都 unavailable，还是按图分开 | 两张图一起 unavailable（实现简单，与 Sell side 一致；阶段 A 已确认 48 条全部存在） |
| OP-6 | 研究里对 null 的建议不一致：SR-5-A 建议 v1 显示 "—"、O3 才沿用；SR-6-A 建议 v1 就沿用 | 按 brief「只做 v1、缺失显示 '—'」取 SR-5-A 的方案 |

研究里**没有阻塞**的问题。两点需要知道：

- 阶段 A 只存了原站的派生读数（`SIZE`、`PNL`），没有存 06:00 那根正在形成的小时的原始序列值（之后它已收盘、数值变了，无法再取）。所以「与原站逐格一致」用**由原站读数反推的锚点**来断言（Task 1，README 写明做法）。真实 BRK 数据的整条链路另用一份 2026-10-16 窗口的新抓取来测（Task 2）：期望表按阶段 A 复算脚本的算法离线算出、写死，并有一条锚点落在真实空块小时的用例。这份抓取本地还没有（阶段 A 只存了 3 条序列），所以期望表在 Task 2 抓完 fixture 后离线算出，写计划时还列不出数值。
- 48 个序列名用逗号拼起来是 2,003 个字符，大于 `MAX_SERIES_CHARS`，所以每小时增量由 `_chunks` 按顺序贪心拆开：上限为 2,000（`d6572aa` 的取值）时拆成 **2 次**（47 + 1 个名字，1,970 + 32 字符）；若合并前改成 1,800，也是 **2 次**（42 + 6 个，1,761 + 241 字符）。首次回填按点数分片（`MAX_POINTS 18000 // 3000 = 6` 条一片，共 8 次，每片最长 273 字符），两种上限下都一样。Task 2 有测试守住这两个请求数，断言只写 `<= MAX_SERIES_CHARS`，不写数值。

## Global Constraints

- 与用户沟通、计划、spec 用中文；代码、标识符、注释、commit message 用英文，conventional commits（`feat(onchain): …`、`feat(wheelhouse): …`、`docs(onchain): …`），末尾加当前会话要求的 `Co-Authored-By` 行。
- 只做 v1：`rules_for_view("sizes", …)` 恒为 `[]`，不实现 O1–O6。
- 读接口只读本地库：处理请求时不访问 BRK，只读 worker 存好的 derived 结果，不现算。
- 缺失或过期显示为缺失（"—"、unavailable、delayed/stale 提示），绝不显示成 0；正在形成的小时标 forming。
- 运行时不用样例、mock 或 fake 数据兜底；样例 JSON 只在测试里用。
- 测试不联网。fixture 的一次性抓取在实现时手动做，测试只读文件。
- BRK bulk 请求的 `series` 参数（解码后的逗号拼接）每次 ≤ `MAX_SERIES_CHARS`（图 2 定义在 `brk.py`）；本计划不改分片逻辑，也不写死这个上限的数值。
- 改到图 2、PLAN-SR3-4 也改过的文件，按符号名定位，只追加，不改它们的写法。
- 制造请求失败用 `test_onchain_sync.py` 里图 2 已有的本地助手 `failing_for(names, **options)`；不给共享的 `brk_transport` 加开关。
- 文案全部走 `i18n.ts`，en/zh 键一一对应（`i18n.test.ts` 已检查）。
- 金融数值用 JetBrains Mono；键盘焦点可见；图高 300–440px。
- 每个任务的最后一步：在 worktree 根目录跑 `make check`，全绿后提交。后端模型改动后先跑 `make contract`。
- 后端单测命令：在 `services/analytics` 下 `../../.venv-foundation/bin/python -m pytest <file> -q`。前端单测：先在仓库根 `make sync`，再在 `.local/wealthfolio` 下 `pnpm --filter frontend exec vitest run src/features/wheelhouse/<file>`。

## Review Focus

1. **锚点落在无块小时**（所有序列在 SE−n 为 null）：该窗口每一行都是 "—"、不画柱、图例为 "—"，图下说明是无块所致，绝不能出现整条累计量那样的巨柱。测试：Task 1 `test_a_no_block_anchor_leaves_that_window_missing`、Task 2 `test_a_real_no_block_anchor_blanks_only_that_window`（真实空块小时 155634）、Task 4 `null anchor` 用例、Task 5 `explains a window whose anchor hour had no block`。
2. **size 阶段失败或请求超长**：卖压、Sell side、图 2、Cost basis 照常更新；sizes 保留上一轮结果并随时间变 delayed/stale；缺失记录不在阶段之间残留。测试：Task 2 `test_size_stage_failure_keeps_every_other_view`、`test_size_requests_stay_under_the_url_limit`、`test_stored_size_missing_survives_a_failed_size_stage`、`test_a_successful_size_stage_clears_its_old_missing_entries_even_when_hour1_fails`。
3. **Entities 下有成员缺失**：整组 "—"，图例 "—"，不能把缺失成员当 0 静默少算。测试：Task 4 `folds a group with a missing member to null`。
4. **390px 窄屏**：5 个子视图按钮换行（PLAN-SR3-4 的 `flex-wrap`）、无横向溢出；行标签不压在条上；切换口径后选中行不越界；刻度不重叠。测试：Task 4 `layout` 用例、Task 5 `clears the reading when a control changes`；图表 CSS 在 Task 5；实测在 Task 7。
5. **worker 停了几个小时**：forming 提示从 "includes the forming hour" 变为 "last hour was partial when computed"，并出现 delayed/stale 横幅，条形仍照画。测试：Task 3 `test_size_cohorts_freshness_and_forming`、Task 5 `warns when the data is delayed`。

---

## 文件结构

**后端（`services/analytics/`）**

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/wheelhouse_service/onchain/brk.py` | 改（追加） | `SIZE_BANDS`、`SIZE_SUFFIXES`、`SIZE_SERIES` |
| `src/wheelhouse_service/onchain/sizes.py` | 新建 | 纯计算 `size_cohorts()` 与存储模型 |
| `src/wheelhouse_service/onchain/sync.py` | 改（追加） | 独立 size 阶段、`_derive_sizes`、`VIEWS` |
| `src/wheelhouse_service/rules.py` | 改（追加） | `View` 加 `"sizes"` |
| `src/wheelhouse_service/onchain/models.py` | 改（追加） | `SizeCohortsView` |
| `src/wheelhouse_service/onchain/api.py` | 改（追加） | `SIZE_REASONS`、`GET /size-cohorts` |
| `tests/onchain/sizes_fixture.py` | 新建 | 由原站读数反推的黄金行 |
| `tests/onchain/fixtures/sr5-6-page-2026-10-19T0600Z/` | 新建 | 原站 `SIZE`、`PNL` 读数副本 + README |
| `tests/onchain/fixtures/brk-2026-10-16/hour1_addrs_*.json` | 新建 48 个 | 假 BRK 回放用的真实序列；README 追加一节 |
| `tests/onchain/fixtures/brk-2026-10-16/sizes-expected.json` | 新建 | 按阶段 A 复算算法离线算出的 168 格期望表 |
| `tests/onchain/test_onchain_sizes.py` | 新建 | 纯函数测试 |
| `tests/onchain/test_onchain_sync.py`、`test_onchain_api.py`、`test_onchain_rules.py` | 改（追加） | 阶段、接口、derive 输出 |

**契约**：`integrations/wealthfolio/openapi.json`、`…/wheelhouse/api-schema.d.ts`（`make contract` 生成）。

**前端（`integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/`）**

| 文件 | 动作 | 职责 |
|---|---|---|
| `onchain-contract.ts` | 改（追加） | 类型、`SIZE_BAND_KEYS`、`SIZE_WINDOWS`、`sizeCohortsSchema` |
| `client.ts` | 改（追加） | `getSizeCohorts` |
| `size-cohorts.ts` | 新建 | 折叠、取值、刻度、版式、格式、图例、读数（纯函数） |
| `size-cohorts-sample.json` | 新建（Task 3 生成） | 接口对黄金库的完整响应 |
| `size-cohorts-expected.json` | 新建 | 阶段 A/B 记录的原站读数 |
| `size-cohorts-charts.tsx` | 新建 | `SizeCohortsCharts`、`DivergingBars`、两块面板 |
| `sell-side.ts`、`sell-side-charts.tsx` | 改（给 `grouped`、`heightFor` 加 `export`） | 复用 `grouped`、`ticks`、`heightFor`；`Segments` 图 2 已导出，直接导入 |
| `flows-panel.tsx`、`i18n.ts`、`market.css` | 改（追加） | 子视图、文案、样式 |
| 对应 `*.test.ts(x)`、`market-defaults.test.tsx` | 新建/改 | 测试 |

**文档**：`SPEC.md`、`CHART-INVENTORY.md`（改）；`SR5-6-VERIFICATION.md`（新建骨架）。

---

### Task 1: 后端纯计算 `size_cohorts` 与原站黄金样本

**Files:**
- Modify: `services/analytics/src/wheelhouse_service/onchain/brk.py`（在图 2 的 `AGE_ONLY_SERIES` 之后追加）
- Create: `services/analytics/src/wheelhouse_service/onchain/sizes.py`
- Create: `services/analytics/tests/onchain/fixtures/sr5-6-page-2026-10-19T0600Z/page_size.json`、`page_pnl.json`、`README.md`
- Create: `services/analytics/tests/onchain/sizes_fixture.py`
- Test: `services/analytics/tests/onchain/test_onchain_sizes.py`

**Interfaces:**
- Consumes: `..market.Model`、`..rules.Rule`。
- Produces（后续任务按这些名字用）：

```python
# brk.py — the 12 wallet-size bands, smallest first (L:48-54), and their 48 hour1 series.
SIZE_BANDS: tuple[str, ...]  # "addrs_under_1k_sats", …, "addrs_over_100k_btc"
SIZE_SUFFIXES = ("_supply", "_realized_profit_cumulative", "_realized_loss_cumulative", "_realized_cap")
SIZE_SERIES: tuple[str, ...]  # band-major: for band in SIZE_BANDS for suffix in SIZE_SUFFIXES

# sizes.py
WindowKey = Literal["1d", "7d", "30d", "90d"]
WINDOWS: tuple[tuple[WindowKey, int], ...] = (("1d", 24), ("7d", 168), ("30d", 720), ("90d", 2160))
DEPTH = 2250  # rows read per series: the original's start=-2250 (L:125-131)

class SizeWindow(Model):
    window: WindowKey
    supply_change: float | None  # BTC, to 0.01 like toFixed(2)
    profit: int | None           # whole dollars like Math.round
    loss: int | None

class SizeBand(Model):
    band: str                    # a SIZE_BANDS prefix
    supply: float | None         # BTC at last_at, to 0.01
    realized_cap: int | None     # USD at last_at, whole dollars
    windows: list[SizeWindow]    # in WINDOWS order

class SizeCohorts(Model):
    last_at: AwareDatetime
    bands: list[SizeBand]        # in SIZE_BANDS order
    # Windows whose anchor hour (last_at - hours) had no block: every one of the 48 series has a
    # row there and all of them are null. Their cells are None; the page says why.
    no_block: list[WindowKey]
    rules: list[Rule] = []

def size_cohorts(rows: dict[str, list[tuple[datetime, float | None]]]) -> SizeCohorts | None

# tests/onchain/sizes_fixture.py
SE: datetime  # 2026-10-19T06:00Z, position 156006, the hour the page read (forming)
def page_size() -> list[dict[str, Any]]   # the page's SIZE bands
def page_pnl() -> list[list[int]]         # the page's PNL rows: [rcap, 1d p, 1d l, 7d p, 7d l, 30d p, 30d l, 90d p, 90d l]
def golden_rows() -> dict[str, list[tuple[datetime, float | None]]]
```

- [ ] **Step 0: 前置核对（只读，不改任何文件）**

  确认当前分支是从 `main` 新开的（不是 `claude/state-report`），且 `main` 已含图 2 与 PLAN-SR3-4。逐项用 `git grep` 核对，形状不对或缺失就**停下报告，不要补建**：
  - `services/analytics/src/wheelhouse_service/onchain/brk.py`：`MAX_SERIES_CHARS` 是整数常量；`_chunks(names, size)` 按 `MAX_SERIES_CHARS` 分片；`AGE_ONLY_SERIES` 是元组；`BrkClient.series` 调用 `_chunks`。
  - `services/analytics/src/wheelhouse_service/onchain/sync.py`：`VIEWS` 含 `"agecohorts"`；`_refresh` 里有币龄阶段（`age_missing`、`age_error`），hour1 失败分支是 `self._stored_hour1_missing() - set(AGE_ONLY_SERIES)`，之后有 `hour1_missing |= age_missing`；`errors` 元组是 `(hour1_error, age_error, urpd_error)`；`derive_from_store` 末尾调用 `_derive_age_cohorts`。
  - `services/analytics/src/wheelhouse_service/rules.py`：`View` 含 `"agecohorts"` 与 `"costflow"`。
  - `services/analytics/tests/onchain/test_onchain_sync.py`：有 `failing_for(names: Set[str], **options)`、`bulk_names(request)`、`HOUR1 = (*HOUR1_SERIES, *SELL_SIDE_SERIES, *AGE_ONLY_SERIES)`、`test_first_run_backfills_hour1_from_minus_3000`（`len(hour1) == 5 + 21`）、`test_o2_reaches_the_derived_pressure`（`11 + 25 + 139`）；`test_onchain_rules.py` 的 derive 输出以 ` agecohorts=v1` 结尾。数值与这里不同时，以 `main` 为准，后面各处的 `+8`、`+48` 照样加在它上面。
  - 前端：`sell-side-charts.tsx` 导出 `Segments`、定义了 `heightFor`；`sell-side.ts` 导出 `ticks`、定义了 `grouped`；`flows-panel.tsx` 的 `Flow` 含 `"costbasis"`；`market.css` 的 `.wh-flows-switch` 有 `flex-wrap: wrap`。

- [ ] **Step 1: 放黄金样本**

  - `page_size.json`：逐字节复制 `verification-2026-10-19/verify/sr5/page-20261019T0616.json`（原站 06:16:46Z 读到的全局 `SIZE`，`sizeAsof` 06:00Z）。
  - `page_pnl.json`：逐字节复制 `verification-2026-10-19/sr6/page-pnl-0600.json`（原站 06:21Z 读到的全局 `PNL`，`asof` 1792389600 = 06:00Z）。
  - `README.md`：写明来源路径、抓取时刻、两份读数分别与 BRK 独立复算的对照结果（SR-5.md:23「max abs diff 0.00」；SR-6.md:22「108 个中 106 个相同，另 2 个差 $1，是取整方式」）；锚点反推做法（下一步）；两处半美元原始差值 88.5、2425253218.5 的出处（SR-6.md:43-45，BRK 06:25Z 复取确认）；说明这是**由原站读数反推**的样本，不是 BRK 原始值。

- [ ] **Step 2: 写 `sizes_fixture.golden_rows()`**

  对 `SIZE_BANDS` 的第 i 档、小时 `SE−2160h … SE`（2161 行），除 SE 和 4 个锚点外的值都是 `None`（证明函数只读这 5 个小时）：
  - `<band>_supply`：SE 处 = `page_size()[i]["supply"]`；`SE−n` 处 = `supply − d[w]`。
  - `<band>_realized_profit_cumulative` / `_loss_`：SE 处 = `BASE = 1e12`；`SE−n` 处 = `BASE − raw`，`raw` 取 `page_pnl()[i]` 的对应整数；例外两格用原始差值：第 0 档 1d profit `raw = 88.5`，第 5 档（`addrs_10m_sats_to_1btc`）90d profit `raw = 2425253218.5`（整数和 .5 在 1e12 量级都能精确表示，差值精确还原）。
  - `<band>_realized_cap`：SE 处 = `page_pnl()[i][0]`，其余 `None`。

- [ ] **Step 3: 写失败的测试** `test_onchain_sizes.py`

```python
def test_size_series_cover_twelve_bands_four_ways():
    assert len(SIZE_BANDS) == 12
    assert (SIZE_BANDS[0], SIZE_BANDS[-1]) == ("addrs_under_1k_sats", "addrs_over_100k_btc")
    assert len(SIZE_SERIES) == len(set(SIZE_SERIES)) == 48
    assert SIZE_SERIES[:4] == tuple(f"addrs_under_1k_sats{s}" for s in SIZE_SUFFIXES)
    # More than MAX_SERIES_CHARS: an incremental round needs two requests (Task 2).
    assert len(",".join(SIZE_SERIES)) == 2003

def test_matches_the_page_supply_cell_by_cell():
    result = size_cohorts(golden_rows())
    assert result is not None and result.last_at == SE and result.rules == []
    assert result.no_block == []
    for page, band in zip(page_size(), result.bands, strict=True):
        assert band.supply == page["supply"]
        assert [w.window for w in band.windows] == ["1d", "7d", "30d", "90d"]
        assert [w.supply_change for w in band.windows] == [page["d"][k] for k in ("1d", "7d", "30d", "90d")]
    assert [b.band for b in result.bands] == list(SIZE_BANDS)

def test_matches_the_page_pnl_cell_by_cell():
    result = size_cohorts(golden_rows())
    for page, band in zip(page_pnl(), result.bands, strict=True):
        assert band.realized_cap == page[0]
        assert [(w.profit, w.loss) for w in band.windows] == [
            (page[1], page[2]), (page[3], page[4]), (page[5], page[6]), (page[7], page[8])]
    # The two half-dollar cells: Math.round goes up where Python's round() would go to even.
    assert result.bands[0].windows[0].profit == 89
    assert result.bands[5].windows[3].profit == 2425253219
```

  再用一个 `flat_rows(value=1.0)` 辅助（48 条序列在 `SE−2160h … SE` 每小时都是 `value`）写：

  - `test_dollars_round_half_up_like_math_round`（parametrize：把第 0 档 profit 的 7d 原始差值设为 `88.5 → 89`、`-88.5 → -88`、`2.5 → 3`、`-2.5 → -2`、`0.49 → 0`）。
  - `test_supply_rounds_like_to_fixed_2`：7d 差值 `1.125 − 1.0 = 0.125 → 0.13`、`1.0 − 1.125 → -0.13`（Python `round(0.125, 2)` 是 0.12，这里必须是 0.13）；SE 处 supply `2.675 → 2.67`（浮点精确值略小于 2.675，`toFixed(2)` 给 "2.67"）。
  - `test_a_no_block_anchor_leaves_that_window_missing`：48 条在 `SE−168h` 全部为 `None` → `result.no_block == ["7d"]`；把结果与 `size_cohorts(flat_rows())` 逐格比较，只有每档 `windows[1]` 的 `supply_change`、`profit`、`loss` 变成 `None`，其余各格（`supply`、`realized_cap` 和另外三个窗口，都是 `1.0`、`1` 或 `0.0`、`0`）完全相等。
  - `test_a_partly_null_anchor_is_not_a_no_block_hour`：只有 `addrs_1btc_to_10btc_supply` 在 `SE−168h` 为 `None` → 第 6 档 7d `supply_change is None`，其他格不变，`no_block == []`（这是序列缺口，不是无块小时）。
  - `test_a_null_last_value_leaves_only_that_series_missing`：`addrs_1btc_to_10btc_supply` 在 SE 为 `None` → 第 6 档 `supply is None`，4 个 `supply_change` 都是 `None`；同档 `profit`、`loss`、`realized_cap` 不是 `None`；其他档不受影响；`no_block == []`。
  - `test_a_short_history_leaves_the_long_window_missing`：只保留最后 1000 行 → 1d/7d/30d 有值，每档 90d 三项都是 `None`；`no_block == []`（锚点小时没有行，不算无块）。
  - `test_last_at_is_the_newest_hour_every_series_has`：给一条序列多加 `SE+1h` 一行 → `last_at == SE`。
  - `test_nothing_to_read_is_none`：所有序列为空列表 → `None`；只有一条为空、其他都有 → `None`。

- [ ] **Step 4: 运行，确认失败**

  Run: `../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_sizes.py -q`
  Expected: FAIL（`ImportError: cannot import name 'SIZE_BANDS'`）

- [ ] **Step 5: 实现**

  - `brk.py`：`SIZE_BANDS` 按 L:48-54 的 12 个前缀原样排列；`SIZE_SERIES` 按上面的 band-major 顺序生成。注释写明它们**不进** `HOUR1_SERIES`，由独立阶段取。
  - `sizes.py`：每条序列转成 `{at: value}`；`last_at = min(每条序列最后一行的时间)`，有空序列则返回 `None`；每档每窗口按时间取 `SE` 与 `SE − hours`，任一端为 `None` 或不存在就是 `None`；`no_block` 按 `WINDOWS` 顺序列出锚点小时在 48 条里都有行且全为 `None` 的窗口。两个取整函数：`_cents(x) = float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))`、`_dollars(x) = math.floor(x + 0.5)`。模块 docstring 写明照 L:323-339，以及 null 不当 0 的有意偏离。

- [ ] **Step 6: 运行，确认通过**

  Run: `../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_sizes.py -q`
  Expected: PASS（12 个以上用例全部通过）

- [ ] **Step 7: `make check` 全绿后提交**

```bash
make check
git add services/analytics/src/wheelhouse_service/onchain/brk.py services/analytics/src/wheelhouse_service/onchain/sizes.py services/analytics/tests/onchain/sizes_fixture.py services/analytics/tests/onchain/test_onchain_sizes.py services/analytics/tests/onchain/fixtures/sr5-6-page-2026-10-19T0600Z
git commit -m "feat(onchain): derive the size-cohort supply and P&L changes"
```

---

### Task 2: 独立的 size sync 阶段

**Files:**
- Modify: `services/analytics/src/wheelhouse_service/rules.py`（`View` 追加 `"sizes"`）
- Modify: `services/analytics/src/wheelhouse_service/onchain/sync.py`（`VIEWS`、`OnchainSync._refresh`、`OnchainSync.derive_from_store`，新增 `OnchainSync._derive_sizes`）
- Create: `services/analytics/tests/onchain/fixtures/brk-2026-10-16/hour1_<SIZE_SERIES 每一条>.json`（48 个）、`sizes-expected.json`，并在同目录 `README.md` 追加一节
- Modify: `services/analytics/tests/onchain/test_onchain_sync.py`、`test_onchain_rules.py`

**Interfaces:**
- Consumes: Task 1 的 `SIZE_BANDS`、`SIZE_SERIES`、`DEPTH`、`size_cohorts`、`SizeCohorts`；图 2 的 `MAX_SERIES_CHARS`、`AGE_ONLY_SERIES`（`brk.py`），以及 `test_onchain_sync.py` 里的 `failing_for(names, **options)`（hour1 bulk 请求只要点名 `names` 中任一条就回 503）和 `bulk_names(request)`。
- Produces: derived kind `"sizes"` = `SizeCohorts.model_dump_json()`，`computed_at` 为 size 阶段结束的时刻；`sync_state.missing_series` 追加 `hour1:<size 序列>`，`reasons` 追加 `series_missing:hour1:<size 序列>`；`VIEWS` 末尾是 `"sizes"`。

- [ ] **Step 1: 一次性抓取 fixture（联网，只做这一次）**

  与 Sell side 补 18 条时的做法相同（见该 README「The 18 hour1 series…」一节）：取与现有 hour1 文件相同的位置窗口，6 条一次，共 8 次请求（每次 2,600 点 × 6 × 16 = 249,600 权重，低于 320,000）。

```sh
cd services/analytics/tests/onchain/fixtures/brk-2026-10-16
python3 -I - <<'EOF'
import json, subprocess
bands = ["addrs_under_1k_sats", "addrs_1k_sats_to_10k_sats", "addrs_10k_sats_to_100k_sats",
         "addrs_100k_sats_to_1m_sats", "addrs_1m_sats_to_10m_sats", "addrs_10m_sats_to_1btc",
         "addrs_1btc_to_10btc", "addrs_10btc_to_100btc", "addrs_100btc_to_1k_btc",
         "addrs_1k_btc_to_10k_btc", "addrs_10k_btc_to_100k_btc", "addrs_over_100k_btc"]
names = [b + s for b in bands for s in ("_supply", "_realized_profit_cumulative",
                                        "_realized_loss_cumulative", "_realized_cap")]
for i in range(0, len(names), 6):
    part = names[i:i + 6]
    url = ("https://bitview.space/api/series/bulk?series=" + ",".join(part)
           + "&index=hour1&start=153338&end=155938")
    body = json.loads(subprocess.run(["curl", "-sf", "-A", "curl/8.7.1", url],
                                     check=True, capture_output=True).stdout)
    for name, item in zip(part, body, strict=True):
        with open(f"hour1_{name}.json", "w") as fh:
            json.dump(item, fh, separators=(",", ":"))
EOF
```

  抓完逐个核对：`start == 153338`、`end == 155938`、2,600 点，`null` 恰好在现有 hour1 文件的那 11 个位置（README 已列出）。不一致就停下来报告，不要改 JSON。README 追加一节：请求、抓取时刻、各文件 `version` 与 `stamp`、null 位置核对结果，以及同一分钟内重取 `price_close` 窗口与原文件逐值一致（说明 BRK 没有改写这一窗口）。

- [ ] **Step 2: 离线算出期望表 `sizes-expected.json`（不联网，先于 Step 5 的实现）**

  照阶段 A 复算脚本的算法：`verify/sr5/sr5_expected.py` 的 `main()` 里逐档求 `supply` 与 `d[w]` 的那段，`sr6/chart6_oracle.py` 的 `main()` 里逐档求 `rcap` 与 `(p, l)` 的那段。写一个独立脚本：
  - 直接读上一步的 48 个 JSON 文件，按 `data[position − start]` 取值；**不 import `wheelhouse_service`，也不读 store**。
  - `SE = 155937`（2026-10-16 09:00Z，文件最后一个位置），锚点 `SE − 24/168/720/2160`。
  - 取整照原站，不照这两个脚本里的 Python `round()`：BTC 用 `Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)`（`toFixed(2)`），美元用 `math.floor(x + 0.5)`（`Math.round`）。若有格子两种取整结果不同，在 README 里列出。
  - 任一端为 null 时该格写 `null`；按上一步的 null 位置核对，这 5 个小时都不是空块小时，所以不应出现 null。

  输出 12 档 × 14 格 = 168 格：`{"source": "…", "last_at": "2026-10-16T09:00:00Z", "bands": [{"band": "addrs_under_1k_sats", "supply": …, "realized_cap": …, "windows": [{"window": "1d", "supply_change": …, "profit": …, "loss": …}, …]}, …]}`，与 `SizeCohorts` 的 `bands` 同形。脚本全文作为代码块放进 README，并写明算法出处（上面两个脚本的路径）、运行日期，以及这是本地离线复算、不是原站读数。之后只读不改。

- [ ] **Step 3: 写失败的测试**（`test_onchain_sync.py`）

  先改已有的（都是追加：size 阶段的请求加进 hour1 的请求数里）：
  - `HOUR1 = (*HOUR1_SERIES, *SELL_SIDE_SERIES, *AGE_ONLY_SERIES)` 末尾追加 `*SIZE_SERIES`。
  - `test_first_run_backfills_hour1_from_minus_3000`：`d6572aa` 上是 `assert len(hour1) == 5 + 21`，改为 `5 + 21 + 8`（48 条、每片 6 条），注释追加 "and the 48 size series 8"。
  - `test_o2_reaches_the_derived_pressure`：`d6572aa` 上是 `assert len(v1_lengths) == len(o2_lengths) == 11 + 25 + 139`（`derive_from_store` 里 hour1 的读表次数），改为 `11 + 25 + 139 + 48`，注释追加 sizes 读它们的 48 条。
  - `d6572aa` 上没有数增量轮 hour1 请求数的用例，所以增量轮的 2 次只在本任务新增的 `test_size_requests_stay_under_the_url_limit` 里断言。合并后再全文搜一遍 `test_onchain_sync.py` 里对 `hour1_calls(...)` 或读表次数计数的断言，凡是数一整轮的，同样加上 size 阶段（回填 +8 次请求，增量 +2 次，派生 +48 次读表）。
  - `test_onchain_rules.py` 中 derive CLI 的两行期望输出（`d6572aa` 上以 ` agecohorts=v1` 结尾）在末尾追加 ` sizes=v1`。

  新增（`NOW = 2026-10-16T10:40Z`，`second = NOW + 1h`，fixture 最后一行 155937 = 09:00Z）：

```python
EXPECTED = json.loads((FIXTURES / "sizes-expected.json").read_text())  # Step 2, offline recompute

def test_size_cohorts_are_derived_in_their_own_stage(tmp_path):
    store = OnchainStore(tmp_path / "onchain.sqlite"); transport, _ = brk_transport()
    assert run(store, transport, NOW) is True
    derived = store.derived("sizes")
    assert derived is not None and derived[1] == NOW
    sizes = SizeCohorts.model_validate_json(derived[0])
    assert sizes.last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)
    assert sizes.rules == [] and sizes.no_block == []
    # All 168 cells against the independent recompute.
    assert [band.model_dump() for band in sizes.bands] == EXPECTED["bands"]

def test_a_real_no_block_anchor_blanks_only_that_window(tmp_path):
    store = OnchainStore(tmp_path / "onchain.sqlite"); transport, _ = brk_transport()
    run(store, transport, NOW)
    # Cut every size series after 155802 (2026-10-10 18:00Z): the 7d anchor is then 155634,
    # 2026-10-03 18:00Z, a real hour without a block. 1d/30d/90d land on 155778, 155082, 153642.
    with store.connection() as db:
        db.executemany("DELETE FROM series WHERE series=? AND idx='hour1' AND position>155802",
                       [(name,) for name in SIZE_SERIES])
    sync_for(store, brk_transport()[0], NOW).derive_from_store()
    sizes = SizeCohorts.model_validate_json(store.derived("sizes")[0])
    assert sizes.last_at == datetime(2026, 10, 10, 18, tzinfo=UTC)
    assert sizes.no_block == ["7d"]
    for band in sizes.bands:
        assert (band.windows[1].supply_change, band.windows[1].profit, band.windows[1].loss) == (None, None, None)
        assert band.supply is not None and band.realized_cap is not None
        assert all(v is not None for w in (band.windows[0], *band.windows[2:])
                   for v in (w.supply_change, w.profit, w.loss))
```

  - `test_size_stage_failure_keeps_every_other_view`：第一轮正常；第二轮（`second`）用 `failing_for(set(SIZE_SERIES))`。断言：`cycle`、`levels`、`costbasis`、`costflow`、`pressure`、`sellside`、`agecohorts` 的 `computed_at == second`；`sizes` 仍是第一轮的（`computed_at == NOW`）；`state["last_error"] == "brk_unavailable"`；`next_due == second + 5min`；`reasons == []`。
  - `test_size_stage_failure_on_first_run_leaves_no_sizes`：第一轮就用 `failing_for(set(SIZE_SERIES))` → `store.derived("sizes") is None`，`pressure` 存在。
  - `test_hour1_stage_failure_still_derives_sizes`：第二轮 `failing_for({*HOUR1_SERIES, *SELL_SIDE_SERIES})`（只打到第一个 hour1 阶段，照图 2 的 `test_a_failed_first_hour1_stage_keeps_the_age_cohorts_as_they_were`）→ `sizes` 的 `computed_at == second`，`pressure` 的仍是 `NOW`。
  - `test_a_missing_size_series_clears_only_the_sizes`：`brk_transport(missing={"addrs_over_100k_btc_realized_cap"})` → `missing_series == ["hour1:addrs_over_100k_btc_realized_cap"]`，`reasons == ["series_missing:hour1:addrs_over_100k_btc_realized_cap"]`，`last_error is None`，`sizes` 为 `None`，`pressure`、`sellside`、`agecohorts` 照常。
  - `test_stored_size_missing_survives_a_failed_size_stage`：第一轮 `missing={SIZE_SERIES[5]}`；第二轮 `failing_for(set(SIZE_SERIES))` → `missing_series == [f"hour1:{SIZE_SERIES[5]}"]`，`reasons` 仍含它，`sizes is None`。
  - `test_a_successful_size_stage_clears_its_old_missing_entries_even_when_hour1_fails`：第一轮 `missing={SIZE_SERIES[5]}`；第二轮 `failing_for({*HOUR1_SERIES, *SELL_SIDE_SERIES})` → `missing_series == []`、`reasons == []`，`sizes` 的 `computed_at == second`。
  - `test_size_requests_stay_under_the_url_limit`：先跑一轮（回填），再在 `later = 2026-10-16T11:30Z` 跑一轮（增量），各自收集 `calls`，只看 `series` 含 `addrs_` 的 hour1 bulk 请求。回填轮恰好 8 次、每次 6 个名字、`start == "-3000"`；增量轮恰好 **2** 次，名字合起来按顺序等于 `SIZE_SERIES`、`start == "155934"`；两轮每次 `len(params["series"]) <= MAX_SERIES_CHARS`；并断言 `len(",".join(SIZE_SERIES)) > MAX_SERIES_CHARS`（说明为什么增量要拆）。
  - `test_derive_from_store_keeps_the_size_stamp`：跑一轮后 `sync_for(...).derive_from_store()` → `sizes` 载荷不变，`computed_at == NOW`。
  - `test_size_failure_still_derives_everything_else`：照 `test_sell_side_failure_still_derives_everything_else` 的写法 monkeypatch `wheelhouse_service.onchain.sync.size_cohorts` 抛 `RuntimeError("secret value 123")` → `sizes is None`，其他视图照常，`last_error is None`，日志含 `code=sizes_failed`、不含 `secret`。

- [ ] **Step 4: 运行，确认失败**

  Run: `../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_sync.py tests/onchain/test_onchain_rules.py -q`
  Expected: FAIL（新用例找不到 `sizes`；请求数和 derive 输出不符）

- [ ] **Step 5: 实现**

  - `rules.py`：`View` 的 Literal 末尾追加 `"sizes"`（`IMPLEMENTED` 由推导式自动给空集，不另写）。
  - `sync.py`：
    - `VIEWS` 末尾追加 `"sizes"`。
    - hour1 阶段的 `except BrkError` 分支：图 2 的 `self._stored_hour1_missing() - set(AGE_ONLY_SERIES)` 改为 `self._stored_hour1_missing() - set(AGE_ONLY_SERIES) - set(SIZE_SERIES)`，让各阶段的缺失记录互不残留。
    - `_refresh`：紧接币龄阶段的 `try … except BrkError` 块和其后的 `hour1_missing |= age_missing` 之后、URPD 之前，新增 size 阶段：`size_missing: set[str]`、`size_error: BrkError | None`、`size_done: datetime | None`；`try: self._increment(SIZE_SERIES, "hour1", at, size_missing); size_done = clock()`；`except BrkError as exc: size_error = exc; size_missing = self._stored_hour1_missing() & set(SIZE_SERIES)`。
      size 阶段之后照币龄阶段的写法加 `hour1_missing |= size_missing`。
    - `self._derive_age_cohorts(...)` 之后调用 `self._derive_sizes(hour1_missing, size_done)`。
    - 缺失与原因：`absent_hour1` 遍历的元组 `(*HOUR1_SERIES, *SELL_SIDE_SERIES, *AGE_ONLY_SERIES)` 末尾加 `*SIZE_SERIES`；reasons 与 `missing_series` 由它照旧生成，size 序列排在最后。
    - `errors` 的元组 `(hour1_error, age_error, urpd_error)` 改为 `(hour1_error, age_error, size_error, urpd_error)`（与其他阶段一样决定 `last_error` 和是否 5 分钟后重试）。
    - `_derive_sizes(self, hour1_missing: set[str], size_at: datetime | None) -> None`：照 `_derive_sell_side`：`size_at is None` 时保留库里的结果；`hour1_missing` 与 `SIZE_SERIES` 有交集时清掉；否则 `size_cohorts({name: self.store.read_series(name, "hour1", tail=DEPTH) for name in SIZE_SERIES})`，异常时记 `onchain_derive_failed code=sizes_failed`（不记异常内容）并清掉；结果为 `None` 也清掉。
    - `derive_from_store`：方法末尾、`self._derive_age_cohorts(hour1_missing, …)` 之后，照它的写法 `sizes = self.store.derived("sizes")`，调 `self._derive_sizes(hour1_missing, sizes[1] if sizes else None)`。

- [ ] **Step 6: 运行，确认通过**

  Run: `../../.venv-foundation/bin/python -m pytest tests/onchain -q`
  Expected: PASS（含已有的 sync、api、rules 用例）

- [ ] **Step 7: `make check` 全绿后提交**

```bash
make check
git add services/analytics/src/wheelhouse_service/rules.py services/analytics/src/wheelhouse_service/onchain/sync.py services/analytics/tests/onchain
git commit -m "feat(onchain): fetch the size-cohort series in their own hour1 stage"
```

---

### Task 3: 只读接口 `GET /onchain/size-cohorts` 与契约

**Files:**
- Modify: `services/analytics/src/wheelhouse_service/onchain/models.py`（追加 `SizeCohortsView`）
- Modify: `services/analytics/src/wheelhouse_service/onchain/api.py`（追加 `SIZE_REASONS`、`stored_sizes`、路由 `size_cohorts`）
- Modify: `services/analytics/tests/onchain/test_onchain_api.py`
- Modify（生成）: `integrations/wealthfolio/openapi.json`、`integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/api-schema.d.ts`
- Create（生成）: `integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/size-cohorts-sample.json`

**Interfaces:**
- Consumes: Task 1 `SizeBand`、`SizeCohorts`；Task 2 的 derived `"sizes"`。
- Produces:

```python
class SizeCohortsView(Model):
    data_state: HourState            # hour1_state(last_at, now)
    reasons: list[str]               # only SIZE_REASONS, in stored order
    refreshing: bool
    forming_at: AwareDatetime | None # last_at while computed_at < last_at + 1h
    last_at: AwareDatetime | None
    bands: list[SizeBand]            # empty when unavailable: never zeros
    no_block: list[WindowKey]        # passed through from SizeCohorts; empty when unavailable
    brk_version: str | None
    rules: list[Rule]
    rules_pending: bool

SIZE_REASONS = (*(f"series_missing:hour1:{name}" for name in SIZE_SERIES), "brk_unavailable")
# GET /api/wheelhouse/v1/onchain/size-cohorts -> SizeCohortsView
```

  前端从 `components["schemas"]["SizeCohortsView"]`、`["SizeBand"]` 取类型。

- [ ] **Step 1: 写失败的测试**（`test_onchain_api.py`）

  - `test_capability_and_get_only_schema`：期望集合追加 `f"{PREFIX}/size-cohorts"`。
  - `test_size_cohorts_unavailable_with_200_and_no_zero`：空库 → 200；`data_state == "unavailable"`、`bands == []`、`no_block == []`、`last_at is None`、`forming_at is None`、`reasons == ["brk_unavailable"]`、`rules == []`、`rules_pending is False`。
  - `test_size_cohorts_view_matches_the_frontend_sample`：`store.save_derived("sizes", size_cohorts(golden_rows()).model_dump_json(), datetime(2026, 10, 19, 6, 21, tzinfo=UTC))`，时钟 06:30Z，`router_app` 读 `/size-cohorts`，响应 JSON **整体等于** `size-cohorts-sample.json`（路径 `Path(__file__).resolve().parents[4] / "integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/size-cohorts-sample.json"`）。其中 `data_state == "fresh"`、`last_at == forming_at == "2026-10-19T06:00:00Z"`。
  - `test_size_cohorts_freshness_and_forming`（parametrize，`last_at` 06:00Z）：`computed_at 06:21, now 06:30 → fresh, forming_at 06:00`；`computed_at 07:05, now 07:10 → forming_at None`；`now 08:30 → delayed`；`now 12:30 → stale`。
  - `test_size_cohorts_reasons_are_module_filtered`：state `reasons = ["series_missing:hour1:sth_supply_in_loss", "series_missing:hour1:addrs_over_100k_btc_realized_cap", "urpd_missing"]` → 接口 `reasons == ["series_missing:hour1:addrs_over_100k_btc_realized_cap"]`。
  - `test_size_cohorts_after_sync_never_touch_network`：`synced(tmp_path)` 后用 `blocked_client` 起 app，读 `/size-cohorts` → `last_at == "2026-10-16T09:00:00Z"`、12 档、`seen == []`。

- [ ] **Step 2: 运行，确认失败**

  Run: `../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_api.py -q`
  Expected: FAIL（404 / 缺 `SizeCohortsView`）

- [ ] **Step 3: 实现**

  `models.py` 追加 `SizeCohortsView`（从 `.sizes` 导入 `SizeBand`、`WindowKey`）；`api.py` 照 `sell_side` 路由的写法：无载荷时 `unavailable`、`reasons or ["brk_unavailable"]`、`bands=[]`、`no_block=[]`；有载荷时 `data_state=hour1_state(result.last_at, now)`、`forming_at=result.last_at if computed_at < result.last_at + HOUR else None`、`rules_pending=pending("sizes", result.rules)`。`/status` 不改。

- [ ] **Step 4: 生成契约与前端样本**

  - 在仓库根运行 `make contract`，确认 `openapi.json` 多了 `/api/wheelhouse/v1/onchain/size-cohorts`，`api-schema.d.ts` 多了 `SizeCohortsView`、`SizeBand`、`SizeWindow`。
  - 用上面 `test_size_cohorts_view_matches_the_frontend_sample` 的同一组输入，把响应写成 `json.dumps(body, indent=1, ensure_ascii=False) + "\n"` 存为 `size-cohorts-sample.json`（只生成这一次；之后测试只比对，不写文件）。它是前端测试唯一的载荷样本，内容可追溯到 Task 1 的 README。

- [ ] **Step 5: 运行，确认通过**

  Run: `../../.venv-foundation/bin/python -m pytest tests/onchain -q`
  Expected: PASS

- [ ] **Step 6: `make check` 全绿后提交**

```bash
make check
git add services/analytics/src/wheelhouse_service/onchain/models.py services/analytics/src/wheelhouse_service/onchain/api.py services/analytics/tests/onchain/test_onchain_api.py integrations/wealthfolio/openapi.json integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/api-schema.d.ts integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/size-cohorts-sample.json
git commit -m "feat(onchain): serve the size cohorts at /onchain/size-cohorts"
```

---

### Task 4: 前端契约、client 与图表算术（纯函数）

**Files:**
- Modify: `onchain-contract.ts`（追加类型、`SIZE_BAND_KEYS`、`SIZE_WINDOWS`、`sizeCohortsSchema`）、`client.ts`（追加 `getSizeCohorts`）、`sell-side.ts`（给已有的 `grouped` 加 `export`）、`sell-side-charts.tsx`（给已有的 `heightFor` 加 `export`；`d6572aa` 只导出了 `Segments`）
- Create: `size-cohorts.ts`、`size-cohorts-expected.json`
- Test: `size-cohorts.test.ts`（新建）、`onchain-contract.test.ts`、`client.test.ts`（追加）

（路径均在 `integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/`。）

**Interfaces:**
- Consumes: Task 3 的 `SizeCohortsView` 类型与样本；`sell-side.ts` 的 `ticks(start, stop, count)`（d3-array 3 的移植）与 `grouped`；`sell-side-charts.tsx` 的 `heightFor`（本任务加 `export`）。
- Produces:

```ts
// onchain-contract.ts
export type SizeCohortsView = components["schemas"]["SizeCohortsView"];
export type SizeBand = components["schemas"]["SizeBand"];
export const SIZE_BAND_KEYS = ["addrs_under_1k_sats", /* … L:48-54 order … */ "addrs_over_100k_btc"] as const;
export type BandKey = (typeof SIZE_BAND_KEYS)[number];
export const SIZE_WINDOWS = ["1d", "7d", "30d", "90d"] as const;
export type WindowKey = (typeof SIZE_WINDOWS)[number];
// Refused unless bands are empty or exactly SIZE_BAND_KEYS in order, each with SIZE_WINDOWS in order;
// no_block is an array of SIZE_WINDOWS values.
export const sizeCohortsSchema: z.ZodType<SizeCohortsView, z.ZodTypeDef, unknown>;

// client.ts
export const getSizeCohorts = (signal?: AbortSignal) =>
  query("/onchain/size-cohorts", sizeCohortsSchema, { signal });

// size-cohorts.ts
export type GroupKey = "retail" | "small" | "mid" | "large";
export const GROUPS: readonly { key: GroupKey; from: number; to: number }[]; // A:1993-1998: 0-6, 6-8, 8-10, 10-12
export type Breakdown = "bands" | "groups";
export interface SupplyChoice { win: WindowKey; group: Breakdown; scale: "btc" | "pct" }
export interface PnlChoice { win: WindowKey; group: Breakdown; view: "net" | "gross"; scale: "usd" | "pct" }
export const SUPPLY_DEFAULT: SupplyChoice; // { win: "7d", group: "groups", scale: "btc" }  (A:2029)
export const PNL_DEFAULT: PnlChoice;       // { win: "7d", group: "groups", view: "gross", scale: "usd" } (A:2196)
export const DASH = "—";
// `change` is the window's supply change in BTC; `CohortRow.supply` is the amount held now.
export interface Cell { change: number | null; profit: number | null; loss: number | null }
export interface CohortRow {
  key: BandKey | GroupKey; group: boolean;
  supply: number | null; rcap: number | null; cells: Record<WindowKey, Cell>;
}
export function cohortRows(view: SizeCohortsView, breakdown: Breakdown): CohortRow[]; // largest first
export interface PlotRow {
  key: CohortRow["key"]; group: boolean;
  bars: { v: number; pos: boolean }[]; // [] when the value is missing
  value: number | null;                // what the label prints; in Gross also where the net tick sits
}
export function supplyPlot(rows: CohortRow[], choice: SupplyChoice): PlotRow[];
export function pnlPlot(rows: CohortRow[], choice: PnlChoice): PlotRow[];
export interface Axis { lo: number; hi: number; ticks: number[] }
export function axis(rows: PlotRow[], count: number): Axis | null; // ±(max|bar| || 1)×1.12; null with no bar
export function band(n: number, extent: number, padding: number): { start: number; step: number; width: number };
export interface Layout { compact: boolean; left: number; right: number; top: number; bottom: number; height: number; padding: number; ticks: number }
export function layout(width: number, rows: number): Layout;
export const signed: (v: number) => string;          // "+" when v >= 0 (also -0), else "−" (U+2212)
export function supplyLabel(v: number, scale: SupplyChoice["scale"]): string;
export function pnlLabel(v: number, scale: PnlChoice["scale"]): string;
export function usdLegend(v: number): string;
export function usdTip(v: number): string;
export function supplyLegend(rows: CohortRow[], win: WindowKey): [string, string, string]; // acc, dis, net
export function pnlLegend(rows: CohortRow[], win: WindowKey): [string, string, string];    // profit, loss, net
export interface Reading { head: string; lines: [MessageKey, string][]; foot: string }
export function supplyRead(text: TextFn, row: CohortRow, win: WindowKey): Reading;
export function pnlRead(text: TextFn, row: CohortRow, win: WindowKey): Reading;
```

  取值与格式的原站依据（逐字照搬）：
  - 折叠：组的 `supply`、`rcap`、每窗口 `change`/`profit`/`loss` 都是成员先求和，按成员顺序相加（A:2048-2054、A:2216-2224）；任一成员为 `null`，该组该项为 `null`。
  - 图 5 取值：BTC 为 `d`；% 为 `d / supply × 100`（A:2056-2059），分母 `null` 或 ≤ 0 时为 `null`。一根柱 `pos = v >= 0`。
  - 图 6 取值：`p`、`l` 任一为 `null` 则整行 `null`；% 为 `v / rcap × 100`（A:2232-2234），`rcap` 为 `null` 或 ≤ 0 时为 `null`；Gross 两根柱 `[{v: p', pos: true}, {v: −l', pos: false}]`、`value = net'`；Net 一根柱 `pos = net' >= 0`（A:2269-2280）。
  - `axis`：`mag` 取所有柱 `|v|` 的最大值（图 6 Gross 含 p 和 −l，A:2250-2258），全为 0 时取 1；`lo = −mag×1.12`、`hi = mag×1.12`、`ticks = ticks(lo, hi, count)`（A:2070-2073、2260-2263）。
  - 图 5 标签 `supplyLabel`：BTC `signed(v) + grouped(|v|)`；% `signed(v) + |v|.toFixed(3) + "%"`（A:2060-2062）。轴标签 `v === 0 ? "0" : label`。
  - 图 6 标签 `pnlLabel`（A:2235-2243）：USD `signed + (a≥1e9 ? "$"+(a/1e9).toFixed(2)+"B" : a≥1e6 ? "$"+(a/1e6).toFixed(1)+"M" : a≥1e3 ? "$"+(a/1e3).toFixed(0)+"k" : "$"+grouped(a))`；% 同图 5。
  - `usdLegend`（A:2333-2334）：`signed + (a≥1e9 ? "$"+(a/1e9).toFixed(2)+"B" : "$"+(a/1e6).toFixed(0)+"M")`。`usdTip`（A:2357-2360）：`signed + (a≥1e9 ? B 两位 : a≥1e6 ? M 一位 : "$"+grouped(a))`。
  - `supplyLegend`（A:2116-2125）：只用 BTC 的 `d`（与 Scale 无关），`pos = Σmax(0,d)`、`neg = Σmin(0,d)` → `["+" + grouped(pos) + " BTC", "−" + grouped(|neg|) + " BTC", signed(pos+neg) + grouped(|pos+neg|) + " BTC"]`；当前行有任一 `null` → `[DASH, DASH, DASH]`。
  - `pnlLegend`（A:2330-2339）：`P = Σp`、`L = Σl`（始终美元）→ `[usdLegend(P), usdLegend(−L), usdLegend(P−L)]`；任一 `null` → 三个 `DASH`。
  - 读数（A:2142-2150、A:2356-2373）：`head` 为行名，组另加 `" · " + 副标题`；图 5 三行 `sizes.supply.change`（`supplyLabel(d,"btc") + " BTC"`）、`sizes.supply.share`（`d/supply×100` 的 % 标签）、`sizes.supply.held`（`grouped(supply) + " BTC"`），`foot = text("sizes.supply.foot", {win})`；图 6 四行 `sizes.pnl.profit`（`usdTip(p)`）、`sizes.pnl.loss`（`usdTip(−l)`）、`sizes.pnl.net`（`usdTip(p−l)`）、`sizes.pnl.vsCap`（`rcap > 0 ? %(net/rcap×100) : DASH`），`foot = text("sizes.pnl.foot", {verdict, win})`，`verdict` 依次为 `p===0&&l===0 → sizes.pnl.none`、`l===0 → sizes.pnl.allProfit`、`p===0 → sizes.pnl.allLoss`、否则 `sizes.pnl.share {n: (p/(p+l)×100).toFixed(0)}`。缺值时各行值为 `DASH`，`foot = text("sizes.gap")`。
  - `band`：d3 `scaleBand`（align 0.5，paddingInner = paddingOuter = padding）：`step = extent / (n + padding)`、`start = step × padding`、`width = step × (1 − padding)`；第 i 行顶边 `start + i × step`。
  - `layout`：`width >= 560` 为宽版：`left 164, right 158, top 16, bottom 26, padding 0.28, height = heightFor(width)`（原站边距 A:2033，底边去掉了移出 SVG 的两侧小字）；否则紧凑版：`left 56, right 64, top 16, bottom 26, padding 0.5, height = clamp(rows × 26 + 42, 300, 440)`，行标签画在条上方。`ticks = (width − left − right) >= 480 ? 7 : 3`。`heightFor` 从 `sell-side-charts.tsx` 导入。

- [ ] **Step 1: 写 `size-cohorts-expected.json`**

  结构写死如下（`null` 表示阶段 B 没记这一项，测试跳过它）。`lines` 里存英文名，测试先用 `phrase("en", key)` 把 `Reading.lines` 的键翻译成英文再比对；`pnlRead` 只列阶段 B 记下的那几行，测试断言它们都出现在读数里（子集）。`source` 写明出自 SR-5.md:22-30、39-61 与 SR-6.md:21-31（2026-10-19 06:16Z / 06:21Z 原站线上读数）。

```ts
{
  source: string;
  supply: { win: string; scale: "btc" | "pct"; labels: string[]; legend: string[] | null; tickLabels: string[] | null }[]; // Entities
  supplyRead: { win: string; row: string; head: string; lines: [string, string][]; foot: string };
  supplyTicks: { group: "bands" | "groups"; scale: "btc" | "pct"; win: string; max: number; step: number }[];
  pnl: { win: string; group: "bands" | "groups"; view: "net" | "gross"; scale: "usd" | "pct";
         labels: string[]; legend: string[] | null; ticks: number[] | null; tickLabels: string[] | null;
         bars: number | null; pos: boolean[] | null }[];
  pnlRead: { win: string; group: "bands" | "groups"; row: string; head: string | null; lines: [string, string][]; foot: string }[];
}
```

  逐字抄入：

  - `supply`（Entities，行序从上到下 Large / Mid / Small / Retail）：
    - `7d btc`：`["−7,385","+15,861","−3,167","−2,012"]`，legend `["+15,861 BTC","−12,564 BTC","+3,297 BTC"]`，tickLabels `["−15,000","−10,000","−5,000","0","+5,000","+10,000","+15,000"]`；`7d pct`：`["−0.248%","+0.167%","−0.051%","−0.144%"]`。
    - `1d`：btc `["+983","+404","−468","−429"]`，pct `["+0.033%","+0.004%","−0.007%","−0.031%"]`。
    - `30d`：btc `["−67,512","+86,884","−3,415","−2,101"]`，pct `["−2.271%","+0.917%","−0.055%","−0.151%"]`。
    - `90d`：btc `["+10,868","+81,684","−27,363","−24,148"]`，pct `["+0.366%","+0.862%","−0.437%","−1.732%"]`。
  - `supplyRead`（默认，`row: "large"`）：head `"Large entities · major exchanges, treasuries"`，lines `["Net change","−7,385 BTC"]`、`["Share of band","−0.248%"]`、`["Band supply","2,972,806 BTC"]`，foot `"7d window · threshold crossings can dominate"`。
  - `supplyTicks`（16 组 `{group, scale, win, max, step}`，SR-5.md:39-51）：Bands BTC 1d 3000/1000、7d 15000/5000、30d 40000/20000、90d 100000/50000；Bands % 1d 0.2/0.05、7d 1/0.2、30d 8/2、90d 3/1；Entities BTC 1d 1000/200、7d 15000/5000、30d 80000/20000、90d 80000/20000；Entities % 1d 0.03/0.01、7d 0.2/0.1、30d 2/1、90d 1.5/0.5。
  - `pnl`：
    - 默认（7d/Entities/Gross/USD）：labels `["−$211.6M","+$176.8M","+$519.7M","+$261.2M"]`，legend `["+$2.51B","−$1.77B","+$746M"]`，tickLabels `["−$1.00B","−$500.0M","0","+$500.0M","+$1.00B"]`，bars 8。
    - Bands/Gross/USD 7d：12 个标签 `["+$0","−$211.6M","+$132.8M","+$44.0M","+$318.2M","+$201.5M","+$221.2M","+$37.5M","+$2.3M","+$261k","+$7k","+$430"]`，ticks `[-6e8,-4e8,-2e8,0,2e8,4e8,6e8]`。
    - Entities/Net/USD 7d：4 根柱 `pos` 依次 `[false,true,true,true]`，ticks 首尾 `±4e8`。
    - Entities/Gross/% 7d：labels `["−0.123%","+0.028%","+0.234%","+0.387%"]`，ticks `[-0.4,-0.2,0,0.2,0.4]`，legend 仍为 `["+$2.51B","−$1.77B","+$746M"]`。
    - Entities/Gross/USD：1d `["+$22.3M","+$63.1M","+$37.7M","+$39.6M"]` 图例 `["+$243M","−$80M","+$163M"]`；30d `["+$1.77B","+$6.46B","+$3.16B","+$1.02B"]` 图例 `["+$19.36B","−$6.95B","+$12.41B"]`；90d `["+$3.46B","+$8.40B","+$5.98B","+$1.50B"]` 图例 `["+$48.65B","−$29.32B","+$19.34B"]`。
  - `pnlRead`（7d）：Entities `large`：head `"Large entities · major exchanges, treasuries"`，lines `["Profit booked","+$255.9M"]`、`["Loss booked","−$467.6M"]`、`["Net","−$211.6M"]`、`["vs realized cap","−0.123%"]`，foot `"35% of booked value was profit · 7d window"`；`mid` / `small` / `retail`：head `null`，lines 只有 vs cap `+0.028%` / `+0.234%` / `+0.387%`，foot 份额 `54%` / `73%` / `84%`；Bands `addrs_over_100k_btc`：lines `["Loss booked","+$0"]`，foot `"no coins from this band moved · 7d window"`。

- [ ] **Step 2: 写失败的测试** `size-cohorts.test.ts`

```ts
const view = sizeCohortsSchema.parse(sample);
const text: TextFn = (key, vars) => phrase("en", key, vars);
const labels = (rows: PlotRow[], fmt: (v: number) => string) => rows.map((r) => (r.value == null ? DASH : fmt(r.value)));
// JSON imports type these fields as string, so they are narrowed here (as sell-side.test.ts does).
const win = (w: string) => w as WindowKey;
const english = (r: Reading) => r.lines.map(([key, value]) => [text(key), value]);

it.each(expected.supply)("matches the original Chart 5 at $win / $scale", (c) => {
  const scale = c.scale as SupplyChoice["scale"];
  const rows = cohortRows(view, "groups");
  const plot = supplyPlot(rows, { win: win(c.win), group: "groups", scale });
  expect(labels(plot, (v) => supplyLabel(v, scale))).toEqual(c.labels);
  if (c.legend) expect(supplyLegend(rows, win(c.win))).toEqual(c.legend);
  if (c.tickLabels) expect(axis(plot, 7)!.ticks.map((v) => (v === 0 ? "0" : supplyLabel(v, scale)))).toEqual(c.tickLabels);
});
it.each(expected.supplyTicks)("puts Chart 5's axis at ±$max in steps of $step for $group/$scale/$win", (c) => {
  const choice = { win: win(c.win), group: c.group as Breakdown, scale: c.scale as SupplyChoice["scale"] };
  const t = axis(supplyPlot(cohortRows(view, choice.group), choice), 7)!.ticks;
  expect([t[0], t[t.length - 1], t[1] - t[0]].map((v) => +v.toFixed(6))).toEqual([-c.max, c.max, c.step]);
});
it("reads Chart 5's default Large row as the original", () => {
  const r = expected.supplyRead;
  const reading = supplyRead(text, cohortRows(view, "groups")[0], win(r.win));
  expect([reading.head, english(reading), reading.foot]).toEqual([r.head, r.lines, r.foot]);
});
```

  同样写图 6 的 `it.each(expected.pnl)`（标签、图例、ticks、柱数、`pos` 序列）和 `it.each(expected.pnlRead)`（按 `row` 找到 `cohortRows(view, group)` 里的那一行；`head` 非 `null` 时相等；`r.lines` 每一项都在 `english(reading)` 里；`foot` 相等），以及：
  - `folds a group with a missing member to null`：把样本第 11 档 7d `supply_change` 设为 `null` → Entities 7d Large `value === null`、`bars` 为空、标签 `"—"`；`supplyLegend` 为三个 `"—"`；Bands 下 `over 100k BTC` 同样为 `null`，`axis` 仍由其余行算出（不为 `null`）。
  - `null anchor`：12 档 7d 的 `supply_change`、`profit`、`loss` 全为 `null`、`no_block: ["7d"]`（与 Task 2 真实空块用例的载荷同形）→ 两张图 7d 的 `axis(...) === null`，图例全 `"—"`，每行标签 `"—"`；1d 不受影响。
  - `percent needs a positive denominator`：某档 `supply = 0` → 图 5 % 下该行 `null`；`realized_cap = null` → 图 6 % 下该行 `null`、`pnlRead` 的 vs cap 为 `"—"`。
  - `a P&L row needs both sides`：只把 `profit` 设为 `null` → 图 6 该行 Gross、Net 都是 `null`。
  - `real zeros stay zeros`：Bands/Gross 7d 的 `over 100k BTC` 两根柱 `v` 为 `0` 与 `-0`、`value === 0`、标签 `"+$0"`、verdict 为 none。
  - `layout`：`layout(1000, 4)` → `{compact: false, left: 164, right: 158, height: 440, ticks: 7}`；`layout(720, 4)` → `height 338, ticks 3`；`layout(336, 12)` → `{compact: true, left: 56, right: 64, height: 354, ticks: 3, padding: 0.5}`；`layout(336, 4).height === 300`。
  - `band(4, 296, 0.28)` → `step ≈ 69.15888`、`start ≈ 19.36449`、`width ≈ 49.79439`（`toBeCloseTo(…, 4)`）。

  `onchain-contract.test.ts` 追加：样本可解析；`bands: []`、`no_block: []` 的 unavailable 载荷可解析；档序颠倒被拒；某档 `windows` 顺序错被拒；只有 11 档被拒；`profit: 1.5` 被拒；`no_block: ["2d"]` 被拒；`null` 值可接受。`client.test.ts` 追加：`getSizeCohorts` 请求 `/api/wheelhouse/v1/onchain/size-cohorts` 并用 `sizeCohortsSchema` 解析（照已有 `getSellSide` 用例写）。

- [ ] **Step 3: 运行，确认失败**

  Run: `make sync`，然后在 `.local/wealthfolio` 下 `pnpm --filter frontend exec vitest run src/features/wheelhouse/size-cohorts.test.ts src/features/wheelhouse/onchain-contract.test.ts src/features/wheelhouse/client.test.ts`
  Expected: FAIL（找不到 `./size-cohorts`、`sizeCohortsSchema`）

- [ ] **Step 4: 实现**（按上面的 Interfaces 与取值依据）

- [ ] **Step 5: 运行，确认通过**（同上命令）Expected: PASS

- [ ] **Step 6: `make check` 全绿后提交**

```bash
make check
git add integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/{onchain-contract.ts,onchain-contract.test.ts,client.ts,client.test.ts,sell-side.ts,sell-side-charts.tsx,size-cohorts.ts,size-cohorts.test.ts,size-cohorts-expected.json}
git commit -m "feat(wheelhouse): add the size-cohort contract and chart arithmetic"
```

---

### Task 5: Size cohorts 子视图、两张图与文案

**Files:**
- Create: `size-cohorts-charts.tsx`、`size-cohorts-charts.test.tsx`
- Modify: `flows-panel.tsx`、`flows-panel.test.tsx`、`i18n.ts`、`i18n.test.ts`、`market.css`、`market-defaults.test.tsx`

**Interfaces:**
- Consumes: Task 4 全部导出；`useChartWidth`（`seller-charts.tsx`）；`Segments`（`sell-side-charts.tsx`，图 2 已导出）、`heightFor`（Task 4 已导出）；`reasonText`、`rulesNote`（`onchain-text.ts`）。
- Produces: `export function SizeCohortsCharts(): JSX.Element`；`Flow` 联合类型与 `flows` 数组含 `"sizes"`（位于 `"costbasis"` 与 `"perp"` 之间），`LABELS.sizes = "flows.sizes"`。

```ts
// size-cohorts-charts.tsx (not exported)
interface DivergingBarsProps {
  rows: PlotRow[];
  rowLabel: (row: PlotRow) => string;   // band or group name, already translated
  fmt: (v: number) => string;           // value labels and tick labels (0 prints "0")
  gross: boolean;                       // labels parked at plotW + 12, a "net" header, net ticks
  selected: number | null;              // index into rows
  onSelect: (index: number | null) => void;
  ariaLabel: string;
}
```

  组件结构（照 `SellSideCharts`）：
  - `SizeCohortsCharts`：根节点 `<div className="wh-seller wh-sizes">`（`.wh-seller-meta`、`.wh-seller-read p` 的样式挂在 `.wh-seller` 下）。`useQuery({ queryKey: ["wh", "onchain", "size-cohorts"], queryFn: ({signal}) => getSizeCohorts(signal), refetchInterval: 300000, retry: false })`。出错 → `sizes.unavailable` + 错误信息；无数据 → `sizes.loading`（不出现数字）；`unavailable` → 警告 + reasons + refreshing；否则页头一行 `seller.meta`（时间 `YYYY-MM-DD HH:MM`）+ forming（`seller.forming`，delayed/stale 时 `seller.formingOld`）、`rulesNote`、delayed/stale 横幅（`seller.delayed` / `seller.stale`）、refreshing、reasons，然后 `SupplyPanel`、`PnlPanel`。
  - 每块面板 `<section className="wh-seller-panel" data-chart="sizes-supply|sizes-pnl">`：标题 h3；控件行 `<div className="wh-ss-controls">`（`Segments`：Window `1d/7d/30d/90d` 原样显示；Breakdown `sizes.bands`/`sizes.groups`；图 5 Scale `sizes.btc`/`sizes.pctBand`；图 6 View `sizes.net`/`sizes.gross`（此顺序，A:507-508）与 Scale `sizes.usd`/`sizes.pctCap`）；`DivergingBars`；当前窗口在 `view.no_block` 里时，图下一行 `<p className="wh-sc-note">{text("sizes.noBlock", { win })}</p>`；两侧小字一行（HTML，`wh-sc-sides`）；图例三项（`wh-seller-legend`，色块 pos/neg/net）；读数行（`aria-live="polite"`）；三栏说明（复用 `.wh-seller-read` 与 `seller.read.*` 小标题）。两张图的控件各自独立（原站 `sstate`、`plstate` 分开）；任一控件变化都清空选中行（照 Sell side 面板的 `change` 先 `setHover(null)`）。
  - `DivergingBars`：`useChartWidth()` 给宽度，`layout(width, rows.length)` 给版式，`band()` 给行位置，`axis(rows, layout.ticks)` 给刻度。`axis === null` 时不画轴和柱：当前窗口在 `no_block` 里就只靠上面的 `sizes.noBlock` 说明，否则显示 `seller.noData`。画：非零刻度的竖网格、x 轴刻度文字（`plotH + 18`）、`0` 线、柱（`x = X(min(0,v))`、宽 `max(0.8, |X(v) − X(0)|)`、高 = 行宽，class `wh-sc-bar wh-sc-bar--pos|neg`）、标签（Net/图 5：柱端外 7px，正值 start、负值 end；缺值 `"—"` 放在 `X(0) + 7`；Gross：统一放在 `plotW + 12`，并在 `(plotW + 12, −4)` 写 `sizes.pnl.netHead`）、Gross 的净额竖线（`y` 从行顶 −3 到行底 +3，class `wh-sc-tick`）、行标签（宽版在 `x = −10` 右对齐；紧凑版在 `x = −left + 4` 左对齐，画在条上方 `rowTop − 4`）、选中行的淡底色。SVG `tabIndex=0`、`role="img"`、`aria-label`=`sizes.aria`；`ArrowDown`/`ArrowUp` 逐行移动（未选中时分别到第一行/最后一行），`Home`/`End`，`Escape` 清除；指针移动按 y 选最近一行。

- [ ] **Step 1: 写失败的测试**

  `size-cohorts-charts.test.tsx`（mock `getSizeCohorts`，样本 `sizeCohortsSchema.parse(sample)`，jsdom 宽度 720 → 宽版、3 个刻度）：
  - `opens on the original defaults`：图 5 的 `7d`、`Entities`、`BTC` 与图 6 的 `7d`、`Entities`、`Gross`、`USD` 按钮 `aria-pressed="true"`；两块标题为 `"Chart 5 — Net Supply Change By Size Cohorts"`、`"Chart 6 — Net Realized Profit & Loss By Size Cohorts"`。
  - `draws the default readings`：图 5 行标签依次 `["Large entities","Mid-size entities","Small entities","Retail"]`，值标签等于 expected 默认用例；图 5、图 6 图例的值等于 expected；图 6 有 8 个 `rect.wh-sc-bar`、4 条 `.wh-sc-tick`、一个 `net` 列头。
  - `switches breakdown, view and scale`：点 `Bands` → 图 5 出现 12 个行标签、首个为 `"over 100k BTC"`；图 6 点 `Net` → 4 个 rect、0 条竖线，两侧小字为 `"USD ← Net loss"` 与 `"Net profit → USD"`；点 `% of realized cap` → 标签等于 expected 的 % 用例，图例不变。
  - `reads a row from the keyboard`：聚焦图 6 的 SVG，按 `ArrowDown` → 读数含 `"Large entities · major exchanges, treasuries"`、`"Loss booked"`、`"−$467.6M"`、`"35% of booked value was profit · 7d window"`；按 `Escape` → 回到提示文字 `sizes.readHint` 的英文。
  - `shows a dash and no bar for a missing row`：样本第 11 档 7d 全为 `null`（`no_block` 仍为 `[]`）→ 图 5 Large 行值标签 `"—"`、该行没有 rect，图例三项都是 `"—"`，不出现 `sizes.noBlock` 的说明；切到 `1d` 后恢复数字。
  - `explains a window whose anchor hour had no block`：12 档 7d 全为 `null`、`no_block: ["7d"]` → 两块面板每行标签 `"—"`、没有 rect，图下都出现 `"No block was mined in the hour this 7d window starts from…"` 的英文全文，**不**出现 `"No data for this chart"`；切到 `1d` 后说明消失、柱子出现。
  - `clears the reading when a control changes`：按 `ArrowDown` 选中一行后点 `Bands` → 读数回到提示文字。
  - `says when the hour is forming`：页头含 `"Data 2026-10-19 06:00 UTC"` 和 `"includes the forming hour"`；`warns when the data is delayed`：`data_state: "delayed"` → 出现 `"Data is delayed · data to 2026-10-19 06:00 UTC"`、forming 改为 `"last hour was partial when computed"`，条形仍在。
  - `invents no number while loading`：未返回时只见 `"Loading size cohorts…"`，`textContent` 不含数字；`unavailable` 时见 `"Size cohorts unavailable"` 与 reason 文本、无 SVG；请求失败时见同一警告与错误信息。
  - 每块面板下都有三栏，标题为 `What it shows` / `What extreme values imply` / `How to read`。

  `flows-panel.test.tsx`：在 `vi.hoisted` 的 `mocks` 里加 `sizes: vi.fn()`，在 `vi.mock("./client", …)` 的替换表里加 `getSizeCohorts: mocks.sizes`（不加的话 `?flow=sizes` 只会显示 unavailable）；追加 `shows the size cohorts for flow=sizes and queries nothing else`：`mocks.sizes.mockResolvedValue(sizeCohortsSchema.parse(sample))`，`?flow=sizes` → 见图 5 标题；`Size cohorts` 按钮 `aria-pressed="true"`；`getSellerPressure`、`getSellSide`、`getPerpStates` 未调用；切换按钮共 5 个，`Size cohorts` 紧挨在 `Perp states` 之前。`market-defaults.test.tsx`：在 `./sell-side-charts` 的 mock 旁追加 `vi.mock("./size-cohorts-charts", () => ({ SizeCohortsCharts: () => <p>size-cohorts-charts</p> }))`。`i18n.test.ts` 的逐字表追加 `flows.sizes`、`sizes.supply.title`、`sizes.pnl.title`、`sizes.noBlock` 四对 en/zh。

- [ ] **Step 2: 运行，确认失败**

  Run: `make sync` 后在 `.local/wealthfolio` 下 `pnpm --filter frontend exec vitest run src/features/wheelhouse/size-cohorts-charts.test.tsx src/features/wheelhouse/flows-panel.test.tsx src/features/wheelhouse/i18n.test.ts`
  Expected: FAIL

- [ ] **Step 3: 文案**（`i18n.ts`，en 与 zh 同键）

| 键 | en | zh |
|---|---|---|
| `flows.sizes` | Size cohorts | 规模分组 |
| `sizes.loading` | Loading size cohorts… | 正在加载规模分组… |
| `sizes.unavailable` | Size cohorts unavailable | 规模分组数据不可用 |
| `sizes.window` / `sizes.breakdown` / `sizes.scale` / `sizes.view` | Window / Breakdown / Scale / View | 窗口 / 拆分方式 / 标度 / 视图 |
| `sizes.bands` / `sizes.groups` | Bands / Entities | 分组 / 实体 |
| `sizes.btc` / `sizes.pctBand` / `sizes.usd` / `sizes.pctCap` | BTC / % of band / USD / % of realized cap | BTC / 占本组比例 / USD / 占已实现市值比例 |
| `sizes.net` / `sizes.gross` | Net / Gross | 净额 / 总额 |
| `sizes.band.<12 个 key>` | under 1k sats · 1k–10k sats · 10k–100k sats · 100k–1M sats · 1M–10M sats · 10M sats–1 BTC · 1–10 BTC · 10–100 BTC · 100–1k BTC · 1k–10k BTC · 10k–100k BTC · over 100k BTC | 低于 1k 聪 · 1k–10k 聪 · 10k–100k 聪 · 100k–1M 聪 · 1M–10M 聪 · 10M 聪–1 BTC · 1–10 BTC · 10–100 BTC · 100–1k BTC · 1k–10k BTC · 10k–100k BTC · 高于 100k BTC |
| `sizes.group.retail/small/mid/large` | Retail · Small entities · Mid-size entities · Large entities | 散户 · 小型实体 · 中型实体 · 大型实体 |
| `sizes.sub.retail/small/mid/large` | under 1 BTC · Satoshi-era wallets, dolphins · whales, minor exchanges · major exchanges, treasuries | 不足 1 BTC · 中本聪时代钱包、海豚 · 巨鲸、小型交易所 · 大型交易所、财库 |
| `sizes.supply.title` | Chart 5 — Net Supply Change By Size Cohorts | 图 5 — 按地址规模分组的净供应变化 |
| `sizes.supply.acc` / `.dis` / `.net` | Net accumulation / Net distribution / Net (issuance) | 净累积 / 净派发 / 净额（新增发行） |
| `sizes.supply.right` / `.left` | Net accumulation → {{unit}} / {{unit}} ← Net distribution | 净累积 → {{unit}} / {{unit}} ← 净派发 |
| `sizes.supply.change` / `.share` / `.held` | Net change / Share of band / Band supply | 净变化 / 占本组比例 / 本组持币量 |
| `sizes.supply.foot` | {{win}} window · threshold crossings can dominate | {{win}} 窗口 · 跨档变动可能占主导 |
| `sizes.pnl.title` | Chart 6 — Net Realized Profit & Loss By Size Cohorts | 图 6 — 按地址规模分组的净已实现盈亏 |
| `sizes.pnl.profit` / `.loss` / `.net` | Profit booked / Loss booked / Net | 入账盈利 / 入账亏损 / 净额 |
| `sizes.pnl.right.gross` / `.right.net` | Profit booked → {{unit}} / Net profit → {{unit}} | 入账盈利 → {{unit}} / 净盈利 → {{unit}} |
| `sizes.pnl.left.gross` / `.left.net` | {{unit}} ← Loss booked / {{unit}} ← Net loss | {{unit}} ← 入账亏损 / {{unit}} ← 净亏损 |
| `sizes.pnl.netHead` | net | 净额 |
| `sizes.pnl.vsCap` | vs realized cap | 相对已实现市值 |
| `sizes.pnl.none` / `.allProfit` / `.allLoss` | no coins from this band moved / spent entirely in profit / spent entirely at a loss | 该组没有币移动 / 全部以盈利花费 / 全部以亏损花费 |
| `sizes.pnl.share` | {{n}}% of booked value was profit | 入账金额中 {{n}}% 为盈利 |
| `sizes.pnl.foot` | {{verdict}} · {{win}} window | {{verdict}} · {{win}} 窗口 |
| `sizes.gap` | No data at one end of this window | 该窗口一端缺数据 |
| `sizes.noBlock` | No block was mined in the hour this {{win}} window starts from, so there is nothing to compare against. It fills in at the next hourly refresh. | 这个 {{win}} 窗口起点那一小时没有出块，没有可比的值；下一次每小时刷新后会补上。 |
| `sizes.readHint` | Hover a row, or focus the chart and use the up and down arrow keys, to read it | 悬停某一行，或聚焦图表后用上下方向键，查看该行数值 |
| `sizes.aria` | {{title}}. Use the up and down arrow keys to read one row; Escape clears the reading. | {{title}}。用上下方向键逐行查看；按 Escape 清除。 |

  三栏说明初稿（交用户审，OP-4）：

| 键 | en | zh |
|---|---|---|
| `sizes.supply.shows` | How many coins each wallet-size band gained or lost over the window: the supply BRK counts in addresses holding that balance at the latest hour, which may still be forming, less the same count 24, 168, 720 or 2,160 hours earlier. Entities adds the twelve bands up into four groups; % of band divides the change by what the band holds now. | 各钱包规模区间在窗口内增减了多少币：BRK 统计的该余额区间地址持币量，取最新一小时（可能尚未收盘）减去 24、168、720 或 2,160 小时前的值。“实体”把 12 个区间合并成 4 组；“占本组比例”用变化量除以该组当前持币量。 |
| `sizes.supply.implies` | This chart sets no thresholds. A large gain means coins are gathering in wallets of that size, a large loss that they are leaving them. A big move matched by an opposite one in the next band is usually wallets crossing the edge between the two, not coins changing hands. Over all twelve bands the net is roughly the newly mined coins. | 本图没有设阈值。某区间大幅增加，说明币在向这一规模的钱包集中；大幅减少，说明币在离开。相邻区间一增一减的成对变动，通常是钱包越过区间边界，而不是币易手。12 个区间合计的净额大致等于新挖出的币。 |
| `sizes.supply.how` | Right is accumulation, left distribution. Before reading a bar as flow, look at the neighbouring band for an opposite bar. The entity names are the original author's reading of the size ladder: BRK does not group addresses into entities. A dash marks a band or window without data, never a zero. | 向右为累积，向左为派发。把某根条读成资金流之前，先看相邻区间有没有方向相反的条。实体名称是原作者对规模档位的解读，BRK 并不把地址归并为实体。“—”表示该区间或窗口缺数据，不是 0。 |
| `sizes.pnl.shows` | Dollars of profit and loss booked by each wallet-size band over the window: the change in BRK's cumulative realized profit and loss from 24, 168, 720 or 2,160 hours earlier to the latest hour, which may still be forming. Gross draws both sides with a tick where the net lands; Net draws one bar. % of realized cap divides by what the band paid for the coins it holds. | 各钱包规模区间在窗口内入账的盈亏美元：BRK 累计已实现盈利和亏损，从 24、168、720 或 2,160 小时前到最新一小时（可能尚未收盘）的变化。“总额”画出两边，并用短竖线标出净额位置；“净额”只画一根条。“占已实现市值比例”以该组买入所持币的成本为分母。 |
| `sizes.pnl.implies` | This chart sets no thresholds. A band booking mostly losses is spending coins below what it paid for them; one booking mostly profits is spending them into strength. BRK books every on-chain spend, moves between a holder's own wallets included, so booked is not the same as sold. Against realized cap a bar reads as a realized return on what the band paid. | 本图没有设阈值。某区间以亏损入账为主，说明它花费的币低于买入成本；以盈利入账为主，说明它在逢高花费。BRK 记录每一笔链上花费，包括持有者在自己钱包之间的转移，所以“入账”不等于“卖出”。按已实现市值看，条形可理解为该组相对其成本的已实现回报。 |
| `sizes.pnl.how` | Right is profit, left is loss. Compare the two bars before the net tick: a small net can hide heavy booking on both sides. The legend always adds up dollars, whatever the scale. Entity names are a reading of the size ladder; BRK has no entity clustering. Wallets crossing a band edge move coins, not booked profit or loss. | 向右为盈利，向左为亏损。先比较两根条，再看净额竖线：净额小也可能两边都有大量入账。无论选哪种标度，图例都按美元合计。实体名称只是对规模档位的解读，BRK 没有实体聚类。钱包越过区间边界移动的是币，不是已入账的盈亏。 |

- [ ] **Step 4: 样式**（`market.css`，在 Sell side 一节之后追加）

  `.wh-sizes { --wh-moss: #7fc98a; --wh-rust: #e0805c; --wh-sc-ink: #e5edf6; }`；`.wh-sc-bar--pos { fill: var(--wh-moss) }`、`.wh-sc-bar--neg { fill: var(--wh-rust) }`；`.wh-sc-tick { stroke: var(--wh-sc-ink); stroke-width: 1.6; shape-rendering: crispEdges }`；`.wh-sc-val`（JetBrains Mono 11px，紧凑版 10px）、`.wh-sc-row`（Inter 11px，紧凑版 10px）、`.wh-sc-grid`、`.wh-sc-zero`、`.wh-sc-hover`；`.wh-sc-sides`（flex、`justify-content: space-between`、`flex-wrap: wrap`、10px、大写、`letter-spacing: 0.14em`、muted）；图例色块 `.wh-sc-swatch--pos/neg/net`；读数 `.wh-sc-read`（JetBrains Mono 11px）；无块说明 `.wh-sc-note`（11px、muted，与 `.wh-ss-note` 同字体）。`.wh-flows-switch` 的换行由 PLAN-SR3-4 加的 `flex-wrap: wrap` 负责，本任务不改；第 5 个按钮加入后由 Task 7 在 390px 下实测。

- [ ] **Step 5: 实现组件与 `flows-panel.tsx`**（按上面的 Interfaces）。

- [ ] **Step 6: 运行，确认通过**（同 Step 2 命令，加上 `size-cohorts.test.ts`、`market-defaults.test.tsx`）Expected: PASS

- [ ] **Step 7: `make check` 全绿后提交**

```bash
make check
git add integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse
git commit -m "feat(wheelhouse): add the Size cohorts flow with Charts 5 and 6"
```

---

### Task 6: SPEC、清单与核验记录骨架

**Files:**
- Modify: `docs/features/btc-onchain-perp/SPEC.md`、`docs/features/btc-onchain-perp/CHART-INVENTORY.md`
- Create: `docs/features/btc-onchain-perp/SR5-6-VERIFICATION.md`

**Interfaces:** Consumes Task 1–5 的结果；不产出代码。

- [ ] **Step 1: SPEC.md**
  SPEC 的改动一律按标题文字定位，不按章节编号：
  - 标题「目标与范围」下的 **不做** 列表：`d6572aa` 上第一条是「state-report 的图 4、5、6、8。…图 2 同日纳入…」。从这一条里删去 5、6（其余图号保持当时 `main` 上的样子），句末追加「图 5、6 同日纳入，做法见 [PLAN-SR5-6.md](PLAN-SR5-6.md)」。
  - 标题「计算规则（v1 = 原站口径）」这一节：在它的最后一个小节之后、标题「优化清单（v1 验收后逐项启用）」之前，新增一个小节「规模分组：图 5、图 6」（编号沿用该节的写法，取下一个空号）：
    - 数据：48 条 hour1 序列、独立阶段、深度 2250、增量请求按 `MAX_SERIES_CHARS` 拆分；存储增量：首次回填 48 × 3,000 = 144,000 行，之后每天 48 × 24 = 1,152 行（hour1 不裁剪）；实测库体积记在 VERIFICATION 第 3 节。
    - 计算：SE、4 个窗口、两种取整及原站出处；本计划「已定的做法」中的缺失值、零值、门控裁定；`no_block` 的判定；O1–O6 未实现（`IMPLEMENTED["sizes"]` 为空）。
    - 与原站的有意偏离：null 显示 "—"（原站当 0）；% 分母无效显示 "—"（原站给 0）；`vs realized cap` 在 realized_cap ≤ 0 时显示 "—"（原站 `n/a`）；无块锚点窗口在图下说明原因；读数行代替浮窗；窄屏改排版；图内文字全部翻译；Net 色块用墨色。
    - 遗留问题：HH:00–HH:12 之间页头仍写 "includes the forming hour"，与卖压、Sell side 共有，三处要一起修；size 阶段持续 5xx 时整轮每 5 分钟重试（hour1/URPD 失败时的已有行为）。
  - 标题「界面（已用可视化伴侣逐屏确认）」下的 **Flows（BTC）** 段：子视图切换写成已定的 5 项顺序；新增 **Size cohorts** 一条：图 5、图 6 纵排，各自的 Window / Breakdown / Scale（图 6 另有 View）控件与默认值，图例，读数行，三栏说明；窄屏规则。
  - 标题「修订记录」下追加一条（日期、图 5/6 纳入、上述偏离）。
- [ ] **Step 2: CHART-INVENTORY.md**：图 5、图 6 两行的本地现状改为 **已做**（2026-10-19，Flows → Size cohorts），见 [PLAN-SR5-6.md](PLAN-SR5-6.md)；「目前本地做了」的图数加 2，并把图 5、6 列进 state-report 的已做清单。
- [ ] **Step 3: SR5-6-VERIFICATION.md 骨架**（照 P5-VERIFICATION 的格式，数字留给 Task 7 填）：
  1. 全量检查：`make check` 各段结果表（ruff、mypy、pytest 条数、type-check、vitest 条数）。
  2. 黄金样本：原站反推样本 168 个值（图 5 60 个、图 6 108 个，含两处半美元格）全部相等；真实 fixture 与离线复算 `sizes-expected.json` 的 168 格全部相等；真实空块锚点（155634）用例结果；前端用例数与结果；fixture 来源。
  3. 真实数据链路：首轮回填请求数（8）、增量请求数（2）与最长 `series` 字符数、本机库上的 `last_at` 与 forming；`series` 表新增行数与 `onchain.sqlite` 体积（回填前后）。
  4. 浏览器（1440、390 两档；en、zh）：默认读数、4 组控件切换、键盘读数、子视图换行、`scrollWidth`、控制台。
  5. 与原站同刻对照（可选）：同一小时默认视图的图 5 四行、图 6 四行与图例。
  6. 与原站的有意偏离（引用 SPEC 新小节）与遗留问题。
- [ ] **Step 4: `make check` 全绿后提交**

```bash
make check
git add docs/features/btc-onchain-perp/SPEC.md docs/features/btc-onchain-perp/CHART-INVENTORY.md docs/features/btc-onchain-perp/SR5-6-VERIFICATION.md
git commit -m "docs(onchain): record charts 5 and 6 in the spec and inventory"
```

---

### Task 7: 浏览器核验（controller 执行）

- [ ] **Step 1:** analytics 以 `WHEELHOUSE_RULES=v1` 启动，overlay 用 `python3 scripts/foundation.py overlay`。新序列要到下一次 HH:12 刷新才首次回填；等不及时，照 P3 的做法把本机开发库 `.local/analytics/onchain.sqlite` 的 `next_due` 置空，触发一轮同步。确认 `/api/wheelhouse/v1/onchain/size-cohorts` 返回 12 档、`last_at` 为当前小时；记录回填前后 `series` 表行数与库体积。
- [ ] **Step 2:** 1440px 打开 `/market-intelligence?symbol=BTCUSDT&method=flows&flow=sizes`：两张图默认控件、行序（最大在上）、标签、图例、x 轴（应为 `ticks(7)`）、Gross 竖线与 `net` 列头；逐个切换 Window / Breakdown / Scale / View；键盘读数；zh 下全部文字为中文；控制台零报错。条件允许时与原站同一小时对照默认读数。
- [ ] **Step 3:** 390px（真实点击打开 390 宽同源弹窗，读 DOM）：`scrollWidth == 390`；5 个子视图按钮换行、无截断；行标签在条上方、不压条；刻度 3 个不重叠；两侧小字换行；三栏说明纵向全部展开。
- [ ] **Step 4:** 把结果填进 `SR5-6-VERIFICATION.md`，发现问题按常规修复流程处理（新提交），截图给用户。

---

## 不做

- O1–O6 在这两张图上的版本（包括无块小时向前沿用的 O3 版本，见 OP-1）。
- 原站空的 Read 块与 Analyst Take（人工撰写）；单独显示原站 caption。
- 浮动 tooltip；图 5/6 的 onchain-pulse（Supplementary）入口——模板相同，日后可直接复用本组件。
- `/status` 的 hour1 数据集纳入 size 序列。
