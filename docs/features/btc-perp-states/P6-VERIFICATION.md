# P6 核验记录

日期：2026-10-19，约 11:05–11:25 UTC 做浏览器与降级核验，V2 取数在 11:10:52 UTC。分支 `claude/coinalyze`，代码范围 `f0f9d0c..25e6329`（Task 1–4，最后一个代码提交是 25e6329），文档提交 d4ac5bc。方案见 [PROPOSAL-COINALYZE](PROPOSAL-COINALYZE.md) v3.1，计划见 [PLAN-P6](PLAN-P6.md)，规则见 [SPEC](SPEC.md) v4 一节。

## 1. 全量检查

代码为 25e6329；Task 5 只改文档，不影响这些检查。

| 项目 | 结果 |
|---|---|
| `make check` | 退出码 0。ruff 通过；mypy strict 52 个源文件无问题；pytest **936 passed**（P6 之前为 823）；type-check 通过；vitest 24 个文件 **446** 个测试通过（P6 之前为 436） |
| `deploy/test/test_composition.py`（不在 `make check` 范围内，单独运行） | 1 passed，断言 perps 的 worker 和采集器都没有启动 |
| 测试不访问外网 | 按设计不访问：客户端测试用 `httpx.MockTransport`，同步测试用 `FakeCoinalyze`，API 测试走注入的 `perps_http`；`conftest.py` 的 autouse 把 key 置为空串并让 `.env` 指向不存在的文件，没有测试读真实的 key。这次没有另做屏蔽 DNS 的运行 |

## 2. 规则对照（本地，不入库；P4-D9、P6-R6）

脚本 `.local/research-samples/alpha-dashboards-2026-10-16/perp-squeeze/tools/states_parity.py` 扩到 hyperliquid（原脚本备份在同目录 `states_parity.py.bak-p6`）：原站样本没有 Hyperliquid 的清算，与 `perp_parity.py` 一样用 All 的清算和 OI 估算，调用本分支的 `grid.estimate_liquidations`（全部桶已覆盖）。all/4h/30d 的页面核对不变。比较结果如下：

| 视图 | 块长 | Show | 排名块 | 在视图内 | 阈值 | 计数 | Max move | Prob. |
|---|---|---|---|---|---|---|---|---|
| all | 4h | 7d | 543 | 42 | 一致 | 一致 | 一致 | 5/9/0/0/0/5/14/67 |
| all | 4h | 30d | 543 | 180 | 一致 | 一致 | 一致 | **4/8/4/2/3/3/12/64，与页面一致** |
| all | 8h | 7d | 271 | 21 | 一致 | 一致 | 一致 | 0/9/0/0/0/5/19/67 |
| all | 8h | 30d | 271 | 90 | 一致 | 一致 | 一致 | 5/7/1/2/1/4/17/63 |
| binance | 4h | 7d | 543 | 42 | 一致 | 一致 | 一致 | 5/10/2/5/2/2/10/64 |
| binance | 4h | 30d | 543 | 180 | 一致 | 一致 | 一致 | 5/8/4/6/2/3/10/62 |
| binance | 8h | 7d | 271 | 21 | 一致 | 一致 | 一致 | 0/9/0/5/5/0/19/62 |
| binance | 8h | 30d | 271 | 90 | 一致 | 一致 | 一致 | 6/7/1/7/2/2/11/64 |
| bybit | 4h | 7d | 543 | 42 | 一致 | 一致 | 一致 | 2/10/7/2/5/7/7/60 |
| bybit | 4h | 30d | 543 | 180 | 一致 | 一致 | 一致 | 4/7/6/3/3/6/10/61 |
| bybit | 8h | 7d | 271 | 21 | 一致 | 一致 | 一致 | 0/10/0/10/0/9/9/62 |
| bybit | 8h | 30d | 271 | 90 | 一致 | 一致 | 一致 | 4/6/4/6/0/7/12/61 |
| hyperliquid | 4h | 7d | 543 | 42 | 一致 | 一致 | 一致 | 5/10/0/2/2/0/12/69 |
| hyperliquid | 4h | 30d | 543 | 180 | 一致 | 一致 | 一致 | 4/8/1/5/7/2/11/62 |
| hyperliquid | 8h | 7d | 271 | 21 | 一致 | 一致 | 一致 | 0/10/0/0/0/0/19/71 |
| hyperliquid | 8h | 30d | 271 | 90 | 一致 | 一致 | 一致 | 6/7/2/5/3/0/11/66 |

