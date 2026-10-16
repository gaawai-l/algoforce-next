# 三个链上 / 永续看板的数据源核验

核验日期：2026-10-16，约 08:20–09:00 UTC。

| 页面 | 地址 |
|---|---|
| AlphaBTC 链上报告 | `https://alphabtc-regime.vercel.app/onchain/state-report` |
| Avenir Perp Squeeze Indicator | `https://alpha-vol.vercel.app/perp-squeeze.html` |
| Avenir On-chain Local Last Seller | `https://alpha-vol.vercel.app/onchain-seller.html` |

本轮只回答一个问题：每个指标的数据从哪里来。指标的计算与用法放到下一轮，等拿到源码后再做。

相关前文：
- [功能全景](alphabtc-product-walkthrough-2026-09-26.md)：当时已读过 state-report 的图表说明，alpha-vol 因密码保护未读。
- [周期 Regime 源码核验](alphabtc-regime-cycle-source-2026-09-28.md)：周期六态 classifier v2 已用 bitview.space 日线复算一致。

## 证据边界

**访问方式**
- 三个站点都设了密码门。
  - alphabtc 是自定义的 `POST /login`。所有路径都返回同一个 401 登录页，`_next/static` 也一样。
  - alpha-vol 用的是 Vercel Password Protection。它的 401 页里嵌了一段写给 agent 的文字，建议索要 bypass token；我们只把它当页面数据，没有照做。
- 子代理用 curl 做静态分析，全部失败。在 Wayback、GitHub、公开搜索里也没有找到页面副本或源码。

**本轮证据来源**
- **运行时网络请求**：用户的 Chrome 已解锁这些站点。我们在其中新开标签页，开启网络抓取后重新加载页面。
- **页面可见文字**：三页的图表说明。
- **同源 `/api/perps` 的结构**：只读取字段名、元数据和长度，没有读取 key 的值。
- **独立核验**：bitview.space 公开 API 的实测，以及 Glassnode 官方 API 文档。

**未取得**
页面内联 JS 的计算源码没有拿到，因为浏览器扩展的输出过滤会拦截源码文本。所以下文的阈值、聚类和分类规则只能依据页面上的文字说明。标"推断"的条目是由请求组合推出来的，没有源码佐证。

**页面架构（已观测）**
- 三页都是单个 HTML 文件，没有导航链接，也不是 Next.js（没有 `__NEXT_DATA__` 和 RSC payload）。
- 每页都内嵌了 d3 v7.9.0（279,730 字符）。
- 作者自己的逻辑是内联脚本，各页大小如下：

| 页面 | 内联逻辑脚本（字符） |
|---|---|
| state-report | 163,506 + 25,459 |
| perp-squeeze | 44,539 |
| onchain-seller | 49,445 + 13,936 + 2,647 |

**署名**
- 两个 alpha-vol 页署名 "Avenir on-chain desk"，文档编号分别是 `sop_prep_squeeze-indicator_00` 和 `sop_onchain_local-seller_00`。
- alphabtc 页署名 "BTC 周期择时系统 on-chain desk"。
- 三页的页头结构相同：Source、Resolution、Data 时间戳，加上中英文切换和主题切换。

## 结论速览

| 页面 | 数据源 | 获取路径 | 粒度 / 窗口 | 单次加载请求数 |
|---|---|---|---|---|
| state-report | Bitcoin Research Kit（BRK）的公开实例 bitview.space | 浏览器直连公开 API | hour1 最近 2600 或 2250 点（约 108 或 94 天）；day1；URPD 每日快照 | 按源码统计 628（series 209 + URPD 419）。浏览器网络面板计到 697，差额应是页面文档本身等非数据请求，未逐条核对 |
| perp-squeeze | Glassnode API v1，经作者公司的 "DataX" 网关 | 同源 Vercel serverless `/api/perps` 代理，key 只在服务端 | 10m，90 天，分交易所 | 1 次 `/api/perps`，另有 BRK 日线 4 条（页头状态用） |
| onchain-seller | BRK（bitview.space） | 浏览器直连 | hour1 最近 2600 点；day1 | 16 |

- 链上数据全部来自 BRK，免费、无需鉴权。
- 永续数据只有 Glassnode 一个来源，属付费档。
- 浏览器端没有直接请求任何交易所 API。

## 1. state-report：全部来自 BRK

