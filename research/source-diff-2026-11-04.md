# 原站与上游数据源变更巡检（2026-11-04）

核验日期：2026-11-04，约 01:05–02:30 SGT（2026-11-03 17:05–18:30 UTC）。对照基线是 2026-10-16 的源码快照和 2026-10-19 的核验快照（`.local/research-samples/alpha-dashboards-2026-10-16/`），以及 [数据源核验](alpha-dashboards-data-sources-2026-10-16.md)、[计算逻辑](alpha-dashboards-logic-2026-10-16.md)。

## 结论速览

1. **BRK 在 2026-10-30 升级，本地链上数据从那时起全部断供。** 主 checkout 的 `onchain.sqlite` 最后一次成功是 2026-10-30 16:12Z，之后每轮都是 `brk_unavailable`。原因有四：
   - 序列响应去掉了 `stamp`；
   - URPD 响应改成列式；
   - 年龄、地址档的 cohort 全部改名；
   - bulk 请求每次最多 32 个序列。

   本分支已修，详见 §3.1，已用线上 BRK 实测通过。
2. **新版 BRK 重算了历史。**
   - 已存的 URPD 快照与新版不一致：总量相同，但单个 lin500 价位桶最多相差约 3.2 万 BTC。Chart 3 用今天的快照对比过去的快照，如果不重取，会算出虚假的买卖量。本分支已改为版本变化后让已存快照失效。
   - Chart 8 的 365 天历史尚未处理，见 §3.2。
3. **onchain-seller 改动很大。**
   - 多分辨率：7d/1h、30d/4h、90d/1d；
   - 阈值窗口随 span 变化；
   - 新增 Percentile 视图；
   - 新增默认开启的 noise filter；
   - 新增 Chart 4 "Average Percentile History"。

   onchain-pulse 也加了 noise filter。这些属于大改，只给方案，见 §4。
4. **state-report 已下线。** `alphabtc-regime.vercel.app/onchain/state-report` 现在跳转到 alpha-vol 的 `onchain-pulse.html`，alphabtc 根路径出现登录墙。
5. **perp-squeeze 只改了 BRK 序列名。** Coinalyze 的端点和字段无变化。
6. **Bybit spot 和 Binance fapi 的响应格式没有核验成。** 本机网络在 DNS 层拦截了 `api.bybit.com` 和 `fapi.binance.com`，浏览器也打不开。本地 perps 库里两者最后成功都是 2026-11-02 08:15Z。

## 1. 方法与证据位置

**原站源码**
- 在用户已登录的浏览器里新开 tab，用页内 `fetch` 取原始 HTML，打包成 JSON 下载。浏览器是 Microsoft Edge 156，按 `navigator.userAgentData.brands` 确认。
- 与 10-16 一样，Edge 把下载停在 `.crdownload`（未确认）。内容已完整：两份 JSON 都能完整解析，按页的长度和 etag 与页内 `fetch` 结果一致。
- 下载件和拆分出的脚本只放在本会话 scratchpad，不进仓库：
  - `…/scratchpad/dl/`：原始下载；
  - `…/scratchpad/new/`、`…/scratchpad/old/`：用同一脚本重新拆分的新旧脚本；
  - `…/scratchpad/diffs/`：diff。
- `~/Downloads/` 里留下两个 `alpha*-20261104.json.crdownload`，可手动删除。

**上游**
- 只读、低频：请求间隔 ≥1 秒，每个序列只取最后几个点。
- BRK 的 catalog 共 22 页，每秒取一页。
- Coinalyze 通过本地 `Coinalyze` 客户端调用，key 由 `Settings.from_env()` 读取，没有打印，也没有写入任何文件。

**本文只用自己的话描述原站逻辑，不摘抄源码。**

## 2. 逐条变化

标记含义：
- **需要改代码**：本地不改就会出错，或与原站行为不符；
- **只更新文档**：只需修正文档里的描述；
- **无影响**。

### 2.1 BRK（bitview.space）

