# BTC 永续状态 P4 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标**：照原站 perp-squeeze 的 v1 规则，在 Flows → Perp states 中给出 Parameters、表 1 和图 1–4。数据只用免费来源：Binance USDⓈ-M 和 Bybit linear 的公开 REST，以及自建的 WebSocket 采集器。

**架构**：新子包 `services/analytics/src/wheelhouse_service/perps/`，分三层：
- 纯计算：`states.py`、`grid.py`；
- 数据层：`rows.py`、`store.py`、`sources.py`、`collector.py`；
- 编排：`sync.py`、`api.py`。

存储用独立的 `perps.sqlite`，WAL 模式。前端新增 Perp states 视图，替换 Flows 里的 "Not connected" 占位。

**技术栈**：同 P1–P3；新依赖 `websockets==17.2`。

**Spec**：[SPEC.md](SPEC.md) v3.1，约束本计划全文；下文的 §x 指 spec 的章节。spec §2 的文件表中没有 `rows.py` 和 `grid.py`，网格放在 `grid.py`，不在 `states.py` 里，以本计划为准。用户已授权全部阶段连续执行。v1 和 v2 各经过一轮独立评审，修订记录见文末。

## 计划层面的裁定

| 编号 | 裁定 | 理由 |
|---|---|---|
| P4-R1 | 内部时间一律用 epoch 秒整数计算，接口输出 ISO 时间 | 网格按 600 秒对齐，用整数不会有歧义 |
| P4-R2 | 原站规则的对照适配器放在 `.local/research-samples/alpha-dashboards-2026-10-16/perp-squeeze/tools/states_parity.py`，**不入库**；结果写进验收记录 | 原站样本是 Glassnode 数据，不能公开（P4-D9） |
| P4-R3 | 回归 fixture 只用公开数据，即 2026-10-15 的以下数据（均来自 `.local/research-samples/perp-free-data-2026-10-17/`）：<br>• Binance hist OI（`bn_oi_1015.json`）<br>• 日包 CSV（`metrics_new/BTCUSDT-metrics-2026-10-15.csv`）<br>• Binance 5m kline（`bn_kl_1015.json`）<br>• Bybit 现货 5m kline 中 10-15 那一段（从 `by_spot.json` 切出） | 公开数据，可以入库 |
| P4-R4 | 采集器写成可单步驱动的状态机：`step(now)`。连接工厂、时钟、等待函数都可注入；测试不起线程，也不打开真实 WebSocket | 让测试有确定性，也不访问外网 |
| P4-R5 | P3 合并到 main 之后开工，分支为 `claude/perp-states` | P3 也改 `i18n.ts`、`market.css` |
| P4-R6 | 图表写 Perp 专用的 SVG 组件（`perp-charts.tsx`），不重构 `seller-charts.tsx` 的内部组件；需要时可以 import 它已经导出的格式化函数 | 避免大范围重构已验收的卖压图 |
| P4-R7 | `requirements.lock` 是按字母排序的纯版本锁，没有哈希。`websockets==17.2` 按字母顺序插入（在 `uvicorn` 之后）。安装用 `.venv-foundation/bin/python -m pip install -r services/analytics/requirements.lock` | 与现有锁文件和 Dockerfile 的安装方式一致 |
| P4-R8 | 仓库根目录有与本项目无关的未跟踪文件，包括 `pyproject.toml`、`requirements.lock`、`backend/`、`frontend/`、`cache/`、`market-zh.png`。提交时一律按路径逐个 `git add` | 防止把它们误提交 |
| P4-R9 | 每个流的每条连接只订阅一个主题，即 3 个流 × 2 条连接 = 6 条连接。每个流的覆盖独立记录 | 各流的覆盖互不影响 |
| P4-R10 | 采集器状态由库里的 coverage 推导，不读进程内的 `Collectors.status()` | `start_perps=False` 或重启之后也能如实报告 |
| P4-R11 | `perpStatesSample` 的数据由 Python 生成：在一份合成网格上运行 `compute_states`，导出为 `perp-states-sample.json` 并入库。Python 测试会重新生成并与入库文件比较。TS 工厂读取这个 JSON，再派生出各种变体。sample 只供测试使用，运行时代码不得 import（AGENTS.md 禁止假数据兜底） | 防止 TS 和 Python 的数值出现偏差 |
| P4-R12 | 三栏说明的文案依据为计算逻辑文档 §2.3、§2.4 和原站页面的说明，用自己的话重写，不照抄原站 | 有据可依，避免凭空编写 |

## 全局约束

- 计算口径按 spec §3 全文执行；表 1、图例和最新块的规则见 §3.5。
- **0 与 None**：已覆盖但没有事件的桶，清算和成交记为 0.0；未覆盖的桶记为 None。REST 序列缺失记为 None。原站补 0 的地方都带 imputed 标记（§3.3）。
- **请求**：交易所请求遵守 §3.8，即同一时刻只有一个请求在途，按 host 分别退避。读接口不访问外网。
- **日志**：只记来源、错误码和耗时，不记数值。
- **文案**：走 `i18n.ts`，en 和 zh 的键保持一致。代码和注释用英文。
- **检查**：运行 `make check`；改了契约先运行 `make contract`。`deploy/test/test_composition.py` 不在 `make check` 范围内，改了它要单独运行 `.venv-foundation/bin/python -m pytest deploy/test/test_composition.py`。
- **设计稿**：`.superpowers/brainstorm/33535-1792151482/content/flows.html`、`mobile.html`。

