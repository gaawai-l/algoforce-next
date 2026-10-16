# TradingSignal 跨周期摘要：主序列与字段映射

核验日期：2026-09-28（数据时刻为 UTC 2026-09-27 16:28:32，即 AlphaBTC `/api/td9` 服务端抓取时间 `1790526512`）。
本文为只读研究：没有访问 tradingsignal.pro，没有修改生产代码或测试。

## 结论

- 本地 v2 引擎（`wheelhouse-sequential-2` + `retain_active` + `strict_at_nine`）的 `DemarkResult` 可以**确定性地**投影成 across 摘要。
  - 5 个周期的 phase、step、setupStep、countdownStep、side/regime、rounds、second、setupRun 全部一致。
  - 15m、1h、4h、1d 的 lastSignal、prev、barsSinceQualified13 也一致。
  - 唯一不一致的是 5m 的 `prev.barsAgo` 和 `barsSinceQualified13`（TS 为 63，本地为 35）。已定位为行情源差异，与映射规则无关（见 §6）。
- **TS 的计算包含形成中的 bar**，用的是它缓存时刻的部分 OHLC。
  - 只用已收盘前缀时，5 个周期都有错位。
  - 用抓取时刻重建的形成中 bar，结果全部对齐。
- **历史窗口约 500 根**：用 500 根最吻合，300 根会丢字段，1000 根以上会多出 TS 没有的旧 13。
- risk 各字段的 DeMark 含义都已查明：
  - 在 TS 自己的行情上复算，残差为 0（15m 用用户导出的行情，1h 由导出的 15m 聚合而来）。
  - 在 Binance 现货上复算，残差为 0.1 至 65 USDT，全部可以由报价差解释。
- 由本地映射推出的 AlphaBTC s9/s13 与由 TS 快照推出的 5/5 一致：
  - 1h 为“阴跌爆拉 `pump`”，4h 为“突破减弱 `decay`”。
  - 第二个快照（asOf 1790526900）的 5 个周期状态也全部复现。

## 1. 证据来源与边界

- **参考数据：**TS 快照只有一个完整时点，外加约 10 分钟后的一个部分时点（只有 phase 和 step）。一致只代表这两个时点，不代表所有市场情形。
- **行情输入：**
  - Binance 现货 BTCUSDT，端点 `data-api.binance.vision/api/v3/klines`。
  - 5m、15m、1h、4h 各取 2000 根，1d 取 1500 根，再截取最后 N 根计算。
  - 另外取了 1m K 线（00:00–16:49）和 1s K 线（16:28:00–16:29:00），用来重建抓取时刻的形成中 bar，也用来补齐第二快照前缺的已收盘 5m bar。
- **15m 的行情：**前 499 根用用户导出的 TS 行情（`tests/demark/fixtures/tradingsignal-btcusdt-15m-candles.json`，已收盘部分），15:30 之后 4 根用 Binance。
  - 该导出比本快照早 3 根 15m。
  - 与 Binance 现货收盘价的平均差约 4.6 USDT，最大 51.7。
- **TS 各周期的缓存时刻不同：**1h 的 close 为 84578.3，其余多为 84592。因此形成中 bar 的具体数值无法逐一还原，本文只比较结构，价格残差单独列出。
- **可复跑脚本在仓库外：**
  - 目录：`/private/tmp/claude-501/-Users-gary-code-AlgoForceNext/766fdf7e-1bf6-49dd-af42-f417d07fde53/scratchpad/across/`
  - `across.py` 是投影实现，`compare.py` 做逐字段对照，`hybrid.py` 用 TS 行情聚合复算，`alpha.py` 推 AlphaBTC 状态，`snap2.py` 复现第二快照，`mc2.py` 做行情扰动测试。
  - 解释器为 `.venv-foundation/bin/python`。

## 2. 形成中 bar：两种口径对照

asOf 等于最新 bar 的开盘时间；抓取时 5 个周期的这根 bar 都还没收盘。

