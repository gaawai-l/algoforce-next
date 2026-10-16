# WebSocket 消息样例（公开行情）

Task 0 实测（2026-10-16 约 20:41–20:47 UTC，websockets 17.2 同步客户端）保存在
`.local/research-samples/perp-free-data-2026-10-17/ws_live/`，这里只截取几条，无账户数据、无 key。
原文件每行包了一层 `{"t": 本地时刻, "msg": 消息}`，这里只保留 `msg`，字段与取值未改动，
只把空白压成紧凑 JSON。实测窗口内没有 BTCUSDT 清算，所以两份 BTC 清算样例是按格式构造的，见下表。

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `binance_force_order.jsonl` | 实测，`liquidation_shapes.json` 前两条（`!forceOrder@arr`） | 真实 `forceOrder` 事件，但是 CTUSDT、FOLKSUSDT，不是 BTCUSDT；用来确认解析只取 BTCUSDT |
| `binance_force_order_btc.json` | **构造** | 与实测完全相同的字段集 `{"e","E","o":{s,S,o,f,q,p,ap,X,l,z,T,ps,st}}`，`s=BTCUSDT`，数值是编的 |
| `bybit_control.jsonl` | 实测，`bybit_liq.jsonl` 前两行 | 订阅确认（`op=subscribe`、`success=true`）与应用层心跳回复。回复是 `op="ping"`、`ret_msg="pong"`，不是 `op="pong"` |
| `bybit_public_trade.jsonl` | 实测，`bybit_trades.jsonl` 前 6 条成交消息 | `publicTrade.BTCUSDT`，每条 `data` 1–6 笔，字段 `T,s,S,v,p,L,i,BT,RPI,seq` |
| `bybit_all_liquidation.json` | **构造（文档形状）** | 实测订阅后 90 秒内没有任何 `allLiquidation` 消息，形状按 Bybit v5 文档：`{"topic","type":"snapshot","ts","data":[{T,s,S,v,p}]}`，数值是编的 |

`S` 的方向含义、`v` 的单位仍是 spec §6 的待验证项；样例只约束格式，不证明语义。