## 开工前

- [ ] **Task 0：实测与文档入库**
  - 先提交本阶段的文档，逐个 `git add`：`docs/features/btc-perp-states/SPEC.md`、`docs/features/btc-perp-states/PLAN-P4.md`、`research/perp-free-data-2026-10-17.md`。
  - 然后做 WebSocket 实测（原 Task 4a 的 Step 0，因为它决定了 Task 1 要写死的原始格式）：用 websockets 分别连接 3 个流，每个流单独一条连接，各 ≤ 60 秒：
    - `wss://fstream.binance.com/market/ws/btcusdt@forceOrder`
    - `wss://stream.bybit.com/v5/public/linear`，订阅 `allLiquidation.BTCUSDT`
    - 同一 URL，订阅 `publicTrade.BTCUSDT`
  - 实测要确认三件事：
    1. 手动 `ping()` 能收到 pong。Bybit 如果不回协议层的 pong，就只用应用层的 pong 作为存活证明；
    2. 把真实 payload 存到 `.local/research-samples/perp-free-data-2026-10-17/ws_live/`；
    3. 记下原始格式。60 秒内没有清算时，按文档的形状处理，并写明这一点。

## 评审重点（Review Focus）

1. **最新的桶还没发布**：网格到 `last` 为止，最新块的 dOI 不会变成 0。测试在 Task 2。
2. **只有一条连接断开**：覆盖不中断；两条都断开时，对应的块为未覆盖，不显示 0。测试在 Task 2（并集）和 Task 4b（连接）。
3. **日包异常**：从第一处异常起到文件末尾记为 null。10-15 的 fixture 中，只用日包构造网格时，10:50 起为 null。测试在 Task 3。
4. **Binance 返回 418**：Binance 这个 host 本轮停止，Bybit 照常。测试在 Task 3、Task 5a。
5. **覆盖不足 7 天**：只显示图 3、图 4 和 Collecting 横幅。测试在 Task 1、Task 7a。

---

## 文件结构

（路径前缀：后端为 `services/analytics/src/wheelhouse_service/`，测试为 `services/analytics/tests/`，前端为 `integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/`）

| 文件 | 职责 |
|---|---|
| `perps/__init__.py`、`perps/rows.py` | 行类型：`Kline`、`OiPoint`、`RawLiquidation`、`Trade`、`Exchange` |
| `perps/states.py` | 块、特征、阈值、8 态、表 1、QC（纯函数） |
| `perps/grid.py` | 由库中数据构造 10m 网格 |
| `perps/store.py`、`perps/migrations/001_perps.sql` | 存储 |
| `perps/sources.py` | REST 客户端、按 host 退避、日包隔离 |
| `perps/collector.py` | WebSocket 采集器与消息解析 |
| `perps/sync.py` | worker |
| `perps/models.py`、`perps/api.py` | 接口契约与路由 |
| `http.py`、`settings.py` | 接线 |
| `services/analytics/pyproject.toml`、`services/analytics/requirements.lock` | 依赖与 package-data |
| `deploy/test/test_composition.py` | 关闭 perps；`deploy/test/application.py` 不改，test 环境会采集（P4-D11） |
| `tests/perps/**` | 后端测试与 fixture |
| `perps-contract.ts`、`client.ts` | 前端契约与客户端 |
| `perp-states.tsx`、`perp-charts.tsx` 及其测试 | 界面 |
| `flows-panel.tsx`、`i18n.ts`、`market.css`、`flows-panel.test.tsx`、`market-defaults.test.tsx` | 接入 |
| `docs/features/btc-perp-states/P4-VERIFICATION.md` | 验收记录 |

---

### Task 1：状态计算（`states.py`）与行类型

**Files**：新建 `perps/__init__.py`、`perps/rows.py`、`perps/states.py`、`tests/perps/__init__.py`（如果其他测试目录有）、`tests/perps/test_perps_states.py`

**Interfaces**
- `rows.py`：
  - `Exchange = Literal["all", "binance", "bybit"]`
  - `Kline(t: int, close: float, volume: float | None, taker_buy: float | None, source: Literal["binance_perp", "bybit_spot"])`：`t` 是开盘时间，单位为 epoch 秒
  - `Stream = Literal["binance_liq", "bybit_liq", "bybit_trades"]`
  - `OiPoint(t: int, oi: float | None, source: Literal["hist", "archive", "bybit"])`：`t` 采用 hist 约定
  - `RawLiquidation(event_ts: float, key: str, raw: str)`，其中 `raw` 为 JSON 文本：
    - Binance：原始消息中的 `o` 对象；
    - Bybit：`data[]` 中的单个元素；
    - `key` 由原始字段的字符串拼成：Binance 为 `T|S|z|ap`，Bybit 为 `T|S|v|p`。
  - `Trade(id: str, ts: float, side: Literal["Buy", "Sell"], qty: float)`
