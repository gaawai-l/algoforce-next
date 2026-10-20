# SR5-6 核验记录

日期：2026-10-20。分支 `claude/size-cohorts`（从 main f304735 新建），范围见 [PLAN-SR5-6](PLAN-SR5-6.md)：state-report 图 5（Net Supply Change By Size Cohorts）和图 6（Net Realized Profit & Loss By Size Cohorts），界面在 Flows → Size cohorts（`flow=sizes`）。规则见 [SPEC.md](SPEC.md) 的"规模分组"一节。

第 1、2 节和第 3 节的请求数按任务报告与评审填写；第 3 节的库体积、第 4 节浏览器、第 5 节实时对照由 controller 在 Task 7 实测填写（2026-10-20）。

提交：
- Task 1：`9aaaa83`、`bc3fa22`（纯计算 `sizes.py`、原站黄金样本、`SIZE_SERIES`；后一个只补测试和文档）；
- Task 2：`d6b7b93`（独立的 size 取数阶段、48 个 fixture、离线期望表 `sizes-expected.json`）；
- Task 3：`ef4fb51`（读接口 `/onchain/size-cohorts`、契约、前端样本）；
- Task 4：`1c79ada`（前端契约、client、图表算术纯函数）；
- Task 5：`6329729`、`1278897`（子视图、图 5 与图 6、文案；后一个修紧凑版的选行并钉住几何）；
- Task 6：本文档提交（SPEC、图表清单、本文件）。

## 1. 全量检查（`make check`）

2026-10-20 在 `044c06f`（终审修复轮完成后）运行，退出码 0；`deploy/test/test_composition.py` 1 passed。此前在 `1278897` 跑过一次（vitest 677）。

| 项目 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy strict | 55 个源文件，无问题 |
| pytest | 1069 passed（1 个 warning，是仓库原有的 Starlette/httpx 弃用提示），用时 294 s |
| types、frontend type-check | 通过 |
| vitest `src/features/wheelhouse` | 31 个文件，680 个测试全部通过 |

各任务完成时的测试数（基线 main f304735：pytest 1024，vitest 589）和变异核对：

| 任务 | pytest | vitest | 变异核对 |
|---|---|---|---|
| 1 纯计算与原站黄金样本 | 1039（`bc3fa22` 后 1041） | 589 | 24 个，全部杀死；补测试轮的 4 个具名变异（N1–N4）也由新增用例杀死 |
| 2 独立的 size 阶段 | 1056 | 589 | 23 个，全部杀死 |
| 3 读接口与样本 | 1069 | 589 | 25 个，全部杀死；评审另做 17 个，全部杀死 |
| 4 契约与图表算术 | 1069 | 654 | 93 个，92 杀死，1 个等价（`percent no null check`：JS 里 `null > 0` 为 `false`，分母为 null 时结果仍是 null） |
| 5 子视图、图 5 与图 6 | 1069 | 675，补修轮后 677 | 72 个，全部杀死；首轮 5 个存活，补测试后重跑全部杀死 |

- 等价变异的理由写在各任务报告里：变异后的代码在所有可达输入上，输出与原代码逐位相同。
- 测试耗时：`tests/onchain` 同口径对比从 202 s 增至 269 s（+33%）。原因是每次完整 sync 都要多回填 48 × 2,600 行。可行的提速办法是做一份会话级的首轮同步模板库，不在本计划内。

## 2. 黄金对照，按来源分栏

期望值的来源分三类，测试注释里逐条标明。**页面记录**是原站页面上读到的值，是最强的锚。

### 页面记录（由原站读数反推的样本）

样本：`services/analytics/tests/onchain/fixtures/sr5-6-page-2026-10-19T0600Z/`（README 写明来源和做法）。图 5 的读数取自 2026-10-19 06:16:46 UTC 的全局 `SIZE`，图 6 的取自 06:21 UTC 的全局 `PNL`，两者都是 06:00 那根正在形成的小时。那根小时的原始序列值之后已收盘、数值变了，无法再取，所以这是**由原站读数反推的锚点**，不是 BRK 原始值：`golden_rows()` 只在 SE 和 4 个锚点小时有值，其余全是 null，证明函数只读这 5 个小时。

