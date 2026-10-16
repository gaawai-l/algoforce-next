# DeMark Regime 对照记录

每行一次对照。「一致」指结构字段一致；价格残差单列。未收盘 bar 按抓取时刻，由 1m/1s K 线重建。

| 抓取时刻 (UTC) | 覆盖情形 | 结构字段 | Regime（日内/跨天） | 置信度 | 备注 |
|---|---|---|---|---|---|
| 2026-09-27 16:28:32 | 1h 刚走完 13、4h 保留 Countdown 同时新 9、1d 取消过的 Countdown | 5m 的 prev 与 barsSinceQualified13 不同（行情源）；15m 在 Binance 行情下 lastSignal/prev 差 1 根 | 阴跌爆拉 / 突破减弱，一致 | 5/5 一致 | 黄金样本，见 tests/regime/fixtures |
| 2026-09-28 03:50:24（按 03:49:55 回放） | 5m countdown 11 且中途又出现同向 BUY 9；15m countdown 2 + 反向 SELL 1 形成中；1h 13 之后 setup 6；4h 保留 Countdown 8 + 被压住的同向 9；1d countdown 9、prev 为未合格的 BUY 5 | 1h/4h/1d 全一致；15m barsSinceQualified13/prev 差 1 根（同黄金样本的 13 落点差）；5m rounds 本地曾多列被压住的 BUY 9（1790561700），已修复 | 阴跌爆拉 / 突破减弱，一致；与 AlphaBTC 页面文字一致 | 5/5 一致 | risk 结构字段（side、risk9Ts、risk13Ts、provisional、setupRun、nextBarNeeds 方向）5/5 一致；价格残差 ≤65，唯 5m riskLevel −92（见下） |
| 2026-09-28 04:00:23 | 5m 的 BUY 13 恰好在形成中的 04:00 bar 上合格（barsAgo 0）；15m countdown 2；1h setup 7；4h 保留 Countdown 8 + 被压住的 SELL 9 + BUY 3；1d countdown 9 | 1h/4h/1d 全一致；15m 13 落点差 1 根（行情源）；5m countdownStep 本地曾为 0，TS 为 13，已修复 | 阴跌爆拉 / 突破减弱，一致；与页面文字一致 | 5/5 一致 | risk 结构 5/5 一致；价格残差 ≤65（5m close13 −28.8：13 落在形成中 bar，随取样时刻变化） |
| 2026-09-28 04:07:54（TS 数据约 04:05:36 计算） | 同 04:00，但 TS 的 5m 最后一根仍为 04:00，close 83274.4 已是 04:05:3x 的实时价 | 1h/4h/1d/5m 全一致；15m 13 落点差 1 根（行情源） | 阴跌爆拉 / 突破减弱，一致；与页面文字一致 | 5/5 一致 | risk 结构 5/5 一致 |
| 2026-09-28 04:16:36 | 5m 在 BUY 13（3 根前、风险位未破）之后翻为 SELL setup 2，SELL 侧 S9（09-27 18:05）的 countdown 曾到 12 后被反向 Setup 取消；15m countdown 2 + SELL 1 | 1h/4h/1d 全一致；5m rounds 与 setupClose 曾不一致，已修复；5m risk13Ts/riskLevel 为黄金样本那个 SELL 13 的 28 根落点差（行情源）；15m 13 落点差 1 根 | 阴跌爆拉 / 突破减弱，一致；5m 页面 BUY 1 显示「——」与修复后一致 | 5/5 一致 | countdownStep 在 13 之后第 3 根为 0，与实现一致 |
| 2026-09-28 04:31:54 | 5m SELL setup 5（BUY 13 之后 6 根，风险位仍有效）；15m countdown 2 + SELL 2；1h setup 7；4h countdown 8；1d countdown 9 | 1h/4h/1d/5m 结构全一致；5m risk13Ts/riskLevel 与 15m 13 落点为已知行情源差异 | 阴跌爆拉 / 突破减弱，一致；5m 页面 BUY 1「——」一致 | 5/5 一致 | 前述 rounds 保留、setupClose 置空、countdownStep 归 0 三条规则均成立，无新差异 |

### 2026-09-28 03:50 快照说明

