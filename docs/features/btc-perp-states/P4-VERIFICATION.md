# P4 核验记录

日期：2026-10-17，约 01:59–02:35 UTC。分支 `claude/perp-states`，范围见 [PLAN-P4](PLAN-P4.md) v3 和 [SPEC](SPEC.md) v3.1。

## 1. 全量检查

| 项目 | 结果 |
|---|---|
| `make check` | ruff 通过；mypy strict 47 个源文件无问题；pytest 572 passed；type-check 通过；vitest 22 个文件 294 个测试通过 |
| `deploy/test/test_composition.py`（不在 `make check` 范围内，单独运行） | 1 passed，断言 perps 的 worker 和采集器都没有启动 |
| 测试不访问外网 | Task 5b 的审查在屏蔽 DNS 和 connect 的条件下运行了 175 个 perps 测试，没有发起任何连接 |

## 2. 规则对照（本地，不入库；P4-D9、P4-R2）

脚本 `.local/research-samples/alpha-dashboards-2026-10-16/perp-squeeze/tools/states_parity.py` 把原站的 `/api/perps` 样本（Glassnode，2026-10-16 10:49Z）构造成全覆盖的网格，再交给 `states.compute_states` 计算。对照基准是复算脚本 `perp_parity.py`（它已在页面上逐项核对过），比较的结果如下：

| 视图 | 块长 | Show | 排名块 | 在视图内 | 阈值 | 计数 | Max move | Prob. |
|---|---|---|---|---|---|---|---|---|
| all | 4h | 7d | 543 | 42 | 一致 | 一致 | 一致 | 5/9/0/0/0/5/14/67 |
| all | 4h | 30d | 543 | 180 | 一致 | 一致 | 一致 | **4/8/4/2/3/3/12/64，与页面一致** |
| all | 8h | 7d / 30d | 271 | 21 / 90 | 一致 | 一致 | 一致 | — |
| binance | 4h、8h | 7d、30d | 543 / 271 | — | 一致 | 一致 | 一致 | — |
| bybit | 4h、8h | 7d、30d | 543 / 271 | — | 一致 | 一致 | 一致 | — |

12 种组合全部一致，阈值逐位相同（`ALL MATCH`）。原站样本中没有 null，所以缺失数据的处理路径由合成数据的单元测试覆盖。

## 3. 日包与 hist 对照（spec §3.1 的决策分支）

脚本 `.local/research-samples/perp-free-data-2026-10-17/tools/archive_vs_hist.py` 使用项目自己的 `PerpsRest`，比较 2026-09-19 到 10-15 共 27 天：

- 7776 行中，7618 行与 hist 的同一时刻对上；隔离之后，相对误差 > 0.1% 的行为 **0（0.00%）**；
- 只有 **10-15** 一天被隔离，共 158 行（10:50 起至当天结束），与回归 fixture 一致；
- 不一致率低于 1%，所以**继续用日包补足 29 天以前的 OI**，不必改为只用 hist。

## 4. 本机实测（01:59:38 启动；perps 默认开启）

**回填与增量**
- 首轮回填用时 61.8 秒；第二轮 82.4 秒（补齐首轮中失败的部分）；之后每轮约 23 秒。
- 共 263 个请求：Bybit 162 个，data.binance.vision 63 个，fapi 38 个，全部在限速之内。
- 入库：Binance OI 共 26235 个点（日包 17880 个 + hist 8355 个，分界在 29 天前），Bybit OI 26236 个点，两家 kline 各 26235 根，都覆盖 2026-07-18 到当前。
- **网络波动**：本机到 `fapi.binance.com` 和 `api.binance.com` 一度整体超时，之后到 `api.bybit.com` 也出现一次超时。worker 记下 `rest_error:<host>:network`，其他 host 照常；下一轮自动补齐。视图把这条原因如实显示出来。