| 项目 | 数量 | 比对方式 | 结果 |
|---|---|---|---|
| 图 5 | 60 个值（12 档 × （当前量 + 4 个窗口的变化）） | `size_cohorts(golden_rows())` 与页面 `SIZE` 逐格比 | 60/60 相等 |
| 图 6 | 108 个值（12 档 × （已实现市值 + 4 个窗口的盈利和亏损）） | 同上，与页面 `PNL` 逐格比 | 108/108 相等 |
| 两处半美元格 | 第 0 档 1d profit（原始差值 88.5）、第 5 档 `addrs_10m_sats_to_1btc` 90d profit（2425253218.5） | `Math.round` 向上取整，得 89 和 2425253219；Python `round()` 会得 88 和 2425253218 | 相等（测试里单独断言） |
| 页面读数与 BRK 独立复算（阶段 A，已存的复算结果重跑） | 图 5 的最大绝对差 0.00；图 6 的 108 个中 106 个相同，另 2 个差 $1 | 差的 2 个就是上面的半美元格，原因是取整方式（页面 `Math.round`，复算脚本 Python `round()`） | 与 README 一致 |
| 评审复核（Task 1） | 原站的 loader JS 原样运行在 `golden_rows()` 上：60 + 108 个格；另有 20,160 格的随机差分 | 与 `size_cohorts` 逐格相等 | 0 处差异 |

### 真实 BRK fixture 与离线复算

fixture：`services/analytics/tests/onchain/fixtures/brk-2026-10-16/hour1_addrs_*.json`，48 个文件，共 1,825,665 字节。一次性抓取于 2026-10-20 01:07:36–01:07:39 UTC，BRK 0.12.2，8 次请求、每次 6 条序列，位置窗口与已有的 hour1 文件相同（153338–155938，2,600 点）；`null` 恰好落在已有 hour1 文件的那 11 个位置，没有别的 `null`。README 追加了一节：请求、抓取时刻、各文件 `version` 与 `stamp`、核对结果。

| 项目 | 数量 | 比对方式 | 结果 |
|---|---|---|---|
| `sizes-expected.json` | 12 档 × 14 格 = 168 格 | 由 README 里的离线脚本算出：直接读 48 个 JSON 文件，不 import `wheelhouse_service`，不读 store；SE = 155937（2026-10-16 09:00 UTC），锚点 155913 / 155769 / 155217 / 153777；取整照原站 | 168 格里没有 null，`no_block` 为空 |
| 经 sync 的整条链路 | 同上 168 格 | `test_size_cohorts_are_derived_in_their_own_stage`：回放 fixture 跑一轮同步，读出的 `bands` 与期望表逐格比 | 168/168 相等 |
| 重新生成 | 期望表 | 评审用 README 脚本重新生成 | 与已提交的文件逐字节相同；另有 5 格独立重算，精确相等 |
| 真实空块锚点 | SE 截到 155802（2026-10-10 18:00 UTC）；7d 的锚点 155634（2026-10-03 18:00 UTC）是真实的空块小时，48 条序列在那里全是 `null` | `test_a_real_no_block_anchor_blanks_only_that_window` | `no_block == ["7d"]`；7d 窗口每档的三项都是 `None`，其余三个窗口（锚点 155778 / 155082 / 153642）全部有值 |
| 抓取时的一致性核对 | `price_close` 窗口 | 同一分钟内重取，与原文件的 `version`（89）和全部值都一致 | 一致。这只说明 `price_close` 没被修订；48 条 size 序列另由终审在 10-19 的重叠区核对：`addrs_over_100k_btc_supply` 在 2,093 个重叠位置全部相同（version 124746337），写在 fixture README 里 |

### 前端（页面记录 + 评审复算）

