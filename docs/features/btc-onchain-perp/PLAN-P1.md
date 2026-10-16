# BTC 链上融合 P1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标**：为 BTCUSDT 交付以下内容，计算口径照原站 v1：
- BRK 数据层；
- 周期六态；
- 5 条链上模型线；
- 页头周期徽章；
- Key levels 的叠加线和 inspector 区块；
- Flows tab 的外壳。

**架构**
- 后端新增 `onchain` 子包，结构照 portfolio 子系统：独立的 `onchain.sqlite`、独立的 worker、只读的 `APIRouter`。
- worker 每小时从 bitview.space 取 day1 序列和 `all` 的 URPD（按权重分片），取完立即算出周期与模型线，存入 `derived` 表。读接口只读库。
- 按 spec §7 分期：hour1 序列在 P2 接入，`sth`/`lth` 的 URPD 在 P3 接入。
- 前端新增页头徽章、Key levels 叠加线与 inspector 区块，以及第 4 个方法 tab「Flows」（两个子视图先放占位）。

**技术栈**
- 后端：Python 3.14、FastAPI、Pydantic v2、httpx、SQLite、pytest、ruff、mypy strict。
- 前端：React、TanStack Query、Zod、Vitest。
- 契约：`make contract`（openapi-typescript）。

**Spec**：[SPEC.md](SPEC.md) v3。P1 范围见 §7。用到的规则：§3.0；§3.1；§3.2 中的模型线部分；§5；§6。

## 执行前提（开工前由用户确认）

### 1. 基线提交

本分支 `claude/btc-onchain-perp` 是从 main 的当前状态开出来的，带着 100 项尚未提交的工作，其中很多文件从来没有提交过。P1 要改的 `market-page.tsx` 依赖其中未跟踪的 `dropdown.tsx`、`regime-check.tsx`、`i18n.ts` 等文件，所以只提交 P1 改到的那几个文件，得到的提交树是坏的。

开工前先做一个基线 commit，包含范围由用户决定：
- **建议纳入**：
  - `services/`：analytics 的 src 和 tests，以及 wallet-auth
  - `integrations/`、`deploy/`、`docs/`、`research/`、`prototypes/`、`scripts/`
  - `AGENTS.md`、`CLAUDE.md`、`.dockerignore`
- **建议排除，交你判断**：
  - `.superpowers/`：mockup 文件，建议加进 `.gitignore`
  - `cache/`
  - 早期实验遗留：`backend/`、`frontend/`（91 MB）、根目录的 `pyproject.toml`、`requirements.lock`、`alembic.ini`
  - `market-zh.png`

基线可以由你自己提交，也可以由你确认清单后让执行者提交。远端还没有这个分支，第一次推送用 `git push -u origin claude/btc-onchain-perp`。

### 2. 本地服务

Task 11 的浏览器核验需要 `make dev` 起全三个服务：Wealthfolio :8088、宿主 :1420、Python :8787。目前 :8088 没有运行。

## 全局约束

- **语言**：代码、标识符、注释、UI 文案、commit message 用英文；文档用中文。UI 文案一律走 `i18n.ts`，en 和 zh 两套 key 必须一致。
- **只读边界**：新接口只有 GET；读接口**不访问外网，也不做计算**，只读 `onchain.sqlite`。
- **计算口径 = 原站 v1**（spec §3）：
  - 包含尚未收盘的最后一行；
  - 周期只保留 W、STH、TMM、`price_close` 四条都存在且都大于 0 的日期，其余日期跳过；
  - 整体门控，死区 `depth 7.0 / pvs 6.8 / spread 1.25`，从 `2013-01-01` 起算，分量大于 0 才算正。
- **未收盘标注**：只要用到了未收盘那一行，响应就带 `forming_at`（即那一行的时间，否则为 null）；界面写 "includes today (forming)"。
- **BRK 约定**：
  - 地址 `BASE_URL = "https://bitview.space"`；超时 20 秒。
  - 每片不超过 `MAX_POINTS = 18_000` 个点（服务端上限是权重 320,000，约每点 16）。
  - bulk 请求遇到 `series_not_found` 时，拆成逐条请求重试。
  - BRK 响应里的额外字段（例如 `type`）一律忽略。
  - 日志只记路由、错误码和耗时。
- **缺失与失败**：不补 0；保留旧数据；记录原因码，原因码只有 `series_missing:<name>`、`brk_unavailable`、`urpd_missing` 三种。
- **位置与时间**：BRK 的 day1 和 hour1 都以下标 0 = `2009-01-01T00:00Z` 起算。
- **测试文件名**：在整个 tests 树内唯一，统一用 `test_onchain_*.py`；辅助模块叫 `onchain_fixture.py`。
- **命令**：
  - 后端：在 `services/analytics` 下运行 `../../.venv-foundation/bin/python -m pytest …`，ruff 和 mypy 同样在这个目录跑。
  - 前端：先 `make sync`，再在 `.local/wealthfolio` 下运行 `pnpm --filter frontend exec vitest run src/features/wheelhouse/<file>`。
  - `make check` 跑全套检查。
- **提交**：每个任务结束时，只提交本任务涉及的文件，然后 push。依据项目记忆：验证通过就直接提交。

## 评审重点（Review Focus）

