# BTC 永续状态（Perp states）Spec

日期：2026-10-17。状态：**v3，按用户授权自主定稿**。用户指令为"全部做完，不要等我说"，数据源已选定方案 C（完全免费）。经过两轮独立评审（opus 评 v1，sonnet 评 v2），修订记录见 §8。

本文是主 spec [btc-onchain-perp/SPEC.md](../btc-onchain-perp/SPEC.md) 中 P4 的独立 spec（§3.4、§7）。

## 依据

| 依据 | 用途 |
|---|---|
| [计算逻辑与用法](../../../research/alpha-dashboards-logic-2026-10-16.md) §2 | 原站 perp-squeeze 的规则 |
| [免费数据源核验](../../../research/perp-free-data-2026-10-17.md) | 下文简称"数据源核验"，核验日期 2026-10-17 |
| [数据源核验（原站）](../../../research/alpha-dashboards-data-sources-2026-10-16.md) §4.3 | Hyperliquid 只有当前快照，没有免费历史 |
| 主 spec §3.4（v1 规则）、§5（界面）、§6（验证） | 上位约束 |
| 原站源码 `.local/research-samples/alpha-dashboards-2026-10-16/perp-squeeze/raw/script_2_app.js`；笔记 `NOTES.md` | 规则细节 |
| 复算脚本 `.local/research-samples/alpha-dashboards-2026-10-16/perp-squeeze/tools/perp_parity.py` | 在原站样本上复现了页面：543 块排名，180 块显示；各状态计数为 LS 14、SS 8、LU 3、SU 8、NL 5、NS 6、spot 21、chop 115；表 1 的 Prob. 和 Max move 也一致 |
| 探测原始文件 `.local/research-samples/perp-free-data-2026-10-17/` | 已从会话临时目录保存 |

## 0. 决定汇总

| # | 决定 | 结论 | 理由 |
|---|---|---|---|
| P4-D1 | 交易所 | Binance USDⓈ-M 和 Bybit linear，BTCUSDT 永续。"All venues" 为两家之和。不做 Hyperliquid | Hyperliquid 没有免费历史；原站对它的清算本来也是估算 |
| P4-D2 | 共用价格 | Bybit 现货 BTCUSDT 5m 收盘价 | 原站用 Glassnode 现货价 `price_usd_close`；Market 页的 BTCUSDT 也固定用 Bybit 现货 |
| P4-D3 | 取数粒度 | 照原站，用 10m 桶：起点为 UTC 的 10 分钟整点，取值为该区间收盘时的状态 | 原站的网格 |
| P4-D4 | 清算 | 自建 WebSocket 采集器：Binance `btcusdt@forceOrder`、Bybit `allLiquidation.BTCUSDT`。覆盖按 §3.2 严格定义，未覆盖的时段不算 0 | 两家都没有免费的清算历史 |
| P4-D5 | Bybit 的 taker delta | 自建采集器 `publicTrade.BTCUSDT`，按 10m 桶累加买卖量，从开始采集起才有 | kline 没有 taker 拆分；逐笔归档每天约 75 MB |
| P4-D6 | 参考窗口与覆盖 | 价格和 OI 的阈值用参考窗口内的全部块（与原站相同）。清算阈值只用清算已覆盖的块。状态只对"所选交易所的所有采集输入都已覆盖"的块判定 | 清算只能从采集开始往后取。这是不让未覆盖时段冒充 0 的最小偏离；满 90 天后与原站口径相同 |
| P4-D7 | 起步门槛 | 覆盖块不足 7 天的块数（4h 为 42 块，8h 为 21 块）时不判定状态，显示 Collecting 横幅 | 样本太少时分位数没有意义 |
| P4-D8 | 新依赖 | `websockets==17.2`（PyPI 发布于 2026-10-03，有 cp314 manylinux wheel；核验于 2026-10-17）。只用同步客户端 | 标准库没有 WebSocket 客户端 |
| P4-D9 | 规则对照 | 原站的 Glassnode 样本**不入库**，只在本机对照。仓库里用合成数据测试规则；公开的 Binance 和 Bybit 探测数据可以作为 fixture 入库 | 那份 Glassnode 样本来自作者公司的订阅 |
| P4-D10 | All venues 的清算 | 两家相加。界面标明 Binance 部分是每秒一条的快照，只能当下限 | 原站的 aggregated 清算也是多家合计，口径同样不一致。数据源核验说两者"不能直接相加"，是指不能当成精确总量；我们只用于分位和比较，并如实标注 |
| P4-D11 | 权威采集端 | 以长期在线的 Coolify test 环境为准。本机开发的采集只用于开发，覆盖不完整 | 采集器需要连续运行 |

