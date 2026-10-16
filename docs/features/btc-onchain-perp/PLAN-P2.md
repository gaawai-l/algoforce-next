# BTC 链上融合 P2（卖压）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标**：照原站 onchain-seller 的 v1 口径，实现 BTC 卖压三张图，放在 Flows tab 的 Seller pressure 子视图里。

**架构**
- P1 的 onchain worker 新增一个 hour1 阶段，与 day1、URPD 两个阶段的失败互相隔离。
- 新增纯函数模块 `pressure.py`，结果存入 `derived` 表，`kind="pressure"`。
- 新增只读接口 `GET /onchain/seller-pressure`。
- 新增前端组件 `seller-charts.tsx`，照原站把三张图上下排列。

**技术栈**：同 P1。

**Spec**：[SPEC.md](SPEC.md) v3，相关章节 §3.0、§3.3、§5、§6。用户已授权全部阶段连续执行。本计划第一版经过一轮独立评审，修订记录见文末。

## 计划层面的裁定（执行前已定）

| 编号 | 裁定 | 理由 |
|---|---|---|
| P2-R1 | hour1 不取 `timestamp` 序列，共 11 条 | 时间由位置推出，与 BRK 的 timestamp 逐点相同（评审已核对）。少取一条，就少一个因单条缺失而清空整个卖压视图的触发点 |
| P2-R2 | hour1 的缺失原因码写成 `series_missing:hour1:<name>`；day1 保持 `series_missing:<name>` 不变，与 P1 兼容 | `price_close` 同时存在于 day1 和 hour1，需要区分 |
| P2-R3 | hour1 阶段放在 day1 阶段之后、URPD 之前，与 URPD 的做法相同：单独捕获错误，cycle 和 levels 照常派生；不往共享 reasons 里加 `brk_unavailable`，错误只记在 `last_error`，过 5 分钟重试；`last_success_at` 不推进 | 一个模块的故障不应牵连别的模块（spec §3.0，对应 P1 的 R12） |
| P2-R4 | hour1 不单独处理 BRK 服务版本变化，只靠每条序列自己的 `version` 检测：任何一条变了，就从 `-HOUR1_BACKFILL` 整条重取 | 机制更简单；版本变化时每条序列的 version 本来也都会变 |
| P2-R5 | 由派生结果的 `computed_at` 判断最后一行是否未收盘：`computed_at < last_at + 1h` 时 `forming_at = last_at` | worker 在 HH:12 取数，那时最后一行还没收盘，之后不管当前时间是多少都是如此 |
| P2-R6 | SPEC §3.0 写的"hour1 首次回填分 3 片"按实际计算改为 2 片 | 11 条 × 3000 点，每片上限 18,000 点，即每片 6 条，共 2 片 |

## 全局约束（沿用 P1，增补如下）

**数据**
- `HOUR1_SERIES` 共 11 条：
  - `price_close`
  - `sth_realized_profit_cumulative`、`sth_realized_loss_cumulative`
  - `lth_realized_profit_cumulative`、`lth_realized_loss_cumulative`
  - `utxos_under_1h_old_realized_profit_cumulative`、`utxos_under_1h_old_realized_loss_cumulative`
  - `sth_supply_in_loss`、`sth_supply_in_profit`
  - `utxos_under_1h_old_supply_in_loss`、`utxos_under_1h_old_supply_in_profit`
- `HOUR1_BACKFILL = 3000`：首次回填和整条重取都用 `start=-3000`，**绝不使用 `START`**。增量取数从 `last_position − 3` 开始。
- BRK 接受负数 start，返回体中的 start 是绝对位置（评审实测）。`brk.py` 估算点数时，负数 start 按 `-start` 计。

