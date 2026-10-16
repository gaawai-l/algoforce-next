# Perp states 免费数据源核验（Binance USDⓈ-M / Bybit linear）

核验日期：2026-10-17（探测时刻为 UTC 2026-10-16 19:35–19:45，下文时间均为 UTC）。目标：只用免费、无需 key/账户的公开行情接口，重做 BTC 永续的 4h/8h 状态分类（long/short squeeze、long/short unwind、new long/short build、spot-led、chop）。

证据等级：**[已验证]** = 文档 + 实测；**[仅文档]** = 只读到文档、未实测；**[实测]** = 仅实测、文档未说明；**[待验证]** = 无法快速确认。探测原始文件在 `/private/tmp/claude-501/-Users-gary-code-AlgoForceNext/47240a3c-cd31-44d3-a11a-8f26a8fe73b4/scratchpad/perp-research2/`（不入库）。仅调用公开行情接口，未登录、未使用 key。

## 结论速览

| 序列 | Binance USDⓈ-M | Bybit linear | 免费可回填 90 天？ |
|---|---|---|---|
| OI（5m） | `/futures/data/openInterestHist` 仅近约 30 天（29 天前可、31 天前报错）；更早靠 data.binance.vision `metrics` 日包（2020-09-01 起，T+1 约 07:00 UTC 发布） | `/v5/market/open-interest` 5min 可回溯到至少 2021-01，单次 200 条 | 两家都可以 |
| Taker delta（BTC） | `/fapi/v1/klines` 第 10 个字段 taker buy base volume，5m、可回溯到 2019-09、单次 1500 根 | 无。kline 无 taker 拆分；仅有逐笔归档（约 75 MB gz/天）或 WebSocket 自采 | Binance 可以；Bybit 基本不可（90 天约 7 GB） |
| 清算 | 仅 WebSocket 快照（1000ms 一条，非全量）；REST `allForceOrders` 404；`liquidationSnapshot` 归档不存在 | 仅 WebSocket `allLiquidation.BTCUSDT`（500ms 推送，文档称全量）；无公开 REST 历史（待验证） | 都不可，必须自采 |
| 价格 | `klines` / `markPriceKlines` / `indexPriceKlines`，5m，单次 1500 | 现货与合约 `kline`、`mark-price-kline`、`index-price-kline`，单次 1000 | 都可以 |
| 限速 | REQUEST_WEIGHT 2400/分钟/IP；`/futures/data/*` weight 0、1000 次/5 分钟/IP | 600 次/5 秒/IP，超限封 10 分钟 | 90 天回填远低于限速 |

## 1. OI 历史（BTCUSDT）

### 1a. Binance `GET /futures/data/openInterestHist`（base `https://fapi.binance.com`）

- 参数：`symbol`、`period`（5m、15m、30m、1h、2h、4h、6h、12h，另有一个文档摘录里未显示的值；实测 `period=1d` 可用，limit=500 返回 30 条日线，即同样只有约 30 天）、`limit`（文档默认 30、最大 500）、`startTime`/`endTime`。weight 0，限 1000 次/5 分钟/IP。[已验证 2026-10-17，文档来自 developers.binance.com 市场数据页的 WebFetch 摘录]
- **limit 实际上限是 1000**：500、501、1000 条均返回对应条数；1001 返回 HTTP 400 `{"code":-1130,"msg":"parameter 'limit' is invalid."}`。文档写 500，1000 属于未文档化行为，[实测]，生产代码建议用 500 或带降级。
- **保留期**：`startTime` = 29 天前 → 200（288 条）；31 天前、40 天前 → HTTP 400 `-1130 parameter 'startTime' is invalid.`。文档："Only the latest 1 month is available"。精确边界（29–31 天之间）未细查。[已验证]
- 字段：`symbol`、`sumOpenInterest`（BTC 张数，单边计）、`sumOpenInterestValue`（USDT）、`CMCCirculatingSupply`、`timestamp`（毫秒）。样例（2026-10-16 19:30）：`sumOpenInterest=95132.275`。文档："A period with no trades has no record"，缺失期不补。
- **时间戳语义**：文档写 "End time of the period"。实测：时间戳 19:35 的记录在 19:36:52–19:37:03 之间出现，19:40 的记录在 19:42:33–19:43:14 之间出现，即**发布滞后约 2–3 分钟**。数值对比：同一时段实时接口 `/fapi/v1/openInterest` 在 19:37–19:43 恒定在约 94 825，而 hist 的 19:40 记录是 95 049.7、19:35 记录是 95 081.7，不等于实时值，疑似 hist(T) 反映的是更早一个周期的快照。语义 [待验证]；对 4h/8h 块影响不大（5 分钟量级），但块边界对齐要在设计里约定并写入测试。
- 对比 data.binance.vision 日包：2026-10-15 全天 hist 与日包同一数值的对应关系是 `hist(T) == zip(create_time = T − 5m)`，287 行里 201 行完全相等，另 86 行不等（日包里 `92082.736` 在 10:50–11:10 窗口内重复 4 次，疑似陈旧填充）。[实测]

