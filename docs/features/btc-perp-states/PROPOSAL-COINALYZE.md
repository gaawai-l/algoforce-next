# 方案：永续清算与买卖量改用 Coinalyze（P6）

日期：2026-10-18 起草，2026-10-19 按 V1 实测和用户决定修订。状态：v3.1，已按独立复核修订，待用户审阅。
依据：
- [P4 spec](SPEC.md) v3.2；
- [免费数据调研](../../../research/perp-free-data-2026-10-17.md)；
- Coinalyze 官方文档 <https://api.coinalyze.net/v1/doc/> 及其 OpenAPI 文件 `api-spec.json`（2026-10-18、10-19 核验）；
- V1 实测（2026-10-19，免费 key）：探测脚本 `.local/coinalyze-v1/probe.py`，原始响应在 `.local/coinalyze-v1/run-2026-10-19T0741Z/`，均不入库。

## 1. 为什么改

P4 的清算和 Bybit 主动买卖差，只能从开始采集起用 WebSocket 往后采：
- 交易所不提供历史，表 1 和图 1、图 2 要采满 7 天才出现，满 90 天参考窗口才完整；
- 每次重新部署 analytics，采集都会留下空洞。

原站的数据源 Glassnode 无法提供，改用 Coinalyze 免费 API 补上这两项的历史。用户同时决定（§7）本期一并做 Hyperliquid 视图，All venues 扩为 Binance + Bybit + OKX。

## 2. Coinalyze：文档与实测

**文档写明**：
- 免费，注册后生成 API key；key 可以放在请求头 `api_key` 里，也可以放在 query 里（我们只用请求头）。公开展示时请注明来源。
- 每个 key 每分钟 40 次；一次请求里每个 symbol 各算一次；超限返回 429，带 `Retry-After`。
- 1 分钟到 12 小时的粒度只保留 1500–2000 个点，旧数据每天删除；日线不删。
- 所有历史接口按时间升序返回；`from`、`to` 都是包含端点的 epoch 秒；`t` 是区间起点。
- `/liquidation-history` 返回 `{t, l, s}`；`/ohlcv-history` 返回 `{t, o, h, l, c, v, bv, tx, btx}`；`/open-interest-history` 返回 `{t, o, h, l, c}`，`o`、`c` 分别是区间起点和终点的 OI。

### 2.1 V1 实测结果（2026-10-19）

**鉴权**
- 新生成的 key 起初返回 401，几分钟后变成 200。
- `/exchanges` 返回 28 家，代码：Binance=A、Bybit=6、OKX=3、Hyperliquid=H、Deribit=2、BitMEX=0。

**市场**：`/future-markets` 中有 26 个 BTC 永续。本期用到的：

| 交易所 | symbol | `oi_lq_vol_denominated_in` | `has_buy_sell_data` | 清算 |
|---|---|---|---|---|
| Binance USDT | `BTCUSDT_PERP.A` | BASE_ASSET | 有 | 有 |
| Bybit USDT | `BTCUSDT.6` | BASE_ASSET | 有 | 有 |
| OKX USDT | `BTCUSDT_PERP.3` | BASE_ASSET | 有 | 有 |
| Hyperliquid | `BTC.H` | BASE_ASSET | 有 | **没有** |

- Deribit `BTC-PERPETUAL.2` 没有清算，OI 以 USD 计。BitMEX 在 Coinalyze 上没有 BTC 永续。

**原待测 7 项**