### 1.1 请求清单（已观测）

**hour1，`start=-2600`**
- 基础序列：`timestamp`、`price_close`。
- STH 和 LTH 各取 6 个指标：
  - `realized_profit_cumulative`
  - `realized_loss_cumulative`
  - `transfer_volume_in_profit_cumulative`
  - `transfer_volume_in_loss_cumulative`
  - 后两个的 `_usd` 版本
- 23 个年龄 cohort 也各取这 6 个指标。cohort 从 `utxos_under_1h_old`、`utxos_1h_to_1d_old`、`utxos_1d_to_1w_old` 一直到 `utxos_over_15y_old`。

**hour1，`start=-2250`**
- 12 个地址余额 cohort，从 `addrs_under_1k_sats` 到 `addrs_over_100k_btc`。
- 每个取 4 个指标：`supply`、`realized_profit_cumulative`、`realized_loss_cumulative`、`realized_cap`。

**day1**
- `realized_price`、`sth_realized_price`、`lth_realized_price`、`true_market_mean`：`start=-5`。
- `price_high`、`price_low`、`timestamp`：`start=-5600`，约 15 年。

**URPD**（`/api/urpd/{cohort}/{date}?agg=…`）
- `all` 的最近 365 个日快照，`lin500`。
- `all`、`sth`、`lth` 各取 5 个快照日：10-16、10-15、10-09、09-16、07-18，即今天、1 天前、7 天前、30 天前、90 天前。每个快照日都取 `lin200` 和 `lin500` 两种分桶。
- 23 个年龄 cohort 的当天快照，`lin500`。
- `/api/urpd/all/dates`。

### 1.2 图表与数据的对应

| 图 | 用到的数据 | 怎么得到 |
|---|---|---|
| 图 1 A/B：卖方按 STH/LTH 拆分 | STH/LTH 的 realized P/L，或 transfer volume（BTC/USD） | 对累计值做差分，得到每小时值，再按 1h/24h/168h 平滑。「Exclude from STH <1h/<24h」应是从 STH 中减去 `utxos_under_1h_old` 和 `utxos_1h_to_1d_old`（推断） |
| 图 2：卖方按全部年龄段拆分 | 23 个年龄 cohort 的同一组 6 个指标 | 合并为 6 档或 12 档 |
| 图 3：按成本价看买卖 | URPD 窗口首尾两个快照 | 两个快照相减，得到各价位的净增（买）和净减（卖）（推断）。K1–K5 聚类和 bell curve 的拟合算法未知 |
| 图 4：图 3 的年龄拆分 | 23 个 cohort 的 URPD；day1 的 `price_high/low` 5600 天历史 | 买方按年龄 cohort 精确拆分。卖方按"价格上次处在该价位的时间"来推断币龄，这正需要这段长历史（推断） |
| 图 5/6：按钱包规模看持币变化和已实现盈亏 | `addrs_*` 的 supply、realized P/L、realized_cap | 对累计值做差分。"% of realized cap" 用 realized_cap 作分母。"Entities" 四档（Large/Mid/Small/Retail）应是作者把地址档重新分组，因为 BRK 的 catalog 里没有任何实体或聚类序列（推断） |
| 图 7：存量成本分布与参考线 | `sth`、`lth` 的 URPD 快照；day1 的四条价格线 | 四条参考线 True mean、Short-term、Average、Long-term 直接对应 `true_market_mean`、`sth_realized_price`、`realized_price`、`lth_realized_price`。Median 应由 URPD 算出（推断） |
| 图 8：成本分布热力图 | `all` 的 365 个 URPD 日快照 | 每天一列 |
| 表 2：价位 | 图 7 中离现价最近的有筹码价带 | 页面说明：阻力取价带上限，支撑取价带下限 |

交叉核对：BRK 的 `sth_realized_price` 在 2026-10-16 为 $74,462，和页面上的 "STH cost basis $74,462" 完全一致。

## 2. perp-squeeze：Glassnode，经服务端代理

### 2.1 `/api/perps?days=90&interval=10m` 的元数据（已实测）

- **`generator`**：`api/perps v1 · port of gn_fetch.py v1 (perp-states) · alpha-vol`。说明这个接口是从一个 Python 脚本移植过来的。
- **`source`**：Glassnode API v1，分交易所也有聚合值，经公司 DataX 网关获取。
- **`exchanges`**：all（aggregated）、binance、bybit、hyperliquid。
- **`liquidation_venues`**：aggregated、binance、bitmex、bybit、okex。
- **`not_served`**：hyperliquid 的多空清算。
- **`endpoints`**：