- `states.py`：
  - 类型与常量：
    - `Window = Literal["4h", "8h"]`、`WINDOW_BUCKETS = {"4h": 24, "8h": 48}`、`BLOCKS_PER_DAY = {"4h": 6, "8h": 3}`；
    - `State = Literal["shortsq", "longsq", "shortun", "longun", "longbd", "shortbd", "spot", "chop"]`；
    - `TABLE_STATES` 为原站顺序：shortsq、longsq、shortun、longun、longbd、shortbd、spot、chop。
  - `@dataclass(frozen=True) class Grid`：
    - `start: int`、`last: int`：都是 600 的倍数，`start` 为第一个桶；
    - `price`、`oi`、`vd`、`long_liq`、`short_liq`：`list[float | None]`，长度为 `(last − start)/600 + 1`；
    - `liq_covered`、`vd_covered`：`list[bool]`。不需要 Bybit vd 的视图，`vd_covered` 全为 True；
    - `rest_series: dict[str, list[float | None]]`：该视图需要的每条 REST 序列，键如 `bybit:price`、`binance:oi`、`binance:kline`、`bybit:oi`，供 QC 和 `series_missing` 使用；
    - `quarantined_days: int`。
  - 模型（`..market.Model`）：
    - `Imputed(dpx: bool, doi: bool, sums: bool)`
    - `Block`：
      - 时间：`t0`、`t1`（AwareDatetime；`t1` 是最后一个桶的起点）、`buckets`、`forming`；
      - 覆盖：`liq_covered`、`delta_covered`、`covered`（= 前两者都为真）；
      - 特征：`dpx`、`doi`、`delta`、`lliq`、`sliq`，以及 `imputed`；
      - `state: State | None`；
      - 绘图值：`price_close`、`oi_close`、`delta_sum`、`lliq_sum`、`sliq_sum`（float | None）。
    - `Tail`：只含 `t0`、`t1` 和上述绘图值。
    - `Thresholds(s_liq: float, l_liq: float, oi: float, px: float, n_liq: int, n_all: int)`：空样本时按原站取 0
    - `TableRow(state, count, share: int, max_move: float | None, run_blocks: int | None)`
    - `Table(show_days: int, view_from: AwareDatetime, judged: int, in_view: int, rows: list[TableRow], latest: State | None, latest_uncovered: bool)`
    - `StatesResult(window, last: AwareDatetime, thresholds, blocks: list[Block], tail: Tail | None, tables: list[Table], covered_days: float, collecting: bool, qc: list[str], series_missing: list[str])`：
      - `blocks` 只含与 30 天视图重叠的块；
      - `tables` 有两张，`show_days` 为 7 和 30。
  - 函数：
    - `quantile(values, q) -> float`：取 `sorted[floor(q·(n−1))]`，空序列返回 0；
    - `compute_states(grid: Grid, window: Window) -> StatesResult`。
  - **块对齐**：块从第一个落在 W 个桶边界上的桶开始；开头不完整的块丢弃（原站 L112–113）。
  - **QC 码**：`missing:<key>`、`gap:<key>:<seconds>`、`archive_quarantined:<n>`。`series_missing` 列出参考窗口内一个值都没有的 `<key>`。
  - **Prob.**：按 `v = 100*c/n` 的顺序计算浮点值（§3.5）。

**步骤**

- [ ] **Step 1：写失败的测试**（合成网格）
  - `test_blocks_align_to_epoch_drop_leading_partial_and_half_rule`：4h 下，开头不完整的块丢弃；尾块 12 个桶时成为 `tail`，13 个时保留并标为 forming。
  - `test_quantile_floor_rank`：`[1, 2, 3, 4]` 取 0.75 → 3；空序列 → 0。
  - `test_cascade_each_branch`：8 个状态各一个块；另加 delta = 0 判为 short unwind。
  - `test_both_liquidations_zero_degenerate_squeeze`
  - `test_liq_thresholds_use_liq_covered_blocks_only`：一个块清算已覆盖、vd 未覆盖时，计入 `n_liq`，但不判定，`state` 为 None。
  - `test_oi_px_thresholds_use_all_blocks`
  - `test_collecting_gate`：4h 下覆盖块 41 个 → collecting，所有 state 为 None；42 个 → 正常判定；`covered_days` = 覆盖块数 ÷ 6。
  - `test_imputed_flags`
  - `test_prob_largest_remainder`：计数为 SS 8、LS 14、SU 8、LU 3、NL 5、NS 6、spot 21、chop 115 → 4/8/4/2/3/3/12/64。再构造一个余数并列的例子，验证按 TABLE_STATES 的顺序取舍。
  - `test_max_move_runs`：段在未覆盖块和下标不连续处断开；价格为 null 或 ≤ 0 的段跳过；并列时保留先出现的。
  - `test_table_in_view_closed_at_from`：中点恰好等于 `from` 时计入，`from − 300` 时不计入。
  - `test_latest_marker`
  - `test_reference_window_uses_last_not_clock`
  - `test_qc_codes`：末尾的连续 null 计入 gap；缺失超过 1% 报 `missing:<key>`；All 视图下 Bybit OI 缺失报 `missing:bybit:oi`；`series_missing`；`archive_quarantined:<n>`。
  - `test_blocks_limited_to_30d_view`
  - `test_collecting_gate_8h`：8h 下 20 个覆盖块 → collecting，21 个 → 正常判定
  - `test_forming_block_doi_nonzero_when_oi_present`