- **抓取时刻：**`/api/td9` 的 `fetchedAt` 为 03:50:24，但 TS 数据本身早于该时刻。5m 的最新 bar 是 03:45，到抓取时已经收盘；TS 给出的 close 83447，与 Binance 该 bar 的终值 83405 不同。15m 形成中 bar 的 TS close 为 83455.3，高于 4 根前的收盘价 83418.24，因此 TS 记为 SELL setup 1；但 03:50:24 时 Binance 价格在 83383–83400。按 03:50:24 回放，15m 会多出 second/rounds 两项差异；改用最后一次高于阈值的时刻 03:49:55 回放后，这两项消失。
- **脚本修正（已被 04:07 快照推翻，见下）：**曾把重建截止时间取为 `min(抓取时刻, asOf + 周期)`。04:07 快照证明 TS 的最后一根会越过收盘时间继续取实时价，这个截断是错的，已撤回。
- **5m rounds（已修复）：**本地规则 B 曾把 `retain_active` 压住的同向 BUY 9（1790561700，countdown 0）列为 rounds[1]；TS 的 rounds 里没有这一轮，尽管 TS 的 `risk9Ts` 正是 1790561700。4h 同类情形（被压住的 SELL 9）TS 会列出。能区分两者的只有「是否完善」：5m 那一轮未完善，4h 那一轮已完善。两者的区间都小于前一轮，所以区间大小不是区分因素。`summary.py` 已改为：被压住且未完善的同向 9 不列入 rounds。回归夹具为 `tests/regime/fixtures/alphabtc-td9-2026-09-28T034955Z.json`，5 个周期的结构与 risk 结构测试全部通过，黄金样本的结果不变。AlphaBTC 只从 rounds 里读取 13 的时间，所以这项修改不影响 s9/s13、Regime 和置信度。
- **5m riskLevel −92：**两边的 13 事件相同（risk13Ts 1790555700）。在 Binance 数据里，Countdown 区间内最低的几根 bar 低点只差 3.8（84132.00 / 84135.78 / 84146.00），最低那根有一根 170 的影线，因此本地得到 83961.32。TS 在它自己的行情上只要影线更短，或者最低点落在另一根 bar，就会得到 84053.5。结论：差异来自行情源，公式本身没有问题。

## Step 2 实际输出

命令：

```sh
.venv-foundation/bin/python scripts/verification/compare_alphabtc_context.py \
  --td9 <scratchpad>/td9-20260927.json --captured-at 1790526512
```

控制台输出：

```text
5m state=OK levels=OK ['barsSinceQualified13', 'prev']
15m state=OK levels=OK ['barsSinceQualified13', 'lastSignal', 'prev']
1h state=OK levels=OK structure OK
4h state=OK levels=OK structure OK
1d state=OK levels=OK structure OK
regime {'alphabtc': {'intraday': 'pump', 'swing': 'decay'}, 'local': {'intraday': 'pump', 'swing': 'decay'}, 'match': True}
```

摘要：5 个周期 `state=OK levels=OK`；`regime` 一致（`intraday=pump`、`swing=decay`，`match: True`）。1h/4h/1d 结构字段完全一致。

- **5m** 只有 `barsSinceQualified13`（TS 63 根 vs 本地 35 根）与 `prev.barsAgo`（同为 63 vs 35，指向同一个 SELL 13 事件）不同，`prev` 的 side/countdown/qualified 本身一致。这与 `docs/features/demark/ACROSS-PRIMARY-SEQUENCE.md` §6（表格行 132、注释行 11）已记录的行情源差异完全吻合：该 SELL 13 出现在两个数据源报告的不同 bar 位置上，属已知的行情源差异，与本脚本或映射规则无关。
- **15m** 比预期多列出 `barsSinceQualified13`（58 vs 57），并列出了 `lastSignal`（ts 相差 900 秒，即 1 根 15m bar）与 `prev.barsAgo`（58 vs 57）。三项都是同一个根因的表现：本脚本按任务约束只读 Binance 行情，而黄金样本的 15m 在 15:30 UTC 之前使用的是用户导出的 TradingSignal 行情（见样本 `note` 字段）；`ACROSS-PRIMARY-SEQUENCE.md` 已经指出「只用 Binance 时 13 落在 02:00，晚 1 根」。`barsSinceQualified13` 与 `prev` 依赖同一次 13 事件的位置，因此随 `lastSignal` 一起整体偏移 1 根，是任务简报预告的差异的自然延伸，不是新问题。
- 两个周期均为 `state=OK`、`levels=OK`：结构性差异只影响这两个纯计数/时间戳字段，未改变 s9/s13 状态判定或 signal 等级计算。
- 价格字段（`risk9`/`setupClose`/`riskLevel`/`close13`/`tdst`）在报告 JSON 中保留有个位数到十位数量级的美元残差（例如 1h `riskLevel` TS 81974.4 vs local 82006.43），符合「价格残差单列」的预期,不计入结构一致性判定。