| # | 项目 | 结果 |
|---|---|---|
| 1 | symbol | 见上表 |
| 2 | 4hour 对齐 | 全部 `t` 是 14400 的整数倍，即 UTC 00/04/08… |
| 3 | 没有清算的区间 | **不返回**，从来不返回 `l = s = 0` 的点。清算点都有同时刻的 OHLCV 点。5min 下空区间很常见：Binance 2086 个区间中 928 个没有清算点 |
| 4 | 单次响应的点数 | **不用分页**。请求 400 天时，4hour 一次返回约 2000 个点（约 334 天）；Bybit 的 1hour 清算一次返回 2659 个点 |
| 5 | 48 个 5min 之和与 4hour | 已收盘窗口中逐位相等（相对误差约 1e-14）：Binance、Bybit 的清算和 OHLCV，HL 的 OHLCV，各 42–59 个窗口。唯一例外是 OKX 10-15 20:00 的 `s`（4hour 1.52，5min 之和 1.99） |
| 6 | 单位与方向 | `l`、`s` 单位为 BTC，`l` 是多头被强平。与本机 10-17 起自采的事件逐个 5min 桶对照，Binance 131 桶、Bybit 132 桶全部相等（相关 1.000）。334 天的 4h 窗口中，涨跌 ≥1% 的下跌窗口里多头清算占 Binance 89%、Bybit 93%、OKX 81%，上涨窗口里只占 12%、12%、20% |
| 7 | Binance 是否同为每秒快照 | 是：Coinalyze 的 Binance 清算与我们自采的 forceOrder 完全相同，只能算下限 |

**其他发现**
- **未收盘的 bar**：4hour 和 5min 的最新一个点都是还没收盘的区间。
- **可回溯时长**（按保留的点数）：

  | 粒度 | 可回溯 |
  |---|---|
  | 5min OHLCV、OI | 约 7.2 天 |
  | 1hour 清算 | Binance 约 90 天，不够用 |
  | 2hour 清算 | 168–195 天 |
  | 4hour | 约 334 天 |

- **买卖量**：Binance 的 `v`、`bv` 与我们的 K 线 volume、taker_buy 一致；Bybit 的 `bv`、`v` 与我们 publicTrade 自采的 10m 买量、总量逐桶相等。
- **OI**：
  - Binance：`c(t)` 等于我们的 `oi(t+5m)`，中位差 8e-5；
  - **Bybit：是我们 `singleOpenInterest` 的 2 倍**，用的是双边的 `openInterest`；
  - OKX、HL：与交易所公开接口一致（OKX `oiCcy`、HL `openInterest`），都是单边。
- **Coinalyze 自身断档**：Binance 2026-04-23 20:00 到 04-24 08:00 连续 4 个 4h 窗口没有清算点。这段时间正好是 Binance 下线旧 WebSocket 路径的那天，不可能是真的 16 小时零清算。Bybit 的 5 个、OKX 的 14 个空窗口都是零散的单个窗口。
- **没有清算的品种整个不出现在回复里**：
  - V1 中请求 `BTC.H`、Deribit 的清算时，回复里没有这两个 symbol；
  - 10-19 补测：请求 OKX 10-10 09:15–13:15（49 个 5min 区间都没有清算点）时，回复里只有 Bybit，OKX 整个被省略。

  所以"回复里没有这个 symbol"既可能是不支持，也可能只是这段时间没有清算，两者无法区分。
- **限速**：
  - 一分钟内第 28 个计费调用时收到 429，同一分钟里另一个会话也在用同一个 key；
  - `Retry-After` 是带小数的秒数（`28.723`、`1.78`），现有 `_retry_after` 只解析整数，要改；
  - 前面挡着 Cloudflare。

## 3. 方案

### 3.1 数据从哪来

| 视图的输入 | Binance | Bybit | OKX（只进 All） | Hyperliquid |
|---|---|---|---|---|
| 价格 | Bybit 现货 5m，交易所 REST，各视图共用（不变） | ← | ← | ← |
| OI | 交易所 REST（不变） | 交易所 REST，单边（不变） | Coinalyze | Coinalyze |
| 买卖差 | 交易所 REST K 线（不变） | **Coinalyze** | Coinalyze | Coinalyze |
| 清算 | **Coinalyze** | **Coinalyze** | Coinalyze | **估算**：All 清算 × HL 的 OI 占比 |

