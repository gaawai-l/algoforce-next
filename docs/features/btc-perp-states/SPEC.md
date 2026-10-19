# BTC 永续状态（Perp states）Spec

日期：2026-10-17；2026-10-19 起为 **v4（P6）**。状态：**v4**。v3 按用户授权自主定稿（用户指令为"全部做完，不要等我说"，数据源选定方案 C，完全免费），经过两轮独立评审（opus 评 v1，sonnet 评 v2）。

v4 把清算和买卖量改读 Coinalyze，并加入 Hyperliquid 视图：见 §7 之后的 "v4（P6）" 一节。被替代的条目在原章节首行有提示，其余仍是 v3.2 的原文。修订记录见 §8。

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
| [方案：改用 Coinalyze](PROPOSAL-COINALYZE.md) v3.1 | v4 的依据，含 2026-10-19 的 V1 实测 |

## 0. 决定汇总

> v4 改写了 P4-D1、D4、D5、D7、D10、D11：见 §7 之后 v4（P6）一节的 §0。

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

> v4 改了成功标准 #1（16 种组合）和 #3，"不做"中删去 Hyperliquid：见 v4 一节的 §1。

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

> v4 在文件表加了 `coinalyze.py`、`grid.py`，存储表加了 `cz_series`，并加了采集器开关：见 v4 一节的 §2。

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

数据保留 125 天（包括 coverage），更早的删除；`trade_ids` 只留 1 小时。REST 回填 121 天（`start` 为 121 天前），不随规则开关变化（P5-R9）。

**启停**
- `create_app` 新增参数：
  - `start_perps: bool`，控制 REST worker 和采集器，默认由设置 `WHEELHOUSE_PERPS`（默认 on）决定；
  - `perps_http: httpx.Client | None`，注入 REST 客户端，用法与 `brk_client` 相同。
  - `start_worker=False` 时一律不启动。
- `deploy/test/test_composition.py` 传 `start_perps=False`，并断言 REST worker 和采集器都没有启动；单元测试注入假的 REST 客户端和假的 WebSocket 连接工厂，不访问外网。

## 3. 计算规则（v1 = 原站口径）

### 3.1 10m 网格

> v4 改了清算和 Bybit 买卖差的来源，OKX 并入 All，另有 Hyperliquid：取值表见 v4 一节的 §3.1，网格放置见 §3.3。其余仍有效。

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

> v4：采集器默认关闭，只用于对照，不参与网格；本节只描述采集器本身。Coinalyze 的取数见 v4 一节的 §3.2。

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

> v4 改了"覆盖"的判定：见 v4 一节的 §3.3。

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

> v4 另加了 Coinalyze OI 的按窗口检查：见 v4 一节的 §3.3。

对每个交易所视图所需的每条 REST 序列，在参考窗口内检查：
- 网格步长 600 秒，按构造必然满足；
- 最大空洞 ≤ 1800 秒：连续 null 桶的个数 × 600 秒，网格末尾的空洞也计入；
- 缺失（null，包括被清洗的日包行）≤ 1%。

与原站的差异：
- 原站检查的是共享时间轴上的空洞，这里按每条序列检查；
- "forming 桶已被丢弃"和"regime spine current"两项不适用，不做。

不满足的项目显示在页头的 QC 行中，不隐藏。采集器的未覆盖不计入 QC，单独显示在覆盖说明中。

### 3.7 新鲜度与状态

> v4 去掉了 `collector_down` 和 `collectors[]`，原因码加了 `coinalyze_units`：见 v4 一节的 §3.7。

新鲜度和采集器状态在**处理请求时**按当前时刻计算。collecting 状态（Collecting 横幅、原因码 `collecting:<days>`）和视图的 `covered_days` 则来自载荷：它们在派生时按当时的覆盖算出，随每轮派生更新，不在请求时重算。覆盖说明里各采集流的天数（`collectors[].covered_days`）按请求时刻从覆盖记录计算。

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
  - `collecting:<days>`；
  - 没有载荷时：`not_derived`，或本进程不运行 perps 时的 `perps_disabled`（§4）。
- **失败**：保留旧数据，状态随时间自然降级；日志只记来源、错误码和耗时。

### 3.8 REST 礼仪（评审 I9）

> v4 加了 `api.coinalyze.net` 的退避和每进程每分钟 20 次的限速：见 v4 一节的 §3.8。

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

> v4：载荷改为 8 份，status 增加 `markets` 和新形状的 `direction_check`：见 v4 一节的 §4。

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