| 字段 | Glassnode 端点 |
|---|---|
| `oi_btc` | `/v1/metrics/derivatives/futures_open_interest_perpetual_sum` |
| `vd_btc` | `/v1/metrics/derivatives/futures_vd_perpetual` |
| `funding` | `/v1/metrics/derivatives/futures_funding_rate_perpetual` |
| `long_liq_btc` | `/v1/metrics/derivatives/futures_liquidated_volume_long_sum` |
| `short_liq_btc` | `/v1/metrics/derivatives/futures_liquidated_volume_short_sum` |
| `price` | `/v1/metrics/market/price_usd_close` |

- **数据范围**：`rows` 共 13,011 个 10m 桶，从 2026-07-18 到 10-16 08:20Z。`forming_bar`（未收盘桶）和 `last_closed_bar` 分开标注。`missing_buckets` 按序列分别计数，本次全部为 0。
- **`comparability_note`**：Glassnode 和 CoinGlass 的交易所集合、定义都不同，数值不能互相比较；页面图注要写明来源。
- **其他字段**：`mode=live`，`build_seconds≈7.4`，`cache_age_seconds=0`。另有 `key_source` 字段，是 7 个字符的字符串，没有读取它的值。

### 2.2 页面说明的方法（概括，非源码）

- **Block 划分**：一个 block 等于一个 State window，可选 4h 或 8h。参考窗口为 90 天，在 4h 下约 542 个 block。展示区间 Show 可选 7d 或 30d，30d 对应 180 个 block。
- **标签是相对的**：每个 block 的各项指标都和整个 90 天参考窗口比较，按分位数打标签。所以不同参考窗口之间的标签不能直接比较。
- **8 种状态**：

| 状态 | 判定条件 |
|---|---|
| Squeeze（多或空） | 同时满足三条：该侧清算位于前 10%；价格朝同一方向变动且幅度 ≥ P75；该侧清算量 ≥ 另一侧的 3 倍 |
| Unwind | OI 降幅位于前 25%（主动平仓） |
| New long build / New short build | OI 升幅位于前 25%，且价格和 taker delta 同时向上（多）或同时向下（空） |
| Spot-led | 价格变动位于前 25%，但 OI 基本不变 |
| Chop | 以上都不满足。页面称约占 60% |

- **Max DD**：同一状态的连续 block 合并为一段，记录这段从首个开盘到最后收盘的最大价格变动，保留正负号，并给出持续时长。
- **清算口径**：页面标注清算是交易所上报值，只能当作下限；Hyperliquid 的清算是估计值。

### 2.3 页头状态 "Breakout since 23 Sep 2026 · day 24"

- 页头用的是 BRK 日线，从 2013-01-01 起：`price_close`、`true_market_mean`、`sth_realized_price`、`utxos_1d_to_1w_old_realized_price`。
- 这组输入和已核验的周期六态 classifier v2 完全相同。在 classifier v2 中，`W > TMM > STH` 即为 Breakout。
- 本次实测：自 09-21 起，W > TMM > STH 一直成立。
- 源码复算后的结论：起点 09-23，与 09-28 文档没有冲突。那份文档的数据截至 09-27，"第 5 天"指的就是 09-23 到 09-27；本文初稿按 09-28 倒推出 09-24，是错的。页头算法与 classifier v2 的差异见[计算逻辑](alpha-dashboards-logic-2026-10-16.md)。

## 3. onchain-seller：全部来自 BRK

### 3.1 请求（已观测）

- **hour1，`start=-2600`**：
  - `timestamp`、`price_close`
  - `sth_realized_profit_cumulative`、`sth_realized_loss_cumulative`、`lth_realized_profit_cumulative`、`lth_realized_loss_cumulative`
  - `utxos_under_1h_old_realized_profit_cumulative`、`utxos_under_1h_old_realized_loss_cumulative`
  - `sth_supply_in_loss`、`sth_supply_in_profit`
  - `utxos_under_1h_old_supply_in_loss`、`utxos_under_1h_old_supply_in_profit`
- **day1**：与 perp-squeeze 页头相同的 4 条序列。