Prob. 的顺序：short squeeze、long squeeze、short unwind、long unwind、new long、new short、spot-led、chop。16 种组合全部一致，最后一行 `ALL MATCH`。原站样本中没有 null，缺失数据的处理路径由合成数据的单元测试覆盖。

## 3. V1：Coinalyze 实测

V1 在 2026-10-19 用免费 key 完成，结果见方案 [§2.1](PROPOSAL-COINALYZE.md)，原始响应在 `.local/coinalyze-v1/`，不入库。要点：
- 4hour 对齐到 UTC 00/04/08…；没有清算的区间不返回；不用分页（4hour 一次约 334 天）；
- 48 个 5min 之和与 4hour 逐位相等（只有 OKX 10-15 20:00 的 `s` 例外）；
- `l` 是多头被强平，单位 BTC；与本机自采的事件逐个 5min 桶对照，Binance 131 桶、Bybit 132 桶全部相等；
- Binance 的清算与自采的 forceOrder 完全相同，仍是每秒快照；
- Coinalyze 自身有断档（Binance 2026-04-23 20:00 起连续 4 个 4h 窗口无清算点）。

## 4. V2：自采清算与 Coinalyze 4hour 的块合计对照

**方法**
- **自采数据**：`.local/analytics-verify/perps.sqlite`，是主工作区 `.local/analytics` 在约 11:00 UTC 的 `sqlite3 .backup` 副本，只读打开。清算按 `PerpsStore` 的口径去重（`probe.py` 的 `local_liq`：同一 key 取各连接次数的最大值），按 4h 窗口汇总；覆盖用 `coverage` 表中各流（`binance_liq`、`bybit_liq`）的并集（`probe.py` 的 `spans`）。
- **Coinalyze 一侧**：用本分支的客户端 `Coinalyze(PerpsRest(), key).history("liq", "4hour", 2026-10-16 00:00 UTC, now)` 取一次，在 11:10:52 UTC，**3 次计费调用**，key 没有打印。每家返回 20 个已收盘窗口（10-16 00:00 至 10-19 04:00）。
- **脚本与输出**：`.local/p6-verify/v2_compare.py`、`v2-output.txt`，Coinalyze 一侧的数据在 `v2-cz-liq-4hour.json`（不含 key），均不入库。
- **分类**：整窗落在覆盖并集内的为 strict；整窗中未覆盖不超过 120 秒的为 near；其余有部分覆盖的为 partial。部分覆盖的窗口，我们的合计不应大于 Coinalyze（缺口里的事件我们会漏，但不会凭空多出来）。

**为什么 strict 不可能。** 本机自采的两条连接在每次服务重启时同时断开，留下 20–60 秒的空洞（例如 10-19 的 04:56:10→04:56:57、08:02:29→08:02:52、08:15:20→08:16:02）。覆盖并集里最长的连续段只有 3.09 h（10-19 04:56:57–08:02:29），不足一个 4h 窗口，所以没有任何窗口整窗落在并集内：Binance、Bybit 的 strict 窗口数都是 **0**。这与 P4-D11 的判断一致：本机的自采覆盖不完整，不能当作权威。

**结果**（单位 BTC；L 为多头，S 为空头）

