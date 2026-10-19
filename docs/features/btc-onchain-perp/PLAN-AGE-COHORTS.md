# 计划：state-report 图 2（Sell Side Breakdown by All Age Cohorts）

日期：2026-10-19（独立复核后修订）。依据：[CHART-VERIFICATION.md](CHART-VERIFICATION.md) 的 SR-2，阶段 A/B 记录（`.local/research-samples/alpha-dashboards-2026-10-16/verification-2026-10-19/verify/SR-2-A.md`、`SR-2.md`），原站源码 `state-report/raw/script_3_app.js:219-245`（loader）和 `raw/script_2_app.js:3146-3412`（图）。

用户 2026-10-19 要求按顺序把 state-report 缺的图做出来，先做图 2。和 1A/1B 一样：原站有做法的一律照原站；原站没有的（三栏说明）先写一版给用户审。

## 已定的做法

| 事项 | 做法 | 理由 |
|---|---|---|
| 位置 | Flows → **Sell side**，接在 1B 下面 | [PLAN-SELL-SIDE.md](PLAN-SELL-SIDE.md) 已定"以后图 2 也放这里" |
| 控件 | 照原站六组：Span 1d/7d/**30d**/90d、Smoothing 1h/**24h**/168h、Measure **Realized P&L $**/Spent vol BTC/Spent vol $、Detail **6 bands**/12 bands、Scale Relative/**Absolute**、Cohorts ☐ One at a time。和图 1 的控件**互不联动**（原站就是两套） | 照原站 |
| 计算分层 | 同 1A/1B：worker 做原站 loader 那段（行闸门、逐群体差分 clamp、并成 12 档、量化），前端做原站 `build()` 那段（SMA、并 6 档、可见合计、Span、Relative） | 隐藏某档会改变保留的行和分母，只能在前端做；读接口仍只读库 |
| 规则 | 只有 v1；最后一行若是正在形成的小时，照原站画进去、读进图例，并标 forming | 同 1A/1B |
| 配色 | 直接用原站暗色主题的年龄色阶：6 档 `#ffcd7d #ffbc7f #d7aa80 #a29980 #678680 #00747e`，12 档 `#ffcd7d … #00747e`（`state-report.html:66-67`） | 原站专门按亮度单调设计（新浅旧深，色盲和灰度下仍有序），本地也是近黑底，照搬即可 |
| 图例数值 | 照原站 d3 `~s`：6 位有效数字、去尾零、G 写成 B，例如 `$4.50625M`、`183.629 BTC`。把 `sell-side.ts` 里的 `si` 换成 d3-format 的逐行移植（含 m/µ 等小于 1 的前缀）。1A/1B 的黄金用例不变；小于 1 的刻度会改成和原站一样（原站图 1 也用 `~s`） | 照原站；现在的 `si` 在 999999.5 这类边界和小于 1 的值上与 d3 不同 |
| 悬停 | 照原站：**图例始终读最新一行**，悬停只移动光标和浮动读数框（与 1A/1B 不同，1A/1B 的图例跟随悬停）。读数框标题 `19 Oct 2026 · 05:00`，每个可见且 p+l>0 的档一行 `$p / −$l`，页脚 `profit / loss · total … · spot $…`；方向键同样可读 | 原站图 2 没有 foot 行，悬停框是唯一的逐档读数；1A/1B 是用图例 + foot 代替 |
| 图例交互 | 照原站：悬停（及键盘聚焦）某档时其他档透明度 0.15；点击切换显隐，不能全隐藏；勾选 One at a time 后点击变单选；切换 Detail 时重置（全开，单选模式下选第一档）；Relative 且有隐藏档时提示 "shares of the N visible band(s), not the whole sell side" | 照原站 |
| 价格线 | 照原站：在保留的行上连续画，不因缺行断开（与 1A/1B 不同，图 2 原站就不断） | 照原站 |
| 图高 | 同 1A/1B，随宽度 300–440px | 一致 |
| 三栏说明 | 原站没有，起草中英文给用户审；本图没有阈值，"What extreme values imply" 只写读法上的极端情形 | AGENTS.md 规定 Flows 每张图都有三栏 |

## 后端

1. **`onchain/brk.py` 分片修复（先做）**：`series()` 现在只按点数分片。实测（2026-10-19 13:5x UTC，httpx）BRK 按**解码后**的 `series` 参数长度限制：1,997 字符通过，2,053 字符返回 400。改为同时限制拼接长度 ≤ `MAX_SERIES_CHARS = 2000`，按顺序贪心装片。删掉 `test_onchain_sellside.py` 里"名字总长 < 1500"的守卫，换成 brk 的分片测试。
2. **`brk.py`**：`AGE_COHORTS`（23 个，照原站顺序）、`AGE_SUFFIXES`（6 个）、`AGE_SERIES`（138 条全集）。其中 12 条已在 `HOUR1_SERIES`/`SELL_SIDE_SERIES` 里，新拉的是其余 126 条（`AGE_ONLY`）。
3. **`onchain/sync.py`：新的独立 stage**（审阅 CHART-VERIFICATION 时的建议，126 条加进现有 stage 会让卖压的失败概率随请求数上升）：
   - 现有 hour1 stage 不变；之后单独 `try` 一次 `_increment(AGE_ONLY, "hour1", …)`，有自己的 `age_missing`、`age_error`。
   - 失败只影响图 2：卖压、1A/1B 照常派生；本轮记为失败（同 URPD 失败的处理），`last_error` 记它的码，可重试时尽快重跑。
   - 两个 stage 的缺失集合分开：图 2 stage 失败时取库里上次记录的缺失 ∩ 126 条；第一个 stage 失败时取上次记录 − 126 条。否则一个 stage 的旧缺失会在另一个 stage 成功后残留。缺失原因 `series_missing:hour1:<name>` 覆盖 126 条新序列。
   - 首次没有存量时走现有整段回填（`-3000` 点，每片 6 条，约 21 次请求）；之后每轮约 4 次增量请求。
   - 新增 `_derive_age_cohorts(missing, at)`：输入是 **139 条**（`price_close`、与 1A/1B 共用的 12 条、新的 126 条）。`missing` 与之有交集时清掉旧结果（unavailable，不用 0 代替），即使本轮图 2 stage 失败也清；计算出错时记固定码 `agecohorts_failed`、清掉旧结果，不影响其他视图。
   - **时间戳**：图 2 也读第一个 stage 的序列，所以只有两个 stage 本轮都成功时才派生，并用第一个 stage 的完成时间 `hour1_done` 盖戳（与卖压一致）。否则若第一个 stage 失败、图 2 stage 成功，最后一行可能是上一轮抓到的未收盘值，却会被当成已收盘。任一 stage 失败时保留库里的旧结果和旧时间戳。`derive_from_store` 用库里图 2 自己的时间戳。
   - `VIEWS` 加 `"agecohorts"`；`rules.py` 的 `View` 加 `"agecohorts"`（未实现任何规则）。
4. **`onchain/agecohorts.py`（新，纯函数）`age_cohorts(rows) -> AgeCohorts | None`**，逐条照原站 loader（`script_3_app.js:219-245`）：
   - 回看 `V1_LOOKBACK = 2600` 个小时位置，窗口终点取 `price_close` 的最后一小时（两个 stage 之间若跨过整点，126 条可能多一小时，按全部输入取终点会让窗口错开一行），按时间对齐。
   - 行闸门：本小时价格不为空，且 **138 条**在本小时和上一小时都不为空，否则整行丢弃（比图 1 严，三种口径共用一个闸门）。
   - 每个群体 `max(0, C[h] − C[h−1])`，按 12 档相加（照原站顺序累加）。
   - 量化在**档合计**上做：P&L $100、USD 量 $1000（半进位，同 `Math.round`），BTC 量 0.1（`Decimal` 半进位，同 `toFixed(1)`）；价格 0.1。复用 `sellside._round`。
   - 输出列式：`at[]`、`price[]`，`pnl`/`volb`/`volu` 各含 `profit[12][n]`、`loss[12][n]`（已乘回原单位，与 1A/1B 一致），另有 `last_at`、`latest_at`、`rules=[]`。没有 QC 码（图 2 无剔除）。
5. **`onchain/models.py` + `onchain/api.py`**：`GET /api/wheelhouse/v1/onchain/age-cohorts` → `AgeCohortsView`（`data_state`、`reasons`、`refreshing`、`forming_at`、`last_at`、`at`、`price`、`pnl`、`volb`、`volu`、`brk_version`、`rules`、`rules_pending`），只读 derived。无数据时 `unavailable`，各列为空。`/status` 不改。
6. `make contract`。

**体积**：库里新增约 126 × 3,000 行（约 60–70 MB），之后每天约 3,000 行。不加裁剪（不删数据）。接口约 2,580 行 × 72 个数（约 18.6 万个数），未压缩约 1.5–1.9 MB（服务没有 gzip）；每 5 分钟轮询一次。

## 前端

1. **`age-cohorts.ts`（新，纯函数，照原站 `script_2_app.js:3181-3237` 与 `render()`/`legend()` 的取值部分）**：
   - `BANDS12`、`FOLD = [[0,1],[2],[3,4],[5,6],[7,8],[9,10,11]]`、`NAME6`；`Choice`（measure、smoothing、span、detail、scale、on[12]、solo）与 `DEFAULT_AGE_CHOICE`。
   - `buildAgeRows`：12 档各自尾随 SMA（复用 `sma`），按 `src` 顺序相加成档；`tp+tl > 0` 才保留（168h 下的 `-0.0` 残差不画）；取最后 span 行。
   - `ageAxis`：`[−dn·1.04 || −1, up·1.04 || 1]`，Absolute 再 `nice()`，`ticks(6)`；刻度标签取绝对值。`niceDomain` 不改：复核实测它与 d3 只在起止相等的退化域上不同，图 2 碰不到。
   - 合计照原站：`tp`、`tl` 分别按档序累加可见档，再 `tot = tp + tl`；每行的上下高度同理。
   - 格式：`fmtV`（`$`+`~s` / `~s`+` BTC`，负号用 `−`）、`fmtP`（`.0%`）、悬停框时间。
   - 选择逻辑：`toggleBand`、`withSolo`（勾选时只留第一个可见档，取消时全开）、`withDetail`，与原站一致；悬停一个已隐藏的档时，所有可见档都变淡（原站如此）。
2. **`age-cohort-chart.tsx`（新）**：一次查询（5 分钟刷新），状态提示同 1A/1B（unavailable / delayed / stale / forming / refreshing / reasons）；一块面板：标题、控件、图（上下发散堆叠柱，零轴，左轴绝对值，右轴价格，左上 "profit ↑"、左下 "loss ↓"，forming 那一列描边）、浮动读数框、图例、Relative 提示、三栏说明。复用 `timeTicks`、`useChartWidth`（已导出）和 `Segments`（从 `sell-side-charts.tsx` 导出）。
   - 90d × 12 档约 5.2 万个单元：每档画成**一条 path**，悬停图例只改 12 条 path 的透明度，几何部分 memo 住不重算。
   - 某个选择下一行都不剩时（例如 168h 下只留一个全为 0 的档），显示"此图暂无数据"，控件和图例照常可用（图例值显示 "—"），用户可以换回来。
3. `sell-side-charts.tsx` 末尾挂上图 2；`client.ts`（`getAgeCohorts`）、`onchain-contract.ts`（zod：12 档、各列与 `at` 等长）、`i18n.ts`（中英，原站中文字典直接用）、`market.css`（`--wh-age6-*`、`--wh-age12-*`）。

## 测试与验证

- **后端黄金样本**：同一时刻用 bulk 抓 139 条（138 + `price_close`）各 400 点，放进 `tests/onchain/fixtures/brk-2026-10-19T1453Z/`（约 0.8 MB；139 条起止相同，含 2 个无块小时）。期望值由**原站 loader 代码原样**在 node 里跑这批数据得到（`script_3_app.js:33-47`、`219-247` 照抄，只替换取数）。要求后端每档每行逐值相等。
- **同步测试夹具**：10-16 的回放夹具补 126 条新序列，只取最后 25 小时（约 60 KB，同时重抓 3 条旧序列确认 BRK 没有修订那段）；回放 BRK 照实测加上 `series` 参数长度上限（> 2,048 字符返回 400），分片一旦退化，所有 sync 测试都会失败。
- **后端单元**：闸门（任一条为空丢行；无块小时连带丢下一行；价格为空丢行）；逐群体先 clamp 再相加；量化在档合计上做；回看 2600；按时间对齐；brk 按长度分片。
- **sync 回归**：图 2 stage 失败时卖压和 1A/1B 照常、图 2 保留旧结果和旧时间戳、`last_error` 记它的码、5 分钟后重试、`last_success_at` 不前进；第一个 stage 失败、图 2 stage 成功时图 2 也保持原样；两个 stage 的缺失集合互不残留；共用序列缺失时即使图 2 stage 失败也清掉图 2；`derive_from_store` 有无旧结果两种情况；只缺一条图 2 序列时图 2 unavailable 并给出原因，且不出现在 `/sell-side`、`/seller-pressure`、`/status`；共用序列缺失时 `/age-cohorts` 和 `/sell-side` 都给出原因；接口不访问网络。
- **前端黄金**：另抓一份 1000 点（2026-10-19 15:10Z），经后端算成前端样本（995 行，约 0.5 MB），这样 30d 与 90d 能区分、168h 平滑后仍有足够的行；后端在这份数据上同样与原站 loader 逐值一致。期望值由**原站图 2 代码原样**（`script_2_app.js:3181-3237`、`3255-3258`，以及 `render()`、`legend()`、图例点击、Detail 与单选处理、tooltip 里产生数值的语句）加 d3（d3-array 3.2.4、d3-scale 4.0.2、d3-format 3.1.2，取自本地 Wealthfolio 依赖；原站内嵌的 d3 7.9.0 带 d3-format 3.1.0，复核确认两者对有限值输出相同）在 node 里跑出，共 54 个用例：3 种 Measure × 3 种 Smoothing × 2 种 Detail × 2 种 Scale，4 档 Span，外加 10 组隐藏档、单选、切换 Detail 的操作序列。比较图例、Relative 提示、Y 轴域与刻度文字、价格轴刻度、行数、首末行时间、柱段数、最新一行与中间一行的悬停框文字。
- **前端单元与组件**：图例切换/单选/Detail 重置；悬停图例时只改透明度、元素不重建；悬停图表时图例不动、读数框跟随；最后一档不能隐藏；无数据和 unavailable 不画 0、无行时控件和图例仍可用；zod 契约（12 档、各列等长）；中英文键一致。
- `make check` 全绿。
- **浏览器**：本地 `?method=flows&flow=sellside` 与原站同一时刻比：页面全局 `AGEPL` 与本地接口逐行逐值比（哈希），默认视图和几组控件的图例逐字比；390px（弹窗法）与控制台；截图给用户。

## 不做

- O1–O6 在图 2 上的版本；hour1 裁剪；原站隐藏的价格叠加开关（原站页面上没有这个控件，价格线恒开）。