## 1. 目标与范围

**目标**：在 Flows → Perp states 中，照原站 perp-squeeze 的 v1 规则，用免费数据给出：
- Parameters；
- 表 1；
- 图 1–4，每张图都配三栏说明。

**成功标准**

| # | 标准 |
|---|---|
| 1 | `states.py` 在原站样本上复现页面（本地核验），12 种组合都与 `perp_parity.py` 一致：3 个交易所视图（all、binance、bybit）× 2 种块长 × 2 种 Show。其中 all/4h/30d 与页面的计数、Prob. 和 Max move 逐项相同 |
| 2 | 所有输入都标明来源和覆盖。未覆盖或缺失不当作 0（规则内按原站补 0 的地方都带 imputed 标记）；QC 失败要显示 |
| 3 | 90 天的 OI、价格、Binance delta 能回填。清算和 Bybit delta 从采集开始累积，界面写明已覆盖几天 |
| 4 | 清算方向在验收时用真实数据核对，并写入记录 |
| 5 | 在 1440px 和 390px 宽度下浏览器核验：无横向溢出，键盘可操作，控制台无报错 |

**不做**
- Hyperliquid；
- funding；
- 交易能力；
- 与原站 Glassnode 数值的直接对照（数据源不同）。

## 2. 架构

沿用 onchain 的模式：独立子包、独立 SQLite（WAL 模式）、独立 worker；读接口只读本地库。

**后端**（`services/analytics/src/wheelhouse_service/perps/`）

| 文件 | 职责 |
|---|---|
| `sources.py` | REST：Binance klines、openInterestHist、data.binance.vision metrics 日包；Bybit 现货 kline、open-interest |
| `collector.py` | 3 个 WebSocket 采集器：Binance forceOrder，Bybit allLiquidation，Bybit publicTrade |
| `store.py` + `migrations/001_perps.sql` | 存储 |
| `sync.py` | REST worker：回填、增量、派生 |
| `states.py` | 纯计算：网格、块、阈值、8 态、表 1、图数据 |
| `models.py`、`api.py` | `GET /api/wheelhouse/v1/perps/states`、`GET /api/wheelhouse/v1/perps/status` |

**存储**

| 表 | 字段 |
|---|---|
| `kline` | venue, t, close, volume, taker_buy, source。Binance perp 5m 存全部列；Bybit spot 5m 只用 close |
| `oi` | venue, t, oi, source。`t` 统一采用 hist 的时间戳约定（见 §3.1）；`source` 为 `hist`、`archive` 或 `bybit`；同一 `t` 上 hist 覆盖 archive |
| `trades_10m` | venue, t, buy, sell。Bybit taker 成交，单位 BTC |
| `trade_ids` | venue, id。只留最近 1 小时，用于去重 |
| `liquidations` | venue, conn, event_ts, raw_json, key。保存交易所原始字段，方向映射在派生时做；`conn` 是连接编号，用于 §3.2 的合并 |
| `coverage` | stream, conn, start, end, open。end 是最后一次存活证明的时刻 |
| `derived` | key（exchange, window）, payload, computed_at |
| `sync_state` | 各 host 最近一次成功时间、错误码、退避截止时间；清算方向核对结果 |

数据保留 120 天（包括 coverage），更早的删除；`trade_ids` 只留 1 小时。

**启停**
- `create_app` 新增参数：
  - `start_perps: bool`，控制 REST worker 和采集器，默认由设置 `WHEELHOUSE_PERPS`（默认 on）决定；
  - `perps_http: httpx.Client | None`，注入 REST 客户端，用法与 `brk_client` 相同。
  - `start_worker=False` 时一律不启动。
- `deploy/test/test_composition.py` 传 `start_perps=False`，并断言 REST worker 和采集器都没有启动；单元测试注入假的 REST 客户端和假的 WebSocket 连接工厂，不访问外网。

## 3. 计算规则（v1 = 原站口径）

### 3.1 10m 网格

桶 `t` 覆盖 `[t, t+10m)`，`t` 是 600 的整数倍。网格**补满**：每个桶都有一行，没有数据的写 null。块边界对齐 UTC epoch。