| 交易所 | 窗口（UTC） | 覆盖 | 未覆盖 s | 自采 L | Coinalyze L | 自采 S | Coinalyze S | 最大绝对差 | 类别 |
|---|---|---|---|---|---|---|---|---|---|
| Binance | 10-17 00:00 | 1.99 h | 7224 | 1.1070 | 11.1630 | 0.4530 | 2.1030 | 10.0560 | partial |
| Binance | **10-17 04:00** | 3.98 h | 66 | 0.0090 | 0.0090 | 2.0220 | 2.0220 | **0.0000** | near |
| Binance | 10-17 08:00 | 1.23 h | 9954 | 0.0000 | 0.3570 | 0.0000 | 0.0300 | 0.3570 | partial |
| Binance | 10-17 16:00 | 0.67 h | 12001 | 5.0600 | 6.5440 | 0.0000 | 5.5200 | 5.5200 | partial |
| Binance | 10-18 12:00 | 1.15 h | 10249 | 12.5130 | 38.1700 | 0.5430 | 0.6300 | 25.6570 | partial |
| Binance | 10-19 04:00 | 3.10 h | 3254 | 0.7760 | 1.0060 | 37.8500 | 44.6730 | 6.8230 | partial |
| Bybit | 10-17 00:00 | 1.99 h | 7230 | 0.0950 | 0.3150 | 0.1590 | 0.1630 | 0.2200 | partial |
| Bybit | **10-17 04:00** | 3.99 h | 26 | 0.0000 | 0.0000 | 0.0030 | 0.0030 | **0.0000** | near |
| Bybit | 10-17 08:00 | 1.24 h | 9923 | 0.0000 | 0.0030 | 0.0000 | 0.0090 | 0.0090 | partial |
| Bybit | 10-17 16:00 | 0.67 h | 11996 | 1.4060 | 1.7670 | 0.0300 | 0.6560 | 0.6260 | partial |
| Bybit | 10-18 12:00 | 1.15 h | 10244 | 10.7170 | 18.2540 | 0.0000 | 0.0030 | 7.5370 | partial |
| Bybit | 10-19 04:00 | 3.10 h | 3251 | 0.1740 | 0.2010 | 5.5390 | 7.0200 | 1.4810 | partial |

| 项目 | Binance | Bybit |
|---|---|---|
| strict 窗口数 | 0 | 0 |
| near 窗口数（10-17 04:00） | 1 | 1 |
| near 窗口的最大绝对差 / 最大相对差 | 0.000000 BTC / 0 | 0.000000 BTC / 0 |
| 有部分覆盖的窗口数 | 6 | 6 |
| 自采大于 Coinalyze（应为 0） | 0 | 0 |
| 自采小于 Coinalyze（缺口里的事件） | 5 | 5 |

**补充（没有额外的 Coinalyze 调用）**：服务自己存进 `cz_series` 的 5min 清算行（该副本上由本分支的第一轮 worker 写入，见 §5），与自采事件在**完整覆盖的 5min 桶**上对照：

| 交易所 | 存储的 5min 行 | 完整覆盖的桶 | 其中 Coinalyze 有清算的桶 | 最大绝对差 | 不相等的桶 |
|---|---|---|---|---|---|
| Binance | 85（10-19 04:00–11:00） | 70 | 41 | 0.000000 BTC | 0 |
| Bybit | 85（同上） | 70 | 23 | 0.000000 BTC | 0 |

**结论**
- 严格意义上"整窗覆盖的块合计"在这份数据上做不到（见上，窗口数为 0）。
- 缺口很小的 near 窗口（10-17 04:00–08:00）上，两家的多头、空头合计与 Coinalyze **逐位相等**。Binance 的空头合计为 2.022 BTC，不是零对零。
- 6 个部分覆盖的窗口里，自采合计都不大于 Coinalyze，没有一个多出来；少的部分落在未覆盖的时段里。
- 70 个完整覆盖的 5min 桶全部相等。这与 V1 的逐桶结论和"48 个 5min 之和 = 4hour"一起，支持"覆盖到的部分两者相等"，但不是方案原本要求的整窗对照。
- 剩下 3 次计费调用的预算没有用。若要补强，可以再取 binance、bybit、okx 的 5min 清算（3 次），按"自采覆盖到的 5min 桶"汇总到 4h 窗口再比。

## 5. 首轮 worker（新进程，数据拷自主工作区）