### 1b. data.binance.vision `data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-YYYY-MM-DD.zip`

- 列（8 列，[已验证]）：`create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio`。5m 粒度，每日 288 行，`create_time` 为 UTC 字符串。
- 单文件约 11–12 KB。**最早日期 2020-09-01**（S3 listing 与 `curl -I` 均 200，文件 LastModified 为 2026-03-18 的批量重传）。2020 年文件每行重复一次（576 行 / 288 个唯一时间戳），需去重；2026 年文件行未按时间排序。[已验证]
- **发布滞后**：`curl -I` 2026-10-16 19:3x UTC：10-16 文件 404；10-15 文件 200，LastModified 2026-10-16 07:13:04；10-14 → 10-15 06:50:45；10-13 → 10-14 07:24:43；10-12 → 10-13 07:56:22；10-11 → 10-12 07:44:45。即第 D 天文件在 D+1 日约 07:00–08:00 UTC 发布，**当日及前一日部分数据最长缺口约 31 小时**，当天用 API 补。[已验证]
- 时间对齐：`sum_taker_long_short_vol_ratio` 在 `create_time = T` 的值与 kline（open time = T）推算的 `takerBuy / (volume − takerBuy)` 在 239/288 行吻合（容差 2e-3），所以 `create_time` = bar 开盘时间；OI 列的 `create_time T` 等于 hist API 的 `T+5m` 记录。OI 的 `create_time` 语义因此是"bar 起点的 OI 值"，与 hist 的 end-of-period 标注差一个周期，已在 1a 说明。

### 1c. Bybit `GET /v5/market/open-interest`（base `https://api.bybit.com`）

- 参数：`category=linear`、`symbol`、`intervalTime`（5min、15min、30min、1h、4h、1d）、`limit`（文档 1–200，默认 50）、`startTime`、`endTime`、`cursor`（响应带 `nextPageCursor`）。[已验证]
- limit=200 → 200 条；**limit=201 不报错，静默返回 200 条**（retCode 0）。[实测]
- **历史深度**：文档："The upper limit time you can query is the launch time of the symbol." 实测 5min 数据在 startTime = 2026-06-18（120 天前）、2025-09-12（400 天前）、2024-01-01、2022-01-01、2021-01-01 均返回 200 条，间隔均为 300 s；startTime = 2020-07-01 返回 0 条。**至少回溯到 2021-01-01**，最早日期未精确定位。[已验证]
- 字段：`openInterest`、`singleOpenInterest`、`timestamp`（毫秒）。**`openInterest` 是双边合计，恒等于 `singleOpenInterest` × 2**（200 条当前数据与 2021 年样本均验证）；linear 单位为 BTC。当前值：`openInterest=59837.35`，`singleOpenInterest=29918.675`。与 Binance（单边 95 132）比较时必须用 `singleOpenInterest`。[已验证]
- 时间戳语义：返回按时间倒序；时间戳 19:40 的记录在 19:40:10–19:40:21 之间出现，**点状快照，滞后不超过约 20 秒**。文档未写更新频率，文档提示极端行情下可能延迟。[实测]

## 2. Taker delta（BTC）

### 2a. Binance `GET /fapi/v1/klines`