- Exchange 选项为 All venues / Binance / Bybit / Hyperliquid，与原站相同。OKX 不单独成视图。
- All venues = Binance + Bybit + OKX，三项输入都齐。任一家为 null 或未覆盖，All 也为 null 或未覆盖（P4 规则不变）。
- Bybit 的 OI 继续用交易所 REST 的单边值，不用 Coinalyze 的双边值。

### 3.2 取数

- **4hour**：
  - 首轮从网格起点（121 天前）取一次，不分页；某家一行都没有、或回填起点晚于网格起点时，同样从网格起点重取；
  - 最新一个已收盘窗口收盘后的 1 小时内，每轮都重取最近 3 个窗口（OVERLAP）。刚收盘的值可能还没聚合完整，这样能在稳定前反复更正；
  - 其余轮次不取 4hour。
- **5min**：每轮取"上一个 4h 窗口起点"到现在，最多 96 个点；5min 只保留 1 天。
- **只存已收盘的点**：`t + 区间长 ≤ 取数时刻`。
- **请求量**：每类数据一次请求带上所有 symbol。清算 3 个 symbol、OHLCV 3 个、OI 2 个：
  - 5min 每轮 8 次；
  - 4hour 只在窗口收盘后的 1 小时里取，每轮 8 次；
  - 单位核对每天 1 次。
- **限速自律**：每个进程每分钟最多 20 次计费调用，按 symbol 数计。不够时就等，worker 停机时立即放弃。这样同一个 key 最多两个进程（本机和 test）同时运行也不会超过 40 次。两个进程的轮次都对齐到 HH:x5，正好落在同一分钟，所以必须在进程内自己限住。
- **单位核对**：每天读一次 `/future-markets`，要求 4 个 symbol 都是 `BASE_ASSET`，用到买卖量的还要 `has_buy_sell_data = true`。不符合的交易所，它的 Coinalyze 数据整体不用，视图带原因码 `coinalyze_units:<venue>`。读取失败时沿用上次的结果；从未成功读到时，照常使用数据。
- **WebSocket 采集器**：默认关闭（`WHEELHOUSE_PERPS_COLLECTORS=off`），只在对照时打开，不再参与网格。

### 3.3 放进 10m 网格（代替 v2 的"窗口值"）

v2 打算给 Grid 加一组 4h 窗口值，并改写 `_block`。实测证明"48 个 5min 之和 = 4hour"，所以改用更简单的做法，**`states.py` 的规则代码不用改**：

1. **已收盘、4hour 已入库、且窗口最后一个桶 ≤ `last` 的窗口**：
   - 清算、买卖差：整窗的值放在窗口的**最后一个桶**，其余 23 个桶记 0.0，全部算已覆盖；
   - OI：窗口第一个桶放 `o`，最后一个桶放 `c`，中间的桶为 null。
2. **其他窗口**（未收盘的、4hour 没取到的、或网格还没走到窗口末尾的）：逐桶用 5min：
   - 一个 10m 桶等于两个已收盘的 5min 点；
   - OI 取后一个 5min 点的 `c`，即 `t + 10m` 时刻的 OI，与 P4 的 REST 口径相同；
   - 缺任何一个点，该桶的清算、买卖差未覆盖，OI 为 null。

对单一交易所的视图，所有用到这些数据的地方都只看块的合计、块首尾的 OI 和块内最后一个非空的 OI：表 1、图 1–4、阈值、forming 块、尾块都是如此。所以结果与逐桶取值相同；复核已逐个核对过 `_block`、`_spans`、O1/O6 路径和前端。

**合成视图（All、HL）要多一条规则**（复核 C2）：All 的每个桶是逐桶的交易所 REST 值与整窗放置的 Coinalyze 值相加。REST 值在窗口末桶缺失时，会出两种错：
- **整窗的值被丢掉**：例如 Binance 的 K 线 delta 为 None，相加的结果也为 None，Bybit 和 OKX 4 小时的买卖差就从块合计里消失了；
- **OI 退回 4 小时前**：块内最后一个非空的 OI 会落到窗口首桶。

