# BTC 永续状态 P6 实施计划：清算与买卖量改用 Coinalyze

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标**：清算、Bybit/OKX/Hyperliquid 的买卖差、OKX/Hyperliquid 的 OI 改从 Coinalyze 免费 API 取，让表 1 和图 1–4 一上线就有约 90 天的历史。同时：
- 新增 Hyperliquid 视图，清算为估算值，并标注 estimated；
- All venues 扩为 Binance + Bybit + OKX。

**架构**：
- 新模块 `perps/coinalyze.py` 只负责请求和整形，HTTP 复用 `PerpsRest`（单请求在途、按 host 退避）。
- worker 把已收盘的 4hour 和 5min 点存进新表 `cz_series`，并在进程内把 Coinalyze 的调用限在每分钟 20 次以内。
- `grid.py` 把这些点放进现有的 10m 网格：
  - 已收盘窗口的值整窗放进窗口最后一个桶；
  - 其他窗口逐桶用 5min；
  - 合成视图另有一条整窗失效规则。

  `states.py` 的判定规则不变。
- WebSocket 采集器保留，默认关闭，只用于对照。

**技术栈**：同 P4，不加依赖。

**Spec**：[PROPOSAL-COINALYZE.md](PROPOSAL-COINALYZE.md) v3.1（下文简称"方案"，§x 指方案的章节），在 [SPEC.md](SPEC.md) v3.2 之上修改。两者冲突时以方案为准；方案没提到的规则按 SPEC v3.2 执行。T5 会把 SPEC 改成 v4，与方案一致。

## 计划层面的裁定

| 编号 | 裁定 | 理由 |
|---|---|---|
| P6-R1 | 另一个会话合并到 main 之后，从 main 开分支 `claude/coinalyze`。第一个提交只放方案 v3.1 和本计划 | 用户要求；当前工作区被另一个会话占用 |
| P6-R2 | 提交时按路径逐个 `git add`。仓库根目录有与本项目无关的未跟踪文件（`backend/`、`frontend/`、`pyproject.toml` 等） | 防止误提交 |
| P6-R3 | Coinalyze fixture 从 V1 的原始响应（`.local/coinalyze-v1/run-2026-10-19T0741Z/raw/`）裁出，放在 `services/analytics/tests/perps/fixtures/coinalyze/`，附 README 注明来源和日期 | 公开行情数据，与 P4-R3 相同 |
| P6-R4 | 测试一律不访问外网：<br>• 客户端测试用 `httpx.MockTransport`；<br>• sync 测试用 `FakeCoinalyze`，写法同现有的 `FakeRest`；<br>• api 测试中 Coinalyze 的请求和交易所请求一起走注入的 `perps_http` | 与 P4 一致 |
| P6-R5 | `states.py` 只加 Grid 的两个 QC 字段，判定、阈值、表 1 的代码不改 | 方案 §3.3 |
| P6-R6 | `states_parity.py` 留在 `.local`，不入库。T5 把它扩到 hyperliquid，调用 `grid.estimate_liquidations` | 原站样本不能公开（P4-D9） |
| P6-R7 | 删除本次改动后变成死代码的部分：<br>• `grid.read_liquidations`、`_covered`、`_liquidations`、`LIQ_STREAM`；<br>• `store.liquidation_sums`、`store.liquidation_sizes`、`LiquidationSizes`；<br>• `sync.qty_units`、`QtyUnits`、`NOTIONAL_RANGE`、`MIN_QTY`；<br>• `api.VIEW_STREAMS`。<br>保留：采集器、`store.trades`（`test_perps_collector.py` 用它读回写入的数据），以及 `liquidations`、`coverage`、`trades_10m` 三张表。删除前先 `grep` 确认没有调用方 | 只清理本次改动造成的死代码；与方案 §3.6 一致 |
| P6-R8 | key：环境变量 `WHEELHOUSE_COINALYZE_KEY` 只要存在就以它为准，空串表示缺失；不存在时，只从仓库根目录的 `.env` 读这一个键。不把整份 `.env` export 给进程 | 用户要求 key 只从环境或 `.env` 读 |
| P6-R9 | 新增 `services/analytics/tests/conftest.py`，其中一个 autouse fixture 把 `WHEELHOUSE_COINALYZE_KEY` 置为空串，并把 `settings.DOTENV` 指向 `tmp_path` 下不存在的文件。测试永远不读开发者真实的 `.env` | 复核 I9 |
| P6-R10 | 核验用的本机服务另开端口（例如 8797），数据目录用 `.local/analytics` 的副本，用完即停。同一个 key 同时最多两个进程运行：核验时如果 test 环境也在跑，本机只起一个服务。不碰 8787 和 1420 上别人的服务，除非用户说可以 | 协作约束；方案 §3.7 的配额 |
| P6-R11 | 修改迁移、SQL 文件时，注释里不得出现 `;`，因为 `store.py` 按 `;` 切分语句 | 复核 C1 |
| P6-R12 | 改写旧测试时，"已判定""已覆盖"之类的前提改用写入 `cz_series` 来构造，不得删减断言来迁就新实现 | 复核 I4 |

## 全局约束

- **语言**：代码、标识符、注释、commit message 用英文；文档用中文；UI 文案走 `i18n.ts`，en 和 zh 的键一一对应。
- **key**：
  - 只放在 Coinalyze 请求的 `api_key` 请求头里；
  - 不进 URL、日志、`repr`、异常消息、fixture、sample 或提交；
  - 不打印。
- **缺失**：未覆盖或缺失记为 None，不记为 0。只有方案 §3.4 写明的 `filled` 清算区间存为 0。
- **只存已收盘的点**：`t + 区间长 ≤ 取数时刻`。
- **Coinalyze 的 symbol**：`binance=BTCUSDT_PERP.A`、`bybit=BTCUSDT.6`、`okx=BTCUSDT_PERP.3`、`hyperliquid=BTC.H`。
- **请求**：
  - 每类数据一次请求带上该类的全部 symbol；
  - 清算：binance、bybit、okx；OHLCV：bybit、okx、hyperliquid；OI：okx、hyperliquid；
  - 清算和 OI 带 `convert_to_usd=false`。
- **检查**：
  - 每个 Task 结束时 `make check` 全绿；
  - 改了契约先运行 `make contract`；
  - `deploy/test/test_composition.py` 要单独运行：`.venv-foundation/bin/python -m pytest deploy/test/test_composition.py`。
- **发布**：只有用户明确说"发布 test"时才发布。
- **推送**：`git push git@github.com:gaawai-l/algoforce-next.git <branch>`。

## 评审重点（Review Focus）

