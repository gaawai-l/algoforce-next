# Coinalyze 测试样本

## 来源

Coinalyze（<https://coinalyze.net>）的公开行情接口，2026-10-19 07:41 UTC 取得（V1 探测的原始响应，`run-2026-10-19T0741Z/raw/`）。取数时刻为 2026-10-19T07:42:00Z：4hour 的最后一个点（04:00）和 5min 的最后一个点（07:40）此时尚未收盘。

## 裁法

每个文件保持接口原样（`[{"symbol": ..., "history": [...]}]`），只裁掉不用的 symbol 和较早的点，数值不改：

| 文件 | 接口 | symbol | 保留的点 |
|---|---|---|---|
| `liquidation-history-4hour.json` | `/v1/liquidation-history`，`interval=4hour` | `BTCUSDT_PERP.A`、`BTCUSDT.6`、`BTCUSDT_PERP.3` | 每个 symbol 最后 6 个，含未收盘的最后一个 |
| `ohlcv-history-5min.json` | `/v1/ohlcv-history`，`interval=5min` | `BTCUSDT.6`、`BTCUSDT_PERP.3`、`BTC.H` | 每个 symbol 最后 4 个，含未收盘的最后一个 |
| `open-interest-history-4hour.json` | `/v1/open-interest-history`，`interval=4hour` | `BTCUSDT_PERP.3`、`BTC.H` | 每个 symbol 最后 3 个，含未收盘的最后一个 |
| `future-markets.json` | `/v1/future-markets` | 本期 4 个 symbol 加 `BTCUSD_PERP.A` | 整条记录原样保留 |

`BTCUSD_PERP.A` 是 Binance 币本位合约（`oi_lq_vol_denominated_in` 为 `QUOTE_ASSET`），用来确认客户端不会把它当成本期的 symbol。

## 不含 key

样本只有公开行情，不含 API key。V1 的探测脚本在写文件前把 key 替换掉，裁剪后又用 `Settings` 取出的 key 逐文件计数，结果都是 0。