| # | 变化 | 证据 | 标记 | 本地文件 |
|---|---|---|---|---|
| B1 | `/version` 从 `"0.12.2"` 变成 `"66f66db"`。GitHub 上这是 `bitcoinresearchkit/mono` 2026-11-03 的提交，比 v0.13.0 标签（2026-10-30T22:56Z）领先 291 个提交。公开实例跟的是主干，以后每次部署都会换版本号 | `curl /version`；GitHub compare `v0.13.0...66f66db`：ahead 291 | 需要改代码（已修，见 §3.1）；文档也要更新 | `onchain/sync.py`（版本变化即全量重建） |
| B2 | 序列响应不再带 `stamp`，本地 `SeriesData.stamp` 是必填字段，所以**所有**序列都校验失败，报 `brk_unavailable` | 单序列与 bulk 响应只有 `version,index,type,start,end,data`；主 checkout 库 `last_error=brk_unavailable`，最后成功 2026-10-30T16:12Z | 需要改代码（已修） | `onchain/brk.py` |
| B3 | 年龄 cohort 改名：`utxos_X_old*` → `age_X*`，例如 `utxos_under_1h_old_supply_in_loss` → `age_under_1h_supply_in_loss`。URPD cohort 同样改名，旧名返回 400 `unknown URPD cohort` | 旧名报 `series_not_found`，提示 "did you mean `age_1d_to_1w_realized_price`"；`GET /api/urpd` 列出 30 个 cohort | 需要改代码（已修） | `onchain/brk.py`、`pressure.py`、`sellside.py`、`agecohorts.py`、`levels.py`、`sync.py` |
| B4 | 地址余额档改名，网格也变细：`addrs_*` → `balance_*`，例如 `addrs_10m_sats_to_1btc` → `balance_10m_to_100m_sats`。旧的 "under 1k sats" 不再是单独一档，等于 `balance_1_to_10_sats` + `balance_10_to_100_sats` + `balance_100_to_1k_sats` 之和。另有 `amount_*` 系列，是按 UTXO 金额分档，**不是**地址档 | 2026-10-21 本地存的旧值（position 156000）与新值对照：`1k–10k sats` 的 supply 504.88580014 逐位相同；`10m sats–1 BTC` 为 1065133.71012913；三档之和 30.18446111 等于旧的 `addrs_under_1k_sats_supply`。`amount_*` 的数值完全不同 | 需要改代码（已修） | `onchain/brk.py`（`SIZE_BANDS` 保持本地名） |
| B5 | bulk 请求每次最多 32 个序列，超出返回 400 "At most 32 series may be requested"。原来 2,000 字符的上限实际上已经碰不到：catalog 里最长的 32 个名字连起来只有 1,785 字符 | 33 个名字：400；32 个最长名字：200 | 需要改代码（已修，`MAX_SERIES = 32`）。增量刷新时一次请求可能包含上百个名字 | `onchain/brk.py` |
| B6 | URPD 响应改成列式：`buckets` 从 `[{price_floor,…}]` 变成 `{price:[],supply:[],realized_cap:[],unrealized_pnl:[]}`，总量字段从 `total_supply` 改名为 `supply`。新增 `height`、`hash`、`weight` 字段 | `/api/urpd/all/2026-11-02?agg=lin500`：252 个桶，桶宽 500，没有零桶，与旧版一致 | 需要改代码（已修） | `onchain/brk.py`（`Urpd` 解析） |
| B7 | **新版重算了历史 URPD**：同一天快照的总量不变，但各价位的筹码重新分配了 | 10-20 的 all/lin500：最大单桶差 31,964 BTC，sth 为 4,054 BTC；10-29：29,847 和 2,782 BTC | 需要改代码：`urpd` 表已修（§3.1）；Chart 8 历史表待定（§3.2） | `onchain/sync.py`、`store.py` |
| B8 | 新版也重算了序列：累计值整体平移，但窗口差值不变 | 7 天差值对比旧库：STH/LTH realized P/L、`age_under_1h` 与旧值的差在 0.0000% 级；`balance_*` 的 realized P/L：1k–10k sats +3.34%，under 1k sats +3.69%，10m sats–1 BTC −0.25%；supply 不变 | 只更新文档。Chart 6（size 档已实现盈亏）读数会小幅变化，其余图不受影响 | `docs/features/btc-onchain-perp/` 验收记录 |
| B9 | 有了新的 `hour4` 索引 | `/api/series/price_close/hour4` 返回正常 | 需要改代码（大改的一部分，见 §4.1） | `onchain/brk.py`（`Index`） |
| B10 | `/api/urpd/{cohort}/dates` 已删除，日期改从 `/api/series/date/day1` 取。`cost_basis_per_*_pctNN` 改名为 `cost_basis_by_*_pNN`，P50 改叫 `_median`。年龄 cutoff 只保留 4、5、6 个月 | 实测 dates 端点返回 400；pulse 新脚本的注释也写明了这几处改名 | 无影响：本地不用这几个端点和序列 | — |
| B11 | 6 条 day1 序列从 2013 年起一次请求，权重 444,840，仍超过 320,000 的上限。每点约 14.7，比原来估计的 16 低，本地按 16 估算更保守 | 实测返回 `weight_exceeded` | 无影响 | `onchain/brk.py`（`MAX_POINTS`） |
| B12 | 某个序列不支持请求的索引时，返回 400 `series_unsupported_index`，不是 404 | 实测 | 无影响：本地只请求受支持的索引 | — |