| 量 | 取法 | 说明 |
|---|---|---|
| price | Bybit 现货 5m kline 中开盘于 `t+5m` 那根的 close | |
| oi（Binance） | 读取 `oi.t = t + 600` 的值。`oi.t` 就是 hist 的时间戳；日包的行存为 `oi.t = create_time + 300`；同一 `oi.t` 上 hist 覆盖日包。hist 只保留约 30 天，更早的靠日包 | 文档称 hist 时间戳为周期终点；也有迹象表明 hist 落后一个周期（数据源核验，待验证 1）。影响为 5 分钟量级，约定固定 |
| oi（Bybit） | `/v5/market/open-interest` 5min 中时间戳 `t+10m` 的 `singleOpenInterest` | `openInterest` 是双边合计，不能用 |
| vd（Binance） | 开盘于 `t` 和 `t+5m` 的两根 5m kline 的 `2·takerBuy − volume` 之和 | 两根中缺任何一根，这个桶的 vd 为 null |
| vd（Bybit） | 采集到的、成交时刻 `T` 落在桶内的 taker 成交，买量减卖量 | 全部成交都计入（包括大宗成交 BT 和 RPI），按成交 id `i` 去重 |
| long_liq / short_liq | 采集到的、事件时刻落在桶内的清算数量（BTC）之和 | 时刻：Binance 用 `o.T`，Bybit 用 `T` |

**日包隔离**（评审在 2026-10-15 的日包中查到：0.0 共 8 行；陈旧重复值 24 行；另有 54 行看似正常，但与 hist 相差最多 2.9%。后者靠数值模式检测不出来）
- 在原始 5m 行上检测，先去重、排序，再映射到网格。
- 一天的文件中出现任何异常（`sum_open_interest ≤ 0`，或连续 ≥2 个相同值），就把这个文件**从第一处异常起到文件末尾**全部记为 null。连续 2 个相同值也算异常，因为 10-15 的陈旧值从 10:50、10:55 这一对开始；而 hist 在 788 个点中没有出现过相邻相等（v3.1 修订）。
- 被隔离的行计入 QC 的缺失。页头 QC 行另加一项：`archive OI days quarantined: n`。
- 2026-10-15 的回归 fixture 断言：`create_time ≥ 10:50` 的行（`oi.t ≥ 10:55`）为 null；只用日包构造网格时，10:50 起的桶为 null，10:40 的桶与 hist 一致。
- 验收时，在 hist 与日包重叠的 29 天上逐行比较，记录不一致率（相对误差 > 0.1% 的行占比）和隔离天数。如果隔离后仍有 > 1% 的行不一致，就把 Binance 的参考窗口改为只用 hist，并相应修改 spec。

**清算方向与数量**（入库时从原始字段映射，写入 `longs`、`qty`、`price` 三列，原始 JSON 一并保留；派生时在 SQL 中按桶汇总，不再逐条解析）
- Binance：`S=SELL` 为多头被强平，`S=BUY` 为空头被强平；数量取 `z`（累计已成交）。只记 `X=FILLED` 的事件，以免部分成交的推送重复累加。
- Bybit：按文档，`S=Buy` 为多头被强平，`S=Sell` 为空头被强平；数量取 `v`。
- 两条方向和 Bybit `v` 的单位都是待验证项，核对方法见 §6。如果结果相反，修改映射（`store.liquidation_fields`），再加一个按原始字段重写这三列的迁移（做法同迁移 002 的回填），历史数据随之重新派生。

**去重**（每个流有两条并行连接，见 §3.2）
- **清算**：
  - 每条事件按原始字段生成 key：Binance 为 `(o.T, o.S, o.z, o.ap)`，Bybit 为 `(T, S, v, p)`；
  - 入库时**不**去重，每条连接各存一份；
  - 派生时，对同一 key，取各连接出现次数的最大值。这样两条连接互为补充，而同一批里两笔 key 相同的真实清算也不会被误删。
- **成交**：Bybit 用成交 id `i`，入库时去重。

**All venues**：oi、vd、清算都是两家之和；任一家为 null 或未覆盖，All 也为 null 或未覆盖。

**数据边界**（评审 C1）
- 每个交易所视图的"最后收盘桶" `last` = 该视图所需各 REST 序列（price、各家 oi、Binance kline）**实际已入库的最后一个桶**中最早的那个。网格到此为止，不会因为某条序列还没发布而把它当成缺失。
- Bybit 现货 kline 和 Binance kline 中，`start + 5m > 取数时刻` 的未收盘 bar 不入库。
- 采集的序列不参与边界计算；它们只影响覆盖。

