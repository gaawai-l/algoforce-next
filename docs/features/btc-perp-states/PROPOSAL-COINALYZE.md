# 方案：永续清算与买卖量改用 Coinalyze（P6）

日期：2026-10-18。状态：v2，已按独立复核修订，待用户审阅。
依据：
- [P4 spec](SPEC.md) v3.2；
- [免费数据调研](../../../research/perp-free-data-2026-10-17.md)；
- Coinalyze 官方文档 <https://api.coinalyze.net/v1/doc/> 及其 OpenAPI 文件 `api-spec.json`（2026-10-18 核验，未调用 API）。

## 1. 为什么改

P4 的清算和 Bybit 主动买卖差，只能从开始采集起用 WebSocket 往后采：
- 交易所不提供历史，表 1 和图 1、图 2 要采满 7 天才出现，满 90 天参考窗口才完整；
- 每次重新部署 analytics，采集都会留下空洞。

原站的数据源 Glassnode 无法提供，改用 Coinalyze 免费 API 补上这两项的历史。

## 2. Coinalyze：已核验与待核验

**文档已写明**：
- 免费，注册后生成 API key；公开展示时请注明来源。
- 每个 key 每分钟 40 次请求；一次请求里每个 symbol 各算一次；超限返回 429，带 `Retry-After`。
- 1 分钟到 12 小时的粒度只保留 1500–2000 个点，旧数据每天删除；日线不删。按此推算的可回溯时长：

| 粒度 | 约可回溯 |
|---|---|
| 5min | 5.2–6.9 天 |
| 1hour | 62–83 天 |
| 2hour | 125–167 天 |
| 4hour | 250–333 天 |

- `/liquidation-history` 返回 `{t, l, s}`：`t` 是区间起点，`l`、`s` 分别是多头、空头的清算量。
- `/ohlcv-history` 返回 `{t, o, h, l, c, v, bv, tx, btx}`；`bv` 是主动买入量，所以买卖差 = 2·`bv` − `v`。
- `/future-markets` 给出各市场的 `oi_lq_vol_denominated_in`（BASE_ASSET 或 QUOTE_ASSET）和 `has_buy_sell_data`。

**拿到 key 后实测（V1）**：
1. Binance、Bybit 的 BTCUSDT 永续 symbol 代码。
2. 4hour 是否按 UTC 00/04/08… 对齐。
3. 没有清算的区间，是返回 0 还是不返回；空区间是否与 OHLCV 的缺口重合。
4. 单次响应的点数上限：回填约 750 个 4hour 点，是否需要分页。
5. 已收盘窗口里，48 个 5min 点之和是否等于对应的 4hour 值。
6. 单位是否为 BTC；`l`、`s` 的方向用我们 10-17 起自采的事件核对（Binance 的 SELL 表示多头被强平）。
7. Binance 的清算是否同样只有每秒一条快照，即只能算下限。

## 3. 方案

### 3.1 数据怎么取

| 数据 | 来源 | 说明 |
|---|---|---|
| 价格（Bybit 现货）、OI、Binance 买卖差 | 不变，交易所 REST | 5m，121 天 |
| **Binance、Bybit 多空清算** | **Coinalyze `/liquidation-history`** | 见下 |
| **Bybit 买卖差** | **Coinalyze `/ohlcv-history`** | 见下 |

**4hour（已收盘窗口用它）**
- 首轮回填 125 天；如果需要分页，就按块分页取。
- 之后每轮重取最近 3 个**已收盘**的 4hour 点，覆盖写入。
- 只存已收盘的点，即 `t + 4h ≤ 当前时刻 − 余量`；未收盘的 bar 一律丢弃。
- 如果 4hour 没有按 UTC 对齐，改用 2hour 两两相加。2hour 约 125–167 天，比网格需要的 122 天只多约 3 天余量。1hour 不够用。

**5min（forming 块、尾块和方向核对用它）**
- 用现有的 `gaps()` 加 OVERLAP，从最后一个已存的点往后续取，首轮先取 Coinalyze 现存的约 5 天。
- 同样只存已收盘的点，存下后保留 125 天。
- 停机超过约 5 天，那一段的 5min 数据会永久缺失；4hour 仍然能补上块的总和。

**请求量**：每轮 2 个清算 symbol 加 1 个 OHLCV symbol，5min 和 4hour 各取一次，共约 6 次，约每小时 36 次，远低于每分钟 40 次的上限。