所以规定，凡是有一家整窗放置的窗口：
- **买卖差、清算**：合成值在窗口末桶为 None 时，整窗都记为未覆盖；
- **OI**：合成值在窗口首桶或末桶为 None 时，整窗的合成 OI 都记为 None。

8h 块的后一窗因此为 None 时，块内最后一个非空的 OI 会退到前一窗的末桶，即 4 小时前；这与 P4 中 REST 序列连续缺失时的行为相同，QC 会报缺失。

与 P4 逐桶取值相比的差别，都写进 spec：
- **整窗只用 4hour**：已收盘、4hour 已入库的窗口一律用 4hour，即使也有 5min；5min 只在 4hour 缺失时才用。
- **块首的 OI 早 10 分钟**：OKX、HL 只有 4hour 的窗口，块首桶放的是 `o`，即窗口起点的 OI，而 P4 读的是 `t0 + 10m`。所以 All 的 dOI 中，OKX 的起点是 `t0`，Binance、Bybit 的起点是 `t0 + 10m`。
- **HL 的估算按窗口末的 OI 占比**：原站逐桶乘各自的占比；整窗放置的窗口只能整窗乘窗口末的占比。

**方向核对**：桶内的分布已不真实，所以方向核对不再按桶做，改为按已收盘的 4h 窗口。规则如下：
- 窗口内价格变动 ≥1%、且有清算的才计入；
- 下跌窗口里多头清算的占比 > 0.6 为 ok，< 0.4 为 inverted；
- 至少要有 20 个下跌窗口才下结论。

核对对 Binance、Bybit、OKX 各做一次。HL 视图沿用 All 的合并结论。

### 3.4 缺失与"没有清算"（复核 I1，按实测改写）

- **清算**：一次成功的请求覆盖的已收盘区间里，Coinalyze 没返回的区间存成 `(0, 0)`，标记 `filled = 1`。库里没有行的区间就是没取到，记为未覆盖。
  - **整个 symbol 不在回复里时也照样补 0**：Coinalyze 会省略这段时间没有清算的品种（§2.1）。我们只请求已知有清算数据的三家，所以省略只可能是没有清算。
  - **断档规则**：同一交易所连续 ≥2 个 `filled` 的 4h 窗口，全部记为未覆盖，也不再拿 5min 补。读取时从网格起点前一个窗口开始，使起点那一窗也能判断。
    - 最新一个 `filled` 窗口在下一窗也被补 0 之前，先显示为 0，之后才翻成未覆盖。
    - 按 V1 的数据，这条规则只会命中 Binance 04-23 那一段，不在 121 天网格之内，所以它还没有在真实数据上触发过；规则本身由单测覆盖。
  - v2 的"同交易所同区间 OHLCV 存在"一条删掉：清算点总有同时刻的 OHLCV，而 5min 空区间本来就很常见，这一条区分不了断档。
- **OHLCV、OI**：缺失一律为 null，不补 0。
- **已接受的风险**：5min 层面 Coinalyze 的短时断档识别不出来，会显示为没有清算。

### 3.5 Hyperliquid 视图（用户决定：照原站估算并标注）

- **清算**：每个桶的估算值 = All 清算 × HL OI ÷ All OI，两侧乘同一个占比。规则如下：
  - All 清算未覆盖的桶，估算也未覆盖；
  - All 两侧都为 0 的桶，估算为 0；
  - 其余的桶，HL 或 All 的 OI 缺失或 ≤ 0 时为未覆盖，不当作 0。
  - All 的 OI 不含 HL，所以这个比值是"HL 的 OI 相对 All 的 OI"，不是严格意义上的占比。原站公式的分子分母也是这样取的，文案照此写。
- **标注**：HL 视图的页头、图 4 的清算带和悬停都写明 "estimated"。估算会让 squeeze 标签基本跟着 All 走，原站也是如此（研究笔记 §4）。
- **数据边界**：HL 视图依赖 All 的 OI，所以它的 `last` 取 Bybit 现货、Binance OI、Bybit OI 三者最后桶中最早的那个。
- **规则对照**：`states_parity.py` 扩到 hyperliquid，在原站样本上用同一个估算函数，共 16 种组合。