### 3.2 采集覆盖（评审 C2）

- **两条并行连接**：每个流保持两条连接，建立时间错开至少 1 分钟。流的覆盖取两条连接覆盖区间的并集，事件按上文合并。这样一次断线或换连接不会造成空洞；只有两条同时断开（例如服务重启）才会出现空洞。
- **覆盖区间**（每条连接）：
  - 起点：Bybit 为订阅确认；Binance 的路径式订阅没有确认，以握手完成为起点；
  - 终点：最后一次存活证明，再减去 2 秒，作为时钟误差的余量；
  - 存活证明：任何一帧数据，或应用层心跳的 pong。websockets 同步客户端自带的 keepalive 不向应用暴露 pong，所以每 20 秒手动调用 `ws.ping()`，并等待它的 pong 回复（超时 20 秒）；
  - Bybit 另外每 20 秒发一次 `{"op":"ping"}`。
- **写库**：采集到的事件先提交，再推进区间的 end。end 至少每 10 秒写一次库。服务启动时，把上次留下的未关闭区间（open）结束在它最后保存的 end。
- **桶的覆盖**：`[t, t+10m)` 完全落在该流覆盖区间的并集内，这个桶才算已覆盖。
- **换连接**：每条连接满 12 小时后重建，两条连接错开时间进行。断线后按指数退避加抖动重连（1s 起，最长 60s）。
- **事务**：采集器在内存中缓冲，每 1 秒批量提交一次。REST 回填按 1 天一个事务分块写入，避免长事务挡住采集器。

### 3.3 块与特征（原站）

- **block**：4h 或 8h，即 W = 24 或 48 个桶，从 UTC epoch 对齐的边界开始。
- **最后一块**：桶数 ≥ `W/2 + 1`（4h 为 13，8h 为 25）才保留并参与判定，标为 forming；不足的丢弃。这与原站的 `j − i < W/2` 相同。
- **特征**：
  - `dPx = (末桶价 ÷ 首桶价 − 1) × 100`，首尾任一为 null 或 ≤ 0 时记为 0，并标 `imputed.dPx`；
  - `dOI = 末桶 oi − 首桶 oi`，首尾任一为 null 时记为 0，并标 `imputed.dOI`；
  - `delta = Σ vd`、`lLiq = Σ long_liq`、`sLiq = Σ short_liq`：null 按 0 计（原站口径）；块内有 null 时标 `imputed.sums`。
- **覆盖**：
  - 块内任何桶的清算未覆盖，这块就是"清算未覆盖"；
  - 所选视图需要 Bybit vd 时（Bybit、All），块内任何桶的 Bybit vd 未覆盖，这块就是"delta 未覆盖"；
  - forming 块按已有的桶判断。
- **覆盖块**：上面两者都不成立的块。

### 3.4 阈值与判定

- **参考窗口**：起点为 `D 00:00 UTC − 90 天` 的块，到 `last` 所在的块为止（包括 forming 块）。D 是 `last` 的 UTC 日期，不是墙钟日期，所以 `states.py` 只依赖网格和 `last`。与原站"90 个完整 UTC 日 + 今天"相同。
- **分位数**：排序后取第 `floor(q·(n−1))` 个值，不插值；判定一律用 `≥`。
- **样本集**：
  - `T_oi = P75(|dOI|)`、`T_px = P75(|dPx|)`：参考窗口内的全部块；
  - `T_sLiq = P90(sLiq)`、`T_lLiq = P90(lLiq)`：参考窗口内**清算已覆盖**的块。
- **判定**：只判定覆盖块，按顺序取第一个命中的状态。

  ```text
  short squeeze : sLiq ≥ T_sLiq and dPx ≥  T_px and sLiq ≥ 3·lLiq
  long squeeze  : lLiq ≥ T_lLiq and dPx ≤ −T_px and lLiq ≥ 3·sLiq
  unwind        : dOI ≤ −T_oi → delta < 0 ? long unwind : short unwind   (delta = 0 → short unwind)
  new long      : dOI ≥  T_oi and dPx > 0 and delta > 0
  new short     : dOI ≥  T_oi and dPx < 0 and delta < 0
  spot-led      : |dPx| ≥ T_px and |dOI| < T_oi
  chop          : otherwise
  ```

- **起步门槛**：参考窗口内的覆盖块不足 P4-D7 的块数时，不判定任何状态。
  - 天数 = 覆盖块数 ÷ 每天块数（4h 为 6，8h 为 3），允许中间有空洞，显示到 1 位小数；
  - 按交易所视图和块长分别计算。