1. **合成视图在窗口末桶缺 REST 值**：例如 All 视图中 Binance 的 K 线 delta 或 OI 为 None。整窗的合成值必须记为未覆盖或 None，不能把 Bybit、OKX 的 4 小时合计丢掉，也不能让 OI 退回 4 小时前。测试在 T3 的 `test_composite_rest_gap_at_window_end_uncovers_the_window`。
2. **4hour 已入库，但网格的 `last` 还没走到窗口末尾**：这个窗口必须逐桶用 5min。测试在 T3 的 `test_window_past_last_uses_5min`。
3. **安静时段**：Coinalyze 会把没有清算的品种整个省略。这时应补 0、算已覆盖；连续 ≥2 个整窗补 0 的窗口则记为未覆盖。测试在 T1 的 `test_symbol_absent_from_reply_is_filled`、T3 的 `test_filled_run_is_uncovered`。
4. **缺 key 或 key 被拒**：
   - 不发请求，key 不出现在日志里；
   - 401 不会把 host 锁到下一轮之后；
   - 视图带 `rest_error:api.coinalyze.net:key_missing` 或 `:401`；页面显示 key 的提示，不显示"历史不足"横幅。

   测试在 T1、T2，以及 T4 的 `shows the key notice instead of the history banner`。
5. **两个进程共用一个 key**：每个进程每分钟不超过 20 次；429 带小数的 `Retry-After` 时，只退避 Coinalyze 这个 host，时长 ≥60 秒。测试在 T1 的 `test_backoff_parses_fractional_retry_after`，以及 T2 的 `test_coinalyze_calls_are_paced` 和 `test_coinalyze_429_closes_only_its_host`。

---

## 文件结构

路径前缀：后端为 `services/analytics/src/wheelhouse_service/`，测试为 `services/analytics/tests/`，前端为 `integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/`。

| 文件 | 改动 | Task |
|---|---|---|
| `perps/coinalyze.py` | 新增：symbol 表、`Coinalyze.history`、`Coinalyze.markets` | T1 |
| `perps/sources.py` | `PerpsRest.coinalyze()`、`CZ_HOST` 的退避、浮点 `Retry-After` | T1 |
| `perps/rows.py` | `CzVenue`、`CzKind`、`CzPoint`（T1）；`Exchange` 加 `hyperliquid`（T3） | T1、T3 |
| `settings.py`、`tests/conftest.py` | `DOTENV`、`coinalyze_key`、测试隔离（T1）；`perps_collectors`（T4） | T1、T4 |
| `perps/migrations/003_coinalyze.sql`、`perps/store.py` | `cz_series`、删除旧的方向核对行、读写、prune | T2 |
| `perps/sync.py` | Coinalyze 取数、限速、单位核对（T2）；按窗口的方向核对、8 份载荷、`excluded`（T3） | T2、T3 |
| `perps/api.py`、`http.py` | 传入 key（T2）；hyperliquid 的 host 表、`direction()`（T3）；采集器开关、视图和 status 的字段（T4） | T2、T3、T4 |
| `perps/grid.py` | Coinalyze 列、合成视图规则、HL 估算、OKX 并入 All、断档规则、窗口级 QC | T3 |
| `perps/states.py` | `Grid.window_qc`、`Grid.window_missing`，`_qc` 带上它们 | T3 |
| `perps/models.py` | 注释（T3）；`PerpStatesView` 去掉 `collectors`、`PerpsStatus` 加 `markets`（T4） | T3、T4 |
| 前端 `perps-contract.ts`、`api-schema.d.ts`（生成）、`perp-states.tsx`、`i18n.ts` 及测试 | 契约与类型同步（T3）；界面（T4） | T3、T4 |
| 前端 `perp-charts.tsx`、两份 sample JSON | 界面 | T4 |
| `docs/features/btc-perp-states/SPEC.md`、`docs/deployment/RELEASING.md`、`deploy/test/compose.yaml`、`docs/features/btc-onchain-perp/CHART-INVENTORY.md`、新增 `P6-VERIFICATION.md` | 文档与核验 | T5 |

---

### Task 1：Coinalyze 客户端与 key

**Files:**
- Create: `perps/coinalyze.py`
- Create: `tests/conftest.py`
- Create: `tests/perps/test_perps_coinalyze.py`
- Create: `tests/perps/fixtures/coinalyze/{README.md, liquidation-history-4hour.json, ohlcv-history-5min.json, open-interest-history-4hour.json, future-markets.json}`
- Modify: `perps/sources.py`
- Modify: `perps/rows.py`
- Modify: `settings.py`

**Interfaces:**
- Consumes: `PerpsRest`、`RestError`（`sources.py`）。
- Produces：

```python
# rows.py
CzVenue = Literal["binance", "bybit", "okx", "hyperliquid"]
CzKind = Literal["liq", "ohlcv", "oi"]

class CzPoint(Model):
    """One closed Coinalyze interval, in BTC. liq: a = longs, b = shorts liquidated;
    ohlcv: a = volume, b = taker buy volume; oi: a = open, b = close interest."""
    t: int  # interval start, epoch seconds
    a: float
    b: float
    # liq only: inside a fetched range but absent from Coinalyze's reply, so stored as 0.
    filled: bool = False

# coinalyze.py
CZ_HOST = "api.coinalyze.net"
SYMBOLS: dict[CzVenue, str]  # the four symbols in Global Constraints
KIND_VENUES: dict[CzKind, tuple[CzVenue, ...]] = {
    "liq": ("binance", "bybit", "okx"),
    "ohlcv": ("bybit", "okx", "hyperliquid"),
    "oi": ("okx", "hyperliquid"),
}
Interval = Literal["5min", "4hour"]
STEPS: dict[Interval, int] = {"5min": 300, "4hour": 14_400}

class MarketCheck(Model):
    venue: CzVenue
    symbol: str
    denominated: str | None  # oi_lq_vol_denominated_in; None if the symbol is not listed
    buy_sell: bool | None  # has_buy_sell_data; None if not listed
    ok: bool  # listed, BASE_ASSET, and buy/sell data where KIND_VENUES["ohlcv"] reads it

class Coinalyze:
    def __init__(self, rest: PerpsRest, key: str | None,
                 clock: Callable[[], datetime] = _utc_now) -> None: ...
    def history(self, kind: CzKind, interval: Interval, frm: int, to: int
                ) -> dict[CzVenue, list[CzPoint]]: ...
    def markets(self) -> list[MarketCheck]: ...

# sources.py
class PerpsRest:
    def coinalyze(self, path: str, params: Mapping[str, str | int], key: str) -> Any:
        """GET https://api.coinalyze.net{path} with the key in the `api_key` header only; the
        parsed JSON body. Errors and backoff as `_get`."""

# settings.py
DOTENV = Path(__file__).resolve().parents[4] / ".env"
Settings.coinalyze_key: str | None  # dataclasses.field(default=None, repr=False)
```

`history` 的语义：
- **缺 key**：`key` 为 None 时抛 `RestError(CZ_HOST, "key_missing")`，不发请求。
- **请求**：一次 GET，`symbols` 为 `KIND_VENUES[kind]` 的 symbol 用逗号连接，参数为 `interval`、`from=frm`、`to=to`：
  - `liq` → `/v1/liquidation-history`，带 `convert_to_usd=false`；
  - `ohlcv` → `/v1/ohlcv-history`；
  - `oi` → `/v1/open-interest-history`，带 `convert_to_usd=false`。