**计算口径（原站 v1；规则已与 `compute.py` 逐位核对）**
- 输入按时间对齐，不按下标对齐，只取最近 `LOOKBACK = 2600` 个小时。
- 行过滤：价格和 4 条累计值在本行和上一行都不为空，才保留该行。
- 每条腿 = `max(0, C[i] − C[i−1])`，按 $100 取整：`floor(x/100 + 0.5)`。
- 剔除持有 <1h 的币：
  - SPx1 用未取整的原始差值计算：`round(max(0, ΔSTH_P − Δu1h_P) / 100)`；SLx1 同理。
  - 本行或上一行的 <1h 累计值为空时不剔除，并记一次 `xgap`。所以一个空值通常会让 xgap 加 2：本行和下一行各 1。
- 三张图（每张图都附价格线）：

  | 图 | 每行的值 | 规则 |
  |---|---|---|
  | 图 1 | `(LL + SLx1)·100` 美元，LTH 和 STH 分开 | 每个保留行都有值 |
  | 图 2 | `SLx1 / (LP + LL + SPx1 + SLx1)`，用取整后的整数单位计算 | 分母 ≤ 0 时跳过该行 |
  | 图 3 | `(sth_in_loss − u1h_in_loss) / (同口径的 in_loss + in_profit)` | 只在图 1 保留的行上取值；任一项为空或总量 ≤ 0 时跳过 |

- **阈值**：每张图各自计算，取 `t > t_last − 720h` 范围内的值，`t_last` 是该图自己序列的最后一行（包含它）。用 R-7 分位算 P95 和 P75，同时记下样本数 `n`。
- **`last_at`**：图 1 最后一个保留行的时间，与原站 "Data" 显示的时间一致。

**hour1 新鲜度 `HourState`**
- 取值：`fresh`（≤2h）、`delayed`（≤6h）、`stale`（>6h）、`unavailable`。
- `/status` 的 `DatasetStatus.data_state` 改用 `HourState`。它是 `DataState` 的超集，day1 和 URPD 永远不会出现 `delayed`。

**原因码与清空规则**
- 卖压视图的 reasons 只保留 `series_missing:hour1:*` 和 `brk_unavailable`。
- `/status` 中 day1 数据集不显示 hour1 的原因码。
- `HOUR1_SERIES` 中任何一条缺失，就把 pressure 整个清空（`clear_derived("pressure")`）。为此 `_derive` 要收到本轮缺失序列的集合。

**接口载荷**：`/seller-pressure` 的每组点只返回最后 2160 个（最大 Span 就是这么多），但阈值始终按完整数据计算。

**文案**
- 三段说明（What it shows / What extreme values imply / How to read）用自己的话概括原站的意思，不照抄。en 和 zh 都要有。
- 数值格式：
  - 阈值金额保留 1 位小数，例如 `$41.3M`；
  - 图例和当前值的金额保留 2 位小数，例如 `$1.98M`；
  - 百分比保留 1 位小数。
- 时间轴和 tooltip 一律用 UTC。

**P1 测试**：P1 中写死"只有 day1"的断言（例如所有 bulk 的 start 都是 START、序列名集合等于 DAY1_SERIES、`/status` 的 datasets 列表、flows-panel 的占位文案和"没有数字"）随功能改动一起更新，不能删掉它们原本覆盖的行为。

## 评审重点（Review Focus）