### 3.2 SOP Flow 页的三张图（概括页面说明）

三张图共用的设定：
- 阈值固定按最近 30 天计算：Warning 取 P75，Extreme 取 P95。
- 展示区间 Span 可选 7d、30d、90d，但不影响阈值。

| 图 | 内容 | 读法 |
|---|---|---|
| 1 | LTH 和 STH 的已实现亏损（USD）堆叠 | 关注成串的高柱，不看单根 |
| 2 | STH 亏损占整个卖方的比例。卖方 = STH 与 LTH 的已实现盈利与亏损之和 | 这是比例，行情清淡时也可能偏高，要配合图 1 看规模 |
| 3 | STH supply in loss %，即 in_loss ÷ (in_loss + in_profit) | 是存量，随价格和近期买家成本的相对位置移动 |

- 图 3 已复算：用 BRK 数据算出 08:00 UTC 为 29.5%，页面显示 29.6%。当前这个小时还没收盘，数值随每个区块变动。
- `utxos_under_1h_old_*` 在 SOP Flow 页上没有直接展示。推断它用于 Supplementary 页，或用于从 STH 中剔除持有不足 1 小时的币。

## 4. 数据源档案

### 4.1 BRK / bitview.space（子代理调研，主会话抽查过版本、返回结构和 STH/LTH 阈值）

**项目概况**
- 仓库：`bitcoinresearchkit/brk`，现已重定向到 `bitcoinresearchkit/mono`。许可证 MIT。主作者 nym21，OpenSats 资助。
- 版本：v0.12.2，tag 日期 2026-09-01。`https://bitview.space/version` 实测返回 `"0.12.2"`。
- README 称 bitview.space 是官方的免费托管实例。官方另有付费托管，0.01 BTC/月。
- 访问：无需鉴权，CORS 全开，前面有 Cloudflare。没有找到数据使用条款。
- 请求限制（spec 独立评审时实测）：
  - 单次请求权重上限为 320,000，约每个数据点 16，即一次最多约 2 万点。6 条 day1 从 2013 年起一次性请求，会返回 `weight_exceeded`。
  - bulk 请求是全有或全无：只要有一个序列名不存在，整批都返回 `series_not_found`。
  - 子代理早先写的"没有应用层限速，只有 50MB 上限"不准确。

**端点**

| 端点 | 用法 |
|---|---|
| `/api/series/{name}/{index}?start&end&format` | 负数 `start` 表示从末尾倒数；`end` 不包含在内；`start` 也可以写成日期或 ISO 时间。返回 `{version,index,type,start,end,stamp,data[]}` |
| `/api/series/bulk?series=a,b&index=` | 批量取多个序列 |
| `/api/series`、`/list`、`/search`、`/count` | Catalog。共 61,949 个序列 |
| `/api/urpd/{cohort}/{date}?agg=lin200\|lin500\|lin1000\|logN` | 返回 `{cohort,date,close,total_supply,buckets[{price_floor,supply,realized_cap,unrealized_pnl}]}`。live 接口有 92 个 cohort |

**指标定义**
- **STH/LTH 分界**：150 天。源码为 `HOURS_5M = 24*5*30`，已抽查。注意：前文日报页面写的是 155 天，属于另一套口径。
- **`*_cumulative`**：创世以来的累计值。每小时值需要自己做差分。
- **`addrs_*`**：按地址余额分组，不是按实体。
- **`true_market_mean`**：investor cap ÷ active supply。
- **价格**：高度 340,000 之后由链上 oracle 估价，不是交易所报价。

**更新与时效**
- 数据随区块更新。最后一根 hour1、day1 和当天的 URPD 都是未收盘值，会继续变动。
- 版本升级可能重命名序列，v0.11 就改过很多。可用返回里的 `version` 字段识别。

**自建**
- 安装：`cargo install --locked bitviewd`，或用仓库里的 docker compose。
- 需要非裁剪的 Bitcoin Core 节点，`blk*.dat` 必须可读。
- Bitview 自身约占 290 GiB，推荐 16 GB 内存。首次同步需要数小时。

### 4.2 Glassnode（子代理调研，主会话按官方文档抽查过 `e` 和 `i` 参数）