### 3.6 停用 WebSocket 采集后的连带修改（复核 I2）

- 新增 `WHEELHOUSE_PERPS_COLLECTORS`，默认 `off`：
  - 关闭时不启动 `Collectors`；
  - 开启时只用于对照，状态只出现在 `/perps/status`。
- **视图**：去掉 `collectors` 字段和 `collector_down` 原因码。网格不再读自采的清算和成交，相关的死代码一并删除：
  - `grid.read_liquidations` 及其辅助函数；
  - `store.liquidation_sums`、`store.liquidation_sizes`；
  - `sync.qty_units`。

  保留：采集器、`store.trades`（采集器的测试要读）、`liquidations`/`coverage`/`trades_10m` 三张表。
- **方向核对的存储**：结构变了，库里旧的 `direction_check` 无法按新模型解析，会让 `/perps/status` 报 500。迁移 003 删掉这一行，新结果在下一轮写入。
- **页头**：去掉 "liquidations collected since"，改为来源行。来源行写明价格和 OI 的来源，以及 "Liquidations and buy/sell volume (Binance's excepted): Coinalyze"，并附链接；后面跟一句"清算覆盖 n 天"，取自 `covered_days`。
- **Collecting 横幅**：文案改为"清算历史不足"。缺 key 或 key 无效时，显示 key 的提示，不显示这个横幅。
- **原因码**：
  - Coinalyze 走现有的 `rest_error:<host>:<code>`，host 为 `api.coinalyze.net`，code 包括 `key_missing`、`401`、`429`、`network` 等；
  - 另加 `coinalyze_units:<venue>`：
    - 由派生时读取的单位核对结果决定，`derive.py` 走同一条路径；
    - 只出现在用到该交易所的视图里；
    - 被排除的交易所，方向核对记为 pending；
    - symbol 不在市场列表里，也算核对失败。

  四个视图的 `VIEW_HOSTS` 都加上 `api.coinalyze.net`；HL 视图用全部 host。
- **QC**：Coinalyze 的 OI（OKX、HL）按窗口检查：参考窗口中缺 OI 的已收盘窗口超过 1% 时，报 `missing:<venue>:oi`；一个都没有时，报 `series_missing`。
- **`prune`**：`cz_series` 的 4hour 保留 125 天，5min 保留 1 天。`derive.py` 走同一条派生路径。

### 3.7 API key 与 HTTP（复核 I3）

- **读取**：
  - 环境变量 `WHEELHOUSE_COINALYZE_KEY` 只要存在就以它为准，空串表示缺失；
  - 环境变量不存在时，只从仓库根目录的 `.env` 读这一个键，`make dev` 不必另外 export；
  - test 环境用 Coolify secret，compose 中写 `WHEELHOUSE_COINALYZE_KEY: ${WHEELHOUSE_COINALYZE_KEY:-}`；
  - 测试一律把这个环境变量置为空串，不读开发者真实的 `.env`。
- **只放在 Coinalyze 请求的头里**：key 逐个请求加在 `api_key` 头上，不进共用 httpx client 的默认头，不进 URL（httpx 在 INFO 级别会记录完整 URL）。加测试，断言日志和 URL 里都没有 key。
- **不进 repr**：`Settings` 的 key 字段设 `repr=False`。
- **退避**（per host，与交易所互不影响）：
  - 429：max(60 秒, `Retry-After`)。`Retry-After` 按浮点秒数解析，非有限值忽略；
  - 403（Cloudflare）：10 分钟；
  - 401：不退避，本轮放弃，下一轮再试。这样换了 key 或新 key 生效后，最多 10 分钟就能恢复，不会把退避存进库、在重启后继续锁住；
  - 缺 key：不发请求，记 `key_missing`。