- **退化情形**：覆盖块少时，清算的 P90 可能为 0，此时价格大幅变动的块都会判为 squeeze（原站同样如此）。照原站保留，加单元测试；悬停信息中注明"liquidation threshold is 0"。

### 3.5 表 1、图与图例（原站 L427、L450–476）

- **表 1 的"在视图内"**：块的中点 `t0 + (t1 + 10m − t0)/2` 落在 `[from, last + 10m]` 内，其中 `from = max(第一个桶, last − show)`，`last` 是最后收盘桶的起点。
- **Prob.**：在视图内的**已判定**块中各状态的占比，用最大余数法取整，算法照原站：
  - `v = 100·c/n`（浮点），`f = floor(v)`，`rem = v − f`；
  - 剩余点数 `100 − Σf`，按 `rem` 降序**稳定排序**后依次补给 `rem > 0` 的状态；
  - 稳定排序的基础顺序为 TABLE_STATES：short squeeze、long squeeze、short unwind、long unwind、new long、new short、spot-led、chop。
- **表 1 副标题**：`n judged of m blocks in view · share of blocks, not a forecast`。
- **Max move / duration**：
  - 在视图内的已判定块中，相邻、下标连续且同状态的块合成一段；未覆盖块会把段截断；
  - 收益 = 首块首桶价 → 末块末桶价，任一价格为 null 或 ≤ 0 时跳过这一段；
  - 每个状态保留绝对值最大的一段，带正负号；并列时保留先出现的；
  - 时长 = 块数 × 块长。
- **图例 `k / n`**：块的名义中点 `t0 + 块长/2` 落在 `[from, last]` 内（与表 1 的规则略有不同，照原站）。
  - n 为这些块中已判定的块数；未覆盖块另写 `(+u uncovered)`；n 为 0 时显示 `—`；
  - 图例项可以点击，隐藏该状态；
  - 计数由前端根据载荷中的块计算，两种 Show 都可以算。
- **最新块标记**：照原站，标在表 1 中最后一块（forming 块也算）的状态那一行。最后一块未覆盖时，不标记任何一行，表 1 副标题注明 `latest block uncovered`。
- **块的 `t1`**：块内最后一个桶的起点，与上面的中点公式一致。
- **图 1、图 2**：价格线取块收盘值，即块内最后一个非 null 的价格，点画在块的最后一个桶上。
  - 图 1 叠加 squeeze 和 unwind 的阴影，图 2 叠加 build 和 spot-led 的阴影；
  - 未覆盖块用单独的斜线纹理，与 chop（不画阴影）区分开；
  - 跨视图左边界的块也画；
  - 不足半块的尾块画出价格，不判定。
- **图 3**：所选视图的 OI 块收盘值（块内最后一个非 null），以及价格块收盘值。
- **图 4**：
  - 每块的 delta 柱：块内非 null 值之和；全为 null 时不画；
  - 清算带：short liq 向上，long liq 向下。
  - 清算未覆盖的块不画清算带；delta 未覆盖的块不画 delta 柱；两者都加未覆盖标记。

### 3.6 QC（原站的规则，照样显示；与原站的差异已写明）

对每个交易所视图所需的每条 REST 序列，在参考窗口内检查：
- 网格步长 600 秒，按构造必然满足；
- 最大空洞 ≤ 1800 秒：连续 null 桶的个数 × 600 秒，网格末尾的空洞也计入；
- 缺失（null，包括被清洗的日包行）≤ 1%。

与原站的差异：
- 原站检查的是共享时间轴上的空洞，这里按每条序列检查；
- "forming 桶已被丢弃"和"regime spine current"两项不适用，不做。

不满足的项目显示在页头的 QC 行中，不隐藏。采集器的未覆盖不计入 QC，单独显示在覆盖说明中。

### 3.7 新鲜度与状态

新鲜度、采集器状态和 collecting 状态都在**处理请求时**按当前时刻计算；载荷里只存 `last`、`computed_at` 和各采集流的覆盖信息。

- **数据新鲜度**：按每个交易所视图的最后收盘桶终点 `last + 10m` 计算：
  - 距现在 ≤ 30 分钟为 fresh；
  - ≤ 2 小时为 delayed；
  - 更久为 stale；
  - 没有数据为 unavailable。