**采集器**
- 3 个流 × 2 条连接都在线；每条连接只有一条覆盖记录，没有被切分。
- 约 25 分钟内：Binance 清算 4 笔，`X` 全为 `FILLED`；Bybit 清算 0 笔；Bybit 成交约每分钟 179 笔。
- 资源：服务进程的 CPU 约 1.5%（包括采集、回填和 API），RSS 约 60 MB，`perps.sqlite` 约 7.9 MB。

**视图**
- 3 个交易所视图都是 `fresh`，处于 `collecting`（覆盖 0.0 天，未到 7 天）。
- QC 没有失败项。原因码包括 `collecting:0.0`，以及当时的 `rest_error`。
- 方向核对为 `pending`（样本为 0）。

## 5. 浏览器核验（:1420，实时数据）

**1440px**
- 页头：`Resolution 10m · Data through 2026-10-17 02:10 UTC · Price Bybit spot · OI/flows … · liquidations collected since 2026-10-17`。
- 覆盖说明逐流列出天数。
- 显示 Binance 清算标注和 Collecting 横幅。
- Parameters 可用。
- 表 1、图 1、图 2 按 collecting 规则隐藏。
- 图 3：OI 124k BTC，即 Binance 约 95k 加上 Bybit 单边约 29k，另有 BTC/USD 线。
- 图 4：采集开始前的块都标为未覆盖，没有画成 0。
- 每张图下方都有三栏说明。

**390px**
- `scrollWidth = 390`，没有横向溢出。
- URL 参数 `pw=8h&ps=7` 正确反映在按钮的选中状态上。
- 三栏说明没有收进 `<details>`。
- perps 请求都返回 200。

## 6. 需要 test 环境采集满 7 天后才能完成的项目

1. **方向核对**：Binance 和 Bybit 各需要 ≥20 个下跌桶，判定为 ok 或 inverted；还要核对 Bybit `v` 的单位统计。
2. **覆盖块占比**：4h 下应 ≥80%，否则重新评估覆盖规则（spec §6）。
3. **表 1、图 1、图 2 的实际显示**：判定状态后，在浏览器里对照 mockup 再看一遍。
4. **用 `problems` 解释空洞**：`/perps/status` 的 `collectors[].problems` 是本进程启动以来各流的计数（两条连接合计）。`rotated`、`stopped` 是正常生命周期；`stalled`、`half_open`、`connect_failed`、`closed`、`no_ack`、`coverage_split`、`bad_frame`、`unexpected_frame` 等都可能对应空洞。覆盖块占比不达标时，先拿这些计数解释空洞。如果 `stalled` 占多数，考虑在短暂间隔后仍承认读到的帧，或者把提交移到单独的写线程。
5. **部署攒在一起做**：每次重新部署 analytics，两条连接同时断开，至少留下一个未覆盖块（发布流程已写明）。7 天的采集期内尽量少部署。
6. **日包和 hist 在同一个 OI 缺口里是耦合的**：Binance OI 的一个缺口由日包和 hist 两个 host 一起补，任一个失败，这个缺口就整体留到下一轮，不会在两者之间留下洞；代价是一个 host 的故障也会拖住另一个的那部分。

权威的采集端是 test 环境（P4-D11）。部署时要放行出站 WebSocket，见发布流程。

## 7. 范围外的观察

市场页 `Market intelligence` 每 3–5 秒轮询一次 `workspace?source=…`，并在任务运行期间轮询 jobs。这个行为在 P4 之前就已存在，与 perps 无关，标签页长时间运行会累积大量请求。可以作为后续优化。

## 8. 终审

整支分支（HEAD 93d5ed4）通过了各任务的评审和一次整支终审。终审没有发现阻断问题，提出两项 Important 和一组小问题，本轮一次修完（简报 `.superpowers/sdd/PLAN-P4/final-fix-brief.md`）。

**改动**