> v4 改了页头、来源行、Hyperliquid 标注、Exchange 选项和 Collecting 横幅：见 v4 一节的 §5。

照主 spec §5 中 Perp states 的定稿；mockup 见 `flows.html` 和 `mobile.html`。

- **页头行**：`Resolution 10m · Data through <last + 10m> UTC · Price Bybit spot · OI/flows Binance USDⓈ-M + Bybit linear (public) · liquidations collected since <日期>`。
- **覆盖说明**：一行写明清算和 Bybit 成交已覆盖多少天。
- **Collecting 横幅**：未达起步门槛时显示 `Collecting liquidations (and Bybit trades) · n of 7 days (target 90)`。此时隐藏表 1、图 1 和图 2，只画图 3 和图 4。横幅和其中的天数取自载荷（派生时算出，§3.7）。
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

> v4：规则对照扩到 16 种组合，方向核对改按窗口：见 v4 一节的 §6。

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

> v4 补充了风险：见 v4 一节的 §7。

- **Binance 清算流不是全量**：每秒最多推送一条，squeeze 会偏少。界面已标注为下限。
- **采集空洞**：部署和宕机会让覆盖块减少，状态出现间断，但不会出错。权威采集端是 test 环境（P4-D11）。
- **交易所接口变更**：Binance 在 2026-04 已改过 WebSocket 路由，使用 `wss://fstream.binance.com/market/ws`。
- **IP 被封**：会连带影响市场页，由 §3.8 的规则约束。
- **部署**：采集器常驻 Python 服务内，需要放行出站 WebSocket；发布流程另行处理。

## v4（P6）：清算与买卖量改用 Coinalyze

日期：2026-10-19。依据 [PROPOSAL-COINALYZE](PROPOSAL-COINALYZE.md) v3.1 和 [PLAN-P6](PLAN-P6.md)；代码范围是分支 `claude/coinalyze` 的 `f0f9d0c..25e6329`，核验记录见 [P6-VERIFICATION](P6-VERIFICATION.md)。

本节只写与 v3.2 不同的部分，其余仍然有效。小节标题里的 § 是 v3.2 的章节，被替代的条目在原章节首行有提示。本节描述的是代码实际做的事；与方案不同之处在小节里直接写明。

**要点**
- 清算和 Bybit 的买卖差不再自采，改读 Coinalyze 免费 API 的历史，首轮就有约 90 天；
- 加入 Hyperliquid 视图（清算为估算），All venues 扩为 Binance + Bybit + OKX；
- WebSocket 采集器默认关闭，只在对照时打开，不再参与网格；
- `states.py` 的判定规则不变，只给 `Grid` 加了两个 QC 字段。

### §0 决定汇总（改写 P4-D1、D4、D5、D7、D10、D11）

| # | v4 的决定 | 理由 |
|---|---|---|
| P4-D1 | 交易所：Binance USDⓈ-M、Bybit linear、OKX 三家的 BTCUSDT 永续，以及 Hyperliquid 的 BTC 永续。视图为 All venues（Binance + Bybit + OKX）、Binance、Bybit、Hyperliquid。不含币本位合约 | 用户 2026-10-19 的决定；Coinalyze 免费提供这四家 |
| P4-D4 | 清算：Coinalyze 的 Binance、Bybit、OKX 三家 `liquidation-history`，单位 BTC，`l` 为多头被强平，`s` 为空头被强平。Hyperliquid 没有清算数据，按 All 的清算估算（见下文 §3.3 的 HL 估算）。未覆盖的时段仍不算 0 | V1 实测：5min 桶与自采逐桶相等；多头占比的方向正确 |
| P4-D5 | 买卖差：Binance 沿用交易所 K 线（不变）；Bybit、OKX、Hyperliquid 取 Coinalyze `ohlcv-history`，`2·bv − v`（`bv` 为主动买量，`v` 为总量） | Bybit 的 `bv`、`v` 与自采 10m 买量、总量逐桶相等 |
| P4-D7 | 起步门槛的块数不变（4h 为 42 块，8h 为 21 块）。横幅文案改为 `Liquidation history too short · n of 7 days (target 90)`；缺 key 或 key 无效时不显示这个横幅，改显示 key 的提示 | 历史由 Coinalyze 回填，不再是"正在采集" |
| P4-D10 | All venues 的清算：三家相加。Coinalyze 的 Binance 清算与自采的 forceOrder 完全相同，仍是每秒一条的快照，界面继续标注为下限 | V1 实测 #7 |
| P4-D11 | 不再有"权威采集端"。清算历史来自 Coinalyze，重新部署不会留下清算空洞；采集器默认关闭，仅用于对照 | 采集器退出网格 |

