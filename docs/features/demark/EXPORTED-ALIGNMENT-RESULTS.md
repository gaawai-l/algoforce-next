# 用户导出样本同输入对齐结果

日期：2026-09-27。输入为用户提供的 `demark-15.json`、`klines-15m.json`，BTC/USDT、15m、Sequential。对应只含市场数据的原始文件已保留在 `services/analytics/tests/demark/fixtures/`；不含账户、凭据或私有源码。

## 结论

在**完全相同的500根导出OHLC**上，新命名规则配置的561个参考标记全部一致，无缺少、无多出。4个合格13的方向、bar时间、Risk Level与失效时间也通过逐项核验。此结论是一个固定样本的一致性，不是所有市场场景或实时行情供应商已对齐。

| 对照 | 参考数 | 匹配 | 缺失/多出 |
|---|---:|---:|---:|
| Setup标记 | 478 | 478 | 0/0 |
| 普通Countdown标记 | 61 | 61 | 0/0 |
| 13延期标记 | 8 | 8 | 0/0 |
| 完善9标记 | 5 | 5 | 0/0 |
| 合格13 | 4 | 4 | 0/0 |
| 反向取消 | 3 | 3 | 0/0 |
| recycling | 1 | 1 | 0/0 |
| TDST取消 | 1 | 1 | 0/0 |
| 合计 | 561 | 561 | 0/0 |

结果风险价用Decimal核算；参考JSON存在如82639.49999999999的二进制浮点尾差，价格对照容差仅1e-8 USDT，并非放宽实质价差。

## 原来为什么多出两个13

原版本在新同向Setup9出现、但不满足回收条件时，允许新旧两个Countdown并行推进。参考样本保留旧Countdown继续，新Setup仍被记录，但不额外启动一个Countdown。原算法因此多产生2个13。

修正采用显式配置：

- `ruleset_version=wheelhouse-sequential-2`
- `same_side_policy=retain_active`
- `perfection_policy=strict_at_nine`

参考样本只输出在Setup9当根确认的5个完善标记；原版本还跟踪后续延迟完善。新配置匹配这一显示/状态政策，不宣称经典DeMark不允许延迟完善。原v1和parallel/strict配置仍保留，旧快照继续可读。

price flip、Countdown含等号、Setup9当根可参与Countdown、13-vs-8极值比较、TDST true extremes、Risk公式无需修改即可复现此样本。先前网页文案“最快22根”“收盘越过8”不足以推断真实实现；本次实际样本显示Setup9与Countdown1可同根，不再沿用此前文案推断。

审查另覆盖样本未包含的后续Setup22组合：retain_active新序列被压制后，回收旧序列时要从当前根激活新Countdown，不能导致两条都不活动，也不能追认过去13。该边界已加独立回归测试；它是明示政策，尚未声称得到TradingSignal的22样本验证。

## 形成中bar与已收盘bar

原文件最后一根15:30–15:45 UTC在导出时未收盘，参考已经给出Buy Setup6。离线全样本对照将其**固定观察值**参与演算，绝不作为当时已收盘事实存入生产库。

只取前499根已收盘bar时，参考截止该处的560个事件同样全部匹配；本地当前Buy Setup5，历史合格13仍4个。最后一根形成中的第6个计数不写入正式closed结果。

因此页面上的5与6必须区分已收盘/形成中，不能为了数字一致而破坏无前视策略。本轮尚未增加独立的实时形成中预览。

## 行情源是另一件事

我们的Binance现货接口经20根同源复核无差异。但用户导出的499根已收盘数据与同窗Binance现货并不相同，Close平均绝对差约4.62 USDT。不同市场可以有小价差，但**本次多出两个13的已确认根因是并存算法政策**，不能用报价差推卸该原因。

实际参考行情供应商尚未查明，导出缺少provider/marketType；不能据小数位猜成Bybit或Binance合约。见 [EXPORTED-SOURCE-CHECK.md](EXPORTED-SOURCE-CHECK.md)。本轮没有把未知来源导入Binance生产数据，也没有改用猜测的交易所。

## 可复跑

```sh
.venv-foundation/bin/python -m pytest services/analytics/tests/demark -q
.venv-foundation/bin/python scripts/verification/compare_tradingsignal.py \
  --exported-bars services/analytics/tests/demark/fixtures/tradingsignal-btcusdt-15m-candles.json \
  --td-result services/analytics/tests/demark/fixtures/tradingsignal-btcusdt-15m-result.json \
  --closed-before 2026-09-27T15:30:00Z \
  --include-forming-observation \
  --output .local/demark-verification/exported/aligned-all-observations.json
```

去掉 `--include-forming-observation` 为499根闭合前缀对照。`--profile classic` 可复跑原算法差异。对照脚本不访问TradingSignal、不读取浏览器凭据。

新增5项导出/策略边界测试，DeMark专项共29项通过。前端配置与运行时校验升级，默认新刷新使用v2；新页面发现旧规则快照时请求一次刷新，已保存旧快照保持原值。后续需要不同周期/行情的样本扩充覆盖，且必须确认实时行情源后才能承诺实时画面一致。