- **采集器状态**：最后一次存活证明在 60 秒内为 live，否则为 `down since <时刻>`。
- **原因码**：
  - `series_missing:<venue>:<series>`：参考窗口内该序列一个值都没有；
  - `rest_error:<host>:<code>`；
  - `collector_down:<stream>`；
  - `collecting:<days>`。
- **失败**：保留旧数据，状态随时间自然降级；日志只记来源、错误码和耗时。

### 3.8 REST 礼仪（评审 I9）

市场页已经从同一 IP 请求 `fapi.binance.com` 和 `api.bybit.com`，perps 不能让这个 IP 被封。
- 同一时刻只有一个请求在途；
- **按 host 分别退避**（`fapi.binance.com`、`data.binance.vision`、`api.bybit.com`）：
  - 截止时间 = `max(下表的值, Retry-After)`：

    | 状况 | 退避 |
    |---|---|
    | Binance 429 | 2 分钟 |
    | Binance 418 | 30 分钟 |
    | Binance 403 | 30 分钟 |
    | Bybit 403 | 10 分钟 |
    | Bybit 返回 200 但 `retCode` 为限流码（10006 等） | 10 分钟 |

  - 遇到上述情况，立即停止该 host 本轮剩下的请求；其他 host 照常；
  - 截止时间之后的第一个调度时刻再恢复；
- Bybit 其他非 0 的 `retCode` 记为错误码 `retcode:<n>`，不重试；
- 这些退避状态与市场页的 `sources.py` **不共享**。perps 的请求量很小，靠上面的规则约束自己；
- **增量**：每轮都重取每条序列的最后 3 条记录（与 onchain 的 `OVERLAP` 相同）。
- **调度**：每 10 分钟一轮，在每个 10 分钟整点后 5 分钟运行（HH:05、HH:15……），给 Binance hist 留出 2–4 分钟的发布延迟。
- **回填**：Binance OI 最近 29 天走 REST，更早的从日包取；停机超过 29 天时，也用日包补。

## 4. 接口与载荷

- **`GET /perps/states?exchange=all|binance|bybit&window=4h|8h`**
  - 返回预先算好的载荷：每个 (exchange, window) 一份，共 6 份；
  - 每份同时包含 Show = 7d 和 30d 两种表 1；
  - 内容包括：
    - 阈值 `T_*` 及各自的样本数；
    - 块列表：**只含与最近 30 天视图重叠的块**（4h 约 181 块），每块有 t0、t1、forming、已覆盖与否、state、各项特征、imputed 标记、价格和 OI 的块收盘值、delta 和清算的块合计；
      - delta 未覆盖的块的 `delta`、清算未覆盖的块的 `lliq` 和 `sliq` 是补出来的值（null 桶按 0 计，结果为 0 或部分和，由 `imputed.sums` 标出），不参与判定和阈值；画图等使用方一律取块合计 `delta_sum`、`lliq_sum`、`sliq_sum`；
    - 两种 Show 的表 1；
    - 不足半块的尾块：只含绘图字段；
    - QC 失败项、覆盖天数、`last`、`computed_at`、原因码。
  - 新鲜度在请求时计算（§3.7）。
  - 第一次派生之前，返回 `data_state = "unavailable"`，并附原因码 `not_derived`；本进程不运行 worker 和采集器时（`WHEELHOUSE_PERPS=0` 或 `start_worker=False`），这个原因码改为 `perps_disabled`，因为不会有派生。
  - 读接口不访问交易所。
- **`GET /perps/status`**：
  - 各来源的最近成功时间、错误码、退避截止时间；
  - 3 个采集器的状态和覆盖起点；
  - 方向核对的结果 `direction: pending | ok | inverted`，以及统计值（§6）。

## 5. 界面

照主 spec §5 中 Perp states 的定稿；mockup 见 `flows.html` 和 `mobile.html`。

- **页头行**：`Resolution 10m · Data through <last + 10m> UTC · Price Bybit spot · OI/flows Binance USDⓈ-M + Bybit linear (public) · liquidations collected since <日期>`。
- **覆盖说明**：一行写明清算和 Bybit 成交已覆盖多少天。
- **Collecting 横幅**：未达起步门槛时显示 `Collecting liquidations (and Bybit trades) · n of 7 days (target 90)`。此时隐藏表 1、图 1 和图 2，只画图 3 和图 4。
- **Binance 清算标注**：`Binance liquidations are a one-per-second snapshot (lower bound)`。
- **Parameters**：
  - Exchange：All venues / Binance / Bybit；
  - State window：4h / 8h；
  - Show：7d / 30d；
  - 三者写入 URL 参数 `px`、`pw`、`ps`。