- [ ] **Step 2–4：失败 → 实现 → 通过**，然后提交。commit message：`feat(perps): classify perp states with original v1 rules`
- [ ] **Step 5（本地，不入库）**：写 `states_parity.py`。
  - 输入：`/api/perps` 样本中 all、binance、bybit 三个视图，各构造成全覆盖的 `Grid`；
  - 范围：4h、8h × 两种 Show，共 12 种组合；
  - 比较：计数和 Max move 与 `perp_parity.py` 一致；all/4h/30d 的 Prob. 与页面的 4/8/4/2/3/3/12/64 一致；
  - 结果写进报告。

### Task 2：存储与网格

**Files**：
- 新建：`perps/store.py`、`perps/migrations/001_perps.sql`、`perps/grid.py`
- 新建测试：`tests/perps/test_perps_store.py`、`tests/perps/test_perps_grid.py`
- 新建 fixture：`tests/perps/fixtures/public-2026-10-15/`（按 P4-R3，附 README）

**Interfaces**
- `PerpsStore(path)`：
  - 迁移写法照 onchain；WAL 在迁移事务**之外**打开，照 `repository.py:66–68`。
  - 连接方式照 `repository.py`：每次调用开一个连接，`timeout=10`；写操作用 `BEGIN IMMEDIATE`。
  - 方法：
    - `upsert_klines(venue, rows: Sequence[Kline])`
    - `upsert_oi(venue, rows: Sequence[OiPoint])`：同一 `t` 上，hist 会覆盖 archive，archive 不会覆盖 hist。`oi` 为 None 的行（被隔离的日包行）也照样存为 NULL 行
    - `record_trades(venue, trades: Sequence[Trade])`：一个事务内，先对 `trade_ids` 做 `INSERT OR IGNORE`，只有新插入的成交才累加进 `trades_10m`
    - `insert_liquidations(venue, conn, rows: Sequence[RawLiquidation])`：按连接存储，不去重；Binance 的所有 BTCUSDT 事件都存（包括 `X` ≠ FILLED 的），FILLED 的过滤放在 `grid.py`
    - `open_coverage(stream, conn, start) -> int`、`extend_coverage(row_id, end)`、`close_open_coverage()`
    - `coverage(stream, since) -> list[tuple[float, float]]`：两条连接的区间，已合并
    - `save_derived(key, payload, computed_at)`、`derived(key)`
    - `set_state(**values)`、`state()`
    - `prune(before: int, trade_ids_before: float)`：同时清理 coverage 行
    - `archive_absent(day) -> bool`、`mark_archive_absent(day)`：记录日包 404 的日期，避免每轮重试
- `grid.py`：
  - `REQUIRED: dict[Exchange, tuple[str, ...]]`：
    - binance：`bybit:price`、`binance:oi`、`binance:kline`；
    - bybit：`bybit:price`、`bybit:oi`；
    - all：以上全部。
  - `build_grid(store, exchange: Exchange, start: int) -> Grid | list[str]`：
    - 必需序列中有缺失时，返回缺失的键，用于 `series_missing:<key>`；
    - 不做未收盘的过滤，那是入库时 `sources.py` 的工作。
  - 映射按 §3.1。`last` 按"数据边界"计算：每条序列的最后一个桶，取它**最后一条存储行**（是不是 NULL 都算）能映射到的最后一个桶；
  - price 和 vd 需要两根 5m bar 都在，桶才有值；
  - `quarantined_days`：参考窗口内，有 `source = archive` 且 `oi` 为 NULL 的行的 UTC 日期数；
  - 覆盖按 §3.2：两条连接的区间取并集，桶完全落在其中才算覆盖；
  - 清算：只取 Binance 的 `X=FILLED`；方向映射按 §3.1；同一 key 取各连接出现次数的最大值；
  - 必需序列一行都没有时返回 None。

**步骤**

- [ ] **Step 1：写失败的测试**
  - `test_store_wal_and_migration`
  - `test_hist_overrides_archive_not_reverse`
  - `test_record_trades_dedupes_in_one_batch_and_across_batches`
  - `test_coverage_union_and_close_open_on_restart`
  - `test_prune_drops_old_rows_and_trade_ids`
  - `test_grid_public_1015`：用 fixture 中的 hist、Binance kline、Bybit 现货 kline 构造 binance 视图的网格，手算几个桶的 price、oi、vd 做断言。`last` 为 23:40：OI 最后一个能映射的桶是 23:40（对应 `oi.t` = 23:50；23:55 那一行对不上任何桶），kline 的 vd 和 price 到 23:50 为止，取两者较早的。
  - `test_grid_edge_is_min_of_series_last`
  - `test_bucket_coverage_union_one_connection_down_vs_both`
  - `test_liquidation_max_count_per_connection`
  - `test_binance_filled_only_and_sides`、`test_bybit_sides_and_qty`
  - `test_covered_empty_bucket_is_zero_uncovered_is_none`
  - `test_null_rows_count_toward_last`：被隔离的 NULL 行也算进 `last`，对应的桶为 None。
  - `test_missing_series_returned`：返回缺失序列的键。
  - `test_all_view_none_if_any_venue_none`
- [ ] **Step 2–4：失败 → 实现 → 通过**，然后提交。commit message：`feat(perps): store perp inputs and build the 10m grid`

### Task 3：REST 来源（`sources.py`）

**Files**：新建 `perps/sources.py`、`tests/perps/test_perps_sources.py`