分支的代码跑在 :8797，数据目录是主工作区 `.local/analytics` 的 `sqlite3 .backup` 副本（`.local/analytics-verify`）。采集器关闭（默认）。key 取自仓库根目录 `.env` 的符号链接。

- `/perps/status`：四个 host 都正常，`api.coinalyze.net` 的 `last_success` 为 11:07:46。
- `markets`：binance、bybit、okx、hyperliquid 四项都是 `ok`。
- 方向核对：合并结论 `ok`。binance 89 个样本、43 个下跌窗口、多头占比 0.889；bybit 89 / 43 / 0.909；okx 89 / 43 / 0.837。
- 八个视图（4 个交易所 × 4h/8h）都是 `fresh`，最后一个桶 10:50 UTC，`covered_days` 为 90.5（4h）/ 90.3（8h），`collecting` 为 false，`qc` 和 `reasons` 为空。
- 与最近 30 天视图重叠的块：4h 181 块，8h 90 块，没有未覆盖块。
- 表 1（30d）已判定块：4h 为 179/180（forming 块在 O1 下不判定），8h 为 90/90。

## 6. 浏览器核验

**1440px**：在真实的 1440×900 弹窗里做（主窗口是全屏），四个交易所 × 4h/8h，Show = 30d。
- `scrollWidth = 1440`，没有横向溢出；
- 4 个图表 SVG，0 个未覆盖标记；
- 表 1 已判定 179/180（4h）、90/90（8h）；
- `(estimated)` 只出现在 hyperliquid 视图：3 处（清算带的标签，加悬停中的 2 行），另有 HL 说明行；
- Binance 下限标注在 all、binance、hyperliquid 视图显示，bybit 视图不显示；
- URL 参数 `px`/`pw`/`ps` 正确反映在按钮的选中状态上。

**主窗口 2056px，all/4h/30d**
- 页头一行，其后是带 Coinalyze 链接的来源行、`Liquidation history: 90.5 d covered in the last 90`、规则行、Binance 标注；
- Parameters 里 Exchange 有 4 个选项；
- 表 1 各状态占比 4/8/6/3/2/4/9/64（O1+O6），图 1–4 都有 30 天历史；
- 图 3 的 All OI 约 154k BTC（Binance 约 94k + Bybit 约 29k + OKX 约 30k）。

**390px 弹窗**
- **en**：`scrollWidth = 390`，没有元素越过右边缘。四个按钮的 Exchange 控件宽 299px（右边缘 329）。表 1 只留 State / Prob. [30d] / Max move 三列，What it is 收进 `<details>`。
- **zh**：`scrollWidth = 390`，没有溢出，Exchange 控件宽 300px。页头各行都是中文，包括 HL 说明。

hyperliquid 8h/7d 视图：控制台没有报错；HL 说明行在；阈值随估算缩放（short liq. 53.5 BTC，long liq. 68.9 BTC）；21/21 已判定。

## 7. 降级核验

每种模式都用主工作区数据库的新副本启动，副本里没有 `cz_series` 行（`.local/analytics-nokey`）。

**缺 key**（`WHEELHOUSE_COINALYZE_KEY=`，变量存在且为空）
- `/perps/status`：`api.coinalyze.net` 的错误为 `key_missing`，没有发出请求。
- all 视图：reasons 为 `series_missing:okx:oi`、`rest_error:api.coinalyze.net:key_missing`、`collecting:0.0`；qc 为 `missing:okx:oi`；清算已覆盖 0/181；`oi_close`、`delta_sum` 为 null。
- binance 视图：OI 照常显示（93760），delta 照常显示（−1750），清算未覆盖。
- bybit 视图：OI 照常显示（29114），delta 为 null，清算未覆盖。
- hyperliquid 视图：OKX、HL 的 OI 都是 `series_missing`，OI 为 null。
- 页面（all/4h）：提示 `Coinalyze API key not set: liquidations and Coinalyze flows unavailable`；**不显示** "history too short" 横幅；QC 和 series_missing 列出；表 1、图 1、图 2 隐藏；图 3、图 4 画出，图上有 362 个未覆盖标记。截图：`.local/p6-verify/shots/key-missing-all-4h.jpg`。