- **整形**：只留已收盘的点（`t + step ≤ clock()`）。字段对应关系：
  - `liq`：`(l, s)`；
  - `ohlcv`：`(v, bv)`；
  - `oi`：`(o, c)`。
- **补 0（只限 liq）**：对 `KIND_VENUES["liq"]` 的**每一家**，不论它的 symbol 是否出现在回复里（Coinalyze 会省略这段时间没有清算的品种，方案 §2.1），`[ceil(frm/step)·step, to]` 中已收盘、但没有点的 `t`，补一个 `CzPoint(t, 0, 0, filled=True)`。
- **不补 0**：ohlcv 和 oi 中，没出现的 symbol 返回空列表。
- **返回**：按 `t` 升序。
- **格式错误**：形状不对的回复抛 `RestError(CZ_HOST, "bad_response")`。

`markets` 只取本期 4 个 symbol 的记录，每家一个 `MarketCheck`。

`sources.py` 的改动：
- `_get`、`_send` 加一个可选的 `headers` 参数，只用于这一次请求；
- `BACKOFF[CZ_HOST] = {429: 60, 403: 600}`。401 不在表里：抛 `RestError(CZ_HOST, "401")`，不设 `until`；
- `_retry_after` 先试 `float(value)`，只接受有限值（`math.isfinite`），再试 HTTP 日期，上限仍为 `MAX_BACKOFF`；
- `_log` 照旧只记 host、path、结果和耗时。

`settings.py`：环境变量里有 `WHEELHOUSE_COINALYZE_KEY`（哪怕是空串）就用它，空串即 None；没有时解析 `DOTENV`，与 `.local/coinalyze-v1/probe.py` 的 `load_key` 相同：跳过注释，去掉 `export ` 前缀和两端引号。

- [ ] **Step 1：裁 fixture**

从 V1 的原始响应裁出 4 个文件：
- `liquidation-history-4hour.json`：3 个清算 symbol，最后 6 个点，含未收盘的最后一个；
- `ohlcv-history-5min.json`：bybit、okx、hyperliquid，最后 4 个点；
- `open-interest-history-4hour.json`：okx、hyperliquid，最后 3 个点；
- `future-markets.json`：只留本期的 4 个 symbol 和 `BTCUSD_PERP.A`。

README 写明来源（Coinalyze，2026-10-19 取）、裁法和"不含 key"。

检查：用与 Settings 相同的解析取出 key，只输出每个文件的计数：

```bash
.venv-foundation/bin/python - <<'EOF'
from pathlib import Path
from wheelhouse_service.settings import Settings
key = Settings.from_env().coinalyze_key
assert key, "no key to check against"
for f in sorted(Path("services/analytics/tests/perps/fixtures/coinalyze").iterdir()):
    print(f.name, f.read_text().count(key))
EOF
```

Expected：每个文件后面都是 `0`。

- [ ] **Step 2：写失败的测试**（`tests/perps/test_perps_coinalyze.py`，clock 固定为 `2026-10-19T07:42:00Z`；`tests/conftest.py` 按 P6-R9 隔离）

```python
KEY = "test-key-0000"

def test_history_maps_fields_and_drops_open_bars():
    got = cz.history("liq", "4hour", frm, to)                 # fixture via MockTransport
    assert set(got) == {"binance", "bybit", "okx"}
    assert all(p.t + 14_400 <= NOW for pts in got.values() for p in pts)  # 04:00 bar dropped
    assert got["binance"][-1] == CzPoint(t=<fixture t>, a=<fixture l>, b=<fixture s>)

def test_liquidation_gaps_inside_the_closed_range_are_filled():
    # reply for binance with t0 and t0 + 2*step only
    pts = cz.history("liq", "4hour", t0, t0 + 3 * 14_400)["binance"]
    assert (pts[1].t, pts[1].a, pts[1].b, pts[1].filled) == (t0 + 14_400, 0.0, 0.0, True)

def test_symbol_absent_from_reply_is_filled():
    # reply holds bybit only (as Coinalyze answered for OKX on 2026-10-10 09:15-13:15)
    pts = cz.history("liq", "5min", t0, t0 + 3 * 300)["okx"]
    assert [p.filled for p in pts] == [True] * 4 and {p.a + p.b for p in pts} == {0.0}

def test_ohlcv_and_oi_are_never_filled(): ...               # absent symbol -> []

def test_key_never_in_url_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    cz.history("oi", "4hour", t0, t1)
    request = seen[0]
    assert request.headers["api_key"] == KEY
    assert KEY not in str(request.url)
    assert all(KEY not in record.getMessage() for record in caplog.records)
    assert KEY not in repr(Settings(coinalyze_key=KEY))

def test_missing_key_sends_nothing():
    with pytest.raises(RestError) as exc:
        Coinalyze(rest, None).history("liq", "5min", t0, t1)
    assert exc.value.code == "key_missing" and seen == []

def test_backoff_parses_fractional_retry_after():
    # 429 + "28.723" -> until == now + 60 s; 429 + "90.5" -> now + 90.5 s; 429 + "nan" -> now + 60 s
    # 403 -> now + 600 s; 401 -> RestError code "401", until None, backoff_until(CZ_HOST) None
    # fapi.binance.com stays open throughout

def test_markets_checks_units():
    checks = {c.venue: c for c in cz.markets()}
    assert all(c.ok for c in checks.values())
    # okx QUOTE_ASSET -> not ok; hyperliquid has_buy_sell_data false -> not ok;
    # a symbol missing from the list -> denominated None, ok False

def test_settings_key_from_env_then_dotenv(monkeypatch, tmp_path):
    # env "abc" -> "abc"; env "" -> None even when DOTENV holds a key;
    # env unset + DOTENV 'export WHEELHOUSE_COINALYZE_KEY="abc"' -> "abc"; neither -> None
```

- [ ] **Step 3：运行，确认失败**

Run: `.venv-foundation/bin/python -m pytest services/analytics/tests/perps/test_perps_coinalyze.py -q`
Expected：FAIL，原因是 `ModuleNotFoundError: wheelhouse_service.perps.coinalyze`。

- [ ] **Step 4：实现**：按上面的语义改 `sources.py`、`coinalyze.py`、`settings.py`、`rows.py`，新增 `conftest.py`。

- [ ] **Step 5：运行，确认通过**

Run: `make check`
Expected：全部通过；P4 的 `_retry_after` 整数用例不受影响。

- [ ] **Step 6：提交**

```bash
git add services/analytics/src/wheelhouse_service/perps/{coinalyze.py,sources.py,rows.py} \
  services/analytics/src/wheelhouse_service/settings.py services/analytics/tests/conftest.py \
  services/analytics/tests/perps/test_perps_coinalyze.py services/analytics/tests/perps/fixtures/coinalyze
git commit -m "feat(perps): add the Coinalyze client and key setting"
```

---

### Task 2：存储、取数与限速