**Interfaces**
- `RestError(Exception)`：`host: str`、`code: str`（例如 `"429"`、`"retcode:10006"`）、`until: datetime | None`
- `PerpsRest(client: httpx.Client | None = None, clock=..., *, page_limits: dict[str, int] | None = None)`：
  - `binance_klines(start, end) -> list[Kline]`
  - `binance_oi_hist(start) -> list[OiPoint]`
  - `binance_oi_archive(day) -> tuple[list[OiPoint], bool] | None`：先去重、排序、隔离（§3.1，≥2 个相同值或 ≤0）；第二个值表示是否发生了隔离；404 返回 None
    - 隔离的起点是相同值那一对中的**第一行**（10-15 为 10:50，而不是 10:55）；
    - 被隔离的行照样返回，`oi` 为 None。
  - `bybit_spot_klines(start, end) -> list[Kline]`
  - `bybit_oi(start, end) -> list[OiPoint]`：用 `singleOpenInterest`，按 cursor 翻页
  - `backoff_until(host) -> datetime | None`
- **规则**（§3.8）：
  - 实例内加锁，保证同一时刻只有一个请求；
  - 按 host 退避，截止时间取 `max(表值, Retry-After)`；
  - 退避期内对该 host 直接抛 `RestError`，不发请求；
  - 超时 20 秒；
  - 过滤未收盘的 kline；
  - Bybit 返回的数据为倒序，统一转成正序。

**步骤**

- [ ] **Step 1：写失败的测试**（`httpx.MockTransport`）
  - 分页（3 页）
  - `test_unclosed_klines_filtered_with_injected_clock`
  - 日包测试在内存中由 CSV 生成 zip；去重测试用合成的重复行，因为真实文件里没有重复
  - `test_archive_quarantine_1015`：
    - `create_time ≥ 10:50`（即 `oi.t ≥ 10:55`）的点都是 None，并标记为已隔离；
    - 更早的点与 hist 在 `oi.t` 上相等；
    - 用这些点只构造 binance 视图的 OI 网格，10:50 起的桶都是 None，10:40 的桶与 hist 相等。
  - `test_archive_dedupes_and_sorts`
  - `test_binance_429_403_418_backoff`：截止时间分别为 2 分钟、30 分钟、30 分钟；退避期内调用会抛错，并且不发请求。
  - `test_retry_after_wins_when_longer`
  - `test_backoff_is_per_host`
  - `test_bybit_403_and_ratelimit_retcode_back_off_10m`、`test_bybit_other_retcode_error_without_backoff`
- [ ] **Step 2–4**，提交。commit message：`feat(perps): fetch public perp data with per-host backoff`

### Task 4a：消息解析、单条采集器与依赖

**Files**：
- 新建 `perps/collector.py`、`tests/perps/test_perps_collector.py`
- 修改 `services/analytics/pyproject.toml`：依赖加入 `websockets==17.2`；package-data 加入 `perps/migrations/*.sql`
- 修改 `services/analytics/requirements.lock`（按 P4-R7）
- 安装依赖（P4-R7）

**样例**：用 Task 0 保存的真实 payload，截取放入 `tests/perps/fixtures/ws/`。

**Interfaces**
- 解析函数：
  - `parse_binance_force_order(msg) -> RawLiquidation | None`：只取 BTCUSDT 的事件，**不过滤** `X`
  - `parse_bybit_liquidation(msg) -> list[RawLiquidation]`
  - `parse_bybit_trades(msg) -> list[Trade]`
- `Collector(store, stream: Stream, conn, *, connect, clock, wait, rng, rotate_gate: Callable[[], bool])`，`connect` 的签名与 `websockets.sync.client.connect` 相同，调用时传 `ping_interval=None`，即关闭库自带的 keepalive：
  - `last_proof: float | None` 属性；
  - 重连退避 = `min(60, 2**n) × rng.uniform(0.5, 1)`；
  - 写库失败（例如 `database is locked`）时：
    - 保留缓冲，下一次 `step` 重试，覆盖终点不推进；
    - 缓冲超过 50,000 条时，丢弃缓冲，并把覆盖区间结束在最后一次成功提交的时刻（形成空洞，不谎报覆盖）；
  - `step(now) -> None`：推进状态机一步，依次处理以下事项：
    1. 连接与订阅；
    2. 用 `recv(timeout ≤ 1s)` 读消息；
    3. 每 20 秒发一次 `ping()`，在读循环里轮询它的事件 `is_set()`，**不阻塞等待**；20 秒内没有 pong，就判定为半开连接，然后重连；
    4. Bybit 每 20 秒发一次 `{"op":"ping"}`；
    5. 缓冲的消息每 1 秒批量提交；提交之后再推进覆盖区间的终点，终点 = 最后一次存活证明 − 2 秒；每 10 秒至少写一次；
    6. 连接满 12 小时就重建；
    7. 断线后指数退避加抖动，从 1 秒到 60 秒。
  - `run()`：线程入口，循环调用 `step`；
  - `stop(deadline)`。

**步骤**

- [ ] **Step 1：写失败的测试**（假连接对象，用 `step` 驱动）
  - 三种消息的解析（真实样例）
  - `test_half_open_ends_coverage_at_last_proof_minus_2s_and_reconnects`
  - `test_events_committed_before_coverage_end_advances`
  - `test_rotation_after_12h`
  - `test_backoff_with_jitter_bounds`
  - `test_trades_recorded_in_batches`
  - `test_commit_failure_keeps_buffer_and_does_not_advance_coverage`
  - `test_buffer_cap_drops_and_ends_coverage`
  - `test_coverage_start_bybit_ack_binance_handshake`