**key 无效**（假的 UUID）
- `api.coinalyze.net` 的错误为 `401`，没有 `backoff_until`；
- bybit 视图的 reasons 为 `rest_error:api.coinalyze.net:401`、`collecting:0.0`；
- 页面：`Coinalyze rejected the API key: liquidations and Coinalyze flows unavailable`，不显示横幅，Bybit 的 OI 线画出，图 4 为斜线；
- 假 key 在服务日志中出现 0 次。截图：`.local/p6-verify/shots/key-invalid-bybit-4h.jpg`。

## 8. 与原站的定性对照（用户决定 Q3）

原站 perp-squeeze（Glassnode）在已登录的浏览器里打开，数据截至 2026-10-19 10:50 UTC，没有输入密码。本地取同一个数据边缘（最后一个桶 10:50 UTC），为了逐项可比，在副本上用 v1 规则离线派生（`python -m wheelhouse_service.derive --rules v1`，不访问网络）。表 1，4h / 30d，格内为 Prob. %，括号内为 Max move：

| 视图 | 来源 | Short sq. | Long sq. | Short unw. | Long unw. | New long | New short | Spot-led | Chop |
|---|---|---|---|---|---|---|---|---|---|
| All | 原站 | 4 (+5.60) | 8 (−2.48) | 5 (+1.52) | 3 (−1.29) | 3 (+0.82) | 3 (−0.61) | 10 (+2.23) | 64 (+1.27) |
| All | 本地 v1 | 4 (+5.58) | 8 (−2.51) | 6 (+2.21) | 4 (−1.29) | 2 (+0.85) | 5 (−1.26) | 8 (+1.87) | 63 (+1.58) |
| Binance | 原站 | 4 (+5.60) | 8 (−2.48) | 4 (+2.23) | 6 (−1.29) | 3 (+0.82) | 3 (−0.72) | 10 (+1.92) | 62 (+1.07) |
| Binance | 本地 v1 | 4 (+5.58) | 8 (−2.51) | 5 (+2.21) | 7 (−1.29) | 4 (+1.87) | 3 (−0.74) | 8 (+1.53) | 61 (+1.07) |
| Bybit | 原站 | 4 (+5.60) | 7 (−2.48) | 7 (+2.23) | 3 (−0.34) | 4 (+1.10) | 5 (−1.65) | 10 (+1.52) | 60 (+1.21) |
| Bybit | 本地 v1 | 4 (+5.58) | 6 (−2.51) | 7 (+1.87) | 3 (−0.66) | 3 (+1.10) | 5 (−1.72) | 9 (+2.21) | 63 (+1.58) |
| Hyperliquid | 原站 | 4 (+5.60) | 9 (−2.48) | 2 (+1.52) | 4 (+0.69) | 7 (+1.05) | 2 (−1.49) | 10 (+2.23) | 62 (−1.40) |
| Hyperliquid | 本地 v1 | 4 (+5.58) | 9 (−2.51) | 2 (+2.21) | 6 (+0.71) | 7 (+1.06) | 1 (−1.29) | 10 (+1.87) | 61 (+1.27) |

- 每个占比与原站相差都在 3 个百分点以内，两个 squeeze 行的占比与走势一致，方向和量级一致。
- 页面实际使用默认的 O1+O6：all/4h/30d 为 4/8/6/3/2/4/9/64；其他视图与各自的 v1 数字相差在 2 个百分点以内。
- Max move 的差别来自价格源（本地 Bybit 现货，原站 Glassnode `price_usd_close`），以及块边缘处的段切分不同。

## 9. 代码与方案的差别

