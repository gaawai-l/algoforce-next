# Sequential 公开规则核验证据

核验日期：2026-09-27。目的：为基础版独立 Python 计算提供可执行规则；不承诺与 TradingSignal、Bloomberg、Symbolik 的专有版本逐根一致。朋友的市场阶段、单边行情分类和期权策略不属于本文的计数算法。

## 一手资料和版本边界

- **D1**：[DeMARK 官方 Sequential](https://demark.com/sequential-indicator/)，本次使用同页 `?x=1` 成功读取正文。§01–09 描述 Setup、Perfection、TDST、Countdown、Risk、12-bar、Deferral、Recycling、Cancellation。
- **D2**：Tom DeMark、Rocke DeMark，*Countertrend forex trading with TD Sequential*，Currency Trader，2005-01，印刷页 28–33。[作者文章 PDF 镜像](https://www.earnforex.com/forex-e-books/Tom%20DeMark%20TD%20Sequential.pdf)。已逐页提取正文。文章作者是一手来源，镜像主机不是版权所有者。
- **S1**：Christopher Ting，SMU QF206 Week 5，2017-02-04，70 页。[历史存档 PDF](https://web.archive.org/web/20200331132911/http://www.mysmu.edu/faculty/christophert/QF206/Week_05.pdf)。这是大学讲义，**不是 DeMARK 官方文档，也不是 Jason Perl 本人署名演示**。EarnForex 链接标签称其为 Perl 演示，实际 PDF 署名 Ting。p43、p56 的 Risk 公式位于图像，已提取并人工查看。
- **V1**：[EarnForex TD Sequential Ultimate](https://www.earnforex.com/indicators/TD-Sequential-Ultimate/)，供应商实现说明、下载 MQ4 源码，用于交叉核对，不作为官方规则最终裁判。

来源并非完全一致：D2 在 2005 年写 recycling 18，而 D1 当前公开页写 22，另加 100%–200% range 条件；S1 的 perfection 使用非严格比较，D2 使用严格比较。必须按命名版本说明所选规则，不能把不同年代和不同供应商默默拼成“官方完整版”。

## 基础计数可执行规则

记 `C[t] / H[t] / L[t]` 为已收盘 bar；Setup 编号 `s1…s9`、Countdown 编号 `d1…d13` 是各自序列引用，不是全局 bar 索引。以下推荐作为公开规则版本的明确合同。

| 项目 | Buy 推荐条件；Sell 镜像反向 | 证据与边界 |
|---|---|---|
| Price flip | `C[t-1] >= C[t-5]` 且 `C[t] < C[t-4]`，当前根即 s1。Sell 为前根 `<=`、当前根 `>` | D2 p30 明确包含前根的等号；前五根不足时不能验证 flip。S1 p6 用严格 `>`，p8 的公式与文字甚至存在方向笔误，故不采用该讲义作为 flip 权威 |
| Setup | 后续每根 `C[t] < C[t-4]`，连续到 9；相等或反向中断未完成 Setup | D1 §01、D2 p30。Buy 名称表示潜在上反转，正在观察的是下行持续 |
| 第 9 根之后 | Setup 完成事实保留；继续跟踪同一连续 run 长度；新 Setup 需要新的 flip | D2 说至少九根、D1 recycling 用延伸至22。不能每九根机械重启一个新 Setup |
| Perfection | s8、s9 任一 low 严格低于 `min(L[s6], L[s7])`；未满足则后续首根 low 严格穿过同门槛时完善；Sell 严格高于 max | D2 p30 明确严格 less/greater，D1 §02 为 exceeded。S1 p12/16 与部分供应商用 `<=/>=`，这是应声明的变体。本版推荐 strict |
| Perfection 时间 | 如果 s8 已满足，s9 收盘才确认“完成且完善”的 Setup，可另存满足条件的 s8 引用；后续完善以实际该根收盘确认 | D1 说完成9后分类。本条确认时间是避免前视的 Wheelhouse 数据政策，不把日后完成的9回写成s8当时已知 |
| Countdown 启动 | s9 当根开始检查；即使 Setup 尚未 perfected 也开始；不满足就等待第一根资格 | D2 p30 原文 “Beginning on the ninth Setup bar”；S1 p20 同样明确。Perfection 不作为 Countdown 门槛 |
| Countdown 1–12 | `C[t] <= L[t-2]`；不要求连续。不满足则保留旧计数，不清零。Sell `C[t] >= H[t-2]` | D2 p30–31，D1 §04；等号计数 |
| 第 13 根 | 同时满足普通 Countdown 条件与 `L[t] <= C[d8]`；Sell `H[t] >= C[d8]` | D1 §07、D2 p30、S1 p21；等号合格。必须保存 d8 收盘价和引用 |
| 延迟 13 | 已到12，某根满足普通资格但不满足13-vs-8时，记录 deferred/+，仍维持12；继续等待同时满足两条件的一根 | D1 §07、D2 p32。不能第13次普通比较不合格就清空序列 |
| 8-vs-5 | 首版关闭 elective qualifier，明确参数 | D1 §07 说 elective；13-vs-8 则 critical |
| 反向取消 | 相反方向 Setup **完成9**，取消尚未完成的 Countdown；仅 price flip 或反向Setup1不足以取消 | D1 §09、D2 p31 |
| 历史13 | 完成13的历史事实永久保留；日后 invalidated/expired/recycled 属于另一个生命周期字段/事件 | D1 §09 “Once completed, a Countdown is permanent and never altered.” |

## TDST 与 true extremes

使用 `TH[t] = max(H[t], C[t-1])`、`TL[t] = min(L[t], C[t-1])`，`TR[t] = TH[t] - TL[t]`。此定义把跳空纳入，而非把 open 当 previous close。

推荐在 Setup9 确认后固定该序列的 TDST：Buy 的 resistance 为 s1…s9 最高 true high；Sell 的 support 为最低 true low。对合法 OHLC，最高 true high 等于九根最高 high 与 s1 前一根 close 的最大值；最低 true low 同理。D1 §03 明确最高/最低 true extreme；V1 源码及更新说明明确纳入 preceding close。D1 公开简介没有细化延伸 Setup 后是否重画 TDST，故首9根固定应列为本版政策。

**取消未完成 Countdown 的经典条件**：

- Buy：`TL[t] > TDST_resistance`，等价于当前 low 与上一根 close 都严格在 resistance 以上。
- Sell：`TH[t] < TDST_support`，等价于当前 high 与上一根 close 都严格在 support 以下。

D1 §09 直接列 True Low/True High，D2 p31 用两个价格同时穿越说明。普通 `close > resistance` 不能充当该规则。若产品支持 close-only 或不含前收盘的 full-bar 模式，应命名为另一个展示/失效政策并在参数中保存。

同根事件优先级公开简介未穷举。推荐先完成当根 Setup、处理反向与 TDST 取消/recycling，再推进幸存 Countdown；每根每个序列最多计数一次。这是可测试的 Wheelhouse 决定，不能用事件顺序制造取消当根的假13。

## Recycling 的已证实内容与必须命名的细节

D1 §08 明确两个触发：

1. 与未完成 Countdown 重叠的后续同向 Setup 连续延伸到 **22**。
2. 后续同向 Setup 的 `highest true high - lowest true low` 为前一 Setup 的 **100%–200%**。

不能将 1.618 当作当前官方网页阈值。D2 p31 的旧文章写 **18**，说明“经典”本身仍须固定版本。

本版可执行推荐：仅处理尚未完成 Countdown；新同向 Setup9 时以首9根 true range 对比旧来源 Setup 首9根，`old_range > 0 and old_range <= new_range <= 2*old_range` 时替换未完成 Countdown；未触发则新 Setup 保留为历史候选、旧 Countdown 继续。后续独立同向 run 到22时再次检查替换。原旧 run 自己达到22不等于“后续 Setup”。新 Countdown 从其所属 Setup9 开始的资格轨迹按已知数据维护，不得把 recycle 发生前的13当成当时已经确认。

上段的**端点是否包含、range 截止首9还是延伸、多个旧候选的挑选、replacement 的起算/追认时点、未触发时是否双重推进**在 D1 简介中未完整公开。它们是命名 ruleset 的具体选择，需要独立边界样本；若实现不同选择必须相应改文档。不能以“官网提过 recycling”证明所有细节已验证。

## Risk Level 与时间限制

D1 §05 只定义风险区域和 qualified/disqualified breakout，不公开完整公式。S1 p43 的图明确示例：Countdown12 为最低 true low，以该 true low 减去同根 true range；p56 的镜像图给最高 true high 加 true range（图中 Buy/Sell 文字有笔误，方向与图明显为 Sell）。因此支持一般公式，但尚不能从示例证明扫描区间和并列极值政策。

可执行推荐以参数命名 `countdown_span_true_extreme`：在 d1…d13 的全部已收盘 bar（包括未计数 bar）选择最低 true low/最高 true high，以该 bar 的 TR 向外扩展；并列极值固定取最早 bar。其扫描区间得到 S1 p64/p69 **Combo** 的文字旁证，但不能冒称该文字就是 Sequential 官方完整规则。如正式实现选择 Setup1…d13，则应明确另一种风险政策与待验证差异，不能两者混称。

Risk 穿越可选明确的 `close` 或 `true_extreme` 政策。收盘即失效是 Wheelhouse 简化政策，D1 没有证明它等价于全部 qualified/disqualified breakout。阈值与历史13可保留用于复核，当前有效性应独立显示。

D1 §06 的12-bar metric 是“13后十二根内应出现反转响应”的时间观察，不等于任意13到第12根无条件注销。推荐默认不自动过期；显示 bars-since 和响应窗口，只有显式配置的本地 TTL 才发出 expired，不能把原实验24根当官方默认。

## 复用候选核验

| 候选 | 版本/许可 | 实际范围与结论 |
|---|---|---|
| [pandas-ta-classic `td_seq`](https://github.com/xgboosted/pandas-ta-classic/blob/8afeec2250c7c114c5d647ade5e2319b67e1aaa2/pandas_ta_classic/momentum/td_seq.py) | commit `8afeec2250c7c114c5d647ade5e2319b67e1aaa2`，2026-09-26；[MIT](https://github.com/xgboosted/pandas-ta-classic/blob/8afeec2250c7c114c5d647ade5e2319b67e1aaa2/LICENSE) | 仅接受 close，计算 `diff(4)` 连续 run，上限13；不读取 high/low，因此不可能实现标准非连续 Countdown、13-vs-8、TDST、Risk。近期有维护，但不适合作为完整9/13核心 |
| [EarnForex TDSequentialUltimate](https://github.com/EarnForex/TDSequentialUltimate) | commit `b7330506f3837b325535d2d03a8a22cc42bd9caf`，2025-08-08；[Apache-2.0](https://github.com/EarnForex/TDSequentialUltimate/blob/b7330506f3837b325535d2d03a8a22cc42bd9caf/LICENSE) | MQL4/5，不是 Python。供应商下载源码确有 flip、非连续 Countdown、延迟 perfection、TDST；但其13-vs-8用严格 `<`，与D1的 `<=` 不一致；未见官方两类 recycling/Risk完整实现。仅用作规则交叉检查，不直接移植成正确性依据 |

另查 ProRealCode 社区版，网页明确是社区作者按找到的规则编写；代码与评论反映与专有版本不同，13失败后清零、缺少完整取消/recycling，因此没有用它作黄金样本。CQG公开文档说明 DeMARK 专门帮助仅供订阅用户；本次没有访问其专用规则文档，不能引用为已核验依据。

以上支持自行编写小型、Decimal、确定性状态机：不是为了重复造轮子，而是已核验 Python 候选功能范围确实不足。黄金样本需手推比较边界，不能以这些候选函数输出反向生成期望值。

## 验收需要特别独立构造的样本

1. Price flip 前根恰好相等仍允许启动；Setup中途相等立即中断。
2. s9同根d1；未完善Setup也开始Countdown；s8满足但s9未完成前不能提前确认完整Setup。
3. perfection严格相等不完善，与13-vs-8相等合格区分。
4. 稀疏Countdown，普通第13资格失败后若干次+，最终满足两条件才13。
5. 当前close穿TDST但low/前close未同时穿越，不取消；跳空但前close在线内不取消；true extreme完整穿线才取消。
6. 同向后续Setup范围等于100%、200%边界，超过200%，连续22；原来源run22与后续run22区分。
7. 同根反向9/取消/13候选的事件顺序、历史完成13不被擦掉。
8. Risk极值bar不是13，未计数bar拥有极值，跳空TR，并列极值；默认不会因12根无条件expire。
9. 每条结论只使用到当前收盘已知数据；前缀重放与批量结果一致。