- [ ] **Step 2–4**，提交。commit message：`feat(perps): parse and collect perp WebSocket streams`

### Task 4b：双连接编排（`Collectors`）

**Files**：修改 `perps/collector.py`、`tests/perps/test_perps_collector.py`

**Interfaces**
- `Collectors(store, *, connect, clock, wait, rng)`，方法有 `start()`、`stop(total_deadline)`、`status()`：
  - 每个流建两个 `Collector`，conn 分别为 `a` 和 `b`；`b` 晚 60 秒启动；
  - 启动时先调用 `store.close_open_coverage()`；
  - **错开换连接**：给每个 `Collector` 传 `rotate_gate`：只有另一条连接在最近 30 秒内有过存活证明时才返回 True，否则推迟换连接；
  - `status()` 只用于日志和测试；接口的状态从库推导（P4-R10）；
  - `stop(total_deadline=8s)`：并行关闭所有连接。

**步骤**

- [ ] **Step 1：写失败的测试**
  - `test_two_connections_union_keeps_coverage_when_one_drops`
  - `test_rotation_deferred_when_sibling_not_live`
  - `test_restart_closes_open_intervals`
  - `test_parallel_stop_within_deadline`
  - `test_status_live_if_either_connection_live`
- [ ] **Step 2–4**，提交。commit message：`feat(perps): run two staggered connections per stream`

### Task 5a：worker（`sync.py`）

**Files**：新建 `perps/sync.py`、`tests/perps/test_perps_sync.py`

**Interfaces**
- `PerpsSync(store, rest, *, clock, horizon_days=90)`：
  - `run_once(now=None) -> bool`：首次启动时立刻运行，之后对齐到 HH:x5；
  - `start()` / `stop()`：线程名为 `wheelhouse-perps`。
- **每条序列**的取数：
  - 补头部缺口 `[D−90d, 库里第一条)`；
  - 补尾部缺口 `(库里最后一条 − 3 条, now]`；
  - 中间的空洞不补，留给 QC 统计为 missing；
  - Binance OI：最近 29 天用 hist；更早的用日包，日包要下载到边界当天为止，hist 覆盖日包；
  - 回填按 1 天一个事务写入。
- 每个 host 的 `RestError` 单独记录，不影响其他 host。
- **派生**：
  - `build_grid(start = UTC 当天 00:00 − (horizon_days + 1) 天)`，再 `compute_states`，共 6 份载荷；
  - `build_grid` 返回缺失的键时，存一份 unavailable 标记，附 `series_missing:<key>` 原因码。
- 日包 404 的日期调用 `mark_archive_absent` 记下，之后不再请求。
- **方向核对**按 spec §6，结果写入 `sync_state`；Bybit `v` 的单位统计也写入。
- **清理**：数据保留 120 天，`trade_ids` 只保留 1 小时。

**步骤**

- [ ] **Step 1：写失败的测试**（假 REST transport，`horizon_days` 设为 2，减少数据量）
  - `test_first_run_immediate_then_x5_slots`
  - `test_head_and_tail_gaps_filled_middle_left`
  - `test_backfill_hist_29d_then_archive`（`horizon_days` 设为 31）
  - `test_binance_backoff_does_not_stop_bybit`
  - `test_derives_six_payloads`
  - `test_build_grid_none_stores_unavailable_marker`
  - `test_direction_check_pending_ok_inverted_and_v_units`
  - `test_prune_keeps_120d_and_1h_trade_ids`
- [ ] **Step 2–4**，提交。commit message：`feat(perps): backfill and derive perp states in a worker`

### Task 5b：接口与接线

**Files**：
- 新建 `perps/models.py`、`perps/api.py`、`tests/perps/test_perps_api.py`
- 修改 `http.py`、`settings.py`、`deploy/test/test_composition.py`
- 生成：`make contract`

**Interfaces**
- `CollectorStatus`（定义在 `models.py`）：`stream: Stream`、`live: bool`、`last_proof`、`down_since`、`covered_days: float`、`since`。
  - 由库里的 coverage 推导：两条连接中任一条的最后证明在 60 秒内，就算 live。
  - 各视图涉及的流：binance 视图为 `binance_liq`；bybit 视图为 `bybit_liq` 和 `bybit_trades`；all 视图为三个全部。`collector_down:*` 只报告所选视图涉及的流。
- `PerpStatesView`：
  - `exchange`
  - `StatesResult` 的全部字段。unavailable 时 `window`、`last`、`thresholds`、`collecting`、`covered_days` 为 Optional
  - `data_state`（fresh / delayed / stale / unavailable，§3.7）
  - `reasons`
  - `computed_at`
  - `collectors: list[CollectorStatus]`
  - 每个流的已覆盖天数
  - 每个流的起点放在 `CollectorStatus.since` 中
  - unavailable 时，其余字段为空列表或 None
- `PerpsStatus`：
  - 每个 host 的 `last_success`、`error`、`backoff_until`
  - `collectors`
  - `direction: Literal["pending", "ok", "inverted"]` 及统计
  - `v` 单位的统计
- 路由：
  - `GET /api/wheelhouse/v1/perps/states?exchange=all|binance|bybit&window=4h|8h`
  - `GET /api/wheelhouse/v1/perps/status`
  - 新鲜度、采集器状态和原因码都在请求时计算