- **悬停**：块的悬停信息中显示 imputed 标记、"uncovered"，以及清算阈值为 0 的提示。
- **方向未核对**：所选视图自己的核对不是 `ok` 时（Binance、Bybit 视图看各自交易所的结果，All venues 看合并的 `direction`），squeeze 状态的标签后加 `(direction unverified)`；视图所含交易所的结果为 `inverted` 时，另显示提示 `Liquidation sides look inverted on <venue>: squeeze labels may be swapped`。
- **前端轮询**：每 5 分钟一次。
- **三栏说明**：表 1 和图 1–4 都带。窄屏下三栏说明全部展开；表 1 只留 State、Prob.、Max move 三列，What it is 可以展开。
- **状态**：unavailable、stale、delayed、collecting、QC 警告、forming 块、未覆盖块、采集器 down。
- **替换现有横幅**：去掉 Perp states 原来的 "Not connected" 横幅，连同 `i18n.ts` 中 `flows.perpPending` 的 en 和 zh 文案，以及 `flows-panel.test.tsx` 和 `market-defaults.test.tsx` 中的对应断言。
- **ETH 和 MU**：显示 "Flows are BTC only"（已有）。

## 6. 验证

- **规则（本地）**：在原站样本上，用适配器把样本喂给 `states.py`，覆盖 12 种组合（all、binance、bybit 三个交易所视图 × 2 种块长 × 2 种 Show），计数、Max move 与 `perp_parity.py` 完全一致。`perp_parity.py` 本身不算 Prob.，所以由适配器按 §3.5 的浮点算法另算 Prob.，并在 all/4h/30d 上与页面的 4/8/4/2/3/3/12/64 对照。原站样本没有 null，所以缺失路径只能靠下面的合成数据测试。脚本和结果只写进验收记录，样本不入库。
- **单元测试（合成数据）**：
  - 块对齐；
  - 半块阈值：4h 下恰好 12 个桶时丢弃，13 个时保留；
  - 分位数；
  - 8 态的判定顺序和每个分支，包括 delta = 0 判为 short unwind；
  - 两侧清算都为 0；
  - 未覆盖块被排除，并截断 Max move 的段；
  - 7 天起步门槛；
  - Prob. 的取整与平局规则；
  - 表 1 与图例"在视图内"的规则不同；
  - imputed 标记；
  - QC 的末尾空洞。
- **数据层**：
  - 10m 网格的映射。用 2026-10-15 的 Binance hist 与日包作为回归 fixture：这是公开数据，取自 `.local/research-samples/perp-free-data-2026-10-17/`，入库；
  - 日包清洗：OI = 0.0，以及连续重复值；
  - 数据边界：hist 晚一条时，网格少一个桶，不出现 0；
  - 回填分页；
  - 429/418/403 时中止本轮并退避；
  - kline 未收盘的过滤；
  - 采集器：
    - 半开连接：只有 ping 没有 pong 时，区间结束在最后一次证明；
    - 崩溃恢复：未关闭的区间结束在最后保存的 end；
    - 12 小时换连接没有空洞，重复数据被去重；
  - 读接口不访问外网；
  - `start_worker=False` 和关闭采集器时都不启动。
- **前端**：
  - Zod 契约；
  - i18n 的 en 和 zh 键一致；
  - 所有状态的渲染；
  - URL 参数；
  - 窄屏下表 1 的列和展开。
- **契约**：运行 `make contract`。
- **依赖**：`websockets` 写入 `services/analytics/pyproject.toml` 和 `services/analytics/requirements.lock`；`perps/migrations/*.sql` 写入 package-data。
- **清算方向核对**：worker 每轮自动计算，结果在 `/perps/status`：
  - 样本：价格 10 分钟变动绝对值 ≥ 0.3%、且有清算的桶；
  - 指标：两家分别算，下跌桶中 `Σlong / (Σlong + Σshort)`；
  - 判定：每家至少 20 个下跌桶时，指标 > 0.6 为 `ok`，< 0.4 为 `inverted`，其余或样本不足为 `pending`；
  - Bybit `v` 的单位：同时检查 `v × p` 的量级（单笔名义金额应在 $10 到 $50M 之间），以及 `v` 的最小值是否等于最小下单量 0.001。

  结果写入验收记录。样本不足时写明"待生产采集后补核"，并在 test 环境上线后补核。

  方向核对不挡住状态的显示，但核对为 `ok` 之前，squeeze 标签带 `(direction unverified)`（§5）。如果结果是 `inverted`，修改映射并用迁移重写已存的三列后，历史会重新派生（§3.1）。