| 项目 | 数量 | 比对方式 | 结果 |
|---|---|---|---|
| `size-cohorts-expected.json`（原站 2026-10-19 06:16 / 06:21 UTC 的线上读数，SR-5.md:22-30、39-61，SR-6.md:21-31） | 图 5 的标签与图例 8 组（4 个窗口 × BTC / %）、默认读数 1 组、轴 16 组（Bands / Entities × BTC / % × 4 个窗口）；图 6 的标签、图例与轴 7 组、读数 5 组 | `size-cohorts.test.ts` 逐项断言（标签、图例、刻度、柱数、正负、读数） | 全部相等 |
| 评审复算（Task 4） | 同上全部条目 | 独立的 Python oracle（移植了 d3 的 `ticks`），从阶段 B 的页面全局重算 | 0 处差异 |
| 文案 | 每种语言共 70 个键（`sizes.*` 69 个加 `flows.sizes`；Task 4 加 34 个，Task 5 加 36 个），en 与 zh 一一对应 | `i18n.test.ts` 核对键一致，并逐字核对 10 对（`flows.sizes`、两个标题、`sizes.noBlock`，以及终审修复轮改过的 `sizes.bands`、`sizes.pctBand`、`sizes.supply.share`、`sizes.supply.held`、`sizes.pnl.none`、`sizes.pnl.implies`），断言 zh 的 `sizes.*` 不再出现"本组""该组"；Task 5 评审另把 50 个键与 brief 的两张表逐字比对 | 0 处差异 |
| 用例数 | `size-cohorts.test.ts` 55 个、`size-cohorts-charts.test.tsx` 19 个起，另有 `onchain-contract.test.ts`、`client.test.ts`、`flows-panel.test.tsx`、`market-defaults.test.tsx` 追加 | 见第 1 节 | 通过 |

**不是逐格页面记录的 expected 项**（`source` 字段已写明）：
- Net 视图的标签：阶段 B 只记了柱数、正负和轴端点；按原站代码 Net 与 Gross 都打印 `plfmt(d.net)`（A:2301-2307），所以用 Gross 已记录的净额标签；
- Net 视图的刻度：只记了两端 `±4e8`，存为两项，测试只比首尾；
- Mid、Small、Retail 三行图 6 读数的 foot：把各自已记录的份额套进 Large 行已记录的措辞；
- 样本里没有 null 格、`no_block` 为空，所以 "—" 与无块的前端用例都是复制样本再置 null 构造的（`blanked()`），样本本身没有改。

## 3. 真实数据链路

**请求数**（由 `test_size_requests_stay_under_the_url_limit` 守住，断言写 `<= MAX_SERIES_CHARS`，不写死上限的数值）：

| 轮次 | size 阶段的请求 | 说明 |
|---|---|---|
| 首次回填 | 8 次 | 每次 6 条、`start=-3000`，每片 `series` 最长 273 字符 |
| 增量（每小时） | 2 次 | 47 + 1 个名字，较长的一次约 1,970 字符；48 个名字拼起来是 2,003 字符，大于 `MAX_SERIES_CHARS`（2,000），所以必须拆 |

**controller 的验证实例**

实例配置：分支 `claude/size-cohorts` @1278897，analytics 起在 8797（`WHEELHOUSE_RULES=v1`、`WHEELHOUSE_PERPS=off`，数据目录是主检出 `onchain.sqlite` 的备份副本），overlay 起在 1430。

- **首轮实时同步（含 size 回填）**：用时约 22.6 s，之后每轮 17–19 s。
- **`/onchain/size-cohorts` 返回**：fresh，`last_at` 2026-10-20 03:00 UTC。
  - `forming_at` 也是 03:00，页头写 "includes the forming hour"；
  - 12 档，`no_block` 为 `[]`。

**库体积**

| 项目 | 回填前 | 回填后 |
|---|---|---|
| `series` 表中 `addrs_*` 的行数 | 0 | 144,000（= 48 × 3,000，与设计值一致） |
| 验证实例 `onchain.sqlite` 体积 | 63,545,344 B（10-19 23:18 UTC 的副本） | 80,838,656 B（10-20 03:58 UTC） |

注：体积的差值不全是 size 回填。还包括这几小时里图 3/4 的输入（年龄快照、日高低价）以及各 hour1 序列的正常增长，所以只能作为上限参考。

之后每天新增 48 × 24 = 1,152 行（hour1 不裁剪）。

## 4. 浏览器检查

2026-10-20 03:31–03:58 UTC 检查。
- 宽屏：自动化窗口是全屏的 2,056 px，`resize_window` 无效，所以直接在全宽下检查。
- 390 px：用真实点击打开 390 宽的同源弹窗，再读它的 DOM。