| 输入口径 | 结果 |
|---|---|
| **含形成中 bar**（用 1m/1s 重建到 16:28:32） | 结构字段全部一致；5m 的 prev 除外，见 §6 |
| 只用已收盘 bar（到 asOf 前一根） | 5 个周期都错位：15m 的 side 变成 SELL；1h 的 step 为 2（TS 为 3）；5m 的 second.step 为 5（TS 为 6）；1d 的 second 变成 BUY 2（TS 为 SELL 1）；所有 barsAgo 少 1 |
| 5m 的 asOf bar 取最终收盘值 | 16:25 那根收盘后变成 BUY setup 1，与 TS 的 SELL 6 不符。说明 TS 用的是部分 bar |

还有一个佐证：1h 的 `nextBarNeeds = 85030.5`，正好是 13:00 那根 1h bar 的收盘价，也就是 `close[last-3]`，其中 last 是 16:00 那根形成中 bar。如果只用已收盘 bar，参考 bar 应该是 12:00。

## 3. 映射规则（伪代码，使用本地模型字段）

```text
输入  r = evaluate_demark(bars, v2)，bars 含形成中的末根，并取最后 500 根；last = len(bars)-1
ACTIVE = {active, count13_unqualified}
seqs = [s for s in r.sequences if s.continuity == "observed"]      # 按 setup 起点排序
done = [s for s in seqs if s.setup_status == "completed"]
run  = seqs[-1]                                   # 当前 setup 连续段，对应 TS 的 setupRun
act  = [s for s in seqs if s.countdown_status in ACTIVE]   # v2 下最多 1 条
t9(s)  = s.setup_bars[8].open_time;   t13(s) = s.countdown_bars[-1].open_time
idx(b) = bar b 在 bars 中的下标;       REG(buy) = down, REG(sell) = up

# 主序列 P 与 phase
if act:  P = act[0]; phase = countdown; target = 13
         step = countdownStep = P.countdown_count
         setupStep = run.setup_count  if run is not P and run.side == P.side
                     else P.setup_count            # 即 9
else:    P = run; phase = setup; target = 9
         step = setupStep = run.setup_count; countdownStep = 0
side = P.side;  regime = REG(side)

# rounds（规则 B：同方向链条）
chain = []
for s in done (按 t9 升序):
    if chain and (s.side != chain[0].side
                  or 存在 c ∈ chain 满足 c.countdown_status == qualified13 且 t13(c) < t9(s)):
        chain = []                                # 反向 9 或 13 之后又出现新 9：重新开始
    elif chain and s.countdown_status == inactive and not s.setup_perfected:
        continue                                  # 被 retain_active 压住、未完善的同向 9 不列入（2026-09-28 补充）
    chain.append(s)
if not act and chain and chain[0].side != run.side and 链中没有风险位仍有效的合格 13: chain = []   # 2026-09-28 补充
if run not in chain: chain.append(run)
rounds[i] = {side, regime, setup: s.setup_count, countdown: s.countdown_count,
             establishedTs: t9(s)   (仅 setup completed),
             exhaustedTs:   t13(s)  (仅 qualified13)}

# prev：最近一次结束的 Countdown
F = [s ∈ seqs 且 s ≠ P，countdown_status ∈ {qualified13, cancelled, recycled}，countdown_count ≥ 1]
prevS = F 中 idx(s.countdown_bars[-1]) 最大的一条
prev  = {side, countdown: prevS.countdown_count, qualified: status == qualified13,
         barsAgo: last − idx(prevS.countdown_bars[-1])}     # 取消的序列从最后一个计数 bar 起算

# lastSignal：看 rounds[0] 自身；它没有信号时退回 prev 的信号
r0 = chain[0]
lastSignal = {13, t13(r0)}       if r0 为 qualified13
           = {9,  t9(r0)}        elif r0 已完成 setup
           = prevS 的 13 或 9    otherwise

# second：只在 countdown 阶段、且当前 setup 段不是 P 本身时出现
second = {phase: setup, side: run.side, regime, step: run.setup_count, target: 9,
          lastSignal: {9, t9(run)} 仅当 run 已完成}

barsSinceQualified13 = min(s.bars_since_qualified13 for s in seqs if 非空)   # 不分方向
setupRun = {start: run.setup_bars[0].open_time, side: run.side, n: run.setup_count,
            active: run.setup_status == forming, completed: run.setup_status == completed}
asOf = bars[last].open_time;  close = bars[last].close
```

**规则要点：**