- **采集器资源与覆盖率**：
  - 观察 publicTrade 的 CPU 和每小时写入量；
  - 记录 Binance `forceOrder` 事件中 `X` 字段的分布，用来检验只记 `X=FILLED` 是否合适；
  - test 环境采集满 7 天后，记录覆盖块占比；4h 下低于 80% 时，重新评估覆盖规则。

  以上写入验收记录。
- **浏览器**：1440px 和 390px，与 mockup 对照。

## 7. 风险

- **Binance 清算流不是全量**：每秒最多推送一条，squeeze 会偏少。界面已标注为下限。
- **采集空洞**：部署和宕机会让覆盖块减少，状态出现间断，但不会出错。权威采集端是 test 环境（P4-D11）。
- **交易所接口变更**：Binance 在 2026-04 已改过 WebSocket 路由，使用 `wss://fstream.binance.com/market/ws`。
- **IP 被封**：会连带影响市场页，由 §3.8 的规则约束。
- **部署**：采集器常驻 Python 服务内，需要放行出站 WebSocket；发布流程另行处理。

## 8. 修订记录

**v1（2026-10-17）**：首版，数据源为方案 C。

**v2（2026-10-17）**：按独立评审（opus）修订。

| 评审意见 | 处理 |
|---|---|
| C1：数据边界由时钟决定，最新块的 dOI 会被记为 0 | §3.1 数据边界；§3.8 调度改为 HH:x5，并重取最后 3 条 |
| C2：覆盖没有定义 | §3.2 |
| C3：日包中有 0 值和重复值 | §3.1 日包清洗 |
| I1：表 1 和图例细则 | §3.5 |
| I2：未覆盖块看起来像 chop | §3.5 单独的纹理 |
| I3：补 0 不显示 | imputed 标记；QC 的差异写明 |
| I4：新鲜度和状态 | §3.7 |
| I5：载荷 | §4 |
| I6：All venues 清算相加 | P4-D10 |
| I7：清算存储与方向 | 存原始字段、去重，验收核对方向 |
| I8：窗口和块边界 | §3.3、§3.4 |
| I9：REST 被封 | §3.8 |
| I10：验收缺项 | §6 |
| I11：回归 fixture 会过期 | 已保存到 `.local`，入库为 fixture |
| M1–M11 | 采纳；Hyperliquid 的依据补上了引用 |

**v3.1（2026-10-17）**：计划评审（opus）在真实 fixture 上发现，"≥3 个相同值"漏掉了 10:50、10:55 这一对，改为 ≥2，并修正了回归断言的口径。

**v3（2026-10-17）**：按 v2 的复核（sonnet）修订。

| 评审意见 | 处理 |
|---|---|
| C-1：靠数值模式检测不出看似正常的错误值 | 改为整天隔离：从第一处异常起到文件末尾记为 null；加回归断言和 29 天的重叠比较 |
| I-1：新鲜度不能预先算 | 改为请求时计算（§3.7） |
| I-2：覆盖率太低 | 每个流两条并行连接，覆盖取并集；验收记录覆盖块占比 |
| I-3：去重会误删真实事件 | 按连接存储，派生时对同一 key 取各连接出现次数的最大值 |
| I-4：部署测试仍会启动 REST worker | 加 `start_perps` 和 `perps_http`；部署测试断言两者都不启动 |
| I-5：细则会被理解成不同的做法 | 写明 `oi.t` 约定、以 `last` 定义 D、图例的 n、最新块标记、Prob. 的浮点算法、适配器另算 Prob. |
| I-6：方向核对不完整 | 自动核对与判定标准、`v` 单位的检查、`(direction unverified)` 标签 |
| I-7：载荷太大 | 块列表只含最近 30 天视图；图例计数由前端算；首次派生前返回 unavailable |
| I-8：退避与 10 分钟节奏不匹配 | 按 host 分别退避，`max(表值, Retry-After)`，补上 Binance 403 和 Bybit retCode 的处理，写明不与市场页共享 |
| M-1–M-6 | 手动 ping 作为存活证明、Binance 以握手完成为起点、2 秒余量；null 价格；`X` 分布；P90 = 0 的退化情形；测试文件清单；`series_missing` 的触发条件、QC 空洞的定义、天数的小数位、轮询频率、未收盘的 Bybit kline、coverage 的清理 |