### 2.2 原站页面

| # | 页面 | 变化 | 标记 | 本地文件 |
|---|---|---|---|---|
| S1 | state-report | `/onchain/state-report` 跳转到 `https://alpha-vol.vercel.app/onchain-pulse.html`，两者内容相同（etag 都是 `519b2842…`）。alphabtc 根路径和 `/onchain` 都返回 401 登录页"AlphaBTC · 访问验证"。**没有输入密码** | 只更新文档。CHART-INVENTORY 的 URL 和数据源表要更新，state-report 今后以 onchain-pulse 为准 | `docs/features/btc-onchain-perp/CHART-INVENTORY.md` |
| S2 | perp-squeeze | 唯一改动：页头周期用的第 4 条 day1 序列，从 `utxos_1d_to_1w_old_realized_price` 改为 `age_1d_to_1w_realized_price`。死区和算法都没变；Glassnode 端点和参数没变；markup 只有 4 行 diff | 需要改代码（已修，等同 B3） | `onchain/cycle.py` 经由 `brk.DAY1_SERIES` |
| S3 | onchain-seller | 分辨率和阈值窗口跟着 span 走（v02，作者标注 2026-10-20 到 10-25），见 §4.1 | 需要改代码（大改，见方案） | `onchain/pressure.py`、前端 seller 页 |
| S4 | onchain-seller | Noise filter（作者 2026-10-25）**默认开启**。标记条件：某条腿超过 50M（M = 前 720 小时全市场 sell side 的中位数），且本小时与下一小时价格变动都小于 1%。被标记小时里超过 10M 的腿，换成它自己前 24 小时的中位数，差额从包含该小时的 4h 和 1d 柱里扣掉。Chart 1、2 的数值和阈值都会受影响，Chart 3 不受影响。为此多拉 8 条 hour1 序列，深度 `-10400` | 需要改代码（大改，见方案） | `onchain/pressure.py` |
| S5 | onchain-seller | 新增 Chart 4 "Average Percentile History, by Span"：三张图在同一时点的排名均值，每个 span 一条线，带 95%/75% 参考线和价格。为此重新内嵌 plotly 2.35.2。原来的雷达图 10-21 已删除，注释里的"Charts 4 and 5"是遗留写法 | 需要改代码（新图，见方案） | 新模块 |
| S6 | onchain-seller | 控件："Rolling Window / Resolution" 三档：7D/1 HR、30D/4 HR（默认）、90D/24 HR，原来的 168/720/2160 小时改成 7/30/90 天。另外新增 View: Value/Percentile 开关、Noise Filter 开关、tooltip 显示过滤前后的数值，QC 里新增"最后一根已收盘"和"4h/1d 柱等于其所含小时之和"。最后一根未收盘的柱不再参与计算（**旧版会参与**），流量也不再量化到 $100 | 需要改代码（并入 §4.1） | `pressure.py`、前端 |
| S7 | onchain-seller | 三栏说明：Chart 1 的单位改成"每柱美元"，"最近 30 天"改成"span 自身窗口"，How to read 增加窗口、Percentile 和 NF 的说明；Chart 2 增加"先对柱内求和再相除"；Chart 3 增加"取每柱收盘值"，以及 7d 记忆最短的说明；Chart 4 是新的三栏。AI prompt 里的 STH 从 155 天改成 150 天 | 需要改代码（文案随 §4.1 一起改） | 前端 i18n |
| S8 | onchain-seller | 页头周期：分类器和死区 7.0/6.8/1.25 不变，只改了序列名；spot 价改读最后一根已收盘小时的收盘价 | 无影响（序列名已修） | `onchain/cycle.py` |
| S9 | onchain-pulse | Chart 1A/1B/2 新增 noise filter（深度 `-3400`，只作用于 realized P&L，直接替换小时数组），带全页开关、tooltip 计数和 QC。图表、表格、Experimental 都没有增删，三栏文案没变，只有 STH 的天数措辞从 155 天改为 150 天 | 需要改代码（大改，见 §4.2） | `onchain/sellside.py`、`agecohorts.py` |
| S10 | onchain-pulse | 1/2/3 个月的年龄 cutoff 被删，pulse 改用年龄段求和来重建（realized price = Σcap ÷ Σsupply）；5m 直接用 `sth` | 无影响：本地不用这些 cutoff | — |
| S11 | onchain-pulse | URPD 读法跟着改成列式（适配器把列还原成行）；顶层 `close` 仍在使用 | 无影响（本地已按 B6 适配） | — |