未发现新 bug；两处已知差异均可追溯到既有研究文档记录的行情源问题。

## 已知怪异点

当 `carry13` 保留、且反向出现新的主 Setup 时（例如黄金样本的 15m），信号 1 显示的是主 Setup 一侧的收盘价（`TradingSignal` 的 `risk.setupClose` 属于主序列一侧），而信号 2 没有价格。这与 AlphaBTC 的行为一致，属于有意保留，不作为缺陷修复。

### 2026-09-28 04:00 快照说明

- **countdownStep（已修复）：**13 在最新一根 bar 上合格时，TS 已经进入 setup 阶段（新 BUY setup 2），但 `countdownStep` 仍然报 13；13 发生在 43 根或 55 根之前时（1h）则报 0。`summary.py` 改为：setup 阶段中，若 prev 为合格 13 且 `barsAgo == 0`，`countdown_step` 取该 13 的计数。13 过去 1 至 42 根之间是否仍报 13 尚未观察到，由后续快照验证。AlphaBTC 的 carry13 在这种情形下本来就由 prev 的合格 13 成立，所以这项修改不改变 s9/s13。
- **回归夹具：**`tests/regime/fixtures/alphabtc-td9-2026-09-28T040023Z.json`。
- **全部快照回放**（本机，修复后）：三份快照 5 个周期的 s9/s13、置信度、risk 结构全部一致，Regime 3/3 一致。剩余的结构差异只有 15m 的 13 落点差 1 根，以及黄金样本中已知的 5m/15m 行情源差异。

### 2026-09-28 04:07 快照说明与对照脚本的取样时刻

- **TS 的最后一根会延伸：**04:07:54 抓取时，TS 的 5m 最新 bar 仍是 04:00（该 bar 应在 04:05 收盘），但 close 为 83274.4。Binance 在 04:05:25 至 04:05:35 之间正是 83274 左右，04:05:00 为 83250，04:07:54 为 83371。结论：TS 的数据在 04:05:3x 计算，当时它的 5m 行情还没有 04:05 这根，于是把实时价并入了 04:00 这根；AlphaBTC 缓存的数据比抓取时刻晚约 2.5 分钟。15m 的 close 同为 83274.4；1h、4h、1d 的 close 与 04:00 那份相同，说明各周期的计算时刻不同。
- **对照脚本改为按周期对齐取样时刻：**对每个周期，在抓取前 20 分钟内，取最后一个 Binance 秒线收盘价与 TS close 相差 ≤5 的秒，作为该周期的计算时刻；找不到时取最接近的一秒。形成中的 bar 由 `asOf` 到该时刻的秒线重建，不在收盘时间截断。可用 `--no-align` 退回统一时刻。报告中的 `replayed_at` 记录了每个周期实际使用的时刻。
- **修改后全部四份快照回放：**黄金样本自动对齐到 16:28:32（与手工取值相同），结果不变；03:50、04:00、04:07 三份除 15m 的 13 落点差 1 根外，全部结构字段、risk 结构字段、s9/s13、置信度和 Regime 一致。03:50 那份不再需要手工改取样时刻（15m 自动对齐到 03:49:37）。
- **countdownStep：**04:07 这份的 TS 最后一根仍是 13 所在的 bar，barsAgo 仍为 0，因此还没有观察到 13 之后 1 到 42 根的情形。

### 2026-09-28 04:16 快照说明