1. **当天的行里有部分序列还没更新**（例如 `realized_price` 为 null）：模型线改用"4 条模型线都齐的最后一行"，周期按自己的规则跳过缺值的日期；不报错，不补 0。测试放在 Task 4 的 `last_complete` 和 Task 3。
2. **UTC 午夜到 02:00 之间，BRK 还没有今天的行**：day1 状态在这段宽限期内仍算 fresh，不会在每天午夜闪成 stale。测试放在 Task 6 的 `day1_state`。
3. **今天的 URPD 还不存在**：退回昨天的快照，`urpd_date` 写昨天；两天都没有时，不出 Median，其余 4 条线照出，并在 reasons 里加 `urpd_missing`。测试放在 Task 5。
4. **BRK 版本变了，但重新取数中途失败**：旧数据保持可读，`refreshing` 保持 true，直到下一次成功替换。界面显示 refreshing 提示。测试放在 Task 5 和 Task 9。
5. **选了 ETH/MU，或者正在看已保存的快照**：不显示徽章，不画叠加线；Key levels 显示 BTC only 或 latest only，Flows 显示 BTC only。测试放在 Task 8、Task 9 和 Task 10。

---

## 文件结构

路径前缀：后端为 `services/analytics/src/wheelhouse_service/`，前端为 `integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/`。

| 文件 | 职责 |
|---|---|
| `onchain/__init__.py`、`onchain/brk.py`（新建） | `BrkClient`：分片 bulk、逐条重试、URPD、`version()`；`BrkError` |
| `onchain/store.py`、`onchain/migrations/001_onchain.sql`（新建） | `OnchainStore` |
| `onchain/cycle.py`（新建） | `raw_state`、`gate`、`classify` |
| `onchain/levels.py`（新建） | `median_cost`、`last_complete`、`model_lines` |
| `onchain/sync.py`（新建） | `OnchainSync` |
| `onchain/models.py`、`onchain/api.py`（新建） | 契约、`day1_state`、`create_router` |
| `http.py`、`pyproject.toml`（修改） | 挂载 router、`brk_client` 参数、capability；package-data |
| `tests/onchain/{conftest,onchain_fixture}.py`、`tests/onchain/fixtures/brk-2026-10-16/`（新建） | fixture 与 mock transport |
| `tests/onchain/test_onchain_{brk,store,cycle,levels,sync,api}.py`（新建） | 后端测试 |
| `openapi.json`、`api-schema.d.ts`（`make contract` 生成） | 契约 |
| `onchain-contract.ts`、`client.ts`（新建/修改） | Zod schema、请求函数 |
| `cycle-badge.tsx`、`onchain-levels.tsx`、`flows-panel.tsx`（新建） | 新组件 |
| `market-chart.tsx`、`market-page.tsx`、`i18n.ts`、`market.css`（修改） | 叠加线、tab、挂载、文案、样式 |
| `{onchain-contract,cycle-badge,onchain-levels,flows-panel}.test.ts(x)`（新建）；`market-chart.test.tsx`、`market-defaults.test.tsx`（修改） | 前端测试 |
| `AGENTS.md`（修改） | 已确认的 UI |
| `docs/features/btc-onchain-perp/P1-VERIFICATION.md`（新建） | 核验记录 |

---

### Task 1：BRK 客户端与 fixture

**Files**
- 新建：`onchain/__init__.py`、`onchain/brk.py`
- 新建：`tests/onchain/conftest.py`（把本目录加入 `sys.path`，写法同 `tests/regime/conftest.py`）
- 新建：`tests/onchain/onchain_fixture.py`、`tests/onchain/fixtures/brk-2026-10-16/`、`tests/onchain/test_onchain_brk.py`

**Interfaces**

产出（`onchain/brk.py`）：
- `Index = Literal["day1", "hour1"]`
- `class BrkModel(Model)`：`model_config` 在 `Model` 的基础上改为 `extra="ignore"`。下面三个 BRK 响应模型都继承它。
- `class SeriesData(BrkModel)`：`version: int`、`index: Index`、`start: int`、`end: int`、`stamp: AwareDatetime`、`data: list[float | None]`
- `class UrpdBucket(BrkModel)`：`price_floor: float`、`supply: float`、`realized_cap: float`、`unrealized_pnl: float`
- `class Urpd(BrkModel)`：`cohort: str`、`date: date`、`aggregation: str`、`close: float`、`total_supply: float`、`buckets: list[UrpdBucket]`
- `class SeriesBatch(Model)`：`found: dict[str, SeriesData]`、`missing: list[str]`
- `class BrkError(Exception)`：属性 `code: str`、`retryable: bool`
- `class BrkClient`：
  - `__init__(self, client: httpx.Client | None = None, base_url: str = BASE_URL, clock: Callable[[], datetime] = <返回当前 UTC 时间>)`
  - `version() -> str`
  - `series(names: Sequence[str], index: Index, start: int | date) -> SeriesBatch`：取到当前最新位置。
  - `urpd(cohort: str, day: date, agg: str = "lin500") -> Urpd | None`：BRK 返回 404 时为 None。
- 常量：
  - `BASE_URL`、`MAX_POINTS = 18_000`、`START = date(2013, 1, 1)`
  - `DAY1_SERIES = ("price_close", "true_market_mean", "sth_realized_price", "lth_realized_price", "realized_price", "utxos_1d_to_1w_old_realized_price")`

产出（`tests/onchain/onchain_fixture.py`）：
- `load_series(name: str, index: Index) -> SeriesData`
- `load_urpd(cohort: str) -> Urpd`
- `class Calls(list[tuple[str, dict[str, str]]])`：按顺序记录每次请求的 path 和 query 参数。
- `brk_transport(*, version="0.12.2", missing: set[str] = set(), fail_paths: set[str] = set(), urpd_dates: set[date] | None = None) -> tuple[httpx.MockTransport, Calls]`
  - 按 fixture 响应以下请求：`/version`、`/api/series/bulk`（返回不带序列名的有序数组，按 start 截取）、`/api/urpd/{cohort}/{day}`。
  - 命中 `fail_paths` 中前缀的请求，返回 503。
  - `urpd_dates` 之外的日期返回 404。
  - `missing` 里的序列名返回 404，body 为 `{"error":{"code":"series_not_found"}}`。