- `Settings.perps_enabled`：环境变量 `WHEELHOUSE_PERPS`，接受 `1/0/true/false/on/off`，默认 on。
- `create_app(..., start_perps: bool | None = None, perps_http: httpx.Client | None = None, perps_connect=None)`：
  - `start_worker=False` 时一律不启动；
  - capability 加入 `"perps"`。
- `deploy/test/test_composition.py`：传 `start_perps=False`，并断言两者都没启动。

**步骤**

- [ ] **Step 1：写失败的测试**
  - `test_freshness_at_request_time`：+20 分钟 fresh，+40 分钟 delayed，+3 小时 stale
  - `test_reason_codes`：`rest_error:<host>:<code>`、`collector_down:<stream>`、`collecting:<days>`（1 位小数）、`series_missing:*`
  - `test_unavailable_before_first_derive`
  - `test_read_does_not_touch_network`
  - `test_start_perps_false_starts_nothing`
  - `test_settings_perps_values`：`WHEELHOUSE_PERPS=0` 时应用层什么都不启动；`start_perps=True` 且 `start_worker=False` 时也什么都不启动
  - `test_freshness_boundaries`：恰好 30 分钟和 2 小时（判定用 `≤`），起算点是 `last + 10m`
  - `test_collector_status_from_store`
  - `test_sample_json_regenerates_identically`（P4-R11）：在合成网格上运行 `compute_states`，包成 `PerpStatesView` 导出 JSON，与入库的 `perp-states-sample.json` 相同
- [ ] **Step 2–4**：
  - 生成 `integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/perp-states-sample.json`；
  - 运行 `make contract`、`make check`，再单独运行 `test_composition.py`；
  - 提交，commit message：`feat(perps): expose perp states and wire the worker`。

### Task 6：前端契约与客户端

**Files**：新建 `perps-contract.ts`、`perps-contract.test.ts`；修改 `client.ts`、`client.test.ts`

**Interfaces**
- Zod 模型：`perpStatesViewSchema`、`perpsStatusSchema`。
- `perpStatesSample(variant: "full" | "collecting" | "uncovered" | "qc" = "full")`：读取 `perp-states-sample.json`（P4-R11）作为 full；其他变体在 full 的基础上修改得到。只供测试使用。
- `getPerpStates(exchange, window, signal?)`、`getPerpStatus(signal?)`。

**步骤**：先写测试，再实现，然后提交。commit message：`feat(perps): add perp states contract and client`

### Task 7a：容器、Parameters、状态与表 1

**Files**：新建 `perp-states.tsx`、`perp-states.test.tsx`；修改 `flows-panel.tsx`、`flows-panel.test.tsx`、`market-defaults.test.tsx`、`i18n.ts`、`market.css`

**Interfaces**
- `PerpStates()` 组件：
  - URL 参数：`px`（默认 all）、`pw`（默认 4h）、`ps`（默认 30）；值不合法时回落到默认值；
  - 数据请求：
    - states：key 为 `["wh","perps",px,pw]`，每 300000 ms 刷新；
    - status：每 60000 ms 刷新；
  - 页面内容：
    - 页头行、覆盖说明（按流分别列出天数）；
    - Collecting 横幅、Binance 清算标注；
    - 各状态的提示（§5）；
    - Parameters；
    - 表 1：副标题、最新块标记、方向未核对标签、窄屏只显示三列且 What it is 可展开；
  - 图 1–4 的位置留给 Task 7b 填入。
- `FlowsPanel`：perp 子视图挂载 `PerpStates`；删除 `flows.perpPending` 的 en 和 zh 文案，以及相关断言。

**步骤**

- [ ] 测试：
  - full 变体：表 1 有 8 行，Prob. 合计 100；
  - collecting 变体：显示横幅，隐藏表 1；
  - 方向未核对时显示标签；
  - URL 写入与非法值回落；
  - 切换 Show 不发请求；
  - 各状态：unavailable、stale、delayed、QC、forming、采集器 down；
  - 窄屏表 1：照 `onchain-levels.tsx` 的 `matchMedia` 写法 mock 窄屏，What it is 收在 `<details>` 中；
  - en 与 zh 的键一致。
- [ ] 实现并提交。commit message：`feat(perps): show perp states parameters and table`

### Task 7b：图 1–4

**Files**：新建 `perp-charts.tsx`、`perp-charts.test.tsx`；修改 `perp-states.tsx`、`i18n.ts`、`market.css`

**Interfaces**：`PerpCharts({ view, show })` 画四张图，规则见 §3.5：
- 图 1、图 2 的阴影；
- 未覆盖块的斜线纹理；
- 悬停：显示 imputed、uncovered、阈值为 0；
- 图例 `k / n`：计入范围为 `[view_from, last]`，未覆盖块另计，n 为 0 时显示 —，点击图例可切换显示；
- 图 3 的 OI 线；
- 图 4 的 delta 柱和清算带，未覆盖时留空并标记；
- 每张图下有三栏说明，窄屏时也全部展开。

**步骤**

- [ ] 测试：
  - 四张图都渲染；
  - 未覆盖块有纹理；
  - 图例的 n 不含未覆盖块；
  - 悬停显示 imputed 和阈值为 0 的提示；
  - 图例切换；
  - 三栏说明不在 `<details>` 中；
  - collecting 变体：没有图 1、图 2，有图 3、图 4；
  - 图例按名义中点统计（与表 1 的实际中点不同）。