P4-D2、D3、D6、D8、D9 不变。D6 中"采集输入已覆盖"的含义见下文 §3.3。

### §1 目标与范围

- **成功标准 #1**：`states.py` 在原站样本上复现页面，**16 种组合**都与 `perp_parity.py` 一致：4 个交易所视图（all、binance、bybit、hyperliquid）× 2 种块长 × 2 种 Show。all/4h/30d 仍与页面的计数、Prob. 和 Max move 逐项相同。Hyperliquid 的清算在样本里没有，对照时与 `perp_parity.py` 一样用 All 的清算估算，调用的是 `grid.estimate_liquidations`。
- **成功标准 #3**：价格、OI、清算和买卖差都能回填约 90 天（Coinalyze 的 4hour 一次最多约 334 天，回填 121 天）。界面写明清算已覆盖几天。
- **"不做"**：删去 Hyperliquid。其余不变：funding、交易能力、与原站 Glassnode 数值的直接对照。

### §2 架构

**后端文件**（在 v3.2 的表上增加）

| 文件 | 职责 |
|---|---|
| `coinalyze.py` | Coinalyze 客户端：4 个 symbol、`liq` / `ohlcv` / `oi` 三类历史（4hour 与 5min）、`/future-markets` 的单位核对 |
| `grid.py` | 把存储的序列折成 10m 网格：REST 序列逐桶，Coinalyze 序列逐窗口放置，Hyperliquid 估算（§3.3） |
| `sources.py` | 增加 `PerpsRest.coinalyze`（key 只放在这一个请求的 `api_key` 头里）、`api.coinalyze.net` 的退避、浮点 `Retry-After` |
| `collector.py` | 仍在，默认不启动，网格不读它写的表 |
| `migrations/003_coinalyze.sql` | 新表 `cz_series`；删除旧形状的 `direction_check` |

**存储**（在 v3.2 的表上增加）

| 表 | 字段 |
|---|---|
| `cz_series` | venue, kind, step, t, a, b, filled。`kind` 为 `liq`、`ohlcv`、`oi`；`step` 为 300（5min）或 14400（4hour）；`t` 是区间起点。`liq` 的 a、b 是多头、空头被强平；`ohlcv` 的 a、b 是总量、主动买量；`oi` 的 a、b 是区间起点和终点的 OI；单位都是 BTC。`filled = 1` 表示清算区间 Coinalyze 没有返回、补成 0 |
| `sync_state` | 另存 `cz_markets`（上次的单位核对）、`cz_markets_at`、`cz_4h:<kind>`（该类 4hour 上次回填的起点）；`direction_check` 改为新形状（见 §4） |

`liquidations`、`coverage`、`trades_10m` 三张表保留，只有采集器写。保留期：`cz_series` 的 4hour 为 125 天，5min 为 1 天。

**启停**
- `WHEELHOUSE_PERPS`（默认 on）仍是总开关，控制 REST worker。
- `WHEELHOUSE_PERPS_COLLECTORS`（默认 off，取值 1/0、true/false、on/off）控制采集器。**采集器只在 worker 运行时才可能启动**：`WHEELHOUSE_PERPS=off` 或 `start_worker=False` 时，即使这个开关是 on，也不启动。
- `create_app` 新增参数 `perps_collectors: bool | None`（默认取设置）和 `coinalyze_key: str | None`（默认取设置）；`create_router` 对应 `start_collectors=False` 和 `coinalyze_key=None`。
- `WHEELHOUSE_COINALYZE_KEY`：环境变量只要存在就以它为准，空串表示缺失；不存在时，只从仓库根目录 `.env` 读这一个键，整个 `.env` 不导出。`Settings` 里这个字段不进 `repr`。
- `deploy/test/test_composition.py` 仍断言 worker 和采集器都没有启动。两处测试都把 key 置为空串，并让 `.env` 指向不存在的文件，不读真实的 `.env`：`services/analytics/tests/conftest.py` 的 autouse fixture，以及这个部署测试自己（它在 `services/analytics/tests` 之外，conftest 管不到，`create_app` 仍会调用 `Settings.from_env()`）。

### §3.1 取值表