- **rounds 在反向 setup 段时的保留（已修复）：**5m 已翻为 SELL setup 2，但 TS 的 rounds 仍为 [BUY 9→13（04:00），SELL 2]；黄金样本的 15m 同为反向段，TS 却只列出当前段。两者的区别：5m 那个 13 的风险位（83088）仍然有效；15m 那个 SELL 13 的风险位在 09-27 08:00 已被突破（invalidated）。`summary.py` 改为：没有活动 Countdown 且当前段反向时，只有当链中不存在风险位仍有效的合格 13 才清空链。依据仅这两例，由后续快照验证。
- **setupClose 置空（已修复）：**5m 的 SELL 侧 S9（09-27 18:05）countdown 计到 12（中间两次 13 延期），之后被反向 Setup 完成取消。TS 给出了 risk9 和 risk9Ts，但 setupClose 为 null，AlphaBTC 页面的 5m「BUY 1」因此显示「——」。黄金样本 15m 的 S9 同样被反向 Setup 取消，但取消时 countdown 为 0，TS 仍给出 setupClose。`summary.py` 改为：S9 的 countdown 已开始计数后被取消时，setupClose 为 null；risk9 不变。依据仅这两例。
- **countdownStep：**13（04:00）之后第 3 根，TS 为 0，与「仅 barsAgo 0 时为 13」的实现一致；barsAgo 1、2 仍未直接观察到。
- **5m risk13Ts / riskLevel：**当前侧为 SELL，R13 是黄金样本中那个 SELL 13；两个行情源把它放在相差 28 根的位置（TS 1790507400，本地 1790515800），riskLevel 随之不同。属于已知的行情源差异。
- **回归夹具：**`tests/regime/fixtures/alphabtc-td9-2026-09-28T041636Z.json`，每个周期的最后一根按 `computed_at` 重建。

## 成功标准 2 结论（2026-09-28）

- 新快照 5 份（03:50、04:00、04:07、04:16、04:31 UTC）加黄金样本，共 6 份。04:14 那一份与 04:07 数据相同（AlphaBTC 未刷新），不计。
- 修复后逐份回放：Regime 6/6 一致；s9/s13 与两个信号的置信度 6×5 全部一致；risk 结构字段（side、risk9Ts、risk13Ts、provisional、setupRun、nextBarNeeds 方向）除 5m 的 risk13Ts 外全部一致。
- 残余差异全部可追溯到行情源，均已逐项写明：15m 那个 SELL 13 在 Binance 上晚 1 根（在 TS 导出行情上一致）；5m 那个 SELL 13 两边相差 28 根（影响 prev、barsSinceQualified13、risk13Ts、riskLevel）；5m 另一个 13 的风险位因极值 bar 选择不同差 92；其余价格残差 ≤65。
- 本轮对照中修复的实现差异：rounds 不列未完善的被压住同向 9；反向段仍保留风险位有效的 13 那一轮；13 合格当根 countdownStep 报 13；S9 的 countdown 开始计数后被取消则 setupClose 为 null。此外还修正了对照脚本的取样时刻。这些规则各只有 2 至 3 个样本支持，后续抓取继续验证。

## 永续合约行情核查（2026-09-28）

背景：test 环境（`1fab597`）已把市场页行情换成 Binance USDⓈ-M 永续。核查它是否更接近 TradingSignal。

- **数据来源：**本机无法直连 `fapi.binance.com`，本次只用 `data.binance.vision` 的公开日线归档（永续与现货），截至 2026-09-26；09-27、09-28 的归档尚未发布，所以 6 份快照还不能用永续重放。
- **TS 自己导出的 15m 行情（09-22 至 09-26，437 根）：**与现货 close 平均差 4.44（中位 3.60，最大 25.19）；与永续平均差 40.40（中位 40.00，最大 64.40）。两边都没有一根 OHLC 完全一致。
- **快照里引用的历史收盘价（4 个）：**TS 与现货差 3.4 至 9.9，与永续差 24.4 至 55.0。
- **同一时刻两种行情的计算结果（截至 09-27 00:00 的已收盘 bar）：**1h、4h、1d 的结构、risk 结构、s9/s13 和 Regime 完全相同；5m 和 15m 的 countdown 计数差 1，13 的落点不同（15m prev 53 根 vs 66 根，risk13Ts 相差 13 根）。
- **结论：**TS 的行情不是 Binance 永续；它比现货还偏离得多（永续与现货的基差约 40）。换成永续不会减少上文列出的行情源差异，反而会让价格残差扩大到约 40，并让 5m/15m 的 9/13 落点更常与 AlphaBTC 不同。TS 的实际来源仍未确认（价格一律一位小数，最接近 Binance 现货）。

## TradingSignal 行情源确认：Bybit 现货（2026-09-28）