**Files:**
- Create: `perps/migrations/003_coinalyze.sql`
- Modify: `perps/store.py`
- Modify: `perps/sync.py`
- Modify: `perps/api.py`（`create_router` 加 `coinalyze_key: str | None = None`）
- Modify: `http.py`（`create_app` 加 `coinalyze_key: str | None = None`；为 None 时取 `Settings.from_env().coinalyze_key`）
- Test: `tests/perps/test_perps_store.py`、`tests/perps/test_perps_sync.py`；`tests/perps/test_perps_api.py:822`（status 的 hosts 列表加一项 `api.coinalyze.net`）

**Interfaces:**
- Consumes：T1 的 `Coinalyze`、`CzPoint`、`KIND_VENUES`、`STEPS`、`MarketCheck`、`CZ_HOST`。
- Produces：

```sql
-- 003_coinalyze.sql  (no semicolon inside comments: store.py splits on it)
-- Closed Coinalyze intervals (P6). step is 300 (5min) or 14400 (4hour), t the interval start.
-- liq: a = longs and b = shorts liquidated. ohlcv: a = volume and b = taker buy. oi: a = open
-- and b = close interest. All in BTC.
-- filled = 1 marks a liquidation interval Coinalyze left out of a fetched range, stored as 0.
CREATE TABLE IF NOT EXISTS cz_series(
    venue TEXT NOT NULL,
    kind TEXT NOT NULL,
    step INTEGER NOT NULL,
    t INTEGER NOT NULL,
    a REAL NOT NULL,
    b REAL NOT NULL,
    filled INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(venue, kind, step, t)
) WITHOUT ROWID;
-- The direction check is stored in a new shape from P6 on: the old one would not parse.
DELETE FROM sync_state WHERE key = 'direction_check';
```

```python
# store.py
def upsert_cz(self, kind: CzKind, step: int, venue: CzVenue, points: Sequence[CzPoint]) -> None
def cz_series(self, kind: CzKind, step: int, venue: CzVenue, since: int) -> dict[int, CzPoint]
def cz_latest(self, kind: CzKind, step: int) -> dict[CzVenue, int]  # venues without rows absent
def prune(self, before: int, trade_ids_before: float, cz_5min_before: int) -> None

# sync.py
HOSTS = (BINANCE_HOST, ARCHIVE_HOST, BYBIT_HOST, CZ_HOST)
H4 = 14_400
CZ_SETTLE = 3600            # a closed 4hour window is fetched again every round for this long
CZ_5MIN_KEEP = DAY
CZ_CALLS_PER_MINUTE = 20    # this process's share of the key's 40: two processes may share it
PerpsSync.__init__(..., coinalyze: Coinalyze | None = None,
                   monotonic: Callable[[], float] = time.monotonic,
                   pause: Callable[[float], bool] | None = None)  # None: self.stopping.wait
# sync_state: "cz_4h:<kind>" = {"from": int}; "cz_markets" = [MarketCheck...]; "cz_markets_at"
def stored_markets(state: Mapping[str, str | None]) -> list[MarketCheck]
```

**一轮中的 `_coinalyze(run, start, now)`**：
- **位置**：放在 `_fetch` 的末尾，也就是 `_round` 的 `try` 之内、`_record_hosts` 之前，这样 Coinalyze 的失败才会记进 hosts。
- **何时跳过**：`coinalyze` 为 None 时跳过。
- **失败**：所有请求都经过 `_ask(run, CZ_HOST, ...)`；host 一旦失败，本轮余下的 Coinalyze 请求都跳过。
- **限速**：每次请求前调用 `_pace(cost)`，`cost` 为 symbol 数，markets 为 1。
  - 用 `monotonic` 记录最近 60 秒的花费；
  - 超出 `CZ_CALLS_PER_MINUTE` 时，用 `pause(秒数)` 等待；
  - `pause` 返回 True（正在停机）时抛 `_Stopped`。

对每个 kind（`liq`、`ohlcv`、`oi`）依次做：

1. **4hour**：设 `newest = now // H4 * H4 − H4`（最新一个已收盘的窗口），`latest = store.cz_latest(kind, H4)`。
   - **要回填**：满足下面任一条时，`frm = start`；成功后记 `{"from": start}`：
     - 没有 `cz_4h:<kind>` 记录；
     - 记录的 `from > start`；
     - `KIND_VENUES[kind]` 中某家不在 `latest` 里。
   - **要更正**：不回填，但 `now − (newest + H4) < CZ_SETTLE`，或某家 `latest[v] < newest` 时，`frm = max(start, min(latest.values()) − (OVERLAP − 1)·H4)`。
   - **其余情况**：本轮不取 4hour。
2. **5min**：每轮都取，`frm = now // H4 * H4 − H4`，`to = now`。
3. **单位核对**：三类都取完后，若没有 `cz_markets_at`，或已过 1 天，调用 `markets()` 并存下结果；失败时保留旧结果。

- [ ] **Step 1：写失败的测试**

```python
# test_perps_store.py
def test_migration_003_creates_cz_series_and_drops_the_old_direction_check(tmp_path):
    # a v2 database with sync_state direction_check -> after open: versions 1-3, key gone
def test_cz_upsert_replaces_and_reads_back_filled(tmp_path): ...
def test_prune_keeps_125_days_of_4hour_and_one_day_of_5min(tmp_path): ...

# test_perps_sync.py (FakeCoinalyze records (kind, interval, frm, to) and returns given points)
def test_first_round_backfills_4hour_from_grid_start_and_5min_from_previous_window():
    # 6 history calls + 1 markets call; 4hour frm == start; 5min frm == now//H4*H4 - H4
def test_next_round_in_the_same_window_after_settling_fetches_only_5min(): ...
def test_rounds_in_the_first_hour_after_a_close_refetch_the_last_three_windows():
    # 4hour frm == min(latest) - 2*H4 on each round until CZ_SETTLE has passed
def test_open_bars_are_never_stored(): ...
def test_coinalyze_calls_are_paced():
    # fake monotonic + pause: 16 symbol-calls within a minute pause once so that no 60 s
    # window holds more than 20; pause returning True abandons the round (_Stopped)
def test_coinalyze_429_closes_only_its_host():
    # Binance and Bybit rows still written; hosts[CZ_HOST].error == "429", until >= now + 60 s
def test_key_missing_records_host_error():
    # Coinalyze(rest, None): no request; hosts[CZ_HOST].error == "key_missing", until None
def test_401_does_not_hold_the_host_into_the_next_round(): ...
def test_markets_checked_once_a_day(): ...
```

- [ ] **Step 2：运行，确认失败**

Run: `.venv-foundation/bin/python -m pytest services/analytics/tests/perps/test_perps_store.py services/analytics/tests/perps/test_perps_sync.py -q`
Expected：新增用例 FAIL。

- [ ] **Step 3：实现**
  - 确认 `services/analytics/pyproject.toml` 的 package-data 覆盖 `perps/migrations/*.sql`。
  - `prune` 的新参数要同步改 `sync._round` 的调用和 `test_perps_store` 的旧用例。
  - `create_router` 用同一个 `PerpsRest` 构造 `Coinalyze(rest, coinalyze_key)`，交给 `PerpsSync`。

- [ ] **Step 4：运行，确认通过**

Run: `make check`
Expected：全部通过。