- [ ] 实现并提交。commit message：`feat(perps): draw perp states charts`

### Task 8：核验与记录

**Files**：新建 `docs/features/btc-perp-states/P4-VERIFICATION.md`；新建本地脚本 `.local/research-samples/perp-free-data-2026-10-17/tools/archive_vs_hist.py`（不入库）

**步骤**
- [ ] 运行 `make check`，并单独运行 `deploy/test/test_composition.py`。
- [ ] 运行 Task 1 Step 5 的本地规则对照。
- [ ] **日包与 hist 对照**：用 `archive_vs_hist.py` 下载最近 29 天的日包（共约 330 KB，请求遵守 §3.8），与 hist 逐行比较，记录不一致率和隔离天数。如果隔离后仍有超过 1% 的行不一致，按 spec 把 Binance 的参考窗口改为只用 hist，同时修改 spec 和代码。
- [ ] **本机实测**：重启本机的 Python 服务和 Vite。记录：
  - 回填用时和请求数；
  - 采集器运行 ≥ 30 分钟后的事件数、`X` 的分布、publicTrade 的 CPU 占用和写入量、覆盖区间、方向核对状态。
- [ ] **浏览器核验**（1440 和 390）：Collecting 状态、图 3 和图 4、Parameters 与 URL、无横向溢出、控制台无错误。
- [ ] 写验收记录，并列出需要 test 环境采集满 7 天才能完成的项目。然后提交。commit message：`docs(perps): record P4 verification`

## 评审修订记录（v1 → v2）

| 评审意见 | 处理 |
|---|---|
| C1：隔离规则与 10-15 的 fixture 对不上 | spec v3.1 改为"≥2 个相同值"；断言按 `create_time ≥ 10:50`，并在仅用日包构造的网格上验证 |
| C2：数据模型缺字段 | `Grid.rest_series`、`Block.delta_covered`；清算阈值只用 `liq_covered` 的块；写明 QC 码的格式 |
| I1：websockets 线程模型的陷阱 | `ping_interval=None`；不阻塞等待 pong；`step` 状态机；并行停止；Task 4a Step 0 实测 |
| I2：成交逐条去重太慢 | 改为 `record_trades` 批量写入；`trade_ids` 的清理归 Task 5a |
| I3：接口在定义之前就被使用 | 新增 `rows.py`，在 Task 1 定义；原始清算的格式在 Task 1 写明；FILLED 的过滤移到 `grid.py` |
| I4：fixture 缺价格数据 | 加入 Bybit 现货 kline 10-15 那一段；`last` 为 23:40 |
| I5：回填语义不清 | 分头尾两段补缺口；1 天一个事务；首次启动立即运行；写明 `build_grid` 的 start；返回 None 时的处理 |
| I6：测试设计有缺陷 | 把"在视图内"的测试改为 `from` 处的闭区间边界；补上原因码、429/403、窄屏表格、阈值为 0 的测试 |
| I7：换连接不保证错开 | 另一条连接没有存活证明时推迟 |
| I8：验证缺口 | 单独运行 `test_composition.py`；加 29 天对照脚本和决策分支；写明 `application.py` 不改 |
| I9：任务太大 | 拆成 4a/4b、5a/5b、7a/7b；图表单独写（P4-R6） |
| I10：sample 的生成方式含糊 | 改为 TS 工厂；`tables` 用列表，并带 `view_from` |
| Minor | 锁文件的格式和安装方式（P4-R7）、完整路径、逐个 `git add`（P4-R8）、WAL 的打开位置、各项细节的写明、可注入的回填天数 |

## 评审修订记录（v2 → v3）

| 评审意见（sonnet 复核） | 处理 |
|---|---|
| I1：NULL 行与 `last` 的关系 | NULL 行照样入库，并计入 `last`；`quarantined_days` 的计数方法；`last` 的口径改为按桶表述 |
| I2：`build_grid` 不告诉调用方缺了什么 | 返回缺失的键；补上 `REQUIRED` 表 |
| I3：`now` 的用途不明 | 未收盘的过滤只在入库时做，`build_grid` 不再接收 `now`，相应测试移到 Task 3 |
| I4：`CollectorStatus` 未定义 | 在 `models.py` 中定义；状态由库推导（P4-R10）；写明各视图涉及的流 |
| I5：Bybit 连接的布局 | 每条连接只订阅一个主题（P4-R9） |
| I6：换连接没有钩子 | 加 `rotate_gate`、`last_proof`、抖动公式和可注入的 `rng` |
| I7：写库失败的处理 | 保留缓冲并重试；缓冲超过上限时丢弃并留下空洞；连接方式照 `repository.py` |
| I8：sample 的数值可能出现偏差 | 改由 Python 生成 JSON 并入库（P4-R11） |
| I9：collecting 状态的图表没有测试 | 加入 Task 7b |
| Minor | 隔离的起点是相同值那一对的第一行；`Thresholds` 全部为 float；unavailable 时的 Optional 字段；补测试；实测提前为 Task 0；字段语义；窄屏测试的写法；`horizon_days`；清理 coverage；文档入库；记录日包 404 的日期；文案的来源（P4-R12） |