- **同向保留 vs 新的同向 9（4h 的情形）：**
  - 主序列仍是保留下来的 Countdown（从 9 月 22 日的 9 起算，当前第 8 根）。
  - 被 `retain_active` 压住的新 9（9 月 27 日 12:00）既进入 `second`（step 9，带 lastSignal），也是 `rounds[1]`（countdown 为 0）。
  - `lastSignal` 仍取旧的那一轮。
  - `setupStep = 9`。
- **Countdown 进行中又出现新 Setup：**
  - 新 Setup 反向（5m 首个快照，SELL 6）：`setupStep` 保持 9。
  - 新 Setup 同向（1d 的 SELL 1；5m 第二快照的 BUY 3）：`setupStep` 取这段新 Setup 的计数。
  - 第二快照中 5m 为 countdown 5 / setupStep 3，本地复现一致，印证了这条规则。
- **13 之后（1h、15m）：**
  - 没有活动 Countdown 时，phase 为 setup，主序列是当前的 setup 段。
  - 1h：当前 setup 段与刚走完 13 的那轮同向，那一轮保留在 rounds 中；lastSignal 为 13；provisional 为 false。
  - 15m：当前 setup 段反向，rounds 只剩当前这一段；lastSignal 退回 prev 的 13。
- **已取消的 Countdown（1d）：**
  - prev 为 BUY countdown 5，qualified 为 false。
  - barsAgo 为 44，从最后一个计数 bar（8 月 14 日）起算，而不是从 TDST 突破取消的那根（8 月 21 日）起算。

## 4. 逐周期对照

以下为 500 根、含形成中 bar 的结果。15m 使用 TS 导出的行情，其余周期使用 Binance。

| 周期 | TS 的主序列与状态 | 本地投影 | 结果 |
|---|---|---|---|
| 5m | BUY countdown 3（9 在 14:55）；second 为 SELL 6；prev 为 SELL 13，barsAgo 63 | 除 prev 外全部相同；prev 为 SELL 13，barsAgo 35（13 在 13:30） | 结构 ✓；prev ✗（行情源，见 §6） |
| 15m | BUY setup 1；rounds 只有 [BUY 1]；lastSignal 为 SELL 13（01:45）；prev barsAgo 58 | 全部相同 | ✓。只用 Binance 时 13 落在 02:00，晚 1 根 |
| 1h | BUY setup 3；rounds 为 [BUY 9（9 月 23 日 14:00）→13（9 月 25 日 21:00），BUY 3]；prev barsAgo 43 | 全部相同 | ✓（`strong` 字段未复现） |
| 4h | SELL countdown 8；rounds 为 [SELL 9（9 月 22 日），SELL 9（9 月 27 日 12:00，countdown 0）]；second step 9；prev 为 SELL 13（9 月 21 日 16:00），barsAgo 36 | 全部相同 | ✓ |
| 1d | SELL countdown 9（9 在 8 月 25 日）；second 为 SELL 1；setupStep 1；prev 为 BUY countdown 5，未合格，barsAgo 44；barsSinceQualified13 250 | 全部相同（250 根前是 2026-01-20 的 BUY 13） | ✓ |

**第二快照：**抓取时刻取 16:36 至 16:40 的任意一分钟，5m 为 countdown 5 / setupStep 3，15m 为 setup 1，1h 为 setup 3，4h 为 countdown 8，1d 为 countdown 9，全部与 TS 相同。

## 5. risk 字段的 DeMark 含义

公式中的 `side` 指主序列方向，即 `P.side`。