步骤：

- [ ] **Step 1：整理 fixture**
  - 从 `.local/research-samples/alpha-dashboards-2026-10-16/` 原样复制以下文件（都是 BRK 响应 JSON）：
    - `onchain-seller/data/` 下的 `d_price_close.json`、`d_true_market_mean.json`、`d_sth_realized_price.json`、`d_utxos_1d_to_1w_old_realized_price.json`；
    - `onchain-pulse/data/d_realized_price.json`。
  - 补抓 `lth_realized_price` 的 day1 数据，参数 `start=2013-01-01&end=2026-10-17`。
  - 补抓 2026-10-16 的 `all` lin500 URPD。
  - 写 `README.md`：注明数据来源（bitview.space 公开数据），列出每个文件的 `stamp`、`version` 和补抓日期；补抓到的 `version` 与样本不一致时，在这里注明。

- [ ] **Step 2：写失败的测试**
  - `test_day1_backfill_is_split_by_weight`：
    - 固定 clock 为 2026-10-16 10:00Z，调用 `series(DAY1_SERIES, "day1", START)`。
    - 断言 `Calls` 里正好 2 个 bulk 请求，每个请求的 `series` 参数含 3 个名字。
    - 每条序列的估算点数是 5,037 天，3 条合计 15,111，不超过 18,000。
    - 6 条序列都出现在 `found` 里。
  - `test_incremental_start_position_estimates_points`：用 `start=6494`，估算点数为 4（位置 6494 到今天的位置 6497），6 条序列放进 1 个请求。
  - `test_bulk_series_not_found_retries_each_series`：
    - 设置 `missing={"lth_realized_price"}`。
    - 断言结果 `missing == ["lth_realized_price"]`，其余 5 条都在 `found` 里。
    - 断言 `Calls` 里出错的那一片之后，跟着 3 个只含 1 个序列名的请求。
  - `test_unreachable_brk_raises_retryable_error`：所有路径都返回 503 时，抛出 `BrkError`，`code == "brk_unavailable"`，`retryable is True`。
  - `test_urpd_404_returns_none_and_parses_buckets`：
    - 404 时返回 None。
    - 解析 fixture 时，响应里多出的字段（如 `weight`）被忽略。
    - 相邻两个桶的 `price_floor` 相差 500。

- [ ] **Step 3：确认测试失败**
  - 运行：`../../.venv-foundation/bin/python -m pytest tests/onchain/test_onchain_brk.py -q`
  - 期望：`ModuleNotFoundError`。

- [ ] **Step 4：实现 `onchain/brk.py`**
  - 估算点数：
    - start 为日期：日期 → 今天（按 clock）的天数加 1；hour1 按小时数计。
    - start 为位置：今天的位置 − start + 1。
  - 每片序列数 = `max(1, MAX_POINTS // 点数)`。
  - bulk 返回的有序数组，按请求顺序配回各自的序列名。
  - 错误处理：
    - HTTP 404：先看 body 里的 code，是 `series_not_found` 就拆成逐条请求。
    - 429、5xx 和超时：`BrkError("brk_unavailable", True)`。
    - 其他 4xx：`BrkError("brk_bad_request", False)`。

- [ ] **Step 5：确认通过**
  - 同一命令期望 5 passed。
  - `ruff check .` 和 `mypy src/wheelhouse_service` 都通过。

- [ ] **Step 6：提交**
  - 提交以上新建文件。
  - commit message：`feat(onchain): add BRK client with weight-chunked bulk requests`

### Task 2：存储

**Files**
- 新建：`onchain/store.py`、`onchain/migrations/001_onchain.sql`、`tests/onchain/test_onchain_store.py`
- 修改：`pyproject.toml` 的 package-data，增加 `"onchain/migrations/*.sql"`

**Interfaces**

用到：Task 1 的 `SeriesData`、`Urpd`、`Index`。

产出 `class OnchainStore`：
- `__init__(self, path: Path)`：迁移写法照 `PortfolioStore`，使用 `onchain_schema(version, checksum)` 表；文件权限 0600。
- 序列：
  - `merge_series(name, index, data: SeriesData, fetched_at: datetime) -> None`：按位置 upsert，同时记下 `version`。
  - `replace_series(batch: dict[str, SeriesData], index: Index, fetched_at: datetime) -> None`：在同一个事务里删掉这些序列的旧数据、写入新数据。
  - `read_series(name, index) -> list[tuple[datetime, float | None]]`：按时间升序。
  - `series_version(name, index) -> int | None`
  - `last_position(name, index) -> int | None`
- URPD：
  - `save_urpd(urpd: Urpd, fetched_at: datetime) -> None`
  - `latest_urpd(cohort: str, agg: str) -> Urpd | None`
- 派生结果：
  - `save_derived(kind: str, payload: str, computed_at: datetime) -> None`
  - `derived(kind: str) -> tuple[str, datetime] | None`
  - `clear_derived(kind: str) -> None`
- 同步状态：
  - `set_state(**values: str | None) -> None`
  - `state() -> dict[str, str | None]`，key 为 `brk_version`、`refreshing`、`last_success_at`、`last_error`、`next_due`、`missing_series`（JSON 数组）、`reasons`（JSON 数组）。