- [ ] **Step 5：提交**：`feat(perps): store Coinalyze history each round`

---

### Task 3：网格、Hyperliquid 估算、All 加 OKX、方向核对

**Files:**
- Modify: `perps/rows.py`（`Exchange` 加 `"hyperliquid"`）
- Modify: `perps/grid.py`
- Modify: `perps/states.py`（只改 Grid 和 `_qc`）
- Modify: `perps/sync.py`：
  - `EXCHANGES` 加 hyperliquid；
  - 方向核对改按窗口；
  - `Directions` 去掉 `bybit_qty`，加 `okx`；
  - `derive_states` 读 `stored_markets` 得到 `excluded`，并加原因码。
- Modify: `perps/store.py`（按 P6-R7 删除）
- Modify: `perps/api.py`：
  - `VIEW_HOSTS["hyperliquid"]` 为全部 4 个 host；其他视图都加 `CZ_HOST`；
  - `VIEW_STREAMS["hyperliquid"] = STREAMS`（T4 会整个删掉，这里只为不报 KeyError）；
  - `direction()` 合并三家。
- Modify: `perps/models.py`（注释）
- Modify：前端
  - `perps-contract.ts`：zod 的 `exchange` 加 `hyperliquid`；`direction_check` 改为 binance、bybit、okx，去掉 `bybit_qty`；
  - `perp-states.tsx`：`exchangeKey` 加 hyperliquid；`VENUES` 的类型改为 `"binance" | "bybit" | "okx"`，all 与 hyperliquid 都是三家；inverted 提示改用 `venueKey`；
  - `i18n.ts`：新增 `perp.exchange.hyperliquid` 和 `perp.venue.binance|bybit|okx`（en/zh 都是交易所名）；
  - 测试对象：`perps-contract.test.ts` 的 `status()` 和 341、364–373 行，`perp-states.test.tsx` 的 `checked()`，改成新的 `direction_check` 形状。
- Generated: `integrations/wealthfolio/openapi.json`、`api-schema.d.ts`（`make contract`）
- Test: `tests/perps/test_perps_grid.py`、`test_perps_states.py`、`test_perps_sync.py`、`test_perps_api.py`

**Interfaces:**
- Consumes：T2 的 `store.cz_series`、`stored_markets`；T1 的 `CzPoint`、`CzVenue`。
- Produces：

```python
# states.py — Grid gains, at the end (defaults keep every existing caller valid):
window_qc: tuple[str, ...] = ()       # QC codes worked out per 4h window (Coinalyze OI)
window_missing: tuple[str, ...] = ()  # series with no window at all in the reference
# _qc returns (codes + window_qc, missing + window_missing)

# grid.py
H4 = 14_400
VIEW_VENUES: dict[Exchange, tuple[CzVenue, ...]] = {
    "all": ("binance", "bybit", "okx"),
    "binance": ("binance",),
    "bybit": ("bybit",),
    "hyperliquid": ("binance", "bybit", "okx", "hyperliquid"),
}
REQUIRED["hyperliquid"] = ("bybit:price", "binance:oi", "bybit:oi")

class Placed(NamedTuple):
    """One venue's Coinalyze column on the grid buckets start..last."""
    values: Values               # liq: (longs, shorts) in two Placed; delta; or OI
    covered: list[bool]          # all True for OI, whose gaps are None values
    whole: list[bool]            # the bucket closes a window placed whole from 4hour

def cz_liquidations(rows4: Mapping[int, CzPoint], rows5: Mapping[int, CzPoint],
                    start: int, last: int) -> tuple[Placed, Placed]   # longs, shorts
def cz_delta(rows4: Mapping[int, CzPoint], rows5: Mapping[int, CzPoint],
             start: int, last: int) -> Placed
def cz_oi(rows4: Mapping[int, CzPoint], rows5: Mapping[int, CzPoint],
          start: int, last: int) -> Placed
def estimate_liquidations(longs: Values, shorts: Values, covered: Sequence[bool],
                          all_oi: Values, venue_oi: Values) -> tuple[Values, Values, list[bool]]
def build_grid(store: PerpsStore, exchange: Exchange, start: int,
               excluded: frozenset[CzVenue] = frozenset()) -> Grid | list[str]

# sync.py
DIRECTION_MOVE = 0.01  # a 4h window's price move, first to last bucket
def direction_check(liq: Mapping[int, CzPoint],
                    spot: Mapping[int, tuple[float, float | None, float | None]]) -> DirectionCheck
class Directions(Model):
    binance: DirectionCheck
    bybit: DirectionCheck
    okx: DirectionCheck
# stored under the same sync_state key "direction_check" (migration 003 dropped the old row)
```

**窗口放置规则**（`cz_*` 三个函数共用，实现者不能自行改变）：

依次处理从 `start` 起每个与 epoch 对齐的 4h 窗口 `w`（`start` 是整天，所以一定对齐），直到 `w > last`。设 `end = w + H4 − STEP`，即窗口最后一个桶。`rows4` 从 `start − H4` 读起，这样起点那一窗也能看到前一个窗口。

- **整窗取 4hour**：要求 `w in rows4`、`end ≤ last`，并且（只对清算）不处于断档。这时：
  - 清算、买卖差：`end` 桶放整窗的值（买卖差为 `2b − a`），窗口内其他桶为 0.0，全部已覆盖；
  - OI：`w` 桶放 `a`（open），`end` 桶放 `b`（close），中间为 None；
  - `whole[end] = True`；OI 另外 `whole[w] = True`。
- **断档（只对清算）**：`rows4[w].filled`，且 `rows4[w − H4]` 或 `rows4[w + H4]` 也存在、也是 filled。这时整窗未覆盖（None），不用 5min 补。
- **其余情况，逐桶取 5min**：对窗口内每个 `t ≤ last`，设 `p = rows5.get(t)`、`q = rows5.get(t + 300)`：
  - 清算：`p`、`q` 都在时为 `(p.a + q.a, p.b + q.b)`，否则未覆盖；
  - 买卖差：`p`、`q` 都在时为 `2(p.b + q.b) − (p.a + q.a)`，否则未覆盖；
  - OI：`q` 在时为 `q.b`，否则 None。

**各视图的组成**：

| venue | OI | 买卖差 | 清算 |
|---|---|---|---|
| binance | 交易所 REST | 交易所 REST K 线（`vd_covered` 恒为 True） | `cz_liquidations` |
| bybit | 交易所 REST | `cz_delta` | `cz_liquidations` |
| okx | `cz_oi` | `cz_delta` | `cz_liquidations` |
| hyperliquid | `cz_oi` | `cz_delta` | `estimate_liquidations`(All 的清算与覆盖, All 的 OI, HL 的 OI) |

**合成规则**：`_sum` 推广到 n 家（复核 C2）：
1. **逐桶相加**：任一家为 None 或未覆盖，结果就是 None 或未覆盖（P4 规则）。
2. **整窗失效**：对任一家 `whole` 为真的窗口：
   - 合成的买卖差或清算在 `end` 桶为 None 时，整窗 24 个桶都记为 None、未覆盖；
   - 合成 OI 在 `end` 桶为 None 时，整窗的合成 OI 都为 None（`w` 桶为 None 不触发，只让该块的 dOI 记为估算）。