| 量 | Binance 视图 | Bybit 视图 | OKX（只进 All） | Hyperliquid 视图 |
|---|---|---|---|---|
| price | Bybit 现货 5m（不变，各视图共用） | ← | ← | ← |
| oi | 交易所 REST（不变） | 交易所 REST，单边（不变） | Coinalyze `oi`，取 `convert_to_usd=false` | Coinalyze `oi` |
| vd | 交易所 REST K 线（不变） | Coinalyze `ohlcv`：`2·bv − v` | 同左 | 同左 |
| 清算 | Coinalyze `liq` | Coinalyze `liq` | Coinalyze `liq` | 估算（§3.3） |

- Coinalyze 的 symbol：Binance `BTCUSDT_PERP.A`，Bybit `BTCUSDT.6`，OKX `BTCUSDT_PERP.3`，Hyperliquid `BTC.H`。
- 每类数据一次请求带上该类所有 symbol：`liq` 取 Binance、Bybit、OKX；`ohlcv` 取 Bybit、OKX、Hyperliquid；`oi` 取 OKX、Hyperliquid。`liq` 和 `oi` 加 `convert_to_usd=false`，使单位是 BTC。
- Bybit 的 OI 继续用交易所 REST 的单边值，不用 Coinalyze 的双边值。
- **All venues** = Binance + Bybit + OKX，oi、vd、清算都是三家之和；任一家为 null 或未覆盖，All 也为 null 或未覆盖（P4 规则不变）。
- **Hyperliquid 视图**：price、oi、vd 取它自己的；清算按 §3.3 的 HL 估算。它依赖 All 的 OI，所以数据边界 `last` 取 Bybit 现货、Binance OI、Bybit OI 三者最后桶中最早的那个（不需要 Binance K 线）。

### §3.2 取数（Coinalyze）；采集器只用于对照

采集器的覆盖规则（v3.2 §3.2）只描述采集器本身。它默认关闭，开启后只写 `liquidations`、`coverage`、`trades_10m`，状态只出现在 `/perps/status`，不参与网格。

Coinalyze 随 REST worker 的每一轮（HH:05、HH:15……）取数，在 Binance 和 Bybit 的 REST 之后：
- **4hour**：
  - **回填**：某类从未取过、记录的回填起点晚于网格起点、或该类有一家一行都没有时，从网格起点（121 个 UTC 日之前）取一次，不分页。
  - **重取**：最新一个已收盘窗口收盘后的 1 小时内，每轮都重取最近 3 个窗口（刚收盘的值可能还没聚合完整）；某家的最新一行落后于最新已收盘窗口时，也同样重取。起点不早于网格起点。
  - 其余轮次不取 4hour。（"落后时重取"是代码比方案多出的一条：Coinalyze 暂时没返回某家的窗口时，下一轮自动补。）
- **5min**：每轮取"上一个 4h 窗口的起点"到现在，最多 96 个点；只保留 1 天。
- **只存已收盘的点**：`t + 区间长 ≤ 取数时刻`。取数时刻在发请求**之前**取，请求途中收盘的 bar 当轮既不存，也不补 0，下一轮再取。
- **补 0**：只对清算。请求范围内、已收盘、Coinalyze 没有返回的区间，存成 `(0, 0)` 并标 `filled = 1`。整个 symbol 不在回复里时也照样补 0：Coinalyze 会省略这段时间没有清算的品种，而我们只请求已知有清算数据的三家。OHLCV 和 OI 不补，缺失就是缺失。
- **请求量**：按 symbol 计费。5min 每轮 8 次（清算 3、OHLCV 3、OI 2）；4hour 只在上面几种情形里取，每轮 8 次；单位核对每天 1 次。
- **限速自律**：每个进程每分钟最多 20 次计费调用，按 60 秒滑动窗口累计。不够时就等，worker 停机时立即放弃这一轮。同一个 key 因此最多两个进程（本机和 test）同时运行。
- **单位核对**：每天读一次 `/future-markets`（在一轮的各类历史都取完之后）。要求 4 个 symbol 都在列表里、`oi_lq_vol_denominated_in = BASE_ASSET`；用到买卖量的 Bybit、OKX、Hyperliquid 还要 `has_buy_sell_data = true`。不符合的交易所，它取自 Coinalyze 的列整体不用，按缺失处理（Binance 为清算，Bybit 为清算和买卖差，OKX 为清算、买卖差和 OI，Hyperliquid 为 OI 和买卖差，它的清算估算也随 OI 缺失；Binance、Bybit 的 REST OI 和 Binance 的 REST 买卖差不受影响），相关视图带原因码 `coinalyze_units:<venue>`。读取失败时沿用上次的结果；从未读到时，照常使用数据。

### §3.3 放进 10m 网格（替代 v3.2 的覆盖规则）