步骤：

- [ ] **Step 1：写失败的测试**
  - `test_migration_is_idempotent_and_private`：连续两次创建，都不报错；文件权限为 `0o600`。
  - `test_replace_is_atomic`：先 merge 一份数据；再调用 replace，用 monkeypatch 让第二条序列写入时抛错。期望 `read_series` 读到的仍是旧数据。
  - `test_positions_map_to_utc_from_2009`：
    - day1 位置 6497 对应 `2026-10-16T00:00Z`；
    - hour1 位置 0 对应 `2009-01-01T00:00Z`。
  - `test_state_roundtrip_and_latest_urpd`

- [ ] **Step 2：确认失败**
  - 运行 `pytest tests/onchain/test_onchain_store.py -q`，期望导入失败。

- [ ] **Step 3：实现**

  | 表 | 字段 / 主键 |
  |---|---|
  | `series` | `series`、`idx`、`position`、`value`、`fetched_at`；主键 `(series, idx, position)` |
  | `series_meta` | `series`、`idx`、`version`；主键 `(series, idx)` |
  | `urpd` | `cohort`、`day`、`agg`、`close`、`total_supply`、`buckets_json`、`fetched_at`；主键 `(cohort, day, agg)` |
  | `derived` | `kind`（主键）、`payload`、`computed_at` |
  | `sync_state` | `key`（主键）、`value` |

- [ ] **Step 4：确认通过**
  - 期望 4 passed；ruff 和 mypy 通过。

- [ ] **Step 5：提交**
  - commit message：`feat(onchain): add private onchain store with atomic series replace`

### Task 3：周期六态

**Files**
- 新建：`onchain/cycle.py`、`tests/onchain/test_onchain_cycle.py`

**Interfaces**

产出：
- `CycleState = Literal["advance", "breakout", "pressure", "repair", "breakdown", "capitulation"]`
- `DEADBANDS = {"depth": 7.0, "pvs": 6.8, "spread": 1.25}`
- `raw_state(depth: float, pvs: float, spread: float) -> CycleState`：按 (depth>0, pvs>0, spread>0) 对照：

  | 三元组 | 状态 |
  |---|---|
  | (1,1,1) | advance |
  | (1,1,0) | breakout |
  | (1,0,1) | pressure |
  | (0,1,0) | repair |
  | (0,0,1) | breakdown |
  | (0,0,0) | capitulation |

- `gate(current: CycleState, depth: float, pvs: float, spread: float) -> CycleState`：整体门控。
- `class Component(Model)`：`name: Literal["depth", "pvs", "spread"]`、`value: float`、`deadband: float`、`supports: bool`
- `class Episode(Model)`：`state: CycleState`、`start: date`、`end: date`、`days: int`
- `class Cycle(Model)`：`as_of: date`、`state: CycleState`、`since: date`、`day: int`、`components: list[Component]`、`episodes: list[Episode]`、`changes: int`
- `classify(rows: Sequence[tuple[date, float | None, float | None, float | None, float | None]]) -> Cycle | None`
  - 每行依次是 `(日期, W, STH, TMM, price_close)`。
  - 只保留四个值都不为空且都大于 0 的行。
  - 一行都不剩时返回 None。

步骤：

- [ ] **Step 1：写失败的测试**
  - `test_raw_state_maps_sign_triplets`：覆盖上表 6 种组合，另外断言分量恰好为 0 时算负。
  - `test_gate_boundary_is_strict`：
    - `gate("breakout", 8, 9, 1.25)` 返回 `"breakout"`，此时只有 spread 翻转，且恰好等于死区。
    - `gate("breakout", 8, 9, 1.26)` 返回 `"advance"`。
  - `test_gate_needs_every_flipped_component`：从 advance 到 repair，depth 和 spread 都会翻转。
    - `gate("advance", -7.5, 3, -1.0)` 返回 `"advance"`：depth 过了死区，spread 没过。
    - 接着调用 `gate("advance", -6.0, 3, -1.5)` 也返回 `"advance"`：这次 spread 过了、depth 没过，而且上一次的部分翻转不会被记住。
  - `test_classify_skips_rows_with_missing_or_nonpositive_values`：最后一行 STH 为 None 时，`as_of` 取前一天；price 为 0 的行同样跳过。
  - `test_fixture_parity_breakout_since_sep_23`：
    - 输入 fixture 中 2013-01-01 至 2026-10-16（含）的全部行。
    - 期望 `state == "breakout"`、`since == date(2026,9,23)`、`day == 24`、`changes == 48`。
    - 三个 component 的 `supports` 都为 True。
    - 用同一份数据算 2026-09-22 和 09-23 的 depth，四舍五入到两位小数，分别为 4.41 和 7.46。

- [ ] **Step 2：确认失败**
  - 运行 `pytest tests/onchain/test_onchain_cycle.py -q`。

- [ ] **Step 3：实现**
  - `gate` 的逻辑：
    ```text
    target = raw_state(depth, pvs, spread)
    if target == current: return current
    flipped = 在 current 和 target 之间符号不同的分量
    return target if 所有 flipped 分量都满足 abs(value) > DEADBANDS[分量] else current
    ```
  - `classify` 的逻辑：第一行直接取 `raw_state`，之后每行用 `gate`。
  - `day` 是当前这一段的行数，包含最后一行。

- [ ] **Step 4：确认通过**
  - 期望 5 passed；ruff 和 mypy 通过。

- [ ] **Step 5：提交**
  - commit message：`feat(onchain): add six-state cycle classifier with joint deadband gate`