| 字段 | 公式（本地字段） |
|---|---|
| `risk9`, `risk9Ts` | 取 side 方向最后一次完成的 Setup，记为 S9；被 `retain_active` 压住、countdown 为 0 的也算。<br>这就是 TD Setup 的风险位：<br>• buy：9 根中 true low 的最小值，减去该 bar 的 true range（true high − true low）；<br>• sell：9 根中 true high 的最大值，加上该 bar 的 true range；<br>• 出现并列时取最早的一根。<br>`risk9Ts = t9(S9)` |
| `setupClose` | `S9.setup_bars[8].close`，即第 9 根的收盘价。AlphaBTC 信号 1 用的就是这个价格。<br>2026-09-28 补充：S9 的 countdown 已开始计数后被取消时为 null（risk9 仍保留） |
| `riskLevel`, `risk13Ts` | 窗口内 side 方向最后一次合格 13，记为 R13。取它的 `risk_level` 和 `t13(R13)`，不看 `risk_status`。<br>公式与本地 `countdown_span_true_extreme_earliest` 一致 |
| `close13` | 仅当 `prev.qualified` 且 `prev.side == side` 时取 `prevS.confirmation_close`，否则为 null |
| `provisional` | `not (R13 is rounds[0] 那一轮)`。本快照中等价于 `lastSignal` 不是 side 方向的 13 |
| `tdst` | phase 为 countdown 时取 `P.tdst`；phase 为 setup 时取最后一次完成的 Setup（不分方向）的 `tdst` |
| `nextBarNeeds` | phase 为 countdown 时取 `P.next_conditions[purpose=countdown]`：buy 为 close ≤ low[last−1]，sell 为 close ≥ high[last−1]。<br>phase 为 setup 时取 `run.next_conditions[purpose=setup]`：close 对比 close[last−3]。<br>操作符为 `<`/`<=` 时方向记为 below，否则记为 above |

**残差：**本地值减 TS 值，单位 USDT。“TS 行情”一栏是用 TS 自有行情复算的结果；“—”表示该字段没有做这项复算，只有 Binance 残差。

| 周期 | risk9 | setupClose | riskLevel | close13 | tdst | nextBarNeeds | TS 行情复算 |
|---|---:|---:|---:|---:|---:|---:|---|
| 5m | +21.19 | +3.42 | null ✓ | null ✓ | −8.69 | +13.20 | — |
| 15m | 0 | 0 | 0 | null ✓ | 0 | +7.83 | 导出行情；15:30 那根取 Binance 的最终值 |
| 1h | +15.72 | −3.51 | +32.03 | +3.40 | −15.87 | −0.09 | 由导出 15m 聚合：**全部为 0** |
| 4h | −64.54 | +7.17 | −27.02 | −9.89 | −16.97 | −7.07 | 聚合后 risk9 与 nextBarNeeds 为 0 |
| 1d | −20.56 | +9.34 | null ✓ | null ✓ | +4.00 | −11.82 | — |

- **4h 的 risk9 残差最大（−64.5）。**原因是 TS 在 15:00 有一根下影到 84313.6，Binance 的低点只有 84364。在 `high + (high − low)` 中这个差被放大；换成 TS 行情后残差为 0。
- **口径无法区分：**本样本中，risk9 用 raw 还是 true 的高低点和 range，数值完全相同。
- **close13 的另一种解释：**TS 只在最近约 345 根以内查 13 的收盘价。这与上表规则同样吻合（15m 的 BUY 13 在 345 根之前）。

## 6. 敏感性

- **历史窗口：**
  - 取 300 根：15m 丢失 BUY 13 的 riskLevel，1d 丢失 barsSinceQualified13 = 250。
  - 取 1000 或 2000 根：5m 多出 9 月 25 日 06:05 的 BUY 13 riskLevel；1d 多出 2025-06-08 的 SELL 13。后者只在 476 根之前，但它的 Setup 起点在 500 根窗口之外，而 TS 没有显示它。
  - 结论：TS 按 limit 500 从头计算，没有看到窗口之前的 warm state。
- **5m 的 prev：**
  - TS 的 13 在 11:10。本地的旧 SELL Countdown（Setup 9 在 08:10）在 10:05 被新 SELL Setup 以 1.07 倍 range 回收，新的那轮在 13:30 走到 13。
  - 关闭回收时，旧 Countdown 在 11:05 走到 13。
  - 相关判断都很脆弱：旧 Setup 的 price flip 余量只有 −6.06 USDT；Countdown 第 9 根余量 2.00，第 12 根余量 7.49。
  - 给 OHLC 加 σ = 5 USDT 的扰动跑 150 次，最后一个 SELL 13 的时间分散在 8 种以上，其中 11:10 占 4%。主序列始终是 14:55 那个 BUY 9 的 Countdown（计数为 3 或 4）。
  - 结论：这是行情源问题，不应修改映射。