1. **库里的 hour1 超过 2600 行**：计算结果与只存 2600 行时完全相同。测试在 Task 2。
2. **没有出块的小时**：这一行和下一行都被丢弃；阈值窗口按时钟计算，不会因此拉长。测试在 Task 2。
3. **hour1 阶段失败**：cycle 和 levels 照常更新，共享 reasons 里不出现 `brk_unavailable`，卖压随时间退化为 delayed 或 stale。测试在 Task 3。
4. **P1 已在运行的库里第一次加入 hour1**：只回填 hour1，不重取 day1。测试在 Task 3。
5. **ETH，或卖压不可用**：不画空坐标轴，不补 0，显示原因。测试在 Task 6。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `onchain/brk.py`（修改） | `HOUR1_SERIES`、`HOUR1_BACKFILL`；负数 start 的点数估算 |
| `onchain/store.py`（修改） | `read_series(..., tail: int \| None = None)`：只读最后 tail 行 |
| `onchain/pressure.py`（新建） | `seller_pressure` 等纯函数 |
| `onchain/sync.py`（修改） | 加入 hour1 阶段、失败隔离、派生 pressure |
| `onchain/models.py`、`onchain/api.py`（修改） | `HourState`、`hour1_state`、`SellerPressureView`、`/seller-pressure` 接口、`/status` |
| `tests/onchain/fixtures/brk-2026-10-16/hour1_*.json`（新建）、`onchain_fixture.py`（修改） | fixture；transport 支持负数 start，以及按 index 注入失败 |
| `tests/onchain/test_onchain_pressure.py`（新建）；`test_onchain_{brk,store,sync,api}.py`（修改） | 后端测试 |
| `openapi.json`、`api-schema.d.ts`（由 `make contract` 生成） | 契约 |
| `onchain-contract.ts`、`client.ts`（修改） | `sellerPressureSchema`、`getSellerPressure`、`pressureSample` |
| `seller-charts.tsx`、`seller-charts.test.tsx`（新建） | 三张图 |
| `flows-panel.tsx`、`flows-panel.test.tsx`、`i18n.ts`、`market.css`（修改） | 把卖压接入 Flows |
| `docs/features/btc-onchain-perp/P2-VERIFICATION.md`（新建） | 核验记录 |

---

### Task 1：hour1 常量、负数 start 与 fixture

**Files**
- 修改：`onchain/brk.py`、`onchain/store.py`、`tests/onchain/onchain_fixture.py`、`tests/onchain/test_onchain_{brk,store}.py`
- 新建：11 个 `hour1_<series>.json`；README 增补

**Interfaces**
- 产出：
  - `HOUR1_SERIES`、`HOUR1_BACKFILL`
  - `_points`：负数 start 按 `-start` 计
  - `OnchainStore.read_series(name, index, tail=None)`
  - fixture 端：`load_series(name, "hour1")`；`brk_transport(..., fail_index: set[str] = frozenset())`，`fail_index` 中的 index 一律返回 503
  - `_bulk` 支持负数 start（取最后 N 行，返回体的 start 写绝对位置），并放宽 `start >= raw.start` 的断言

步骤：

- [ ] **Step 1**：从 `.local/research-samples/alpha-dashboards-2026-10-16/onchain-seller/data/h_<series>.json` 原样复制 11 个文件（不含 `h_timestamp`），最后一行是 2026-10-16 09:00。README 写明每个文件的 stamp、version、start 和 end。

- [ ] **Step 2：写失败的测试**
  - `test_hour1_backfill_uses_negative_start_and_two_chunks`：`series(HOUR1_SERIES, "hour1", -3000)` 发出 2 个 bulk 请求，每个最多 6 个序列名，`start` 参数都是 `-3000`，`found` 中有 11 条。
  - `test_negative_start_points_estimate`：start = −3000 时估算为 3000 点。
  - `test_read_series_tail_returns_last_rows`

- [ ] **Step 3–5：失败 → 实现 → 通过**，然后提交。
  - commit message：`feat(onchain): add hour1 series, negative-start chunking and fixtures`

### Task 2：卖压计算（`pressure.py`）

**Files**
- 新建：`onchain/pressure.py`、`tests/onchain/test_onchain_pressure.py`

**Interfaces**
- 常量：`LOOKBACK = 2600`、`WINDOW = timedelta(hours=720)`
- 模型：
  - `class Levels(Model)`：`p95: float | None`、`p75: float | None`、`n: int`
  - `class LossPoint(Model)`：`at: AwareDatetime`、`lth: float`、`sth: float`
  - `class Point(Model)`：`at: AwareDatetime`、`value: float`
  - `class Pressure(Model)`：
    - `last_at: AwareDatetime`
    - `loss: list[LossPoint]`、`share: list[Point]`、`supply: list[Point]`、`price: list[Point]`
    - `loss_levels: Levels`、`share_levels: Levels`、`supply_levels: Levels`
    - `kept: int`、`xgap: int`