### Task 4：模型线与 Median

**Files**
- 新建：`onchain/levels.py`、`tests/onchain/test_onchain_levels.py`

**Interfaces**

用到：Task 1 的 `Urpd`。

产出：
- `LineName = Literal["true_mean", "short_term", "average", "long_term", "median"]`
- `LINE_SERIES = {"true_mean": "true_market_mean", "short_term": "sth_realized_price", "average": "realized_price", "long_term": "lth_realized_price"}`
- `class ModelLine(Model)`：`name: LineName`、`price: float`
- `last_complete(rows: dict[str, list[tuple[datetime, float | None]]]) -> tuple[datetime, dict[str, float]] | None`
  - 找出 `LINE_SERIES` 对应的 4 条序列全都有值且大于 0 的最后一个时间点。
- `median_cost(urpd: Urpd) -> float | None`
  - 总供应为 0 时返回 None。
  - 桶宽从 `aggregation` 里取：`lin<N>` 的桶宽就是 N。
- `model_lines(last: dict[str, float], urpd: Urpd | None) -> list[ModelLine]`
  - `urpd` 为 None 时只返回 4 条线，不含 median。

步骤：

- [ ] **Step 1：写失败的测试**
  - `test_median_interpolates_inside_bucket`：三个桶，floor 为 0、500、1000，供应依次为 1、2、1，结果应为 `750.0`。
  - `test_median_includes_buckets_below_1000`
  - `test_last_complete_skips_partial_today`：今天这一行的 `realized_price` 为 None，返回昨天的时间点和昨天的 4 个值。
  - `test_model_lines_without_urpd_has_four_lines`
  - `test_fixture_median_is_near_page_value`：用 fixture 的 URPD 计算，结果与页面 08:20 显示的 $63,721 相差不超过 $1,000。这只是合理性检查，因为日内快照会变。

- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 期望 5 passed。

- [ ] **Step 5：提交**
  - commit message：`feat(onchain): add model cost lines and URPD median`

### Task 5：同步 worker

**Files**
- 新建：`onchain/sync.py`、`tests/onchain/test_onchain_sync.py`

**Interfaces**

用到：Task 1 到 Task 4。

产出：
- `class OnchainSync`：
  - `__init__(self, store: OnchainStore, client: BrkClient)`
  - `run_once(self, *, now: datetime | None = None) -> bool`：到期就刷新并返回 True，没到期返回 False。
  - `start()`：起一个线程，名字为 `wheelhouse-onchain`，空闲时 `stopping.wait(30)`。
  - `stop()`：join 超时 25 秒。
- `derived` 表的内容：
  - `kind="cycle"`：`Cycle` 的 JSON。
  - `kind="levels"`：`{"as_of": <ISO 时间>, "urpd_date": <date 或 null>, "onchain_close": <float 或 null>, "lines": [...]}`。
  - 某个 kind 的数据缺失时，用 `clear_derived` 清掉。

步骤：

- [ ] **Step 1：写失败的测试**（统一使用 `brk_transport` 和固定的 now）
  - `test_first_run_backfills_and_derives`：
    - now = 2026-10-16 10:40Z。
    - 跑完后 cycle 的 state 为 breakout，levels 有 5 条线。
    - `next_due == 2026-10-16T11:12Z`，即严格晚于 now 的第一个整点 12 分。
    - `last_success_at == now`。
  - `test_incremental_run_starts_three_positions_back`：第二次运行时，`Calls` 里每个 bulk 请求的 `start` 都等于各序列的 `last_position − 3`。
  - `test_version_change_failure_keeps_old_data`：
    - 第二次运行时 transport 的 version 为 `"0.13.0"`，`fail_paths={"/api/series"}`。
    - 期望旧数据和派生结果都还在，`refreshing == "true"`，`last_error == "brk_unavailable"`，`next_due == now + 5 分钟`。
    - 第三次运行时去掉 `fail_paths`。期望序列被整体替换，`brk_version == "0.13.0"`，`refreshing == "false"`。
  - `test_urpd_falls_back_to_yesterday_then_reports_missing`：
    - `urpd_dates={2026-10-15}` 时，`urpd_date` 为 10-15。
    - `urpd_dates=set()` 时，levels 只有 4 条线，reasons 包含 `"urpd_missing"`。
  - `test_missing_series_clears_levels_but_keeps_cycle`：
    - 设置 `missing={"lth_realized_price"}`。
    - 期望 `missing_series` 中有它，`derived("levels")` 为 None，cycle 照常生成。

- [ ] **Step 2：确认失败**

- [ ] **Step 3：实现**，刷新顺序如下：
  1. 调 `version()`。和已存版本不同时，先写 `refreshing=true`，并且本轮对 `DAY1_SERIES` 全部从 `START` 重新取，取完用 `replace_series` 一次性替换。
  2. 版本相同时，增量取数：每条序列从 `last_position − 3` 开始取。某条序列返回的 `version` 和已存的不同时，单独把这条从 `START` 重取并替换。
  3. 取 URPD：先取今天的，没有就取昨天的。
  4. 计算派生结果：
     - cycle 用 `classify`，输入是 W、STH、TMM、`price_close` 四条序列；
     - levels 用 `last_complete` 加 `model_lines`。
  5. 写入状态：`last_success_at`、`refreshing=false`、`missing_series`、`reasons`、`next_due`。
  - 失败时，可重试的错误设 `next_due = now + 5 分钟`；其他错误设为下一个整点 12 分。

- [ ] **Step 4：确认通过**：期望 5 passed。