单一交易所视图同样适用这两条：Bybit 视图的 REST OI 与 Coinalyze 不混合，规则不会触发。

`excluded` 中的 venue，它的 Coinalyze 列全部按缺失处理。

**`estimate_liquidations` 的逐桶规则**：
- All 未覆盖 → `(None, None, False)`；
- All 两侧都为 0 → `(0.0, 0.0, True)`；
- `venue_oi` 或 `all_oi` 为 None，或任一 ≤ 0 → `(None, None, False)`；
- 否则两侧都乘 `venue_oi / all_oi`，记为已覆盖。

**窗口级 QC**（只针对来自 Coinalyze 的 OI：`okx:oi`、`hyperliquid:oi`，各视图只查它用到的）：
- 参考窗口从 `last // DAY * DAY − 90 天` 起，取其中 `end ≤ last` 的窗口；
- 一个窗口的 `w` 桶或 `end` 桶的 OI 为 None，就算这个窗口缺失；
- 缺失超过 1% 时，记 `missing:<venue>:oi`；全部缺失时，`window_missing` 加上 `<venue>:oi`。

**单位核对**：`derive_states` 读取 `stored_markets`，`ok` 为假的 venue 进入 `excluded`：
- 用到该 venue 的视图（按 `VIEW_VENUES`），`StoredStates.reasons` 加 `coinalyze_units:<venue>`；
- 方向核对中，被排除的 venue 记为 pending。

**方向核对**（每家一次：binance、bybit、okx）：
- 只看已收盘、`filled` 为假的 4h 行；
- 涨跌 = 现货 K 线中开盘于 `w + H4 − 300` 那根的 close ÷ 开盘于 `w + 300` 那根的 close − 1，即块首桶到块末桶；
- `|涨跌| ≥ DIRECTION_MOVE` 且有清算的窗口计入样本，其余阈值沿用 P4：下跌窗口 ≥20 个时，多头占比 > 0.6 为 ok，< 0.4 为 inverted。

- [ ] **Step 1：写失败的测试**（`tests/perps/test_perps_grid.py`）

```python
def test_closed_window_value_sits_in_its_last_bucket():
    longs, shorts = cz_liquidations({W: CzPoint(t=W, a=3.0, b=1.0)}, {}, W, W + H4 - STEP)
    assert longs.values == [0.0] * 23 + [3.0] and shorts.values == [0.0] * 23 + [1.0]
    assert all(longs.covered) and longs.whole == [False] * 23 + [True]

def test_window_past_last_uses_5min():
    rows5 = {W + k * 300: CzPoint(t=W + k * 300, a=0.1, b=0.0) for k in range(12)}
    longs, _ = cz_liquidations({W: CzPoint(t=W, a=9.0, b=0.0)}, rows5, W, W + 5 * STEP)
    assert longs.values == [0.2] * 6 and all(longs.covered)     # never the 9.0 window total

def test_bucket_missing_a_5min_point_is_uncovered(): ...
def test_filled_run_is_uncovered():
    # W and W+H4 filled -> 48 buckets None, uncovered; a lone filled window -> 24 zeros, covered;
    # a filled window at `start` whose previous window (read from start - H4) is filled -> uncovered
def test_oi_window_open_first_close_last_middle_none(): ...  # 5min path: q.b, p not needed
def test_delta_is_two_buy_minus_volume(): ...

def test_composite_rest_gap_at_window_end_uncovers_the_window(store):
    # All view, Bybit and OKX delta placed whole at W, Binance kline missing at the end bucket:
    # all 24 buckets of W have vd None and vd_covered False; the block is delta-uncovered and
    # its delta_sum is None, not the Binance-only partial sum.
    # Binance OI missing at W's end bucket: All OI None for all of W, so a 4h block's oi_close
    # is None rather than the value 4 hours earlier.

def test_estimate_liquidations():
    longs, shorts, cov = estimate_liquidations(
        [0.0, 4.0, 4.0, None, 4.0, 4.0], [0.0, 2.0, 2.0, None, 2.0, 2.0],
        [True, True, True, False, True, True],
        [None, 100.0, None, 100.0, 0.0, 100.0], [10.0, 25.0, 25.0, 25.0, 25.0, None])
    assert longs == [0.0, 1.0, None, None, None, None] and shorts == [0.0, 0.5, None, None, None, None]
    assert cov == [True, True, False, False, False, False]

def test_all_view_sums_three_venues_and_is_none_where_okx_is(store): ...
def test_hyperliquid_view_last_is_bounded_by_binance_and_bybit_oi(store): ...
def test_window_qc_reports_missing_okx_oi(store): ...  # "missing:okx:oi" in compute_states(...).qc
def test_excluded_venue_is_uncovered(store): ...
def test_only_4hour_history_is_judged_under_o6(store):
    # 100 days of 4hour rows only, `last` on a window's end bucket (no forming block):
    # compute_states(grid, "4h", rules=O1O6) -> blocks in view are judged; none has imputed.sums
```

**要改写或删除的旧测试**：按 P6-R12，前提改为写入 `cz_series`。

- **`test_perps_grid.py`**：
  - 删除（测的是已删除的自采路径）：`test_bucket_coverage_union_one_connection_down_vs_both`、`test_liquidation_max_count_per_connection`、`test_binance_filled_only_and_sides`、`test_bybit_sides_and_qty`、`test_covered_empty_bucket_is_zero_uncovered_is_none`、`test_liquidation_sums_match_the_python_merge`、`test_liquidation_coverage_is_read_before_the_events`；
  - 改写：`test_all_view_none_if_any_venue_none` 改为三家。
- **`test_perps_sync.py`**：
  - 改写：`full_round`、`test_round_backfills_121_days_and_checks_directions_over_the_whole_grid`（三家的方向，`collecting` 为假的前提改用 `cz_series` 构造）、`test_o1_reaches_compute_states_and_leaves_the_forming_block_out`、`test_derive_command_keeps_the_grid_start_of_the_stored_payloads`、`test_derive_command_rederives_the_perps_of_a_copy`、`test_prune_keeps_125d_and_1h_trade_ids`、`test_direction_check_pending_ok_inverted_and_v_units`（改按窗口）；
  - 删除：`test_qty_units_unknown_without_events`、`test_qty_units_from_sql_equals_the_python_check`；
  - 新增：`test_derive_states_stores_eight_payloads`、`test_units_mismatch_excludes_the_venue_and_gives_a_reason`。
- **`test_perps_states.py`**：新增 `test_window_qc_joins_qc_and_missing`。
- **`test_perps_api.py`**：`direction()` 的用例改为三家；新增 `test_hyperliquid_view_is_served`。
- **`test_perps_store.py`**：`liquidation_sizes` 的用例随 P6-R7 一起删除。
- **`test_perps_collector.py`**：如有读取 `liquidation_sums` 的地方，改为直接查表。