不给 `states.py` 加窗口值，也不改块的计算。Coinalyze 的 4hour 值放进窗口的**最后一个桶**，块和阈值只看块合计、块首尾的 OI，规则代码不用改。实测 48 个 5min 之和与 4hour 逐位相等，所以两种来源可以混用。

**放置规则**（窗口 `w` 是 14400 秒的整数倍，从网格起点算起）：
1. **已收盘、4hour 已入库、且窗口最后一个桶 ≤ `last` 的窗口**：
   - 清算、买卖差：整窗的值放在窗口的最后一个桶，其余 23 个桶记 0.0，全部算已覆盖；
   - OI：窗口第一个桶放 `o`（起点的 OI），最后一个桶放 `c`（终点的 OI），中间的桶为 null。
2. **其他窗口**（未收盘的、4hour 没取到的、或网格还没走到窗口末尾的）逐桶用 5min：
   - 一个 10m 桶等于两个已收盘的 5min 点之和；
   - OI 取后一个 5min 点的 `c`，即 `t + 10m` 时刻的 OI，与 REST 口径相同；
   - 缺任何一个点，该桶的清算、买卖差未覆盖，OI 为 null。

**覆盖与缺失**
- 清算和买卖差：已放置的桶为已覆盖，`filled` 的 0 也算已覆盖；没有行就是没取到，未覆盖。OHLCV、OI 缺失一律为 null，不补 0。
- 块的"清算未覆盖"、"delta 未覆盖"沿用 v3.2 §3.3 的定义。Binance 视图的 delta 来自 REST，不存在"未覆盖"；Bybit、All、Hyperliquid 视图的 delta 来自 Coinalyze，缺失时记未覆盖。
- **断档规则**（清算，同一交易所）：连续 ≥2 个 `filled` 的 4h 窗口，全部记为未覆盖，也不再拿 5min 补。读取时从网格起点前一个窗口开始，使起点那一窗也能判断。最新一个 `filled` 窗口在下一窗也被补 0 之前先显示为 0，之后才翻成未覆盖。依据 V1：Binance 在 2026-04-23 20:00 到 04-24 08:00 连续 4 个窗口没有清算点，不可能是真的零清算。这一段不在 121 天的网格内，所以规则还没有在真实数据上触发过，由单元测试覆盖。买卖差没有这条规则。
- **已接受的风险**：5min 层面 Coinalyze 的短时断档识别不出来，会显示为没有清算。

**合成视图（All、Hyperliquid）的规则**：All 的每个桶是逐桶的 REST 值与整窗放置的 Coinalyze 值相加。REST 值在窗口末桶缺失时，会出两种错：整窗的值被丢掉，或块内最后一个非空的 OI 退回 4 小时前。所以凡是有一家整窗放置的窗口：
- 买卖差、清算：合成值在窗口末桶为 null 时，整窗都记为未覆盖；
- OI：合成值在窗口末桶为 null 时，整窗的合成 OI 都记为 null；首桶为 null 不触发，它只让该块的 dOI 记为估算。

8h 块的后一窗因此为 null 时，块内最后一个非空的 OI 会退到前一窗的末桶，即 4 小时前；这与 P4 中 REST 序列连续缺失时相同，QC 会报缺失。

**Hyperliquid 的清算估算**（`grid.estimate_liquidations`，逐桶）：
- 估算值 = All 的清算 × HL 的 OI ÷ All 的 OI，多头、空头两侧乘同一个比值；
- All 的清算未覆盖的桶，估算也未覆盖；All 两侧都为 0 的桶，估算为 0；其余的桶，HL 或 All 的 OI 缺失或 ≤ 0 时为未覆盖，不当作 0；
- All 的 OI 不含 HL，所以这个比值是"HL 的 OI 相对 All 的 OI"，不是严格意义上的占比。原站公式的分子分母也是这样取的，界面文案照此写；
- 估算会让 squeeze 标签基本跟着 All 走，原站也是如此。

**与 P4 逐桶取值相比的差别**
- **整窗只用 4hour**：已收盘、4hour 已入库的窗口一律用 4hour，即使也有 5min；5min 只在 4hour 缺失时才用。
- **清算在桶内的分布不再真实**：整窗的值全在末桶。所以一切只看块合计；方向核对改为按窗口（见 §6）。
- **块首的 OI 早 10 分钟**：OKX、Hyperliquid 只有 4hour 的窗口，块首桶放的是 `o`，即窗口起点的 OI，而 REST 读的是 `t0 + 10m`。All 的 dOI 中，OKX 的起点因此是 `t0`，Binance、Bybit 的起点是 `t0 + 10m`。
- **HL 的估算按窗口末的 OI 占比**：原站逐桶乘各自的占比；整窗放置的窗口，值在末桶，只能整窗乘窗口末的占比。
- **数值不再与原站逐数相同**：数据源换了，阈值和状态计数只做定性对照；规则层面的一致由 16 种组合的对照证明。