- [ ] **Step 5：提交**
  - commit message：`feat(onchain): add hourly BRK sync worker with derived cycle and levels`

### Task 6：接口与契约

**Files**
- 新建：`onchain/models.py`、`onchain/api.py`、`tests/onchain/test_onchain_api.py`
- 修改：`http.py`
- 重新生成：`openapi.json`、`api-schema.d.ts`

**Interfaces**

用到：Task 2 到 Task 5。

产出（`onchain/models.py`）：
- `DataState = Literal["fresh", "stale", "unavailable"]`
- `day1_state(last: date | None, now: datetime) -> DataState`：

  | 情况 | 结果 |
  |---|---|
  | `last` 是今天 | fresh |
  | `last` 是昨天，且 `now` 早于 02:00 UTC | fresh |
  | 其他有值的情况 | stale |
  | `last` 为 None | unavailable |

- `class DatasetStatus(Model)`：`name: Literal["day1", "urpd"]`、`data_state: DataState`、`last_at: AwareDatetime | None`、`reasons: list[str]`
- `class OnchainStatus(Model)`：`brk_version: str | None`、`refreshing: bool`、`last_success_at: AwareDatetime | None`、`last_error: str | None`、`datasets: list[DatasetStatus]`
- `class CycleView(Model)`：
  - 状态字段：`data_state: DataState`、`reasons: list[str]`、`refreshing: bool`、`forming_at: AwareDatetime | None`
  - 结果字段：`as_of: date | None`、`state: CycleState | None`、`since: date | None`、`day: int | None`、`components: list[Component]`、`episodes: list[Episode]`、`changes: int`
  - 来源：`brk_version: str | None`
- `class LevelsView(Model)`：
  - 状态字段：`data_state`、`reasons`、`refreshing`、`forming_at`
  - 结果字段：`as_of: AwareDatetime | None`、`urpd_date: date | None`、`onchain_close: float | None`、`lines: list[ModelLine]`
  - 来源：`brk_version`

产出（`onchain/api.py`）：
- `create_router(path: Path, client: BrkClient | None = None, *, start_worker: bool = True, clock: Callable[[], datetime] = <当前 UTC 时间>) -> APIRouter`
- 前缀 `/api/wheelhouse/v1/onchain`，路由为 `GET /status`、`GET /cycle`、`GET /levels`。
- 两个视图的 `data_state` 都等于 `day1_state(as_of, now)`。URPD 的问题只体现在 reasons 里。
- `forming_at` 等于 `as_of` 那一行的时间，但只在 `as_of` 是今天时才有值。

`http.py` 修改：
- `create_app` 增加关键字参数 `brk_client: BrkClient | None = None`。
- 挂载 `create_router((database.parent if database else data_dir) / "onchain.sqlite", brk_client, start_worker=start_worker)`。
- `capabilities` 追加 `"onchain"`。

步骤：

- [ ] **Step 1：写失败的测试**
  - 所有测试都用 `with TestClient(create_app(tmp / "m.sqlite", start_worker=False, brk_client=<任何请求都抛异常的客户端>)) as client:` 的形式。
  - `test_empty_store_is_unavailable_with_200`：三个接口都返回 200，`data_state == "unavailable"`。
  - `test_read_routes_never_touch_network`：
    - 先用 fixture 客户端对 `tmp/"onchain.sqlite"` 跑一次 `OnchainSync.run_once`。
    - 然后通过 app 读取：`/cycle` 的 state 为 breakout，`/levels` 有 5 条线，期间没有任何网络调用。
  - `test_day1_state_midnight_grace`：直接测试 `day1_state`：

    | `now` | `last` | 期望 |
    |---|---|---|
    | 10-17 01:30Z | 10-16 | fresh |
    | 10-17 02:30Z | 10-16 | stale |
    | 10-16 | 10-16 | fresh |
    | 任意 | None | unavailable |

  - `test_worker_not_started_when_disabled`：在 `with TestClient(...)` 期间，`threading.enumerate()` 里没有名为 `wheelhouse-onchain` 的线程。
  - `test_capability_and_get_only_schema`：capabilities 含 `"onchain"`；openapi 中所有 `/onchain/` 路径只有 `get` 方法。

- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 运行 `pytest tests/onchain -q`，再跑一遍全量 `pytest -q`，确认没有回归。

- [ ] **Step 5：生成契约**
  - 在仓库根目录运行 `make contract`。
  - 期望 `api-schema.d.ts` 中出现 `CycleView`、`LevelsView`、`OnchainStatus`。
  - 基线提交已经包含了既有的契约改动，所以这里的 diff 只会是新增的 schema。

- [ ] **Step 6：提交**
  - commit message：`feat(onchain): expose read-only cycle, levels and status endpoints`

### Task 7：前端契约与客户端

**Files**
- 新建：`onchain-contract.ts`、`onchain-contract.test.ts`
- 修改：`client.ts`

**Interfaces**
- 产出：
  - `cycleViewSchema`、`levelsViewSchema`，类型都是 `z.ZodType<…, z.ZodTypeDef, unknown>`；
  - `getOnchainCycle(signal?: AbortSignal): Promise<CycleView>`；
  - `getOnchainLevels(signal?: AbortSignal): Promise<LevelsView>`；
  - 类型 `CycleView`、`LevelsView`，取自 `components["schemas"]`。
- 另外导出 `cycleSample` 和 `levelsSample` 两个对象，供后续测试复用。

步骤：