- 参数：`symbol`、`interval=5m`、`limit`（默认 500、最大 1500，实测 1500 条）、`startTime`/`endTime`。weight 按 limit 分档，文档为 1/2/5/10（<100 / 100–499 / 500–1000 / >1000）；实测 limit=1500 时 `x-mbx-used-weight-1m` 增加 10；limit=100 时增加 1（文档档位写 2，差异未追究）。[已验证]
- 字段（12 元组）：`[0]` open time、`[1..4]` OHLC、`[5]` volume（BTC）、`[6]` close time、`[7]` quote volume、`[8]` trades、`[9]` **taker buy base volume**、`[10]` taker buy quote volume。时间戳是 **bar 开盘时间**。
- **delta = 2 × takerBuy − volume**。2026-10-15 00:00 bar：volume 352.686、takerBuy 205.552，delta = +58.418 BTC。
- 回溯：`startTime` = 2019-09-08 返回首根 bar（2019-09-08 17:55，价格 10000 为上线占位）；`startTime` = 90 天前返回 1500 根（2026-07-18 19:45 起）。**5m 可回溯到合约上线，90 天回填可行**。
- 注意：返回包含**未收盘的当前 bar**（最后一根 open=19:40，探测时刻 19:4x），入库前必须按 `closeTime < now` 过滤。

### 2b. Binance `GET /futures/data/takerlongshortRatio`

- 参数同 hist（`symbol`、`period`、`limit`、`startTime`、`endTime`）；limit=500、501、1000 均成功，1001 → 400 `-1130`。保留期同 OI：29 天前 200，31 天前 400 `-1130`。[实测]。该接口的官方文档段落在 WebFetch 中被截断，没有读到原文，[仅实测]。
- 字段：`buySellRatio`、`buyVol`、`sellVol`、`timestamp`。**timestamp = bar 开盘时间**（与 kline open 对齐）；发布滞后约为 bar 收盘后 2 分 14 秒–2 分 25 秒（时间戳 19:30 的记录在 19:37:14–19:37:25 之间出现）。
- **不建议作为 delta 来源**：2026-10-15 当日 287 个对齐 bar 中，158 个的 `buyVol` 与 kline 的 `[9]` 完全相等；另外 129 个偏低（最多低 1178.3 BTC），`buyVol + sellVol` 比 kline volume 最多低 3497.6 BTC，从不更高。该接口的数据不完整，delta 一律用 kline 计算。[实测]

### 2c. Bybit

- `GET /v5/market/kline`（`category=linear` 与 `spot`）：每行只有 7 个字段 `[start, open, high, low, close, volume, turnover]`，**没有 taker 拆分**。[已验证 2026-10-17]
- 公开逐笔归档 `https://public.bybit.com/trading/BTCUSDT/` **存在**：2396 个文件，`BTCUSDT2020-03-25.csv.gz` 至 `BTCUSDT2026-10-15.csv.gz`。2026-10-15 文件 LastModified 为 2026-10-16 01:11:21 GMT，大小 78 328 845 字节（约 75 MB gz）；探测时刻（UTC 10-16 19:3x）当天文件尚未生成，所以**滞后约 1 天**。
- 列（首 4 行实测）：`timestamp`（epoch 秒，带小数）、`symbol`、`side`（Buy/Sell）、`size`、`price`、`tickDirection`、`trdMatchID`、`grossValue`、`homeNotional`、`foreignNotional`、`RPI`。`side` 是否等于 taker 方向 [待验证]（未读到归档说明文档）。
- 90 天回填约 90 × 75 MB ≈ 6.8 GB gz，只有在确实需要 Bybit taker delta 时才值得；否则用 WebSocket `publicTrade.BTCUSDT` 自采（Bybit 公共 WS 限 500 连接/5 分钟，单 IP 每市场最多 1000 连接，[仅文档]）。

## 3. 清算

### 3a. Binance `<symbol>@forceOrder` / `!forceOrder@arr`