### 3.2 块的数值从哪来（复核 C1、C2）

8h 块正好是两个 epoch 对齐的 4h 窗口，已经核实。所以 Grid 新增一组**4h 窗口值**：

```
window[t0] = (long, short, delta, liq_covered, delta_covered)
```

**已收盘的块**：`lliq`、`sliq`、`delta`、`*_sum`、`liq_covered`、`delta_covered`、`imputed.sums` 全部取窗口值。
- 首选规则（V1 第 5 项成立时）：已收盘窗口一律用 4hour 值。
- 第 5 项不成立时的备选：48 个 5min 齐全就用 5min 之和，否则用 4hour。
- 两者都没有：这个窗口未覆盖（null），所以 `imputed.sums` 为真，块不判定。

**forming 块和尾块**：只用 5min，而且必须从窗口起点连续覆盖到 `grid.last + 10m`，否则未覆盖。

**10m 桶**只在两处使用：
- forming 块、尾块；
- 方向核对。

一个桶等于两个已收盘的 5min 点。图 4 本来就只画块的总和，所以没有桶级的显示问题。

**Binance 的买卖差**仍从 K 线按桶求和，窗口值按同样的规则由桶合成。v1 的对照适配器保持按桶求和，P4 的 12/12 对照不受影响。

### 3.3 缺失与"没有清算"（复核 I1）

- 每次请求都记录在 `cz_fetch` 表里（交易所、接口、粒度、from、to、取数时间），这样能区分"没请求过"和"请求了但为空"。
- **清算**：某个区间可以补 0，必须同时满足三个条件，否则记 null：
  1. 它在某一次请求的范围内；
  2. 它早于这次响应返回的最后一个点；
  3. 同一交易所、同一区间的 OHLCV 点存在。
- **OHLCV**：缺点一律记 null。BTC 永续不可能 5 分钟内零成交。
- **已接受的风险**：Coinalyze 自身的采集断档，我们这边无法识别。

### 3.4 停用 WebSocket 采集后的连带修改（复核 I2）

- 网格的数据源固定为 Coinalyze，不随采集器开关变化。
- 新增 `WHEELHOUSE_PERPS_COLLECTORS`，默认 `off`：
  - 关闭时不启动 `Collectors`，视图不报 `collector_down`；
  - 开启时只用于对照，状态只出现在 `/perps/status`，不进视图的原因码。
- **前端页头**：原来的 "liquidations collected since …" 和覆盖天数，改为 Coinalyze 的来源行，加上清算历史覆盖到哪一天。
- **Collecting 横幅**：改为按窗口覆盖计算的"历史不足"，文案不再写"采集中"。缺 key 时不报 `collecting`，只报 `coinalyze_key_missing`。
- **`qty_units`**：不再读 WebSocket 事件，改为每天读一次 `/future-markets` 核对单位。请求时显式传 `convert_to_usd=false`，并要求 `oi_lq_vol_denominated_in=BASE_ASSET`、`has_buy_sell_data=true`；不符合时记未覆盖，原因码为 `coinalyze_units`。
- 三个视图的 `VIEW_HOSTS` 都加上 `api.coinalyze.net`。
- `prune` 加入两张 cz 表；`derive.py` 走同一条派生路径。

### 3.5 API key 与 HTTP（复核 I3）

- **提供方式**：通过 `WHEELHOUSE_COINALYZE_KEY`。
  - 本机：`make dev` 不读 `.env`，所以在启动前 `export`；
  - test：Coolify secret，compose 里加 `WHEELHOUSE_COINALYZE_KEY: ${WHEELHOUSE_COINALYZE_KEY:-}`，空字符串视为缺失。
- **只在 Coinalyze 请求上加请求头**：key 逐个请求加在 `api_key` 头上，不设成共用 httpx client 的默认头，避免发给 Binance、Bybit。禁止放在 query 里，因为 httpx 在 INFO 级别会记录完整 URL。加一个测试，断言日志里不出现 key。
- **不进 repr**：`Settings` 的 key 字段设 `repr=False`。
- **退避**：
  - 429：退避 max(60 秒, `Retry-After`)；
  - 401：长时间退避，原因码 `coinalyze_key_invalid`。
- **缺 key 时**（复核 M4）：
  - 表 1、图 1、图 2、图 4 的清算带不可用；
  - Bybit 和 All 视图的买卖差柱也不可用；
  - 价格、OI 和 Binance 视图的买卖差照常显示。