- 函数：
  - `quantile_r7(sorted_values: Sequence[float], q: float) -> float | None`
  - `seller_pressure(rows: dict[str, list[tuple[datetime, float | None]]]) -> Pressure | None`：`rows` 以 `HOUR1_SERIES` 的序列名为键，按时间升序；没有可保留的行时返回 None。

步骤：

- [ ] **Step 1：写失败的测试**
  - `test_parity_with_original_page_at_0800`：输入为 fixture 中 2026-10-16 08:00 及以前的全部行，结果用 `pytest.approx(rel=1e-12)` 比较。期望值来自 `compute.py`，与原站页面一致：

    | 项目 | 期望值 |
    |---|---|
    | `kept` | 2576 |
    | `loss[-1].lth` / `loss[-1].sth` | 1983300.0 / 8540500.0 |
    | `loss_levels` | 41345525.0 / 10050150.0，n = 716 |
    | `share[-1].value` | 0.41893330324776934 |
    | `share_levels` | 0.5611976039771673 / 0.22150410301296825，n = 716 |
    | `supply[-1].value` | 0.2957342245796155 |
    | `supply_levels` | 0.38687086545521404 / 0.26151208272764137，n = 716 |
    | `last_at` | 2026-10-16 08:00Z |

  - `test_lookback_ignores_rows_beyond_2600`：以截至 09:00 的完整 2600 行为基线，在它前面再拼 500 行合成数据，结果与基线完全相同。
  - `test_no_block_hour_drops_itself_and_next`
  - `test_under_1h_null_keeps_rows_and_counts_xgap_twice`：<1h 累计值中间有一个空值时，相邻两行都保留，两行的 `sth` 都等于未剔除的值，`xgap == 2`。
  - `test_rounding_is_half_up_in_hundreds`：差值 150 → 200；差值 149.99 → 100。
  - `test_share_skips_zero_denominator`
  - `test_supply_only_on_kept_rows`
  - `test_quantile_r7`：对 `[1, 2, 3, 4]` 取 q = 0.75，结果为 3.25；空序列返回 None。

- [ ] **Step 2–4：失败 → 实现 → 通过**，然后提交。
  - commit message：`feat(onchain): compute seller pressure with original v1 rules`

### Task 3：hour1 阶段与派生

**Files**
- 修改：`onchain/sync.py`、`tests/onchain/test_onchain_sync.py`

**Interfaces**
- 用到：Task 1 和 Task 2 的产出。
- 产出：
  - `derived` 中的 `"pressure"` 条目；`missing_series` 改为带 index 前缀的 JSON 数组，例如 `["day1:x", "hour1:y"]`。
  - reasons 按 P2-R2 的格式写。
  - hour1 阶段的失败按 P2-R3 处理。

步骤：

- [ ] **Step 1：写失败的测试**（同步更新 P1 中写死"只有 day1"的断言）
  - `test_first_run_backfills_hour1_from_minus_3000`：首次运行时，hour1 的每个请求 start 都是 `-3000`；`derived("pressure")` 存在，其中 `last_at` 是 09:00。
  - `test_hour1_added_to_existing_day1_store_does_not_refetch_day1`
  - `test_incremental_hour1_starts_three_back`
  - `test_hour1_series_version_change_refetches_from_minus_3000`
  - `test_hour1_stage_failure_keeps_cycle_and_levels`：用 `fail_index={"hour1"}` 让 hour1 请求失败。期望：
    - cycle 和 levels 照常重新派生；
    - 共享 reasons 中没有 `brk_unavailable`；
    - `last_error == "brk_unavailable"`；
    - 5 分钟后重试；
    - pressure 保留旧值。
  - `test_missing_hour1_series_clears_pressure_only`：缺少 hour1 的 `sth_supply_in_loss` 时，pressure 被清空，cycle 和 levels 不受影响；reasons 含 `series_missing:hour1:sth_supply_in_loss`。

- [ ] **Step 2–4：失败 → 实现 → 通过**，然后提交。
  - commit message：`feat(onchain): sync hour1 as an isolated stage and derive seller pressure`

### Task 4：接口与契约