- 文档页（All-Market-Liquidation-Order-Streams，WebFetch 2026-10-17）：Update Speed 1000ms；引文："only the latest one liquidation order within 1000ms will be pushed"；某 1000ms 区间无清算则不推送。
- **文档自相矛盾**：developers.binance.com Change Log 2026-04-10 条目写明把 "latest" 改成 "largest"（WebFetch 与 WebSearch 摘要均如此）。页面正文仍写 "latest"。哪一条为准 [待验证]；无论哪一条，都是**每个 symbol 每秒最多一条的快照，爆仓密集时必然漏单**，只能做相对强度指标，不能做精确总量。
- 路由变更：市场流改用 `wss://fstream.binance.com/market/ws/<stream>` 与 `wss://fstream.binance.com/market/stream?streams=...`；旧路径 `/ws`、`/stream` 按 Change Log（2026-04-02 公告）于 2026-04-23 下线。
- 实测（2026-10-16 19:4x，22 秒）：`!forceOrder@arr` 全市场共收到 3 条（样例 `SHAZUSDT`），`btcusdt@forceOrder` 0 条。字段：`e`、`E`、`o{s,S,o,f,q,p,ap,X,l,z,T}`，实测还多出 `ps`、`st` 两个文档未列字段。样例 `q=12.96`、`l=6.99`、`z=12.96`，一次清算可分多次成交，名义金额应取 `z × ap`。
- 方向语义：文档示例为 `"S":"SELL"`、`BTCUSDT`；"SELL = 多头被强平" 是订单方向（平仓方向）的推论，文档未明说，[待验证]（需要抓到 BTCUSDT 样本并与价格方向对照）。
- REST 历史：`GET /fapi/v1/allForceOrders` → HTTP 404（2026-10-16 实测）；`/fapi/v1/forceOrders` 是需签名的账户自身强平接口（Change Log 2026-04-06 注明仅返回 90 天），不适用。[已验证]

### 3b. Bybit v5 `allLiquidation.{symbol}`（`wss://stream.bybit.com/v5/public/linear`）

- 文档（WebFetch 2026-10-17）：推送频率 500ms；"pushes all liquidations that occur on Bybit"，覆盖 USDT/USDC/inverse；字段 `T`（更新时间戳 ms）、`s`、`S`（Position side，Buy/Sell）、`v`（成交数量，字符串，文档未写单位）、`p`（破产价 bankruptcy price，不是成交价）。方向语义：文档写 `Buy` 表示 "a long position has been liquidated"，`Sell` 文档未明说（推论为空头被强平）。[仅文档]
- 实测：订阅 `allLiquidation.BTCUSDT/ETHUSDT/SOLUSDT/XRPUSDT` 的订阅确认 `success:true`，两轮共约 44 秒内**没有收到任何清算消息**，因此 payload 未见，`v` 单位 [待验证]（linear 预期为 BTC 张数）。
- 无公开 REST 清算历史 [待验证，仅为常识，本轮未逐个端点证实]。

### 3c. data.binance.vision `liquidationSnapshot`

- S3 listing（2026-10-16）：`data/futures/um/daily/` 下的数据类型只有 `aggTrades`、`bookDepth`、`bookTicker`、`indexPriceKlines`、`klines`、`markPriceKlines`、`metrics`、`premiumIndexKlines`、`trades`；`liquidationSnapshot/BTCUSDT/` 的 daily 与 monthly 前缀均 0 个对象。**已不再发布**。[已验证]

## 4. 价格

- Binance：`GET /fapi/v1/markPriceKlines?symbol=BTCUSDT&interval=5m&limit=1500` → 200，1500 条；`GET /fapi/v1/indexPriceKlines?pair=BTCUSDT&interval=5m&limit=1500` → 200，1500 条；90 天前 `startTime` 同样可取（2026-07-18）。字段只有 `[0]` open time 和 OHLC、`[6]` close time，其余为 ignore（实测填 0）。weight 分档同 klines（实测 +10）。[已验证]
- Bybit 现货：`GET /v5/market/kline?category=spot&symbol=BTCUSDT&interval=5&limit=1000` → 1000 条，倒序，`[start, o, h, l, c, volume(BTC), turnover(USDT)]`，探测时覆盖到 2026-10-13 08:25。合约 `category=linear` 同结构。另有 `mark-price-kline`、`index-price-kline`（各返回 200）。limit 上限 1000 仅验证了 1000 成功，1001 未测。
- "spot-led" 判定需要现货价格/量：Bybit 现货 kline 已验证；Binance 现货 `/api/v3/klines` 本轮未探测 [待验证]。

## 5. 限速与 90 天回填预算

- Binance：`GET /fapi/v1/exchangeInfo` 的 `rateLimits`：`REQUEST_WEIGHT` 2400/分钟（IP 维度）。429 须退避，继续请求会被 418 封禁，2 分钟至 3 天（文档）。响应头 `x-mbx-used-weight-1m` 实测。`/futures/data/*` weight 0，每 IP 1000 次/5 分钟（文档来源：market data 页摘录与 2023-10-19 Change Log）。
- Bybit：每 IP 5 秒内 600 次，超限 403 并需等待至少 10 分钟；公共 WS 5 分钟内最多 500 次连接，单 IP 每市场最多 1000 个连接（文档，WebFetch 2026-10-17）。
- 90 天 5m 回填（25 920 根/序列）：