- [ ] **Step 2：运行，确认失败**

Run: `.venv-foundation/bin/python -m pytest services/analytics/tests/perps -q`
Expected：新增用例 FAIL。

- [ ] **Step 3：实现**，并按 P6-R7 删除死代码。

- [ ] **Step 4：同步契约**

先运行 `make contract`，再改前端的 zod、类型、i18n 键和测试对象（见 Files）。

Run: `make check`
Expected：ruff、mypy、pytest、type-check、vitest 全部通过。

- [ ] **Step 5：规则对照不退步**

Run: `.venv-foundation/bin/python .local/research-samples/alpha-dashboards-2026-10-16/perp-squeeze/tools/states_parity.py .local/research-samples/alpha-dashboards-2026-10-16/perp-squeeze/samples/api-perps-90d-10m-2026-10-16T1049Z.json`
Expected：最后一行 `ALL MATCH`，12 种组合；扩到 16 种在 T5 做。

- [ ] **Step 6：提交**：`feat(perps): build the grid from Coinalyze and add the Hyperliquid view`

---

### Task 4：采集器开关、接口与界面

**Files:**
- Modify: `settings.py`：`perps_collectors: bool = False`，读 `WHEELHOUSE_PERPS_COLLECTORS`，取值同 `WHEELHOUSE_PERPS` 的 1/0、true/false、on/off。
- Modify: `http.py`：`create_app(..., perps_collectors: bool | None = None)`，默认取设置。
- Modify: `perps/api.py`：
  - `create_router(..., start_collectors: bool = False)`；
  - 删 `VIEW_STREAMS`；`states_view` 去掉 `collectors` 参数和 `collector_down`；
  - `/perps/status` 加 `markets`。
- Modify: `perps/models.py`：`PerpStatesView` 删 `collectors`；`PerpsStatus` 加 `markets: list[MarketCheck]`，没核对过时为空。
- Modify：前端 `perps-contract.ts`（zod；`collecting` 和 `uncovered` 变体不再改 `collectors`，`uncovered` 的原因改为 `rest_error:api.coinalyze.net:429`）、`perp-states.tsx`、`perp-charts.tsx`、`i18n.ts`。
- Regenerate：两份 sample JSON，用 `.venv-foundation/bin/python services/analytics/tests/perps/test_perps_api.py` 重写。
- Generated：`make contract`
- Test：`tests/perps/test_perps_api.py`、`tests/test_http.py`（如有采集器启停的断言）、前端 `perp-states.test.tsx`、`perp-charts.test.tsx`、`perps-contract.test.ts`、`flows-panel.test.tsx`、`market-defaults.test.tsx`、`i18n.test.ts`

**Interfaces:**
- Consumes：T3 的 `Exchange`、`Directions`；T1 的 `MarketCheck`、`CZ_HOST`。
- Produces：`create_router(path, http, *, rules, start_worker, start_collectors=False, coinalyze_key=None, connect=None, clock=utc_now)`。

**文案**（en / zh，键名照写）：

| 键 | en | zh |
|---|---|---|
| `perp.meta`（改） | `Resolution 10m · Data through {{time}} UTC · Price Bybit spot · OI Binance and Bybit (public), OKX and Hyperliquid (Coinalyze)` | `粒度 10m · 数据截至 {{time}} UTC · 价格 Bybit 现货 · OI：Binance、Bybit（公开接口），OKX、Hyperliquid（Coinalyze）` |
| `perp.source`（新） | `Liquidations and buy/sell volume (except Binance's):` | `清算与主动买卖量（Binance 的买卖量除外）：` |
| `perp.coverage`（改） | `Liquidation history: {{days}} d covered in the last 90` | `清算历史：近 90 天覆盖 {{days}} 天` |
| `perp.collecting`（改） | `Liquidation history too short · {{days}} of 7 days (target 90)` | `清算历史不足 · 已覆盖 {{days}} / 7 天（目标 90 天）` |
| `perp.hlNote`（新） | `Hyperliquid liquidations are estimated: All venues' liquidations scaled by Hyperliquid's OI relative to theirs` | `Hyperliquid 的清算是估算值：全部交易所的清算 × Hyperliquid OI 与它们 OI 之比` |
| `perp.estimated`（新） | `{{label}} (estimated)` | `{{label}}（估算）` |
| `perp.reason.keyMissing`（新） | `Coinalyze API key not set: liquidations and Coinalyze flows unavailable` | `未设置 Coinalyze API key：清算和来自 Coinalyze 的数据不可用` |
| `perp.reason.keyInvalid`（新） | `Coinalyze rejected the API key: liquidations and Coinalyze flows unavailable` | `Coinalyze 拒绝了 API key：清算和来自 Coinalyze 的数据不可用` |
| `perp.reason.units`（新） | `Coinalyze {{venue}} market check failed: its data is left out` | `Coinalyze 的 {{venue}} 市场核对未通过，已停用其数据` |
| `perp.series.okxOi`、`perp.series.hyperliquidOi`（新） | `OKX OI`、`Hyperliquid OI` | `OKX OI`、`Hyperliquid OI` |

删除的键：`perp.collectingTrades`、`perp.coverageDays`、`perp.stream.*`、`perp.reason.collectorDown`、`perp.reason.collectorNever`。

**界面规则**：
- Exchange 选项为 All venues / Binance / Bybit / Hyperliquid，URL 参数 `px=hyperliquid`。
- 来源行在 `perp.meta` 之后，形如 `{text("perp.source")} <a href="https://coinalyze.net" target="_blank" rel="noreferrer">Coinalyze</a>`。
- **标注**：
  - `perp.binanceNote` 在 `exchange !== "bybit"` 时显示；
  - `perp.hlNote` 只在 hyperliquid 视图显示；
  - hyperliquid 视图中，图 4 的清算带标签和悬停里的空头、多头清算两行都用 `perp.estimated` 包一层。
- **key 的提示**：`reasons` 含 `rest_error:api.coinalyze.net:key_missing` 或 `:401` 时，显示 keyMissing 或 keyInvalid，代替通用的 restError 文案，并且不显示 collecting 横幅。
- **单位**：`coinalyze_units:<venue>` 用 `perp.reason.units` 显示，venue 名用 T3 的 `perp.venue.*`。

- [ ] **Step 1：写失败的测试**

```python
# test_perps_api.py
def test_collectors_do_not_start_by_default(): ...           # Collectors never constructed
def test_collectors_start_when_enabled(): ...
def test_views_have_no_collectors_and_no_collector_down(): ...
def test_every_view_reports_coinalyze_errors():
    # hosts[CZ_HOST].error == "key_missing" -> each of the 4 views has "rest_error:api.coinalyze.net:key_missing"
def test_status_lists_market_checks(): ...
```

```ts
// perp-states.test.tsx
it("offers Hyperliquid and keeps it in the URL", ...)        // px=hyperliquid selected
it("labels Hyperliquid liquidations as estimated", ...)      // hlNote, band label and hover rows
it("credits Coinalyze with a link", ...)                     // link to https://coinalyze.net
it("shows the key notice instead of the history banner", ...)
it("shows the units notice", ...)
```