**Files**
- 修改：`onchain/models.py`、`onchain/api.py`、`tests/onchain/test_onchain_api.py`；执行 `make contract`

**Interfaces**
- `HourState`
- `hour1_state(last: datetime | None, now: datetime) -> HourState`
- `class SellerPressureView(Model)`，字段：
  - 状态：`data_state: HourState`、`reasons`、`refreshing`、`forming_at`（按 P2-R5）
  - 数据：`last_at`、`loss`、`share`、`supply`、`price`
  - 阈值：`loss_levels`、`share_levels`、`supply_levels`（无数据时为 None）
  - 其他：`xgap: int | None`、`brk_version`

  构造时逐字段赋值，不对 `Pressure` 做 `**model_dump()`。
- `GET /api/wheelhouse/v1/onchain/seller-pressure`
- `/status`：
  - `DatasetStatus.data_state` 的类型改为 `HourState`；
  - 新增 hour1 数据集；
  - day1 数据集过滤掉 hour1 的原因码。

步骤：

- [ ] **Step 1：写失败的测试**
  - `test_hour1_state_boundaries`：1h59m 为 fresh，2h01m 为 delayed，6h01m 为 stale，None 为 unavailable。
  - `test_pressure_view_after_sync`：固定时钟。期望：
    - `data_state == "fresh"`；
    - `computed_at` 落在 09:00 这一小时内时，`forming_at` 为 09:00；
    - 四组点都非空，每组最多 2160 个点；
    - `reasons == []`。
  - `test_forming_cleared_when_computed_after_hour_end`
  - `test_pressure_unavailable_with_200_and_no_zero`：所有列表为空，三组阈值都是 None。
  - `test_pressure_reasons_are_module_filtered`：只缺 day1 序列时，卖压视图的 reasons 为空；只缺 hour1 序列时，cycle 视图不受影响。
  - `test_status_lists_hour1_dataset`

- [ ] **Step 2–4：失败 → 实现 → 通过**，然后执行 `make contract` 并提交。
  - commit message：`feat(onchain): expose seller pressure endpoint`

### Task 5：前端契约与客户端

**Files**
- 修改：`onchain-contract.ts`、`onchain-contract.test.ts`、`client.ts`

**Interfaces**
- `sellerPressureSchema` 与 `SellerPressureView` 类型
- `getSellerPressure(signal?)`
- `pressureSample()`：一个工厂函数，返回 2200 个逐小时合成点，最后一个点和三组阈值取 Task 2 的对照值，`forming_at` 设为最后一个点的时间。

步骤：

- [ ] **Step 1–5**：先写测试，然后实现并提交。
  - 测试内容：样本能通过解析；`data_state` 为 `delayed` 时可以通过；未知状态被拒绝。
  - commit message：`feat(onchain): add seller pressure contract and client`

### Task 6：三张图与 Flows 接入

**Files**
- 新建：`seller-charts.tsx`、`seller-charts.test.tsx`
- 修改：`flows-panel.tsx`、`flows-panel.test.tsx`、`i18n.ts`、`market.css`

**Interfaces**
- `SellerCharts()`
  - query key 为 `["wh", "onchain", "seller-pressure"]`，`refetchInterval: 60000`。
  - 由 `FlowsPanel` 在 seller 子视图、标的为 BTC 时渲染。`FlowsPanel` 的测试中要提供 `QueryClientProvider`。

**界面**：以 mockup `flows.html` 和 `mobile.html` 为准。
- **页头行**：`Resolution 1h · Data {{time}} UTC · Source Bitcoin Research Kit`；处于 forming 时追加 `includes the forming hour`。
- **三张图上下排列**，默认 Span 为 30d。每张图包含：
  - 标题；
  - Span 切换：7d / 30d / 90d，分别显示最后 168 / 720 / 2160 个点；
  - Extreme 和 Warning 的数值，放在各自独立的元素中；
  - 图例与当前值；
  - SVG 图，带右侧价格轴和价格线；
  - 下方三段说明，一律展开。