- [ ] **Step 1：写失败的测试**
  - 手写 `cycleSample`：`state: "breakout"`、`since: "2026-09-23"`、`day: 24`、`changes: 48`、`forming_at: "2026-10-16T00:00:00+00:00"`、3 个 component、`refreshing: false`。解析应当通过。
  - `state: "bull"` 被拒绝。
  - `lines[].name` 只接受 5 个合法值。

- [ ] **Step 2：确认失败**
  - 运行 `make sync`，然后执行 `pnpm --filter frontend exec vitest run src/features/wheelhouse/onchain-contract.test.ts`。

- [ ] **Step 3：实现**
  - 在 `client.ts` 中复用 `query()`，路径分别为 `/onchain/cycle` 和 `/onchain/levels`。

- [ ] **Step 4–5：通过 → 提交**
  - commit message：`feat(onchain): add frontend onchain contract and client`

### Task 8：页头周期徽章

**Files**
- 新建：`cycle-badge.tsx`、`cycle-badge.test.tsx`
- 修改：`market-page.tsx`、`i18n.ts`、`market.css`

**Interfaces**
- 产出：`CycleBadge({ symbol, live, onOpen }: { symbol: Stream["symbol"]; live: boolean; onOpen: () => void })`
  - query key 为 `["wh", "onchain", "cycle"]`，`refetchInterval: 60000`。
  - `symbol !== "BTCUSDT"` 或 `!live` 时返回 null。

步骤：

- [ ] **Step 1：写失败的测试**
  - 用 `cycleSample` 渲染，显示 `Cycle · Breakout · day 24`、`since 23 Sep` 和 `includes today (forming)`。
  - ETH 不渲染；`live=false` 不渲染。
  - `data_state="stale"` 时有 `wh-cycle--muted` 类，并显示 stale 文案；`unavailable` 时显示 `Cycle unavailable` 和原因。
  - 点击时调用 `onOpen`。

- [ ] **Step 2–4：失败 → 实现 → 通过**
  - 新增 i18n key `cycle.*`，en 和 zh 各一套。状态的中文：上行、突破、承压、修复、破位、投降。
  - `market-page.tsx`：
    - 徽章挂在 symbol 选择所在那一行 toolbar 的末尾，`live={!selectedId}`。
    - `onOpen` 执行 `setMethod("levels")` 并设置 `scrollToCycle=true`。
    - 用一个 effect，在 Key levels 面板渲染之后（`requestAnimationFrame`）滚动到 `#wh-onchain-cycle`，然后把 `scrollToCycle` 复位。
  - `market.css`：≤600px 时，徽章单独占一行（`flex-basis: 100%`）。

- [ ] **Step 5：提交**
  - commit message：`feat(onchain): add cycle badge to market header`

### Task 9：Key levels 叠加线与 inspector

**Files**
- 新建：`onchain-levels.tsx`、`onchain-levels.test.tsx`
- 修改：`market-chart.tsx`、`market-chart.test.tsx`、`market-page.tsx`、`market-defaults.test.tsx`、`i18n.ts`、`market.css`

**Interfaces**
- 产出（`market-chart.tsx`）：
  - `export interface ChartOverlay { id: string; label: string; price: number }`
  - `ChartProps` 增加 `overlays?: ChartOverlay[]`。
- 产出（`onchain-levels.tsx`）：`OnchainLevels({ levels, cycle }: { levels?: LevelsView; cycle?: CycleView })`，分三个区块：
  - Model lines：5 条线的名称和价格；
  - Cycle：`id="wh-onchain-cycle"`，显示状态、开始日期、天数，以及三个分量的值、死区和是否支持当前状态；
  - Source。
  - Cycle 和 Source 用 `<details>`：宽度 ≥601px（`matchMedia` 判断）时默认展开，否则默认折叠。
  - `refreshing` 为真时，Source 区块显示 `Refreshing on-chain data…`。

步骤：

- [ ] **Step 1：写失败的测试**
  - `market-chart.test.tsx`：
    - `overlays do not change the price axis`：加上一条超出范围的 overlay，y 轴刻度文本不变。
    - `out-of-range overlays render edge markers`：价格低于下限时，下沿出现 `↓ Average $53,842`；高于上限时，上沿出现 `↑`。
    - `in-range overlay draws a dashed line labelled inside the plot`：标签的 x 坐标小于 `right`，不与刻度列重叠。
  - `onchain-levels.test.tsx`：
    - 渲染 5 条线和 3 个分量。
    - 在 jsdom 中 mock `matchMedia` 为窄屏时，Cycle 和 Source 默认折叠。
    - `refreshing` 时显示提示。
  - `market-defaults.test.tsx`：先把对 MarketChart 的 mock 改为记录收到的 props，再断言：
    - BTC 实时视图下，`overlays` 有 5 项；
    - ETH 下没有 overlays，并显示 `levels.btcOnly` 的文案；
    - 选中快照（mock `getSnapshot`）时没有 overlays，并显示 `levels.latestOnly` 的文案。

- [ ] **Step 2：确认失败**

- [ ] **Step 3：实现**
  - `market-chart.tsx`：
    - overlay 不加入 `values`，因此不影响 y 轴范围（约 173–188 行）。
    - 在范围内的 overlay 画成虚线；标签右对齐（`text-anchor="end"`），x 为 `right - 4`，放在线的上方。
    - 超出范围的 overlay 按方向分组，在图的上沿或下沿各画一行文本。
  - `market-page.tsx`：
    - 条件为 `method === "levels" && symbol === "BTCUSDT" && !selectedId` 时，把 levels 的 lines 转成 overlays，label 走 i18n。
    - inspector 顶部插入 `<OnchainLevels/>`，原有的 baseline facts 保留在它下方。
  - Source 区块文案：`Bitcoin Research Kit · bitview.space · BRK {{version}} · as of {{date}}`，并注明 oracle 价格，以及 `STH (<150d)`。

