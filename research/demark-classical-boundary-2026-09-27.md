# 经典 DeMARK 与 AlphaBTC 扩展的边界

核验日期：2026-09-27。范围：重新读取 DeMARK 官方 Sequential 说明及指标目录，并对照本仓库 2026-09-26 的 AlphaBTC 页面观察。本文未重新操作 AlphaBTC；朋友站的当前交互反推由本轮另一份记录负责。

## 结论

用户明确目标是独立正确计算经典 9／13，再理解朋友如何增加市场状态和单边行情判断。**不能把经典 DeMARK 简化成“只数 9／13”，也不能把所有突破判断、多周期分析都归为朋友原创。** 经典 Sequential 本身已有趋势强弱、TDST、取消、Recycling、Risk Level 和突破资格；朋友的具体状态标签、周期分组和策略映射应单独建模。[D1][D2]

| 层次 | 内容 | 当前证据边界 |
|---|---|---|
| 经典 Sequential | Setup、Perfected Setup、Countdown、13 vs 8、TDST、Risk Level、延期、取消、Recycling、12-bar metric | 官方明确有这些组成部分；公开简介并非完整可执行规格。[D1] |
| 更广的 DeMARK 指标库 | Qualified／Disqualified Breakout、Resonance、Combo、Aggressive Sequential 等 | 属于 DeMARK 官方体系；不能未经证据假定朋友实际使用这些独立指标。[D2] |
| 上游供应商实现与呈现 | TradingSignal 的 `active`／`cancelled`／`qualified13` 字段、中文阶段名、多轮结构选择、算法切换、AI 解读 | 来自既有页面观察；这些字段不是证明其实现完全符合官方规则的验收结果。[A1][A2] |
| 朋友的策略解释层 | “反转阴跌／突破减弱／阴跌爆拉”、1h 校准短周期及 4h 校准长周期、BUY_1/2 与 SELL_1/2、置信度调整、期权动作 | 对应 AlphaBTC 的业务呈现与组合规则；精确分支须从交互或公开规则中验证，无法验证的少量缺口再问作者。[A1][A2] |
| 独立的链上周期与外部辅助 | BTC Cycle Index、成本基础、盈亏分布、IV／RV、事件等 | 不属于 9／13 的原始 OHLC 计数。是否参与某一 Regime 输出应逐项验证，不能因同页出现就假设相互依赖。[A2][A3] |

## 经典算法已经处理了哪些“单边继续走”的情况

1. **TDST**：官方称其用途是 “confirm market trends and likely trend failures”，使用 true high／true low 建立参考边界。因此判断趋势继续或失败并非从朋友的扩展层才开始。[D1 §03]
2. **Countdown 取消**：尚未完成的 Countdown 可因反向 Setup 完成而取消；也可因 TDST 被违反而取消。官方具体表述为 true high 低于 TDST Downside，或 true low 高于 TDST Upside。这不能直接简化成只看收盘，也不能忽略 true extreme 中可能涉及的上一根收盘。[D1 §09]
3. **Recycling**：后续同向 Setup 符合条件时，说明趋势增强到足以削弱原 Countdown，重置过程。官方列出后续 Setup 达到 22，或新 Setup 的 true range 跨度为上一轮的 100%–200% 两种情况。具体实现仍需处理各规则顺序与适用边界。[D1 §08]
4. **Risk Level 与突破资格**：完成 13 后，价格仍可延伸一定程度。官方明确说 qualified 和 disqualified Breakout Rules 用于判断 Sequential 信号是否保持完整；不能未经核验把“一次收盘穿线”宣称为全部经典规则。[D1 §05]
5. **12-bar metric**：官方表示完成 13 后应在 12 根内出现反应；若未发生，既有趋势更可能继续。这是反应时间评价，公开文字不足以自动推出“第 13 根后删除历史信号”的程序规则。[D1 §06]

官方目录的 Qualified Breakout 解释为满足突破资格后更可能延续，Disqualified Breakout 则较不可能短期延续；目录还包含将多周期 Sequential／Combo 汇总成振荡器的 Resonance。因此，“突破过滤”和“跨周期组合”的一般思想也不是朋友独有。[D2：对应条目]

## 需要避免的三种混淆

**把供应商文案当经典结论。** 既有专题记录中的“9 是趋势确立”“13 才是反转结论”是第三方页面表达。官方称 13 后市场 “prone to a reversal”，不是反转已发生。正确科普应区分持续条件完成、衰竭候选和后续价格实际反应。[A1][D1 §04]

**把“市场周期”混成一个变量。** 朋友的 1h／4h DeMark Regime 描述价格结构阶段；链上 BTC Cycle Index 描述持币成本／盈亏大环境；5m／1h／4h 是 K 线时间尺度。三者分别保留输入和输出，实际联动需由证据确认。[A2][A3]

**把“9 旁边的风险线”自动认作原创。** 官方指标目录的 Risk Level 条目也提到 Setup 或 Countdown 完成后产生的风险区域，不只涉及 Countdown 13。因此 AlphaBTC 的“趋势衰退阈值”需要按数值和来源判断，不能仅凭中文名称断言是朋友新公式或等同 TDST。[D2：Risk Level；A1]

## 对当前工作的直接约束

- Python 的经典计数层只依据已选定且可复核的规则和 OHLC 产生序列、资格与生命周期；朋友的 Regime 不回写或篡改原始 9／13。
- 反推朋友策略时，分别记录原始输入、当前状态、控件动作、输出变化，区分可重复验证的规则与只能拟合某个快照的猜测。
- 只有页面行为不能区分的分支、不可见阈值或数据口径才列为作者问题；无需再次询问官方已解释的基本计数概念。
- 本报告只建立归属边界，不宣称已取得经典算法全部执行细节，也不宣称朋友策略完全来自某一个官方独立指标。

## 来源

- [D1：DeMARK Sequential](https://demark.com/sequential-indicator/)，2026-09-27 直接抓取官方页面正文核验；§01–09 分别涵盖 Setup、Perfected Setup、TDST、Countdown、Risk Level、12-bar metric、Deferral、Recycling、Cancellation。
- [D2：DeMARK Indicator List](https://demark.com/indicators-list/)，2026-09-27 直接抓取官方页面正文核验；重点为 Qualified／Disqualified Breakout、Resonance、Risk Level、Setup Trend、Recycle 条目。
- [A1：DeMark 已实现模型专题研究](demark-completed-model-study-2026-09-26.md)，历史第三方页面观察；其中较强的反转措辞须按上文纠正。
- [A2：AlphaBTC 功能全景与中文阅读指南](alphabtc-product-walkthrough-2026-09-26.md)，历史页面观察，尤其 §5–7。
- [A3：AlphaBTC 概念分层与新手解释参考](alphabtc-concepts-reference-2026-09-26.md)，用于对照已区分的链上成本与 DeMark Regime 概念。