SPEC v4 写的是代码实际所做的事。与方案 v3.1 不同之处：
1. **多出一条 4hour 重取**：方案只在窗口收盘后 1 小时内重取最近 3 个窗口。代码（`sync._coinalyze`）在某家的最新 4hour 行落后于最新已收盘窗口时，也同样重取（起点为各家最新行的最小值再往前 2 个窗口）。不超出配额，但如果 Coinalyze 对某家始终不返回最新窗口（例如 OKX 的 OI），每轮都会触发。
2. **方向核对的价格变动**：方案只写"窗口内价格变动 ≥1%"。代码取 Bybit 现货的窗口第一个桶价格到最后一个桶价格（开盘于 `w+5m` 与 `w+4h−5m` 的两根 bar 的收盘），且窗口有清算（`l + s > 0`）、不是 `filled`。
3. **单位核对的时机**：在一轮的各类历史都取成功之后才读 `/future-markets`；前面的请求失败时顺延到下一轮。方案只写每天一次。
4. **回填记录**：各类 4hour 的回填起点存在 `sync_state` 的 `cz_4h:<kind>`，而不是从数据推断。与方案的条件等价。
5. `/perps/status` 在新的 `direction_check{binance,bybit,okx}` 之外保留合并的 `direction`，与方案"HL 视图沿用 All 的合并结论"一致。

## 10. 待补

**4hour 刚收盘值的稳定性**（方案 §3.2、§6 V2）：收盘于 2026-10-19 12:00 UTC 的 4h 窗口，在 12:06 和 13:06 UTC 各取一次它的 4hour 值（`.local/p6-verify/settle.py`，结果写入 `.local/p6-verify/settle.json`），看 1 小时内是否被更正。结果：**待补**，由取数的人在此处补写。

另外，发布到 test 之后还要做：在 Coolify 设好 `WHEELHOUSE_COINALYZE_KEY`，按 [发布流程](../../deployment/RELEASING.md) 的"Perps（永续状态）"一节核对 `/perps/status` 的 `api.coinalyze.net` 和 `markets`。发布要等用户说"发布 test"。

## 11. 未完成或与预期不同

**与预期不同**
1. **V2 的 strict 窗口数为 0**（§4）。方案要求"只比较完整覆盖的块"，本机自采覆盖被重启切碎，没有一个 4h 窗口整窗被覆盖。用缺口 ≤120 秒的 near 窗口（1 个）、部分覆盖窗口的不等式（6 个，无一违反）和完整覆盖的 5min 桶（70 个，全部相等）代替，没有达到方案原本的整窗对照。
2. **页面文案残留（小问题，按发现记录，未修；留给终审分类）**：
   - 图 1 的 "What it shows"（en；zh 大概同样）仍写灰色斜线标出的是"因为清算或 Bybit 成交的采集有缺口"而未判定的块。改用 Coinalyze 之后没有"采集"，应改为数据有缺口；
   - 图 4 的 "What it shows" 写的是 "that input was not collected for the block"，同样是过时的措辞；
   - 中文来源行里，全角冒号后面多一个空格，再接 Coinalyze 链接（"（Binance 的买卖量除外）： Coinalyze"）。
3. **:1430 上的 HTTP 403 是环境产物，不是 P6 的问题**：核验用的是本分支的 Wealthfolio 宿主（:1430）代理到 :8797。analytics 服务拒绝 Origin 不是 :1420 的 POST（`http.py` 的 origin 检查），所以市场页显示 "Python service unavailable (HTTP 403)"。perps 的接口都是 GET，不受影响。

**未做或未覆盖**
- 4hour 稳定性测量（§10）。
- 单位核对失败（`coinalyze_units`）、429 和 403 退避没有在浏览器里复现，只有单元测试覆盖；断档规则没有在真实数据上触发过（Binance 04-23 那一段不在 121 天的网格内），只有单元测试覆盖。
- 没有发布到 test，也没有在 Coolify 上用真实的 secret 验证；采集器的对照（开 `WHEELHOUSE_PERPS_COLLECTORS`）没有再跑。
- 这次核验在 Coinalyze 上的计费调用：V2 用了 3 次；首轮 worker 与降级模式的调用由 worker 自己按每进程每分钟 20 次限速，没有单独统计。
- 原站对照只有 4h / 30d 一个设定；数值不要求逐数相同，只比较方向和量级（用户决定 Q3）。