- **缺 key 或 key 无效时**：
  - 不可用：表 1、图 1、图 2；图 4 的清算带；Bybit、All、HL 的买卖差柱；All 和 HL 视图的 OI（All 含 OKX），这两个视图的图 3 为空，并报 `series_missing`；
  - 照常显示：价格；Binance、Bybit 两个视图的 OI；Binance 视图的买卖差。
- **署名**：来源行注明 Coinalyze，并附 <https://coinalyze.net> 链接。
- **同一个 key 的配额**：每个进程限在每分钟 20 次以内（§3.2），所以同一个 key 最多两个进程同时运行。核验时另起的服务要先停掉第三个进程，或者另用一个 key。

### 3.8 规则与原站对照

- v1 的状态规则不变。数据源换成 Coinalyze 后，阈值和状态计数不再与原站逐数相同。
- P4 的规则对照仍然有效，并扩到 hyperliquid（16 种组合）：用的是原站同一份 Glassnode 数据，证明的是规则一致。
- 验收时比较两份结果：
  - 原站页面上的 30 天状态占比，按定性一致的标准（用户已接受，§7）；
  - 同一时段 Coinalyze 与本机自采数据的块合计（V2）。

## 4. 改动范围

- **代码**：
  - 新增 `perps/coinalyze.py`、`perps/migrations/003_coinalyze.sql`；
  - 修改：
    - `sources.py`：按请求的 headers、Coinalyze 的退避、浮点 `Retry-After`；
    - `settings.py`；
    - `rows.py`、`store.py`；
    - `sync.py`：取数、单位核对、方向核对、prune；
    - `grid.py`：Coinalyze 列、HL 估算、OKX 并入 All、窗口级 QC；
    - `states.py`：Grid 加窗口级 QC 字段，`_qc` 带上它；
    - `models.py`、`api.py`、`http.py`。
- **契约与前端**：
  - `make contract`、zod；
  - 两份 sample JSON；
  - `perp-states.tsx`：Exchange 选项、页头、横幅、原因码、HL 标注；
  - `perp-charts.tsx`：清算带的 estimated 标注；
  - i18n 的 en 和 zh。
- **文档**：
  - P4 SPEC 新增 v4 一节：P4-D1、D4、D5、D10、D11，§3.1、§3.2、§5 页头、§6 方向核对；
  - RELEASING：key 与 secret、`WHEELHOUSE_PERPS_COLLECTORS`，以及迁移 003 之后旧镜像会拒绝启动的回滚提示；
  - `deploy/test/compose.yaml`；
  - CHART-INVENTORY 的 perp-squeeze 部分。

## 5. 任务拆分（每个 Task 一个实现者、一次复核）

1. **T1**：Coinalyze 客户端、设置项与 key 读取、按请求的 headers、退避、浮点 `Retry-After`、日志不含 key 的测试，以及由 V1 响应裁出的 fixture（不含 key）。
2. **T2**：迁移 003、存储、取数（4hour 与 5min、补 0、只存已收盘）、单位核对、prune。
3. **T3**：网格接入 Coinalyze、HL 估算、OKX 并入 All、断档规则、窗口级 QC、按窗口的方向核对、hyperliquid 视图的派生，以及删除自采路径的死代码；`make contract` 与 zod 同步。
4. **T4**：采集器开关、视图去掉 `collectors`、`VIEW_HOSTS`、`/perps/status`；前端的 Exchange、页头、横幅、原因码、HL 标注；i18n、sample。
5. **T5**：文档（SPEC v4、RELEASING、compose、CHART-INVENTORY），以及核验与记录。

## 6. 核验

- **V1**：已完成，见 §2.1。
- **V2**：本机自采数据与 Coinalyze 逐个 5min 桶相等，已在 V1 完成。T5 再用 4hour 行与 10-17 以来的全部自采数据，按块合计对照一次，只比较完整覆盖的块；同时记录刚收盘的 4hour 值在 1 小时内是否被更正。
- **V3**：
  - `make check`、`deploy/test/test_composition.py`；
  - 规则对照扩到 16 种组合，仍为 ALL MATCH；
  - 新增单测：只有 4hour 数据的块在 O6 下能被判定；日志里不出现 key；未收盘的 bar 不入库；断档规则；HL 估算的缺失路径。