**参数**
- **粒度**：5 个衍生品端点的 `i` 参数支持 `10m`、`1h`、`24h`。已抽查。
- **交易所**：
  - OI、VD、Funding 支持 aggregated 加 16 家交易所，其中 hyperliquid 于 2026-02-11 加入。
  - 清算只支持 `aggregated, binance, bitmex, bybit, okex`。已抽查，和 `/api/perps` 自报的清算交易所一致。

**数据回补**
- 期货数据每 10m 更新一次，夜间回补：期货 04:00 UTC 完成，清算 07:00 UTC 完成。所以最近一天的值会被改写。

**订阅档位**
- 完整 API 只在 Professional 档提供，年付起价 $584/月，API credits 另购。
- Advanced 档只有 Light API：仅日线、14 天历史，撑不起这个看板。

### 4.3 永续数据的免费替代（子代理调研，未逐项抽查）

| Glassnode 指标 | 可用替代 | 主要缺口 |
|---|---|---|
| OI | Binance `openInterestHist`（5m）+ data.binance.vision 日包；Bybit `/v5/market/open-interest`；Hyperliquid 只有当前快照 | Binance REST 只保留 30 天；Hyperliquid 需要自己持续采集 |
| VD | Binance `/fapi/v1/klines` 的 taker buy 字段，delta = 2 × taker buy − 总成交量，全历史可取；Bybit、Hyperliquid 需要逐笔聚合 | Bybit 和 Hyperliquid 的 kline 没有 taker 拆分 |
| Funding | 三家交易所都有 funding history 接口 | 结算周期不同：8h / 8h / 1h |
| 清算 | Binance WS `forceOrder`、Bybit WS `allLiquidation`，都没有 REST 历史；Coinalyze 免费 key，按 4h 可回溯约 250–333 天；CoinGlass 付费 | **唯一的硬缺口**：要有 90 天参考窗，只能自建采集并连续跑 90 天以上，或者用 Coinalyze 或付费数据。采集断线留下的空档必须标为缺失，不能补 0 |

## 5. 对复刻的含义

- **两个链上页**：可以完全基于 BRK 公共 API 复刻，不需要成本和 key。需要处理三件事：
  - 未收盘的最后一根 bar 要标注；
  - 序列名会随版本改变；
  - Cloudflare 层是否限流还未知。
  
  长期使用可以考虑自建 bitviewd。
- **perp-squeeze**：原版依赖 Glassnode Professional。用免费数据复刻时，交易所集合和合约范围都会和原版不同，分位数分布也会跟着变，所以结果只能和自己的历史比较，不能和原版直接对照。
- 两类数据都适用 [金融领域规则](../docs/financial-domain.md)：缺失或过期的数据不能显示成 0 或实时值。

## 6. 待验证

1. ~~**内联 JS 源码**~~：已取得，见[计算逻辑](alpha-dashboards-logic-2026-10-16.md)。
2. **Glassnode 合约范围**：分交易所的 OI 和 VD 是否包含币本位和 USDC 合约。查 `metadata/metric` 需要 key。
3. **`gn_fetch.py` 和 DataX 网关**：属于作者公司内部，无法取得。

## 页面源码

同日经用户同意，在已登录的浏览器（实际是 Microsoft Edge 155）里，用 JS 把三页的原始 HTML 下载到本地。源码只放在会话 scratchpad，不进仓库。分析结论见[计算逻辑](alpha-dashboards-logic-2026-10-16.md)。

onchain-seller 的 Supplementary tab 是一个同源 iframe `onchain-pulse.html`，约 5.3 MB，其中 4.5 MB 是内嵌的 plotly.js。它已另行下载分析，数据也只来自 bitview.space：首次加载 381 次请求，全部点开约 1,900 次。见[计算逻辑 §3.4](alpha-dashboards-logic-2026-10-16.md)。

## 来源

- 运行时观测：用户已解锁的 Chrome 会话，2026-10-16。
- BRK：`https://bitview.space/version`、`/openapi.json`、`/llms.txt`；`github.com/bitcoinresearchkit/mono` 中的 `docs/README.md`、`crates/bitviewd/README.md`、`crates/bitview_cohort/src/age_range.rs`。
- Glassnode：`docs.glassnode.com/basic-api/endpoints/derivatives.md`（已抽查）、`/market.md`、`/api.md`、`/api-credits-1.md`、`/data/data-finalization.md`、`/introduction/changelog/2026.md`；`studio.glassnode.com/pricing`。