### 2.3 Coinalyze

2026-11-03 17:19Z 通过本地客户端核验：
- `/v1/future-markets` 里的 4 个 symbol 都存在，都是 `BASE_ASSET`，`has_buy_sell_data=true`：`BTCUSDT_PERP.A`、`BTCUSDT.6`、`BTCUSDT_PERP.3`、`BTC.H`。
- `liquidation-history`、`ohlcv-history`、`open-interest-history` 在 5min 和 4hour 下都返回正常。字段与本地读取的一致：
  - liq：`l,s,t`；
  - ohlcv：`v,bv,…`；
  - oi：`o,c,…`。
- 本地 perps 库最后成功 2026-11-03T17:15Z。

**无影响。**

### 2.4 Bybit spot kline / Binance fapi kline：未核验

- 本机把 `api.bybit.com` 和 `fapi.binance.com` 都解析到 182.23.79.195 和 139.255.196.196，连接被拒。curl 和 Edge 都一样，属于网络层拦截，不是上游变化。
- 本地 perps 库 `hosts`：fapi.binance.com 和 api.bybit.com 的 `last_success` 都是 2026-11-02T08:15Z，之后是 `network`。
- 需要换一个网络，或在 Coolify test 环境上复核。

## 3. 本分支的修复（`claude/site-diff-1104-14810d`）

### 3.1 已修（都有测试）

1. **名字只在请求时翻译**
   - `brk.REMOTE_COHORTS` 和 `remote_names()`：本地名保持不变，仍然是 store 键、payload 键和前端 i18n 键，只在发请求时翻译成 BRK 的新名字。这样存量数据、前端和全部 fixture 都不受影响。
   - "under 1k sats" 由三档逐点求和：任一档缺值，该点就是缺值，不当 0 处理；`version` 取三档之和，任一档变化都会触发重取；任一档 `series_not_found`，整档记为 missing。
   - URPD 用新名请求，返回后改回本地 cohort 名再存储。
2. `SeriesData` 去掉 `stamp` 字段，它从来没被用过。
3. `Urpd` 增加 before-validator：把列式响应还原成原来的桶列表，`supply` 映射为 `total_supply`。store 里的旧格式照常通过。
4. `MAX_SERIES = 32`：分片时同时受点数、字符数和 32 个的限制。
5. BRK 版本变化、day1 序列重建后，调用 `store.expire_urpd()`：把 `urpd` 表所有快照的 `fetched_at` 置为 BRK 纪元起点，让它们一律视为非终态，各调用点都会重取。重取成功前，它们仍可作为"最近一次快照"兜底，所以 URPD 故障时的原有行为不变。

**测试**
- `test_onchain_brk.py` 新增 7 个测试：名字翻译、求和、缺档、32 上限、无 `stamp` 的响应、列式 URPD 加本地 cohort 名。
- `test_onchain_sync.py` 新增版本变化后重取全部快照的测试。
- 假 BRK（`onchain_fixture.py`）改为使用新名字和 32 上限。旧录制没有拆档，所以最后一档回放整档旧值，其余两档回放 0，三档之和等于录制值。
- 新 fixture 放在 `tests/onchain/fixtures/brk-2026-11-04/`，都是公开数据。

**线上实测**（修复后的客户端直连 bitview.space）
- 本地用到的 8 条 day1、203 条 hour1 序列全部找到，没有全空的；
- URPD_SET 的 9 个快照加上 6 个年龄 URPD，全部解析成功，桶的供应之和等于总量。