| 项目 | 请求数 | 备注 |
|---|---|---|
| Binance `klines`（OHLCV + taker） | 18 | 18 × weight 10 = 180，约一分钟配额的 7.5% |
| Binance `markPriceKlines` / `indexPriceKlines` | 各 18 | 各 180 weight |
| Binance OI（API，近 30 天） | 9（limit=1000）或 18（limit=500） | weight 0 |
| Binance OI（>30 天） | 约 60 个日包下载 | 每个约 11 KB，共约 1 MB；缺 D 日需用 API 补 |
| Bybit OI 5min | 130（200 条/页） | 600 次/5 秒限速内约 13–30 秒 |
| Bybit 现货与合约 kline | 各 26（1000 条/页） | 同上 |
| Bybit 逐笔归档（可选） | 90 个文件 | 约 6.8 GB gz，不建议 |

## 对 P4 设计的含义

1. **能回填 90 天的序列**：Binance 5m kline（含 taker buy，得 delta）、mark/index kline；Binance OI（API 30 天 + metrics 日包拼接，去重并处理 2020 年重复行）；Bybit OI（用 `singleOpenInterest`）、Bybit 现货/合约 kline。4h/8h 块由 5m 聚合；块边界 5 分钟量级的 OI 时间戳歧义可以接受，但需在聚合里固定一种约定并用 2026-10-15 的 hist vs zip 样本做回归测试。
2. **硬缺口（免费无法回填）**：Binance 与 Bybit 的清算历史（REST 与归档均无）；Bybit 的 taker 拆分（除非下载约 75 MB/天的逐笔归档）。
3. **采集器必须自己长期运行**：清算只能 WebSocket 前向采集。Binance 流是 1 条/秒/symbol 的快照（语义 latest 还是 largest 待定），Bybit 流声称全量；两者口径不同，不能直接相加。若分类用滚动 30 天分位基线，需先运行约 30 天（4h 块 180 个，8h 块 90 个）；要与 90 天价量/OI 回填对齐则需 90 天。采集器应落库原始事件（时间、方向、`z × ap` 名义金额、来源），断线要记缺口，不能补零。
4. **缺失与滞后处理**：Binance hist/taker 发布滞后 2–3 分钟，metrics 日包滞后到 D+1 约 07:00–08:00 UTC，Bybit OI 滞后约 20 秒；"当前块"必须标记数据新鲜度，缺失期写成缺失而非 0。kline 的未收盘 bar 要过滤。
5. **Bybit taker delta 的取舍**：若只做 Binance 口径的 delta 分类，Bybit 只提供 OI 与价格即可；要两家都有 delta，需要自采 `publicTrade` WS（前向、无回填），或按需下载归档的有限窗口。
6. **清算指标定位**：在样本不完整的前提下，清算只能用来区分 squeeze 与 unwind 的相对强弱，不应作为精确金额出现在界面，并在界面上标注 "Binance 快照，非全量"。

## 待验证

1. Binance `openInterestHist` 时间戳实际含义（文档 end of period；实测值与实时 OI 不一致，疑似落后一个周期）。需在 OI 剧烈变动的时段，用 5 秒级实时轮询对照。
2. 30 天保留期的精确边界（只知 29 天可、31 天不可）；`limit` 1000 为未文档化上限。
3. `takerlongshortRatio` 官方文档段落未读到；其数据比 kline 少的原因未明。
4. 日包 OI 中重复值（如 `92082.736` 在 10:50–11:10 重复 4 次）的原因。
5. Binance `forceOrder` "latest" 与 "largest" 的矛盾，以及 `S=SELL` 对应多头被强平；`ps`、`st` 字段含义。
6. Bybit `allLiquidation` 的实际 payload、`v` 单位、`Sell` 语义，以及是否确无 REST 历史。
7. Bybit 逐笔归档的 `side` 是否为 taker 方向，以及每日文件的准确生成时刻（本轮只看到 D 日文件在 D+1 01:11 UTC 已存在）。
8. Bybit OI 最早日期（2020-07-01 无数据，2021-01-01 有数据）。
9. Binance `klines` limit=100 的 weight（实测 +1，文档档位 2）。
10. Binance 现货 `/api/v3/klines` 与 Bybit kline limit=1001 的行为未探测。