- [ ] **Step 4：确认通过**
  - 运行上述三个测试文件，以及 `market-defaults.test.tsx`。

- [ ] **Step 5：提交**
  - commit message：`feat(onchain): overlay model cost lines on key levels without rescaling`

### Task 10：Flows tab 外壳与 AGENTS.md

**Files**
- 新建：`flows-panel.tsx`、`flows-panel.test.tsx`
- 修改：`market-page.tsx`、`market-defaults.test.tsx`、`i18n.ts`、`market.css`、`AGENTS.md`

**Interfaces**
- 产出：`FlowsPanel({ symbol }: { symbol: Stream["symbol"] })`
  - 子视图来自 URL 参数 `flow`，取值 `"seller" | "perp"`，默认 `"seller"`。
- `market-page.tsx` 中 `Method` 增加 `"flows"`，`methods` 增加第 4 项。

步骤：

- [ ] **Step 1：写失败的测试**
  - `flows-panel.test.tsx`：
    - seller 子视图显示 `Seller pressure is not implemented yet`；
    - perp 子视图显示 `Not connected — perp data source pending`；
    - 两个子视图中都没有任何数字；
    - 切换子视图会写入 `flow=perp`；
    - ETH 下显示 `Flows are BTC only`。
  - `market-defaults.test.tsx`：
    - tablist 有 4 个 tab，第 4 个是 Flows；
    - 在 Fibonacci 上按 → 键，焦点移到 Flows；
    - 进入 Flows 后，时间周期控件不渲染。

- [ ] **Step 2–4：失败 → 实现 → 通过**

- [ ] **Step 5：更新 AGENTS.md 的「已确认的 UI」一节**
  - 方法 tab 改为 TD Sequential / Key levels / Fibonacci / Flows。
  - 写明 Flows 内照原站多图纵排，这是"一张大图"规则的唯一例外。
  - 写明 Key levels 的链上密集带画在右侧刻度轨，P3 实施。
  - 写明窄屏下三栏说明全部展开。

- [ ] **Step 6：提交**
  - commit message：`feat(onchain): add flows tab shell and record confirmed UI`

### Task 11：全量检查与浏览器核验

**Files**
- 新建：`docs/features/btc-onchain-perp/P1-VERIFICATION.md`

步骤：

- [ ] **Step 1**：运行 `make check`。期望 ruff、mypy、pytest、types、type-check、vitest 全部通过。
- [ ] **Step 2**：运行 `make dev`，再运行 `make doctor`，三个服务都应为 ready。然后等 `GET /api/wheelhouse/v1/onchain/status` 的 `last_success_at` 不为空。
- [ ] **Step 3：对照原站**
  - 记录 `/onchain/cycle` 返回的状态、开始日期和天数。
  - 在已登录的 Edge 中读取 alpha-vol 页头的文字，与上述三项对照，应当一致。
  - `/onchain/levels` 的 5 条线与 BRK 最后一行的值对照。
- [ ] **Step 4：浏览器核验**（内置浏览器，1440px 和 390px 各一次）
  - BTC：
    - 页头徽章可见；点击后跳到 Cycle 区块。
    - Key levels 有叠加线；Average 和 Long-term 两条线贴在下沿，标签不和刻度重叠。
    - inspector 三个区块齐全；390px 下 Cycle 和 Source 默认折叠，徽章单独占一行。
  - ETH：没有徽章，显示 BTC only。
  - Flows：两个子视图显示占位文案；可以用键盘切换。
  - 控制台无报错；390px 下没有横向溢出。
  - 与 `.superpowers/brainstorm/33535-1792151482/content/` 下的 `key-levels.html`、`mobile.html` 对照，差异写进核验记录。
- [ ] **Step 5**：提交核验记录并 push。commit message：`docs(onchain): record P1 verification`

## 评审修订记录

本计划第一版经过一轮独立评审：2 条严重、7 条中等、3 条低等，全部已改：

| 问题 | 修订 |
|---|---|
| BRK 响应带 `type` 字段，而 `Model` 不允许额外字段 | 改为 `BrkModel(extra="ignore")` |
| 用价格反推的方式无法精确测到死区边界；"depth 与 spread 同时翻转"的场景在数学上不成立 | 暴露 `gate` 函数直接测；部分翻转的场景改为 advance 到 repair |
| 跳过缺值行的口径与原站不一致 | 周期改为四条序列都存在且大于 0；模型线的取行逻辑移到 `last_complete`，并补上测试 |
| mock transport 能力不够 | 增加 `version`、`fail_paths`、`urpd_dates` 参数和 `Calls` 记录；补全点数估算规则；明确 404 时先看 body 里的 code |
| 时钟无法注入；TestClient 没有跑 lifespan | 改用纯函数 `day1_state`，`create_router` 增加 `clock` 参数；测试统一用 `with TestClient` |
| 版本变化、URPD 缺失、`data_state` 合成三处行为未定义 | 已在 Task 5 和 Task 6 写明 |
| 快照模式下徽章是否显示、滚动时机、refreshing 显示、窄屏规则、`start_worker` 测试、`forming_at` 字段 | 已补到 Task 6、Task 8、Task 9 |
| 执行前提的说法不准（许多文件其实是未跟踪的新文件；需要明确基线的纳入和排除清单；第一次推送要 `-u`） | 已重写执行前提 |
| 测试文件命名、标签与刻度重叠、`next_due` 定义 | 已修正 |