- **图形**：
  - 图 1 是 LTH 和 STH 的堆叠柱；
  - 图 2 是柱，只画值 > 0 的点；
  - 图 3 是折线；
  - 价格线和图 3 的折线在相邻两点不相差 1 小时的地方断开；
  - P95 用红色虚线，P75 用琥珀色虚线；
  - 处于 forming 时，最后一个点带 `data-forming="true"`，并画虚线框。
- **状态**：
  - 加载中：显示加载文案；
  - 请求失败：显示错误，不显示旧数据；
  - unavailable：显示原因，不画坐标轴；
  - delayed 或 stale：显示提示；
  - refreshing：显示提示。
- **窄屏（≤600px）**：三段说明改为上下排列。这一点在 Task 7 的浏览器里核验。

步骤：

- [ ] **Step 1：写失败的测试**
  - 用 `pressureSample()` 渲染。期望三张图的标题都在；在各图头部元素的 textContent 中能找到 `$41.3M`、`$10.1M`、`56.1%`、`22.2%`、`38.7%`、`26.2%`；图例中有 `41.9%`、`29.6%`。用 `getAllByText` 或正则匹配，因为这些值可能出现不止一次。
  - 把图 2 从 30d 切到 7d：图 2 的柱数变为 ≤168，图 1 和图 3 的点数不变。
  - 九段说明都在 DOM 中，并且都不在任何 `<details>` 内。
  - unavailable 时没有 svg，显示原因；delayed 时显示提示；请求失败时显示错误。
  - 有 forming 时，最后一点带 `data-forming="true"`，页头出现 forming 文案。
  - `FlowsPanel` 的 seller 子视图中不再出现 P1 的占位文案。

- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 运行 wheelhouse 全套测试和 type-check，然后提交。
  - commit message：`feat(onchain): render seller pressure charts in flows`

### Task 7：核验与记录

**Files**
- 新建：`docs/features/btc-onchain-perp/P2-VERIFICATION.md`

步骤：

- [ ] **Step 1**：运行 `make check`。
- [ ] **Step 2**：用分支代码重启本机的 Python 服务和 Vite（Vite 不会自动刷新）。重启后会立刻同步一次。
- [ ] **Step 3：与原站对照**
  - 重启后几分钟内，在已登录的 Edge 中打开原站 onchain-seller 并读取各项数值。
  - 比较三张图的 P95、P75，以及**倒数第二个点**（最后一个已收盘的小时）。最后一个点可能是未收盘值，两边取数的时间不同，不作为严格对照。
  - 判定标准：在页面显示精度内一致。
- [ ] **Step 4：浏览器核验**（1440px 和 390px）
  - 三张图、Span 切换、说明是否全部展开、窄屏下说明是否上下排列、有无横向溢出、控制台是否有错误。
  - 与 mockup 对照。
- [ ] **Step 5**：写核验记录并提交。
  - commit message：`docs(onchain): record P2 verification`

## 评审修订记录（v1 → v2）

独立评审给出 2 项严重、7 项中等、1 组低等问题，修订如下：

| 问题 | 修订 |
|---|---|
| 负数 start 让分片退化成每片一条序列，fixture 也不支持负数 start | 改进点数估算，扩展 transport |
| hour1 阶段失败会连带 cycle 和 levels | P2-R3：单独捕获，失败隔离 |
| pressure 的清空规则不明确，序列名有歧义 | 定义清空规则；P2-R2 给原因码加 index |
| xgap 的期望值算错了 | 改为 2 |
| lookback 测试的基线有误 | 改用完整的 2600 行 |
| 数值格式与测试断言相互矛盾 | 统一格式；断言改用 textContent 和正则 |
| 样本点太少 | 改为 2200 个点的工厂函数 |
| forming 会被误标 | P2-R5：改用 `computed_at` 判断 |
| 与原站对照时，两边的时间对不上 | 改为对照阈值和最后一个已收盘的点 |
| 低等问题若干 | `last_at` 的定义、按时间对齐、模型逐字段构造、`/status` 的类型、P1 测试的更新、三张图都画价格线、窄屏、UTC、载荷截断、`read_series` 加 tail 参数 |