| 项目 | 宽屏（2,056 px） | 390 px |
|---|---|---|
| 打开 `?method=flows&flow=sizes` | 两张图都正常渲染 | 正常 |
| 图 5 默认（7d / Entities / BTC） | 4 行、标签、图例、7 个刻度（±15,000，步长 5,000） | SVG 宽 330、高 300，无越界文字 |
| 图 6 默认 | 4 行、净额标签、刻度 ±$1.00B / $500.0M、图例 | SVG 宽 330、高 300，无越界文字 |
| 控件切换 | Bands、Gross、30d 切换后数值与原站一致（见第 5 节） | 切到 Bands 和 Gross 后两张图都是 330×354，无越界文字 |
| 键盘读数 | 聚焦图 6 后按 ArrowDown，读数为 "10k–100k BTC · Profit booked +$273.4M · Loss booked −$412.4M · Net −$139.0M · vs realized cap −0.114% · 40% of booked value was profit · 7d window"。Home、End、Esc 由单测覆盖，浏览器里没有逐个按。焦点环这次没有目视检查：`market.css` 的 `.wh-market :focus-visible` 覆盖这个 SVG，留到下面的 1440 弹窗检查里看 | — |
| 5 个子视图按钮 | 一行 | 换成两行（容器宽 352 px），没有截断。这次检查时，两行的边框问题（SR3-4 遗留的 T7-M7）还在：第一行末端是双线，两行之间没有分隔线。终审修复轮已改（M5，见表后） |
| 12 档 Gross 的标签 | 都在 SVG 内 | 都在 SVG 内 |
| 三栏说明 | 横排 | 纵向全部展开，每栏宽 330 |
| `scrollWidth` | 等于窗口宽 | 390 |
| zh | 切换条显示：卖压、卖方结构、成本分布、规模分组、永续状态。图内文字、档名（如"高于 100k BTC"、"10M 聪–1 BTC"）、图例和三栏说明都已翻译，数值不变 | — |
| 控制台 | 重新加载并切换控件后无报错 | — |

终审修复轮（M1、M5）：
- M1：负值标签会压到行名时（宽版是本行的，窄屏是下一行的），改放在条内末端，用深色墨（SPEC"规模分组"偏离第 10 条）。单测钉住了宽版 720 / 1,160 / 1,280 px 和窄屏 336 px（12 行、4 行、zh）。窄屏这一半是 controller 在 390px 弹窗里发现后补的（`46bd4fb`）。
- M5：Flows 切换条的分隔线改为每个按钮左侧和上方 1px 的 box-shadow，容器边缘的那一段被裁掉；换行后按钮撑满每一行。修复轮用 headless Chrome 只渲染 `market.css` 和切换条做了核对：
  - 390 px：两行，行间有一条通栏分隔线，第一行末端没有双线；
  - 宽屏一行：外观不变，只是整条窄了 4 px（454.8 → 450.8），因为原先每条右边框占 1 px；
  - 视口宽于 600 px 但容器窄到换行时，按钮同样撑满每一行。

  这只核对了样式，不是在真实页面里看的。

1440/1024 弹窗检查（M1、M5，终审修复轮之后，2026-10-20）：
- 1024 px：`scrollWidth` 1024；Bands 视图下两张图在 1d/7d/30d/90d × Net/Gross 共 16 种组合里，值标签与行名的文字框 0 处相交；最长负值条的 −15,781 移进条内，深色字（`--wh-surface`，约 6:1）。
- 1440 px：`scrollWidth` 1440；没有相交，也不需要移进条内；切换条一行（469 px）。
- 390 px：`scrollWidth` 390；切换条两行，第一行 4 个按钮铺满、第二行 Perp states 占满，分隔为单线；16 种组合里只剩图 6 Bands · 7d · Net 的 −$171.7M 与下一行行名文字框有一处 3.4 × 0.8 px 的角接触（条只有 43 px 宽，放不进条内），字形不相碰，接受。
- 焦点环：键盘聚焦图 5 的 SVG 时 `:focus-visible` 生效，2 px 青色实线（rgb(89, 230, 205)），目视可见。

## 5. 与原站同刻对照

本地先在 03:50:46 UTC 重新同步，随后立即重新加载原站。两边读到的是同一个仍在形成的小时（03:00 UTC），对照结果如下：

| 项目 | 原站 | 本地 | 结果 |
|---|---|---|---|
| 图 5 默认四行（Large / Mid / Small / Retail） | −8,526 / +17,177 / −2,624 / −2,690 | 同左 | 相同 |
| 图 5 刻度 | ±15,000，步长 5,000 | 同左 | 相同 |
| 图 5 图例 | +17,177 / −13,840 / +3,337 BTC | 同左 | 相同 |
| 图 5 Bands · 7d 的 12 行 | +6,711 / −15,237 / +14,806 / +2,371 / −1,393 / −1,231 / −2,958 / +162 / +106 / −0 / +0 / +0 | 同左（含原站的 "−0 / +0"） | 相同 |
| 图 5 Bands 图例 | +24,157 / −20,820 / +3,338 BTC | 同左 | 相同 |
| 图 6 默认四行 | −$139.0M / +$189.1M / +$550.2M / +$276.7M | 同左 | 相同 |
| 图 6 刻度 | ±$1.00B，步长 $500.0M | 同左 | 相同 |
| 图 6 图例 | Profit booked +$2.54B / Loss booked −$1.66B | 同左（本地 Net +$877M） | 相同 |
| 图 6 Gross · 30d 四行净额 | +$1.67B / +$6.47B / +$3.18B / +$1.05B，刻度 ±$10.00B | 同左 | 相同 |