| 项目 | 提交 | 内容 |
|---|---|---|
| A 清算的解析与汇总（Important） | f4a5088 | 迁移 002 给 `liquidations` 加 `longs`、`qty`、`price` 三列，用 `json_extract` 按 spec 的映射回填旧行；入库时由 `store.liquidation_fields` 填写（Python 中唯一一份映射，`raw_json` 保留以便重新映射）。网格的清算改为 SQL 按桶汇总（同一 key 取各连接次数的最大值，key 的时刻取最早），`qty_units` 也改为 SQL；一次派生中每家只读一次 |
| B 采集器故障可解释（Important） | fa45351 | 除 `rotated`、`stopped` 之外的连接结束记 WARNING（带 stream、conn、code）；每个流的连接结束码和问题码按进程累计，作为 `CollectorStatus.problems` 返回，采集器不在本进程运行时为空；`make contract`、zod 与样本同步 |
| C.1–C.5、C.7 | 3109109 | 停机先通知 worker，worker 在下一个请求前放弃本轮（不派生，照常裁剪，已问过的 host 状态保留）；test 的 analytics 加 `stop_grace_period: 30s`。意外的帧（Bybit 其他 topic、Binance 非 `forceOrder`）计为 `unexpected_frame` 并切分覆盖。各交易所视图按自己的方向核对，`inverted` 时显示提示。perps 关闭时原因码为 `perps_disabled`。`Block` 的补值字段加注释。不再写没人读的 `sync_state.reasons`；`stored_hosts` 只留一份；缺口检测只读时间戳。补测试：能力测试关闭 perps、套接字级的断网测试、Bybit 失败而 Binance 照常、`sync_failed`、经 worker 的日包隔离 |
| C.6、C.8 | 本提交 | 发布流程写明 perps 的出站网络、开关、部署后检查和攒批部署；spec 与本记录更新 |

**清算汇总的基准**（复制评审留下的数据库后测量，不入库；一次派生 = 六份载荷 + 方向核对，单进程峰值 RSS）

| 数据库 | 改动前（93d5ed4） | 改动后 |
|---|---|---|
| `rv-liq.sqlite`：约 100 万行合成 Binance 清算，91 天，两条连接 | 7.40 s / 7.61 s，峰值 755 / 731 MB | 1.69 s / 1.56 s，峰值 82 / 80 MB（约快 4.5 倍，内存约为原来的 1/9）；迁移 002 一次性 3.14 s |
| `perps-copy.sqlite`：本机实测数据 | 0.22 s，77 MB | 0.21 s，78 MB |

- 两个库上，改动前后派生出的六份载荷和方向核对逐项相同（浮点差 ≤ 1e-9）。
- `EXPLAIN QUERY PLAN`：查询走已有的 `liquidations_venue_ts`（`venue=? AND event_ts>?`），GROUP BY 用临时 B 树。试过覆盖索引 `(venue, event_ts, key, conn, longs, qty)`：单次查询约快 0.1–0.5 秒，但库文件大 25%（100 万行多 70 MB），写入也更慢，所以没有加。以 `(venue, key, conn)` 开头的索引不被规划器选用。

**检查**

| 项目 | 结果 |
|---|---|
| `make check` | ruff 通过；mypy strict 47 个源文件无问题；pytest 593 passed；type-check 通过；vitest 22 个文件 302 个测试通过 |
| `deploy/test/test_composition.py` | 1 passed |
| 测试不访问外网 | 屏蔽 DNS 和 inet connect 后运行 196 个 perps 测试，没有任何连接尝试 |
| 浏览器 | 用 `start_worker=False` 的临时服务和合成数据库（Binance 核对 ok、Bybit inverted）另起一个 Vite 检查：Bybit 视图显示 `Liquidation sides look inverted on Bybit: squeeze labels may be swapped`，squeeze 标签带 `(direction unverified)`；Binance 视图没有提示，标签不带后缀；All venues 视图显示 Bybit 的提示；390px 下 `scrollWidth = 390`；中文文案正常 |
