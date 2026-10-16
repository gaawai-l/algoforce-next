# TradingSignal 导出行情来源核查

核验时间：2026-09-27 UTC。只读核查，不修改行情源或生产计算规则。

## 结论

用户提供的 500 根 `BTC/USDT · 15m` **不等于 Binance 现货同时间行情**。排除最后一根形成中 K 线后，499 根已收盘 K 线仍无一根 OHLC 四项完全一致。因此即使算法相同，直接使用当前 Binance 现货输入也不能保证与此参考输出完全一致。

两份导出未包含交易所名称、现货/合约类型或服务器采集时间。不能据小数位、价格或成交量猜定实际供应商。`drift: none` 也不构成来源证明。

## 样本与窗口

- 行情：用户提供 `/Users/gary/Downloads/klines-15m.json`。
- 指标：用户提供 `/Users/gary/Downloads/demark-15.json`。
- 500 根开盘时间从 **2026-09-22 10:45 UTC** 到 **2026-09-27 15:30 UTC**，间隔连续 900 秒，无重复时间。
- 本地行情文件保存时间为 2026-09-27 15:32:11 UTC，指标文件为 15:32:52 UTC。文件时间不是 API 自带的采集证明，但此次核查时钟也尚未到 15:45 UTC。
- 最后一根的收盘边界是 **15:45 UTC**：它在此次导出/核查时仍在形成中。其导出 close 为 `84606`。
- 指标输出含最后一根的 `BUY Setup 6`，快照 `84606 / 83830.4 - 1` 与 `closeVsTdstPct` 一致（仅浮点尾差）。因此参考输出确实包含这根形成中 bar，而不只是行情列表包含它。
- 本项目正式结果的已收盘策略与参考快照的形成中策略应分别标示；离线同输入对照可以固定原始导出值，但不能把其最后一根伪装成已收盘数据。

## Binance 现货独立对照

使用官方公共市场数据端点 `https://data-api.binance.vision/api/v3/klines`，`symbol=BTCUSDT`、`interval=15m`，按原始导出首尾时间请求；返回 500 根，时间戳全部对应。

| 比较项 | 前 499 根已收盘样本 | 全部 500 根（末根未收盘，仅供诊断） |
|---|---:|---:|
| OHLC 全匹配 bar | 0 | 0 |
| Open 不同 | 498 | 499 |
| High 不同 | 499 | 500 |
| Low 不同 | 496 | 497 |
| Close 不同 | 498 | 499 |
| Volume 不同 | 499 | 500 |

前 499 根最大单项 OHLC 绝对差为 `51.70 USDT`，平均绝对 Close 差约 `4.62 USDT`。比较容差为 `1e-9`，不是把显示舍入差当作算法差异。

第一根 2026-09-22 10:45 UTC 的明确例子：

| 字段 | TradingSignal 导出 | Binance 现货 |
|---|---:|---:|
| Open | 85852.30 | 85846.01 |
| High | 85983.00 | 85980.01 |
| Low | 85787.70 | 85790.64 |
| Close | 85898.20 | 85904.00 |
| Volume | 39.326202 | 126.204540 |

末根 Binance 数值在稍后的请求时继续变化，因此末根差异不能单独证明行情源不同；上述已收盘 499 根才是结论依据。

## 参考引擎配置证据

`variantTag` 明确给出：

```json
{
  "requireLeadingPriceFlip": true,
  "countdownCompareInclusive": true,
  "tdstBreakBasis": "BarClears",
  "recycleMinRatio": 1,
  "recycleMaxRatio": 2
}
```

这些字段足以约束 price flip、Countdown 比较含等号、TDST 突破依据名称和 recycling 范围参数。范围是否含边界、同向序列替换策略等仍需同输入逐根推断；不能单凭参数名补全算法。

`engineWarm: true` 仅是对方引擎自报状态，没有 warmup 根数、历史起点、规则版本号或状态恢复来源，不能据此声称它读取了导出窗口之前的行情，也不能证明初始化状态完全相同。

## 其他来源的有界探测

同窗前 20 根分别请求 Binance USD-M 官方 `fapi.binance.com/fapi/v1/klines`、Bybit 官方 `api.bybit.com/v5/market/kline` 的 `spot` 和 `linear` 类别。三项均返回 `Connection refused`，未取得价格；没有改域名绕行或规避限制。因此实际来源仍未识别，不能把“不是相同 Binance 现货 OHLC”扩写成“已确认 Bybit”或“已确认合约”。

## 原始诊断

本地目录 `.local/demark-verification/exported/` 保存：

- `binance-spot-same-window.json`：官方现货原始响应。
- `binance-fetch-metadata.json`：完整请求 URL、采集时间、HTTP Date。
- `binance-spot-comparison.json`：逐根逐字段差异。
- `export-source-summary.json`：导出文件 SHA-256、时间窗口、形成中证据、配置标签。
- `other-source-probes.json`：其余官方端点的访问失败记录。

下一步应先用**用户导出的同一份 OHLC**隔离和核验算法差异，再确定可持续取得相同来源行情的方式。不要通过修改算法去补偿不同交易所的价差。

## 2026-09-28 补充：Bybit 现货同窗核验通过

通过部署服务器成功请求官方 Bybit V5 `/v5/market/kline`，category=spot、symbol=BTCUSDT、interval=15，固定原导出时间范围。原样本499根已收盘OHLC与Bybit499/499完全一致，最大价格差0。用Bybit这批输入重新执行v2计算，560/560参考标记匹配，无缺失/多出，Risk Level无差异。该证据替代此前“Bybit接口未取得价格”的状态，但不将固定样本匹配扩写为所有实时窗口一致。

按用户要求，BTC默认源切换为Bybit现货；MU和ETH保持Binance USDT永续。实现与发布见 `docs/deployment/BYBIT-BTC-PLAN.md` 和对应发布记录。