- [ ] **Step 2：运行，确认失败**

Run: `.venv-foundation/bin/python -m pytest services/analytics/tests/perps/test_perps_api.py -q`，以及 `pnpm --filter frontend exec vitest run src/features/wheelhouse`
Expected：新增用例 FAIL。

- [ ] **Step 3：实现**

顺序：后端 → `make contract` → 重写 sample JSON → 前端。

- [ ] **Step 4：运行全量检查**

Run: `make check`，以及 `.venv-foundation/bin/python -m pytest deploy/test/test_composition.py`
Expected：全部通过；部署测试断言 worker 和采集器都没有启动。

- [ ] **Step 5：提交**：`feat(perps): turn collectors off by default and show Coinalyze sources`

---

### Task 5：文档与核验

**Files:**
- Modify: `docs/features/btc-perp-states/SPEC.md`：新增 "v4（P6）" 一节，改写的条目必须覆盖以下全部：
  - §0：P4-D1、D4、D5、D7（横幅文案）、D10、D11；
  - §1：成功标准由 12 种组合改为 16 种；"不做"中删掉 Hyperliquid；
  - §2：文件表加 `coinalyze.py`，存储表加 `cz_series`；启停加采集器开关；
  - §3.1：取值表；
  - §3.2：采集器只用于对照；
  - §3.3：覆盖规则，按方案 §3.3、§3.4，包括合成视图的规则和与 P4 的差别；
  - §3.7：去掉 `collector_down` 和 `collectors[]`，原因码加 `coinalyze_units`；
  - §3.8：Coinalyze 的退避行、host 列表、每进程每分钟 20 次；
  - §4：载荷由 6 份改为 8 份，exchange 的取值，status 的 `markets` 和 `direction_check` 的形状；
  - §5：页头、来源行、HL 标注、Exchange 选项；
  - §6：方向核对改按窗口；
  - §8：修订记录。
- Modify: `docs/deployment/RELEASING.md`：
  - `WHEELHOUSE_COINALYZE_KEY` 作为 Coolify secret；同一个 key 最多两个进程同时使用；
  - `WHEELHOUSE_PERPS_COLLECTORS`；
  - 迁移 003 之后，旧镜像会以 "Perps database is newer" 拒绝启动，回滚要连同数据卷一起处理；
  - 部署后检查 `/perps/status` 的 `api.coinalyze.net` 和 `markets`。
- Modify: `deploy/test/compose.yaml`：analytics 的环境变量加 `WHEELHOUSE_COINALYZE_KEY: ${WHEELHOUSE_COINALYZE_KEY:-}`。
- Modify: `docs/features/btc-onchain-perp/CHART-INVENTORY.md`：perp-squeeze 的 Parameters、表 1、图 1、图 2、图 4 改为"已补"。
- Create: `docs/features/btc-perp-states/P6-VERIFICATION.md`
- Local only：`.local/.../tools/states_parity.py` 加 hyperliquid。

- [ ] **Step 1：规则对照扩到 16 种组合**

`grid_of(sample, "hyperliquid")` 用 `estimate_liquidations` 估算清算：All 视图的清算和覆盖全为 True，All OI 取样本的 `all.oi_btc`。循环中加上 `"hyperliquid"`。

Run: 同 T3 Step 5
Expected：16 行全部 match，最后一行 `ALL MATCH`。

- [ ] **Step 2：全量检查**

Run: `make check`，以及 `.venv-foundation/bin/python -m pytest deploy/test/test_composition.py`
Expected：全部通过，记录测试数量。

- [ ] **Step 3：V2 对照与稳定性**

按 P6-R10 另起服务，跑一轮取数后做两件事：
- **对照**：用本机库中 10-17 以来自采的清算，与 `cz_series` 的 4hour 行按块合计对照，只比较完整覆盖的块；
- **稳定性**：某个 4h 窗口收盘后，在第一轮和 1 小时后各记一次它的 4hour 值，看是否被更正。

Expected：两家的块合计相等，与 V1 的逐桶结论一致。结果写进记录。

- [ ] **Step 4：浏览器核验**

在 1440 和 390 两种宽度下检查：
- 四个视图 × 4h、8h：表 1 有判定，图 1–4 约有 90 天历史，图 4 有清算带；
- 来源署名和 HL 的 estimated 标注；
- 390 宽度下 `scrollWidth = 390`，控制台没有报错；
- **缺 key**：启动时设 `WHEELHOUSE_COINALYZE_KEY=`，即环境变量存在且为空；
- **key 无效**：用一个假的 UUID。

两种降级显示各截图一张，截图放 `.local`。

- [ ] **Step 5：与原站定性对照**

在已登录的浏览器中打开 perp-squeeze，all/4h/30d 下，把原站表 1 的各状态占比与本地的写成两列，标出方向和量级是否一致。不要输入密码。

- [ ] **Step 6：写 `P6-VERIFICATION.md`**

内容包括：上面各步的结果，规则对照的表格，以及未完成或与预期不符的项目。

- [ ] **Step 7：提交**：`docs(perps): record the Coinalyze switch and its verification`

---

## 收尾

1. **整分支终审**：用 superpowers:requesting-code-review，带上方案 v3.1 和本计划。按 superpowers:receiving-code-review 修复问题，修完重跑 `make check` 和规则对照。
2. **合并**：合并到 main，然后 `git push git@github.com:gaawai-l/algoforce-next.git main`。
3. **发布**：要等用户说"发布 test"。

## 修订记录

| 版本 | 内容 |
|---|---|
| v1（2026-10-19） | 首版，依据方案 v3 |
| v1.1（2026-10-19） | 按独立复核修订。<br>• **C1**：迁移注释去掉分号，并加 P6-R11。<br>• **C2**：合成视图的整窗失效规则，`Placed.whole`。<br>• **I1**：4hour 的 `frm` 只在需要回填时为 `start`。<br>• **I2**：迁移 003 删除旧的方向核对行。<br>• **I3**：T3 补上前端类型、i18n 键、测试对象和 api 的 host 表，保证每个 Task 结束时 `make check` 全绿。<br>• **I4**：逐条列出要改写的旧测试，并加 P6-R12。<br>• **I5**：每进程每分钟 20 次的限速与测试。<br>• **I6**：401 不退避。<br>• **I7**：收盘后 1 小时内反复更正，T5 实测是否被更正。<br>• **I8**：key 检查改用 Settings 的解析。<br>• **I9**：P6-R8、P6-R9 测试隔离。<br>• **补测**：省略的 symbol 照样补 0。<br>• **M1–M16**：NaN、死代码清单、prune 调用方、fixture 文件名、sample 重写命令、O6 测试的前提、SPEC v4 清单、HL 估算规则与文案、5min OI 只要 `q`、断档边界、悬停标注、`_coinalyze` 的位置、`excluded` 的来源、403 退避、首轮请求计数 |
| v1.2（2026-10-19） | 整支分支终审：T3 的合成 OI 整窗失效只看 `end` 桶，不再看 `w` 桶（方案 v3.2） |