**QC**：v3.2 §3.6 的检查不变，另加 Coinalyze 的 OI（OKX、Hyperliquid）按窗口检查：参考窗口内已收盘的窗口，首桶或末桶的 OI 为 null 就算缺失；缺失的窗口超过 1% 时报 `missing:<venue>:oi`，一个窗口都不全时报 `series_missing:<venue>:oi`。Coinalyze 的清算和买卖差缺口属于"未覆盖"，不进 QC。

**Grid 的改动**：`states.py` 只给 `Grid` 加了 `window_qc` 和 `window_missing` 两个字段，`_qc` 把它们并入结果；判定、阈值、表 1 的代码没有改。

### §3.7 新鲜度与状态

- **去掉** `collector_down:<stream>` 原因码和视图里的 `collectors[]`；采集器状态只留在 `/perps/status`。
- **原因码**，按载荷中的顺序：
  1. `series_missing:<venue>:<series>`，series 现在还有 `okx:oi`、`hyperliquid:oi`；
  2. `coinalyze_units:<venue>`（venue 为 binance、bybit、okx、hyperliquid）：该交易所的单位核对未通过，数据已停用。只出现在用到该交易所的视图里：All 为前三家，Binance、Bybit 各自一家，Hyperliquid 为四家；
  3. `rest_error:<host>:<code>`，host 现在可以是 `api.coinalyze.net`，code 与其他 host 相同（`429`、`403`、`network`、`bad_response`、`backoff` 等），Coinalyze 另有 `key_missing`（没配 key，不发请求）和 `401`（key 无效）；
  4. `collecting:<days>`；
  5. 没有载荷时：`not_derived`，或 `perps_disabled`。
- **各视图看的 host**（`VIEW_HOSTS`，只有这些 host 的错误才进该视图的 `rest_error`）：

  | 视图 | host |
  |---|---|
  | all、binance、hyperliquid | `fapi.binance.com`、`data.binance.vision`、`api.bybit.com`、`api.coinalyze.net` |
  | bybit | `api.bybit.com`、`api.coinalyze.net` |

- **缺 key 或 key 无效时**：
  - 不可用：表 1、图 1、图 2；图 4 的清算带；Bybit、All、Hyperliquid 的买卖差柱；All 和 Hyperliquid 视图的 OI（含 OKX、Hyperliquid 的部分），这两个视图的图 3 为空，并报 `series_missing`；
  - 照常显示：价格；Binance、Bybit 两个视图的 OI；Binance 视图的买卖差。
- 新鲜度、`collecting` 与 `covered_days` 的来源不变（v3.2 §3.7）。

### §3.8 REST 礼仪（加入 Coinalyze）

- 新增 host `api.coinalyze.net`，退避状态与其他 host 互不影响：

  | 状况 | 退避 |
  |---|---|
  | Coinalyze 429 | max(60 秒, `Retry-After`) |
  | Coinalyze 403（Cloudflare） | 10 分钟 |
  | Coinalyze 401 | **不退避**，本轮放弃，下一轮再试 |
  | 缺 key | 不发请求，记 `key_missing` |

- `Retry-After` 按浮点秒数解析（Coinalyze 返回 `28.723` 这样的值），非有限值忽略，也可以是 HTTP 日期；最长不超过 3 天。
- 401 不把退避存进库：换了 key 或新 key 生效后，下一轮（最多 10 分钟）就能恢复，重启后也不会被锁住。
- 一个 host 在一轮里失败，或已在退避，本轮不再请求它；其他 host 照常。
- **配额**：免费 key 每分钟 40 次，一次请求里每个 symbol 各算一次。每个进程限在每分钟 20 次以内（§3.2），所以同一个 key 最多两个进程同时运行。
- key 只放在 Coinalyze 请求的 `api_key` 头里，不进共用 httpx client 的默认头，不进 URL，不进日志、`repr` 和异常信息。

### §4 接口与载荷

