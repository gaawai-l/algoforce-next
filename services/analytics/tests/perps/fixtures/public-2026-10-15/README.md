# Perp fixtures, 2026-10-15 (public data)

公开行情数据，无需 key、无账户数据；按 P4-R3 可以入库。采集于 2026-10-16（UTC 约 19:35–19:45），
来源是 `.local/research-samples/perp-free-data-2026-10-17/` 中的探测原始文件，内容未改动（Bybit 现货只切出
10-15 那一段）。各文件覆盖 2026-10-15 00:00–23:55 UTC 全天，每个文件 288 行，5m 粒度。请勿手工编辑。

| 文件 | 来源文件 | 请求 | 说明 |
| --- | --- | --- | --- |
| `binance_oi_hist_5m.json` | `bn_oi_1015.json` | `GET https://fapi.binance.com/futures/data/openInterestHist`，`symbol=BTCUSDT`、`period=5m`，时间范围为 10-15 全天 | 原样复制。`timestamp`（毫秒）00:00–23:55，升序，无空洞 |
| `binance_klines_5m.json` | `bn_kl_1015.json` | `GET https://fapi.binance.com/fapi/v1/klines`，`symbol=BTCUSDT`、`interval=5m`，时间范围为 10-15 全天 | 原样复制。12 元组，`[0]` 为开盘时间，`[5]` volume，`[9]` taker buy base volume |
| `bybit_spot_klines_5m.json` | `by_spot.json` | `GET https://api.bybit.com/v5/market/kline`，`category=spot`、`symbol=BTCUSDT`、`interval=5`、`limit=1000`（响应 `time` 为 2026-10-16T19:43:32Z） | 原响应有 1000 行（10-13 08:25 至 10-16 19:40）；这里只保留开盘时间在 10-15 当天的 288 行，信封字段不变。`list` 按时间倒序，与 Bybit 原响应相同 |
| `BTCUSDT-metrics-2026-10-15.csv` | `metrics_new/BTCUSDT-metrics-2026-10-15.csv` | `https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-10-15.zip` 解压所得 | 原样复制。行未按时间排序，无重复行 |

探测时没有记录完整的查询串，表中的参数按响应内容和
[免费数据源核验](../../../../../../research/perp-free-data-2026-10-17.md) 还原。

## 约定（spec §3.1）

- 网格桶 `t` 覆盖 `[t, t+10m)`。price 取 Bybit 现货中开盘于 `t+5m` 那根的 close；vd 取 Binance
  开盘于 `t` 和 `t+5m` 两根 kline 的 `2·takerBuy − volume` 之和。
- Binance OI 读 `oi.t = t + 10m`，`oi.t` 就是 hist 的 `timestamp`。日包的行存为
  `oi.t = create_time + 5m`：10-15 当天 `create_time` 10:45 及之前的行与 hist 的 `create_time + 5m` 完全相等。
- hist 最后一行是 23:55，它映射不到任何桶（23:45 不是 10 分钟整点），所以 OI 的最后一个桶是 23:40；kline
  的最后一个桶是 23:50。binance 视图的 `last` 取两者较早的 23:40。
- 日包隔离：这一天的日包从 `create_time` 10:50 起出现陈旧重复值（`92082.736`），13:40 起另有
  `sum_open_interest = 0` 的行。按 spec，`create_time ≥ 10:50` 的行（`oi.t ≥ 10:55`）全部隔离为 null。