- **署名**：来源行写 "Liquidations and Bybit buy/sell volume: Coinalyze"，并附链接。

### 3.6 规则与原站对照

- v1 的状态规则不变。数据源换成 Coinalyze 后，阈值和状态计数不再与原站逐数相同。
- P4 的 12/12 对照仍然有效：它用的是原站同一份 Glassnode 数据，证明的是规则一致。
- 验收时比较两份结果：
  - 原站页面上的 30 天状态占比，按定性一致的标准；
  - 同一时段 Coinalyze 与自采数据的块总和（V2）。

### 3.7 不在本期（第二阶段，另行决定）

- Hyperliquid 视图；
- All venues 扩展为多家交易所的汇总。

## 4. 改动范围（复核 I6）

- **代码**：
  - 新增 `perps/coinalyze.py`；
  - `sources.py` 加按请求的 headers 和新 host 的退避；
  - 迁移 `003_coinalyze.sql`：`cz_liq`、`cz_ohlcv`、`cz_fetch`、`cz_markets`；
  - `sync.py`：取数、回填、prune；
  - `grid.py` 和 `states.py`：窗口值，`_block` 按窗口取值；
  - `api.py`、`settings.py`、`http.py`、`derive.py`。
- **契约与前端**：
  - `make contract`、zod；
  - 两份 sample JSON；
  - `perp-states.tsx` 的页头、横幅和原因码；
  - i18n 的 en 和 zh。
- **文档**：
  - P4 SPEC：P4-D4、D5、D10、D11，§3.2，§5 页头，新增 v4 一节；
  - RELEASING：`WHEELHOUSE_PERPS` 与采集器的描述、key 与 secret、迁移 003 之后旧镜像会拒绝启动的回滚提示；
  - deploy/test/compose.yaml。

## 5. 任务拆分（每个 Task 一个实现者、一次复核）

1. **T1**：Coinalyze 客户端、按请求的 headers、退避、设置项，以及用真实 key 录制的 fixture（fixture 里不含 key）。V1 在这一步做完。
2. **T2**：迁移 003、4hour 和 5min 的取数与回填、`cz_fetch`、单位核对、prune。
3. **T3**：Grid 的窗口值、`_block` 按窗口取值、forming 块和尾块的规则、方向核对改用 5min。
4. **T4**：停用采集器的连带修改（原因码、页头、横幅、`VIEW_HOSTS`、status），前端、契约和文档。
5. **T5**：核验与记录。

## 6. 核验

- **V1**：见 §2，在 T1 里用本机的探测脚本完成，结果不入库。
- **V2**：P4 从未发布到 test 环境，所以没有完整的自采数据。对照只能用本机 10-17 起断断续续采到的数据，只比较完整覆盖的块；必要时在本机把采集器打开，连续跑几天再对照。
- **V3**：`make check`、组装测试，v1 对照脚本仍为 ALL MATCH。新增三个单测：
  - 只有 4hour 数据的块在 O6 下能被判定；
  - 日志里不出现 key；
  - 未收盘的 bar 不入库。
- **V4**：浏览器核验 1440 和 390 两种宽度：
  - 表 1、图 1–4 有约 90 天的历史；
  - 来源署名正确；
  - 缺 key 和 key 无效时的降级显示正确。

## 7. 需要用户决定

1. WebSocket 采集器默认关闭，只在对照时开启，是否同意？
2. Hyperliquid 视图和多家交易所的 All venues 放到第二阶段，是否同意？
3. 换数据源之后，与原站的"逐数一致"只保留在规则层面，数值改为定性对照，是否接受？

## 修订记录

| 版本 | 内容 |
|---|---|
| v1 → v2 | **C1**：块级的覆盖、补 0 标记和总和全部按 4h 窗口取值，避免 O6 下只有 4hour 的块全部不判定。**C2**：只存已收盘的 bar，每轮重取最近 3 个；forming 块只用连续的 5min；5min 用 `gaps()` 续取；首选"已收盘一律用 4hour"。**I1**：`cz_fetch` 记录请求范围，补 0 的三个条件。**I2**：停采后的原因码、页头、横幅、qty、`VIEW_HOSTS`。**I3**：key 只放单个请求的头、日志测试、repr、退避、compose。**I4**：每天核对一次单位。**I5**：V2 的数据来源。**I6**：补全改动范围。**M1–M5**：已并入相应各节 |