**上线后的一次性代价**
- 所有序列的 version 都变了，hour1 会各自从 `-3000` 全量重取，day1 从 2013 年起重取。
- `urpd` 表重取约 100 个快照。

### 3.2 待定：Chart 8 历史（`urpd_history`）

- 历史表是按天存的、已终态的快照，B7 的重算让 10-30 前后成为两个版本。每天一列，列内自洽，但 10-30 前后会有一条接缝。
- 方案一：BRK 版本变化时清空 `urpd_history`，按现有回填逻辑重取。约 1,456 个请求，每轮 120 个，要 12–13 小时；期间热力图只有部分天数，会如实标注缺失。
- 方案二：保留现状，在页面注明 2026-10-30 之前是 BRK 旧版的计算。
- 还要注意 B1：公开实例跟主干，版本号可能频繁变化。如果选方案一，宜只在"重大版本变化"时清空。这需要先定义判断规则，比如抽一天对比桶差值超过阈值才算。**建议先选方案二，等用户决定。**

### 3.3 版本频繁变化的成本（观察项）

B1 之后 `/version` 是 git 提交号，每次部署都会触发一次：
- day1 全量重取：2–3 个请求；
- 当前网格的 URPD 重取：约 100 个请求；
- hour1 只重取 version 变化的序列。

一天部署一两次的话，这个量可以接受。如果太频繁，可以改成按 URPD 抽样对比来决定是否让快照失效。暂不改。

## 4. 大改动方案（未实施）

### 4.1 onchain-seller v02：多分辨率、span 窗口、Percentile 视图、noise filter、Chart 4

1. **数据**
   - `brk.Index` 增加 `hour4`。
   - 每个分辨率各取 12 条序列：hour1 `-1700`，hour4 `-1400`，day1 `-400`。
   - 4h 和 1d 的流量用 BRK 自己的 `hour4`/`day1` 索引，对累计值做差分，不在本地把小时数据加总。
   - QC 校验 4h/1d 柱等于其所含小时之和。
2. **计算**
   - `pressure.py` 改为按 span 计算：7d→1h，30d→4h，90d→1d。
   - P95/P75 的窗口是 span 自身按时钟往回数的天数，`t > last − days`。
   - 丢掉最后一根未收盘的柱，去掉 $100 量化。
   - Chart 2 先对柱内求和再相除。
   - 本地的 O2（窗口不含自身）和原站的 Percentile 定义（窗口 `(t−ref, t]`，含自身，按 `≤` 计数）要分开实现，O2 只作为 rules 选项。
3. **Noise filter**
   - 用 hour1 `-10400` 的 8 条序列计算。
   - 按原站的标记和替换规则，把被替换掉的差额从 4h/1d 柱里扣除。
   - 默认开启，payload 同时给出原值和过滤后的值，以及被标记的小时，前端提供开关。
4. **Chart 4**：在三张图的同一时点取排名均值，每个 span 一条线，hour1 线约覆盖 63 天。
5. **前端**：替换控件和三栏文案，新增 Percentile 视图、NF 开关、Chart 4 和 tooltip 的过滤前后值。
6. **验证**：用同一时刻的原站页面读数（阈值、最后一根的值、被标记的小时）逐数对照。

这是非平凡的计算改动。按项目规则，先写中文计划并独立复核，再动手。

### 4.2 onchain-pulse 的 noise filter，对应本地 Sell side 的图 1A/1B 和图 2

- 规则同 S4，但做法不同：直接替换小时数组，只作用于 realized P&L，深度 `-3400`。
- 本地的 `sellside.py`、`agecohorts.py` 要增加过滤后的数值和开关，前端相应增加开关。
- 可以和 §4.1 共用一套标记逻辑，但两页的替换对象不同，要分开对照验证。

## 5. 没做成的检查

- Bybit spot 和 Binance fapi 的 kline 响应格式：本机网络拦截，见 §2.4。
- alphabtc 根站的其他页面：遇到登录墙，按规则没有输入密码，已跳过。state-report 本身经跳转仍可访问。
- Coolify test 环境没有查看，也没有发布。test 环境的链上数据大概率也从 10-30 起断供，修复要走 [发布流程](../docs/deployment/RELEASING.md)。