- **证据：**
  - TradingSignal 首页 FAQ 写明加密数据来自 Binance、服务端不可达时切换到 Bybit。
  - 它的 `/api/klines` 返回的 BTC/USDT 1h K 线与 Bybit 现货 BTCUSDT 的 OHLCV 完全一致，成交量精确到 6 位小数；与 Bybit 永续不同。
  - 用户提供的 15m 导出 499 根已收盘 K 线与 Bybit 现货 499/499 完全一致，最大差 0。
- **本机取数：**`api.bybit.com` 在本机不可达，对照脚本改用 Bybit 官方的 `api.bybit.nl`（同一行情，已用上面的导出核对）。
- **重放结果：**对照脚本默认改为 Bybit（`--feed bybit`）。6 份快照 × 5 个周期全部一致，包括 12 个结构字段、risk 结构字段、s9/s13、信号置信度和 Regime；risk9、setupClose、riskLevel、close13、tdst 以及 nextBarNeeds 价格全部精确相等。上文所有"行情源差异"（15m 的 13 晚 1 根、5m 的 13 差 28 根、5m riskLevel 极值 bar）都消失，证实它们确实来自行情源。
- **形成中 bar 的局限：**Bybit 没有 1 秒 K 线，最后一根只能用 1 分钟 K 线重建到 TS 计算的那一分钟，并以 TS 的 close 收尾；那一分钟内的最高、最低价未知。多数快照的 5m/15m 标为 `forming-ambiguous`，但结果仍全部一致。
- **发布版 `1f4d9dc`（BTC 已切到 Bybit，但不含本轮 4 处规则修复）：**Regime、s9/s13、置信度全部一致；5m 在 5 份快照中 rounds 或 countdownStep 不一致，其中 2 份的 setupClose 应为空却给出了价格（页面「BUY 1」应显示「——」）。
- **测试夹具：**分支 `codex/demark-regime-bybit-parity` 把 6 份夹具换成 Bybit 行情，去掉全部行情源豁免，价格要求精确相等；去掉本轮修复后有 7 个用例失败。

### 2026-09-28 09:15 快照与发布后核对

- **发布：**`530ccd0` 已部署到 test（deployment `16wgacnuac9gz2pwbifohagl`）。用户 Chrome 已登录，BTC Market intelligence 的 5 个周期均为 Bybit 现货、最新、499 根；日内 反转阴跌、跨天 突破减弱，与 AlphaBTC 同刻一致。test 只用已收盘 K 线，计数比 AlphaBTC 慢一根（例如 1h 为 2/13，AlphaBTC 为 3/13）。
- **rounds（已修复）：**5m 回到 BUY setup 3，04:00 那个 BUY 13 的风险位 83088 已被跌破。TS 只列当前段 [BUY 3]，本地仍保留 [BUY 9→13, BUY 3]。规则改为：没有活动 Countdown 时，只要链里合格 13 的风险位都已失效就清空链，不论当前段同向还是反向；链里没有 13 时，仍只在反向段清空。
- **provisional（已修复）：**链清空后，原先"链首就是该 13"的判断会误报 true，而 TS 为 false。从全部 7 份快照看，TS 的规则是：最近的同向合格 13 之后，只要还没有新的同向 9 完成就不是 provisional（1h 在 05:00 新 9 完成后变为 true）。改为比较两者时间。
- **TS 内部时间差：**这份数据的 5m risk 块比 across 块晚一根计算：setupRun 为 4（across 为 setup 3），nextBarNeeds 价格 82773.6 正是 09:00 那根的收盘价。测试中对这一个周期跳过 setupRun 与 nextBarNeeds 价格。
- **结果：**修复后 7 份快照 × 5 个周期除上面这一项外全部一致；新夹具 `alphabtc-td9-2026-09-28T091511Z.json` 在 `530ccd0` 上失败、修复后通过。

### 2026-09-28 10:00 快照（`45735e2` 部署后）

- 用 test 当前部署的代码（`45735e2`）回放 10:00:42 抓取的 AlphaBTC 数据：5 个周期的结构、risk、s9/s13、置信度、Regime 全部一致，价格残差 0。
- test 页面（用户 Chrome）5 个周期均为"最新"，日内 反转阴跌、跨天 突破减弱，与 AlphaBTC 一致；计数按已收盘 K 线，比 AlphaBTC 晚一根。