- **`GET /perps/states?exchange=all|binance|bybit|hyperliquid&window=4h|8h`**：每个 (exchange, window) 一份，共 **8 份**。内容同 v3.2，去掉了 `collectors` 字段。
- **`GET /perps/status`**：
  - `hosts`：各 host 的最近成功时间、错误码、退避截止时间，现在包括 `api.coinalyze.net`；
  - `collectors`：3 个采集器的状态和覆盖，仅供对照；采集器没有运行时，`problems` 为空；
  - `markets`：Coinalyze 单位核对的结果，每个 symbol 一项 `{venue, symbol, denominated, buy_sell, ok}`；`venue` 为 binance、bybit、okx、hyperliquid；symbol 不在列表里时 `denominated`、`buy_sell` 为 null、`ok` 为 false；还没核对过时为空数组；
  - `direction_check`：`{binance, bybit, okx}`，每项 `{verdict: ok | inverted | pending, samples, down, long_share}`；第一轮之前为 null。旧的 `bybit_qty` 去掉了；
  - `direction`：三家的合并结论，三家都是 `ok` 才是 `ok`，任一家 `inverted` 则 `inverted`，其余为 `pending`。

### §5 界面

- **页头**共三行：
  - `Resolution 10m · Data through <last + 10m> UTC · Price Bybit spot · OI Binance and Bybit (public), OKX and Hyperliquid (Coinalyze)`；
  - **来源行**：`Liquidations and buy/sell volume (except Binance's): Coinalyze`，Coinalyze 链接到 <https://coinalyze.net>；
  - `Liquidation history: n d covered in the last 90`，n 取自载荷的 `covered_days`，一位小数；没有载荷时不显示。
- **Binance 清算标注**不变，Bybit 视图以外都显示。
- **Hyperliquid 标注**：视图下加一行 `Hyperliquid liquidations are estimated: All venues' liquidations scaled by Hyperliquid's OI relative to theirs`；图 4 的清算带，以及悬停中的 Short liq. / Long liq.，都写 `(estimated)`。
- **Parameters**：Exchange 选项为 All venues / Binance / Bybit / Hyperliquid，与原站相同；URL 参数 `px` 取值 `all`、`binance`、`bybit`、`hyperliquid`。
- **Collecting 横幅**：`Liquidation history too short · n of 7 days (target 90)`。缺 key 或 key 无效时隐藏它，改显示 key 的提示：`Coinalyze API key not set: liquidations and Coinalyze flows unavailable` 或 `Coinalyze rejected the API key: liquidations and Coinalyze flows unavailable`。
- **单位核对失败**：`Coinalyze <venue> market check failed: its data is left out`。
- **方向未核对**：Binance、Bybit 视图看各自交易所的 `direction_check`；All 和 Hyperliquid 视图看合并的 `direction`。视图所含交易所（Binance、Bybit、OKX）的结果为 `inverted` 时，提示 `Liquidation sides look inverted on <venue>: squeeze labels may be swapped`。
- 原来页头的 "liquidations collected since" 和覆盖说明里逐流的天数去掉了。中英文文案都经 `i18n.ts`，键一一对应。

### §6 验证

- **规则对照**：覆盖 **16 种组合**（all、binance、bybit、hyperliquid × 2 种块长 × 2 种 Show）。Hyperliquid 的清算在样本里没有，适配器用 `grid.estimate_liquidations`，把 All 的清算和 OI、HL 自己的 OI 喂进去，与 `perp_parity.py` 的估算对照。脚本和结果只写进验收记录，样本不入库。
- **方向核对改为按窗口**（桶内的分布已不真实）。worker 每轮对 Binance、Bybit、OKX 各算一次，用网格范围内已收盘、不是 `filled` 的 4hour 清算行：
  - 计入的窗口：价格变动 ≥1%（Bybit 现货，窗口第一个桶的价格到最后一个桶的价格），且有清算；
  - 指标：下跌窗口里多头清算占比 `Σl / (Σl + Σs)`；
  - 判定：至少 20 个下跌窗口时，占比 > 0.6 为 `ok`，< 0.4 为 `inverted`，其余或样本不足为 `pending`；
  - 单位核对失败的交易所记 `pending`（样本为 0）；
  - Hyperliquid 视图沿用 All 的合并结论。

  方向不挡住状态的显示，但核对为 `ok` 之前，squeeze 标签带 `(direction unverified)`。`v` 的单位不再自己检查，改由单位核对（`BASE_ASSET`）担保。