第一次对照时两边不一致。原因是本地在 03:31 算出的那个仍在形成的小时，到 03:50 原站加载时已经多了几个区块；重新同步后完全一致。

## 6. 与原站的有意偏离和遗留

### 与原站的有意偏离

详见 [SPEC.md](SPEC.md) "规模分组"一节的"与原站的有意偏离"：

1. null 显示 "—"、不画柱（原站当 0，无块锚点时会画出整条累计量的假柱，图 5 约 +5.27M BTC、图 6 约 +$558.8B）；Entities 下缺成员则整组缺失，图例遇缺失行显示 "—"。
2. 百分比的分母无效显示 "—"（原站给 0）。
3. 图 6 读数的 `vs realized cap` 在 `realized_cap` ≤ 0 时显示 "—"（原站 `n/a`）。
4. 无块锚点的窗口在图下说明原因（`sizes.noBlock`），不显示通用的"此图暂无数据"。
5. 读数行代替浮动 tooltip。
6. 窄屏改排版，不整体等比缩小。
7. 图内由 JS 生成的文字全部翻译。
8. Net 图例色块用墨色 `#e5edf6`，与图 6 的净额竖线一致。
9. 三栏说明是我们起草的（原站两张图只有一行 caption）。
10. 负值标签会压到行名时（宽版是本行的，窄屏是下一行的），改放在条内末端（原站宽版也会压，终审 M1 及其补修）。

### 交用户审的文案

- 终审修复轮（`635bd7d`）已改，请一并审：
  - zh `sizes.bands`："分组"改为"区间"，它切换的是 12 个规模区间；
  - zh 里指"这一行"的"本组 / 该组"都改为"本档 / 该档"，因为 Bands 下一行是一个区间，不是一组：`sizes.pctBand`、`sizes.supply.share` 改为"占本档比例"，`sizes.supply.held` 改为"本档持币量"，`sizes.pnl.none` 改为"该档没有币移动"；`sizes.supply.shows`、`sizes.pnl.shows`、`sizes.pnl.implies` 里的同一说法也一起改了；
  - `sizes.noBlock` 不再说"下一次刷新补上"：en 改为 "It usually fills in within an hour or two, once the window's start moves past that hour."，zh 改为"通常一两个小时内、窗口起点移过这一小时后就会补上。"；
  - `sizes.pnl.implies` 末句的分母是该档全部持币的已实现市值：en 改为 "a share of what the band paid for everything it holds"，zh 改为"占该档全部持币买入成本的比例"。
- 全部三栏说明（`sizes.supply.shows` / `implies` / `how`、`sizes.pnl.shows` / `implies` / `how`）的中英文措辞都是我们起草的，交用户审定（OP-4）；按钮、图例、读数、两侧小字、`sizes.noBlock` 等其余文案随同一次审阅。

### 遗留问题

计划里已记录：
- 页头 forming 提示在 HH:00–HH:12 之间仍写 "includes the forming hour"，与卖压、Sell side 共有，三处要一起修；
- size 阶段持续 5xx 时，整轮每 5 分钟重试（hour1、URPD 失败时的已有行为）；
- 无块锚点的窗口显示 "—"（OP-1）；若嫌空白，另立 O3 版本（向前沿用上一小时），本计划不做。

终审修复轮之后仍留着的：
- 文案交用户审（OP-4），见上一小节；
- 卖压、Sell side、图 2 各内联了一份三栏说明。`ReadColumns` 已移到共享的 `flow-notes.tsx`，以后单独把这三份换成它（终审 §5）；
- 提速办法（不在本计划内）：会话级的首轮同步模板库（终审 §6）；
- pytest 的 1 个 warning 是仓库原有的 Starlette/httpx 弃用提示，与本分支无关。