- **其余周期的扰动测试：**1h、4h、1d 各跑 40 次，σ 分别为 5 / 10 / 10 USDT，结构字段 38/40 至 40/40 保持一致。5m 的形成中 bar 离阈值很近，step 与 second 只有 23 至 26 次一致。

## 7. AlphaBTC s9 / s13 / Regime 复核

按 [AlphaBTC §2.1](../../../research/alphabtc-regime-cycle-source-2026-09-28.md) 的 `dmkLive` 规则计算：

| 周期 | 由 TS 快照推出 | 由本地投影推出 | 一致 |
|---|---|---|---|
| 5m | s9 红，cd 3，无 13 | 同左 | ✓ |
| 15m | carry13 成立，s9 绿（prev 为 SELL），s13 | 同左（只用 Binance 也相同） | ✓ |
| 1h | carry13 成立，s9 红，s13 → **阴跌爆拉** | 同左 | ✓ |
| 4h | s9 绿，cd 8 → **突破减弱** | 同左 | ✓ |
| 1d | s9 绿，cd 9 | 同左 | ✓ |

**绕过 across 的等价捷径：**

- 有活动 Countdown：s9 取 `P.side` 对应的颜色（sell 为绿，buy 为红），s13 为否。
- 否则，若 `run.setup_count ≥ 9`：s9 取 run 方向的颜色，s13 为否。
- 否则，若 lastSignal 为 13，且 prev 是合格 13：s9 取 `prev.side` 对应的颜色，s13 为是。
- 以上都不满足时，s9 为未确认。

## 8. 待确认

1. **rounds 用规则 A 还是规则 B。**
   - 规则 A：取最后一次完成、且与当前 setup 段同向的 Setup 作为锚点。
   - 规则 B：见 §3。
   - 两者在本快照上结果相同，但在一种情形下会分歧：13 之前有一个被压住的同向 9，之后当前 setup 段又与它同向。第二快照的 15m 在 Binance 行情上正是这种情形（SELL 1）：规则 A 得到 s9 未确认，规则 B 得到 s9 绿 + s13。
   - 第二快照没有给出 15m 的方向，无法判定。本文暂取语义上更自然的 B，需要下一份完整快照验证。
   - 2026-09-28 补充：同一规则 B 下，被 `retain_active` 压住的同向 9 只有「已完善」才列入 rounds。依据是 4h 完善的 SELL 9 被 TS 列出（两份快照都是如此），而 5m 未完善的 BUY 9（1790561700）没有列出，尽管 TS 的 `risk9Ts` 正指向它。两者的 Setup 区间都小于前一轮，因此区间大小不是区分因素。目前只有这两例，后续快照继续验证。
2. **`strong`** 的含义未知。1h 那一轮是完善 Setup、13 没有延期、13 之后 12 根内最大反弹约 0.65%，TS 给出 `strong: false`。可见它不等于 perfection，也不等于“未延期”。
3. **close13 与 provisional** 各有两种等价写法（见 §5），需要用 prev 与 R13 不是同一轮的样本区分。
4. **lastSignal 在 setup 阶段的回退来源**：本文用 prev 的信号，也可能是全局最近的 9/13。两者在以下情形会分歧：13 之后出现过一个因 TDST 被取消、countdown 为 0 的 9。
5. **prev 的候选范围**：是否包括 countdown 为 0 就被取消、或被回收（recycled）的序列。回收的轮次是否留在 rounds 中，也未验证。
6. **13 延期时的显示**（`count13_unqualified`）：step 是 12 还是 13，phase 是否仍为 countdown。这会直接影响 AlphaBTC 的 s13。
   - 2026-09-28 补充：13 **合格**的那一根，TS 的 phase 已经是 setup，但 `countdownStep` 仍为 13（5m，barsAgo 0）；43 根之后则为 0。本地已按 `barsAgo == 0` 实现，中间区间待验证。
7. **当前 setup 段已中断、且还没有新 flip 时**，second 和 setupRun 怎样显示。
8. **产品口径需要决策**：本项目的正式结果只用已收盘 bar，而复现 TS 必须计入形成中 bar。Regime 是否使用形成中 bar、是否另做一个“形成中预览”，需要用户决定。按现有原则，不应把形成中的计数写成已收盘结果。