- **V4**：
  - 浏览器 1440 和 390 两种宽度下，四个视图的表 1、图 1–4 都有约 90 天的历史；
  - 来源署名和 HL 的 estimated 标注正确；
  - 缺 key 和 key 无效时的降级显示正确；
  - 与原站的 30 天状态占比做定性对照。

## 7. 用户决定（2026-10-19）

| # | 问题 | 决定 |
|---|---|---|
| 1 | WebSocket 采集器默认关闭，只在对照时开启 | 同意 |
| 2 | Hyperliquid 视图和多家交易所的 All venues | **本期一起做** |
| 2a | Coinalyze 没有 HL 清算，HL 视图怎么办 | 照原站估算（All 清算 × HL 的 OI 占比），并标注 estimated |
| 2b | All venues 含哪几家 | Binance + Bybit + OKX（各自的 USDT 永续，不含币本位合约） |
| 3 | 与原站逐数一致只保留在规则层面，数值做定性对照 | 接受 |

## 修订记录

| 版本 | 内容 |
|---|---|
| v1 → v2 | **C1**：块级的覆盖、补 0 标记和总和全部按 4h 窗口取值，避免 O6 下只有 4hour 的块全部不判定。**C2**：只存已收盘的 bar，每轮重取最近 3 个；forming 块只用连续的 5min；5min 用 `gaps()` 续取；首选"已收盘一律用 4hour"。**I1**：`cz_fetch` 记录请求范围，补 0 的三个条件。**I2**：停采后的原因码、页头、横幅、qty、`VIEW_HOSTS`。**I3**：key 只放单个请求的头、日志测试、repr、退避、compose。**I4**：每天核对一次单位。**I5**：V2 的数据来源。**I6**：补全改动范围。**M1–M5**：已并入相应各节 |
| v2 → v3 | 按 V1 实测和用户决定修订。<br>• **范围**：本期加入 Hyperliquid 视图（清算为估算并标注），All venues 改为 Binance + Bybit + OKX。<br>• **§3.3**：不再给 Grid 加窗口值、改写 `_block`，改为把 4hour 值放进窗口最后一个桶，`states.py` 的规则不变；O6 下只有 4hour 的块照样能判定。<br>• **§3.2**：不用分页；4hour 改为按需重取；5min 只取最近两个窗口、只留 1 天，不再用 `gaps()` 续取。<br>• **§3.4**：`cz_fetch` 改为写 `filled` 的 0 行；删掉 OHLCV 条件；新增连续 ≥2 个空 4h 窗口记为未覆盖的断档规则。<br>• **方向核对**：改按 4h 窗口做，含 OKX。<br>• **其他**：Bybit 的 OI 继续用交易所的单边值；`Retry-After` 按浮点数解析；key 允许从仓库根目录的 `.env` 读；删除自采路径的死代码 |
| v3 → v3.1 | 按独立复核修订。<br>• **C2**：合成视图在窗口末桶缺 REST 值时，整窗记为未覆盖；OI 整窗为 None。<br>• **I1**：4hour 只在窗口收盘后的 1 小时内重取，起点为最近 3 个窗口。<br>• **I2**：迁移 003 删除旧的方向核对结果。<br>• **I5**：每个进程每分钟最多 20 次。<br>• **I6**：401 不退避。<br>• **I7**：刚收盘的 4hour 在 1 小时内反复更正。<br>• **I9**：环境变量存在即为准，测试不读真实的 `.env`。<br>• **补测**：没有清算的品种整个被省略，所以对请求的每家都补 0。<br>• **其他**：403 退避；`Retry-After` 防 NaN；缺 key 时 All、HL 的 OI 也不可用；HL 估算的 OI ≤ 0 规则与文案；断档规则的边界；死代码清单与计划对齐 |