- **单元测试**另有：只有 4hour 数据的块在 O6 下能被判定；日志、URL、`repr` 和异常信息里不出现 key；未收盘的 bar 不入库；断档规则；HL 估算的缺失路径；合成视图的整窗规则；缺 key、key 无效和各种退避。测试不访问外网，不读真实的 `.env`。
- **V2 对照**：本机自采的清算与 Coinalyze 的 4hour 行按块合计对照，只比较完整覆盖的块；同时记录刚收盘的 4hour 值在 1 小时内是否被更正。结果见 [P6-VERIFICATION](P6-VERIFICATION.md)。
- **契约**：改 `contracts.py` 或视图模型后运行 `make contract`。
- 采集器资源与覆盖率的观察只在打开采集器对照时才有意义。

### §7 风险（补充）

- **单一来源**：清算和三家的买卖差只有 Coinalyze 一个来源。免费条款、限速或字段变化会直接影响表 1 和图 1、图 2；缺 key、key 无效或限速时界面降级（§3.7），不回退到假数据。
- **Coinalyze 自身的断档**：4h 层面由断档规则识别，5min 层面识别不出来（§3.3）。
- **估算**：Hyperliquid 的清算是估算，只能做定性参考。
- **共用 key**：本机和 test 共用同一个 key，最多两个进程同时运行（§3.8）。

## 8. 修订记录

**v4（2026-10-19）**：P6，清算与买卖量改用 Coinalyze，加入 Hyperliquid 视图。依据 [PROPOSAL-COINALYZE](PROPOSAL-COINALYZE.md) v3.1 和 [PLAN-P6](PLAN-P6.md)，核验见 [P6-VERIFICATION](P6-VERIFICATION.md)。

| 变更 | 处理 |
|---|---|
| 清算和 Bybit 买卖差只能自采，要采满 7 天，每次部署留下空洞 | 改读 Coinalyze，首轮回填约 90 天；采集器默认关闭，只用于对照（§0 P4-D4、D5、D11；§3.2） |
| 加入 Hyperliquid，All venues 并入 OKX | 四个视图，All = Binance + Bybit + OKX；HL 的清算按 All 估算并标注 estimated（§0 P4-D1、D10；§3.3；§5） |
| 4hour 和 5min 如何进 10m 网格 | 4hour 值放窗口末桶，`states.py` 的规则不变；合成视图的整窗规则（复核 C2）；Coinalyze 自身断档的规则（§3.3） |
| 4hour 刚收盘时的值可能不完整（复核 I1、I7） | 收盘后 1 小时内每轮重取最近 3 个窗口；落后时也重取（§3.2） |
| 旧的方向核对无法按新模型解析（复核 I2） | 迁移 003 删除旧行；方向核对改按 4h 窗口，Binance、Bybit、OKX 各一次（§6） |
| 同一个 key 的配额（复核 I5、I6） | 每进程每分钟 20 次；401 不退避，429 为 max(60 秒, `Retry-After`)，403 为 10 分钟（§3.8） |
| key 的保管（复核 I8、I9） | 环境变量存在即为准，否则只读仓库根目录 `.env` 的这一个键；只放在请求头里，不进 URL、日志、`repr`；测试不读真实的 `.env`（§2；§3.8） |
| 没有清算的品种整个被 Coinalyze 省略 | 对请求的每家都补 0（§3.2） |
| 页头、横幅、原因码随之改变 | 来源行与署名、`Liquidation history too short`、缺 key 的提示、`coinalyze_units`（§3.7；§5） |
| 规则对照 | 扩到 16 种组合（§6） |

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

**v3.2（2026-10-17）**：按 P4 整支终审修订（代码与本文同步，记录见 [P4-VERIFICATION](P4-VERIFICATION.md) §8）。

| 终审意见 | 处理 |
|---|---|
| 每次派生都把 91 天的原始清算逐条解析五遍 | §3.1：清算的方向、数量和价格在入库时映射并存列（迁移 002 回填旧行），派生在 SQL 中按桶汇总；改映射需要迁移重写这三列 |
| test 环境只输出 WARNING 以上的日志，覆盖空洞无从解释 | 连接异常结束记 WARNING；`/perps/status` 的 `collectors[].problems` 给出本进程以来的计数（发布流程写明部署后检查） |
| 未覆盖块的 delta / lLiq / sLiq 是补出来的值 | §4 写明，使用方取 `*_sum` |
| 视图只看合并的方向核对 | §5：各交易所视图看自己的核对，`inverted` 时显示提示 |
| perps 关闭时视图仍写 `not_derived` | §4、§3.7：改为 `perps_disabled` |
| collecting 状态的来源写错 | §3.7、§5：来自载荷，派生时算出 |

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
